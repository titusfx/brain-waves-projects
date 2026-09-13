"""What is on disk: saved flows, recordings and datasets.

Everything the app can *load* is enumerated here — the flow definitions the
operator authored, and every recording this project has ever produced (the web
API's datasets, ``live_view.py``'s session folders, ``record.py``'s flat CSVs).
That is why the reader is tolerant: the point of the library is that a recording
made from the terminal three months ago still opens in the browser.
"""

from __future__ import annotations

import csv
import json
import re
import shutil
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import numpy as np

from eeg_api.domain.flows import FlowSpec, FlowStep
from eeg_api.domain.models import CHANNELS, FS, FloatArray
from eeg_api.eeg import csvio
from eeg_api.services.recorder import (
    EEG_FILENAME,
    LABELS_FILENAME,
    META_FILENAME,
    Segment,
    slugify,
)


_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")


def _time_mask(times: FloatArray, start: float | None, end: float | None) -> np.ndarray:
    """Rows of ``times`` inside ``[start, end)``.

    Times are matched rather than sample indices, because every file that carries a
    label table also carries a ``t`` column on the same clock as the recording's start —
    so a state's window means the same thing in ``labels.csv``, ``eeg.csv`` and a
    request, and a row-count mismatch cannot silently shift the answer.
    """
    mask = np.ones(times.shape, dtype=bool)
    if start is not None:
        mask &= times >= start
    if end is not None:
        mask &= times < end
    return mask


def _select_states(
    segments: list[dict[str, Any]],
    labels: list[str],
    instances: dict[str, list[int]] | None,
    min_seconds: float,
) -> dict[str, list[dict[str, Any]]]:
    """The states to analyse: the requested labels, long enough, and chosen instances.

    A state shorter than one analysis window is dropped rather than padded: the final
    state of a stopped loop is usually a fraction of a second, and averaging it in would
    put a fragment into the class mean.
    """
    wanted = set(labels)
    out: dict[str, list[dict[str, Any]]] = {}
    for segment in segments:
        label = str(segment["label"])
        if label not in wanted or float(segment["duration"]) < min_seconds:
            continue
        chosen = (instances or {}).get(label)
        if chosen is not None and int(segment["index"]) not in chosen:
            continue
        out.setdefault(label, []).append(segment)
    return out


def _excluded(
    segments: list[dict[str, Any]],
    selected: dict[str, list[dict[str, Any]]],
    min_seconds: float,
) -> list[dict[str, Any]]:
    """What was left out, and why — so an analysis cannot quietly drop a state."""
    kept = {int(segment["index"]) for group in selected.values() for segment in group}
    out: list[dict[str, Any]] = []
    for segment in segments:
        if int(segment["index"]) in kept:
            continue
        out.append(
            {
                "index": int(segment["index"]),
                "label": str(segment["label"]),
                "duration": round(float(segment["duration"]), 3),
                "reason": (
                    f"shorter than the {min_seconds:g} s analysis window"
                    if float(segment["duration"]) < min_seconds
                    else "not selected"
                ),
            }
        )
    return out


class LibraryError(RuntimeError):
    """A recording or flow that was asked for does not exist, or is out of bounds."""


class LibraryNotFoundError(LibraryError):
    """There is nothing under that name."""


class LibraryInUseError(LibraryError):
    """The recording is being read or written right now, so it cannot be removed."""


def _delete_target(root: Path, entry_id: str) -> Path:
    """Resolve an id to something inside ``recordings/``, or refuse.

    Deleting is the one operation in this project that cannot be undone, so the checks
    are deliberately paranoid: the id must be a bare name, the resolved path must be
    *inside* the recordings folder, and it must not be the folder itself. Without all
    three, a request could name a directory one level up and take the library with it.
    """
    if not _SAFE_ID.match(entry_id) or ".." in entry_id or entry_id.strip(".") == "":
        raise LibraryError(f"invalid recording id {entry_id!r}")
    root = root.resolve()
    target = (root / entry_id).resolve()
    if target == root or not target.is_relative_to(root):
        raise LibraryError(f"{entry_id!r} is outside the recordings folder")
    if not target.exists():
        raise LibraryNotFoundError(f"no recording called {entry_id!r}")
    return target


def _folder_size(path: Path) -> int:
    if path.is_dir():
        return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return path.stat().st_size


# --------------------------------------------------------------------------- #
# Flows
# --------------------------------------------------------------------------- #
def spec_to_storage(spec: FlowSpec) -> dict[str, Any]:
    """The authored fields only — computed values are not persisted."""
    return {
        "id": spec.id,
        "name": spec.name,
        "mode": spec.mode,
        "countdown_seconds": spec.countdown_seconds,
        "repeat": spec.repeat,
        "rest_seconds": spec.rest_seconds,
        "discard_tail": spec.discard_tail,
        "description": spec.description,
        "steps": [
            {"label": step.label, "seconds": step.seconds, "speak": step.speak}
            for step in spec.steps
        ],
    }


def spec_from_storage(payload: dict[str, Any], *, flow_id: str = "") -> FlowSpec:
    """Rebuild a :class:`FlowSpec` from JSON, tolerating hand-edited files."""
    steps: list[FlowStep] = []
    for raw in payload.get("steps") or []:
        seconds = raw.get("seconds")
        steps.append(
            FlowStep(
                label=str(raw.get("label", "")).strip(),
                seconds=None if seconds in (None, "", "null") else float(seconds),
                speak=(str(raw["speak"]).strip() if raw.get("speak") else None),
            )
        )
    mode = str(payload.get("mode", "linear")).lower()
    repeat = payload.get("repeat")
    discard = payload.get("discard_tail")
    return FlowSpec(
        id=flow_id or str(payload.get("id", "")),
        name=str(payload.get("name", "")).strip(),
        mode="loop" if mode == "loop" else "linear",
        countdown_seconds=float(payload.get("countdown_seconds", 3.0)),
        repeat=None if repeat in (None, "", "null") else int(repeat),
        rest_seconds=float(payload.get("rest_seconds", 0.0)),
        discard_tail=None if discard in (None, "", "null") else int(discard),
        description=str(payload.get("description", "")).strip(),
        steps=tuple(steps),
    )


class FlowStore:
    """Saved flow definitions, one JSON file each."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, flow_id: str) -> Path:
        if not _SAFE_ID.match(flow_id) or ".." in flow_id:
            raise LibraryError(f"invalid flow id {flow_id!r}")
        return self.root / f"{flow_id}.json"

    def list(self) -> list[FlowSpec]:
        specs: list[FlowSpec] = []
        for path in sorted(self.root.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            specs.append(spec_from_storage(payload, flow_id=path.stem))
        return specs

    def get(self, flow_id: str) -> FlowSpec | None:
        path = self._path(flow_id)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LibraryError(f"{flow_id}.json is not readable: {exc}") from exc
        return spec_from_storage(payload, flow_id=flow_id)

    def _unused_id(self, name: str) -> str:
        base = slugify(name)
        candidate = base
        suffix = 1
        while (self.root / f"{candidate}.json").exists():
            suffix += 1
            candidate = f"{base}-{suffix}"
        return candidate

    def create(self, spec: FlowSpec) -> FlowSpec:
        flow_id = self._unused_id(spec.name)
        return self.save(spec, flow_id)

    def save(self, spec: FlowSpec, flow_id: str) -> FlowSpec:
        stored = replace(spec, id=flow_id)
        self._path(flow_id).write_text(
            json.dumps(spec_to_storage(stored), indent=2) + "\n", encoding="utf-8"
        )
        return stored

    def delete(self, flow_id: str) -> bool:
        path = self._path(flow_id)
        if not path.exists():
            return False
        path.unlink()
        return True

    def ensure_seeds(self) -> None:
        """Seed the three flow *shapes* the first time the app runs.

        Without this the builder opens empty and the two protocols that motivated
        the feature — the alternating alpha test and the "lie down / stand up"
        sequence — would have to be retyped to be discovered.
        """
        if any(self.root.glob("*.json")):
            return
        from eeg_api.domain.flows import eyes_open_closed_flow, single_label_flow

        seeds: list[FlowSpec] = [
            eyes_open_closed_flow(),
            FlowSpec(
                name="Lie down, then stand up",
                mode="linear",
                countdown_seconds=5.0,
                repeat=1,
                description=(
                    "A linear protocol: the countdown runs first and is not recorded, then "
                    "each state runs once, in order."
                ),
                steps=(
                    FlowStep(label="lie down", seconds=10.0, speak="lie down"),
                    FlowStep(label="stand up", seconds=20.0, speak="stand up"),
                ),
            ),
            single_label_flow("quick label"),
        ]
        for spec in seeds:
            self.create(spec)


# --------------------------------------------------------------------------- #
# Recordings and datasets
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class LibraryEntry:
    """One thing in ``recordings/``, in the shape the browser lists it."""

    id: str
    name: str
    kind: str  # "dataset" | "session" | "recording"
    path: str
    created: str
    samples: int
    duration_s: float
    size_bytes: int
    channels: int = len(CHANNELS)
    labels: list[dict[str, Any]] = field(default_factory=list)
    flow_name: str | None = None
    segments: int = 0
    source: str | None = None
    notes: str | None = None
    dropped_chunks: int = 0

    def as_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "path": self.path,
            "created": self.created,
            "samples": self.samples,
            "duration_s": round(self.duration_s, 2),
            "size_bytes": self.size_bytes,
            "channels": self.channels,
            "labels": self.labels,
            "flow_name": self.flow_name,
            "segments": self.segments,
            "source": self.source,
            "notes": self.notes,
            "dropped_chunks": self.dropped_chunks,
        }


class RecordingLibrary:
    """Enumerates ``recordings/`` and reads individual recordings back."""

    def __init__(self, root: Path, fs: float = FS) -> None:
        self.root = root
        self.fs = fs
        self._cache: dict[str, tuple[float, int, LibraryEntry]] = {}

    # --------------------------------------------------------------------- scan
    def scan(self) -> list[LibraryEntry]:
        if not self.root.exists():
            return []
        entries: list[LibraryEntry] = []
        for path in sorted(self.root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if path.name.startswith("."):
                continue
            entry = self._describe(path)
            if entry is not None:
                entries.append(entry)
        return entries

    def _describe(self, path: Path) -> LibraryEntry | None:
        try:
            stat = path.stat()
        except OSError:
            return None
        key = str(path)
        cached = self._cache.get(key)
        if cached and cached[0] == stat.st_mtime and cached[1] == stat.st_size:
            return cached[2]

        entry: LibraryEntry | None = None
        if path.is_dir():
            meta_file = path / META_FILENAME
            csv_file = path / EEG_FILENAME
            if meta_file.exists():
                entry = self._describe_dataset(path, meta_file, stat.st_mtime)
            elif csv_file.exists():
                entry = self._describe_flat(
                    path, csv_file, stat.st_mtime, kind="session", name=path.name
                )
        elif path.suffix.lower() == ".csv":
            entry = self._describe_flat(path, path, stat.st_mtime, kind="recording", name=path.stem)

        if entry is not None:
            self._cache[key] = (stat.st_mtime, stat.st_size, entry)
        return entry

    def _describe_dataset(self, path: Path, meta_file: Path, mtime: float) -> LibraryEntry | None:
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        size = sum(f.stat().st_size for f in path.iterdir() if f.is_file())
        samples = int(meta.get("samples", 0))
        duration = float(meta.get("duration", samples / self.fs))
        segments = meta.get("kept_segments") or []
        flow = meta.get("flow") or {}
        return LibraryEntry(
            id=path.name,
            name=str(meta.get("name", path.name)),
            kind="dataset",
            path=str(path),
            created=str(
                meta.get("started", time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(mtime)))
            ),
            samples=samples,
            duration_s=duration,
            size_bytes=size,
            labels=list(meta.get("labels") or []),
            flow_name=str(flow.get("name"))
            if isinstance(flow, dict) and flow.get("name")
            else None,
            segments=len(segments),
            source=str(meta.get("source")) if meta.get("source") else None,
            notes=str(meta.get("notes")) if meta.get("notes") else None,
            dropped_chunks=int(meta.get("dropped_chunks", 0)),
        )

    def _describe_flat(
        self, path: Path, csv_file: Path, mtime: float, *, kind: str, name: str
    ) -> LibraryEntry | None:
        samples = csvio.count_rows(csv_file)
        return LibraryEntry(
            id=path.name,
            name=name,
            kind=kind,
            path=str(path),
            created=time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(mtime)),
            samples=samples,
            duration_s=samples / self.fs,
            size_bytes=csv_file.stat().st_size,
        )

    # ------------------------------------------------------------------- lookup
    def resolve(self, entry_id: str) -> Path:
        """The CSV for ``entry_id``. Refuses anything outside ``recordings/``."""
        if not _SAFE_ID.match(entry_id) or ".." in entry_id:
            raise LibraryError(f"invalid recording id {entry_id!r}")
        candidate = (self.root / entry_id).resolve()
        root = self.root.resolve()
        if not candidate.is_relative_to(root):
            raise LibraryError(f"{entry_id!r} is outside the recordings folder")
        if not candidate.exists():
            raise LibraryError(f"no recording called {entry_id!r}")
        if candidate.is_dir():
            for name in (EEG_FILENAME, "eeg.csv"):
                inner = candidate / name
                if inner.exists():
                    return inner
            csvs = sorted(candidate.glob("*.csv"))
            if not csvs:
                raise LibraryError(f"{entry_id!r} contains no CSV")
            return csvs[0]
        return candidate

    def get(self, entry_id: str) -> LibraryEntry:
        for entry in self.scan():
            if entry.id == entry_id:
                return entry
        raise LibraryNotFoundError(f"no recording called {entry_id!r}")

    def describe_for_deletion(self, entry_id: str) -> dict[str, Any]:
        """Everything a confirmation prompt needs, without touching anything.

        The UI can then say exactly what it is about to remove — the name, the kind, how
        many samples and how much disk — instead of asking "are you sure?" about a string.
        """
        target = _delete_target(self.root, entry_id)
        entry = next((item for item in self.scan() if item.id == entry_id), None)
        return {
            "id": entry_id,
            "path": str(target),
            "name": entry.name if entry else entry_id,
            "kind": entry.kind if entry else ("dataset" if target.is_dir() else "recording"),
            "samples": entry.samples if entry else 0,
            "segments": entry.segments if entry else 0,
            "labels": [label["label"] for label in entry.labels] if entry else [],
            "bytes_freed": _folder_size(target),
        }

    def delete(self, entry_id: str, *, blocked: list[Path] | None = None) -> dict[str, Any]:
        """Remove a recording from disk, and report what went.

        Refuses anything the acquisition side is currently reading or writing: deleting
        the file a replay is streaming from, or the folder a session is writing into,
        would turn a working stream into a confusing failure.
        """
        target = _delete_target(self.root, entry_id)
        for path in blocked or []:
            resolved = path.resolve()
            if target == resolved or target in resolved.parents:
                raise LibraryInUseError(
                    f"{entry_id!r} is in use by the current source or recording; stop it first"
                )

        summary = self.describe_for_deletion(entry_id)
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        # Drop the cached description, or the deleted entry would keep being listed
        # until its mtime happened to change.
        for key in [k for k in self._cache if k.startswith(str(target))]:
            self._cache.pop(key, None)
        return summary

    def segments(self, entry_id: str) -> list[dict[str, Any]]:
        """The label table of a dataset, from ``labels.csv``."""
        csv_file = self.resolve(entry_id)
        labels = csv_file.parent / LABELS_FILENAME
        if not labels.exists():
            return []
        out: list[dict[str, Any]] = []
        try:
            with labels.open("r", newline="", encoding="utf-8") as handle:
                for row in csv.DictReader(handle):
                    try:
                        out.append(
                            {
                                "index": int(row["segment"]),
                                "label": row["label"],
                                "cycle": int(row["cycle"]),
                                "step_index": int(row["step"]),
                                "start_time": float(row["start_time"]),
                                "end_time": float(row["end_time"]),
                                "duration": float(row["duration_s"]),
                                "start_sample": int(row["start_sample"]),
                                "end_sample": int(row["end_sample"]),
                                "samples": int(row["end_sample"]) - int(row["start_sample"]),
                                "truncated": bool(int(row.get("truncated", 0) or 0)),
                                # `labels.csv` only ever holds kept states, so this is
                                # always False here — but the field is part of the
                                # contract, so it is always sent.
                                "discarded": bool(int(row.get("discarded", 0) or 0)),
                            }
                        )
                    except (KeyError, ValueError):
                        continue
        except OSError as exc:
            raise LibraryError(f"cannot read {labels.name}: {exc}") from exc
        return out

    def preview(
        self,
        entry_id: str,
        points: int = 900,
        *,
        start: float | None = None,
        end: float | None = None,
    ) -> dict[str, Any]:
        """Downsampled samples for the dataset browser's chart.

        Decimated rather than averaged: a mean would hide exactly the transient the
        operator is looking for (a blink, a jaw clench) and make a bad recording look
        reassuring.

        ``start``/``end`` restrict the window, in seconds from the recording's start —
        the same clock as ``labels.csv`` — which is what lets the screen show one state
        instead of the whole session while keeping the chart identical.
        """
        csv_file = self.resolve(entry_id)
        samples, times = csvio.read_all(csv_file)
        keep = _time_mask(times, start, end)
        samples, times = samples[keep], times[keep]
        total = int(samples.shape[0])
        if total == 0:
            return {"t": [], "data": [], "total_samples": 0, "decimation": 1}
        step = max(1, total // max(1, points))
        picks = np.arange(0, total, step)
        return {
            "t": [round(float(times[i]), 4) for i in picks],
            "data": [[round(float(v), 2) for v in samples[i]] for i in picks],
            "total_samples": total,
            "decimation": int(step),
        }

    def spectrum(
        self,
        entry_id: str,
        channel: str = "O1",
        seconds: float | None = None,
        *,
        start: float | None = None,
        end: float | None = None,
    ) -> dict[str, Any]:
        """A log power spectrum for one channel, for the dataset detail view.

        Averaged over the window rather than computed from one 2-second slice: a state is
        usually 15-20 seconds long, and using all of it is what makes the picture stable
        enough to compare two states by eye.
        """
        from eeg_api.domain.metrics import log_power_freqs, welch_log_power

        csv_file = self.resolve(entry_id)
        samples, times = csvio.read_all(csv_file)
        if samples.shape[0] == 0 or channel.upper() not in CHANNELS:
            return {"freqs": [], "power": [], "channel": channel.upper()}
        keep = _time_mask(times, start, end)
        column = samples[keep, CHANNELS.index(channel.upper())]
        if seconds is not None:
            column = column[: int(seconds * self.fs)]
        _freqs, log_power = welch_log_power(np.asarray(column, dtype=np.float64), fs=self.fs)
        return {
            "freqs": log_power_freqs(fs=self.fs),
            "power": [round(float(v), 6) for v in log_power],
            "channel": channel.upper(),
        }

    # ---------------------------------------------------------------- discovery
    def discover(
        self,
        entry_id: str,
        *,
        channel: str = "O1",
        labels: list[str] | None = None,
        instances: dict[str, list[int]] | None = None,
        window_seconds: float = 6.0,
        points: int = 600,
        min_seconds: float = 2.0,
        permutations: int = 200,
    ) -> dict[str, Any]:
        """Everything the Discovery screen needs, for one dataset and one channel.

        Reads the samples once and derives, for every labelled state: its averaged
        spectrum, its band shares, and its opening seconds for the overlay. Then the
        within-state repeatability for each label, the between-state comparison for the
        two labels asked for, and a per-channel ranking so it is possible to ask *which
        electrode* separates these states rather than assuming one.
        """
        from eeg_api.domain.discovery import compare, summarise
        from eeg_api.domain.metrics import log_power_freqs

        csv_file = self.resolve(entry_id)
        samples, times = csvio.read_all(csv_file)
        if samples.shape[0] == 0:
            raise LibraryError("this recording has no samples")

        segments = self.segments(entry_id)
        if not segments:
            raise LibraryError(
                "this recording has no labels: only a dataset written from a protocol has "
                "states to compare"
            )

        available = sorted({segment["label"] for segment in segments})
        requested = [label for label in (labels or []) if label in available]
        selected = _select_states(segments, requested or available, instances, min_seconds)
        if not selected:
            raise LibraryError(
                f"no state long enough to analyse: every selected state is shorter than "
                f"{min_seconds:g} s, which is less than one analysis window"
            )

        built: dict[str, list[Any]] = {}
        for label, rows in selected.items():
            group = [
                item
                for item in (
                    self._segment_features(
                        row, samples, times, channel, window_seconds, points, label
                    )
                    for row in rows
                )
                if item is not None
            ]
            if group:
                built[label] = group

        if not built:
            raise LibraryError(
                f"no state has at least {min_seconds:g} s of {channel.upper()} to analyse"
            )

        # Keep the order that was asked for, so "A" and "B" in the comparison mean what
        # the caller asked for rather than whichever state happens to come first.
        order = requested or available
        features = {label: built[label] for label in order if label in built}

        freqs = log_power_freqs(fs=self.fs)
        axis = np.asarray(freqs, dtype=np.float64)
        summaries = {
            label: summarise(label, np.vstack([f.log_power for f in group]))
            for label, group in features.items()
        }

        labels_present = list(features)
        ranking: list[dict[str, Any]] = []
        comparison = None
        if len(labels_present) >= 2:
            first, second = labels_present[0], labels_present[1]
            # The channel ranking answers "which electrode?" by measuring every one of
            # them, rather than by picking one and hoping. Fewer permutations than the
            # headline test: it is a shortlist, and the chosen channel is then tested
            # properly.
            ranking = self._channel_ranking(
                samples,
                times,
                selected,
                first,
                second,
                axis,
                permutations=min(permutations, 64),
            )
            comparison = compare(
                first,
                np.vstack([f.log_power for f in features[first]]),
                second,
                np.vstack([f.log_power for f in features[second]]),
                axis,
                permutations=permutations,
            )

        return {
            "id": entry_id,
            "channel": channel.upper(),
            "channels": list(CHANNELS),
            "labels": available,
            "analysed_labels": labels_present,
            "fs": self.fs,
            "window_seconds": window_seconds,
            "min_seconds": min_seconds,
            "freqs": freqs,
            "classes": [
                {
                    "label": label,
                    "summary": summaries[label].as_payload(),
                    "instances": [item.as_payload() for item in group],
                }
                for label, group in features.items()
            ],
            "comparison": None if comparison is None else comparison.as_payload(freqs),
            "channel_ranking": ranking,
            "excluded": _excluded(segments, selected, min_seconds),
        }

    def _segment_features(
        self,
        row: dict[str, Any],
        samples: FloatArray,
        times: FloatArray,
        channel: str,
        window_seconds: float,
        points: int,
        label: str,
    ) -> Any:
        """One state's spectrum, band shares and drawing window, or None if too short."""
        from eeg_api.domain.discovery import SegmentFeatures, log_power_of
        from eeg_api.domain.metrics import band_powers

        keep = _time_mask(times, float(row["start_time"]), float(row["end_time"]))
        column = samples[keep, CHANNELS.index(channel.upper())]
        if column.size < 64:
            return None
        log_power = log_power_of(np.asarray(column, dtype=np.float64), fs=self.fs)
        if log_power.size == 0:
            return None

        opening = column[: int(window_seconds * self.fs)]
        step = max(1, int(opening.size) // max(1, points))
        trace = opening[::step]
        return SegmentFeatures(
            index=int(row["index"]),
            label=label,
            cycle=int(row.get("cycle", 0)),
            step_index=int(row.get("step_index", -1)),
            start_time=float(row["start_time"]),
            end_time=float(row["end_time"]),
            duration=float(row["duration"]),
            samples=int(column.size),
            log_power=log_power,
            bands=band_powers(np.asarray(column, dtype=np.float64)),
            trace=np.asarray(trace, dtype=np.float64),
            trace_step=step,
        )

    def _channel_ranking(
        self,
        samples: FloatArray,
        times: FloatArray,
        selected: dict[str, list[dict[str, Any]]],
        label_a: str,
        label_b: str,
        freqs: FloatArray,
        *,
        permutations: int,
    ) -> list[dict[str, Any]]:
        """How well each electrode separates the two states, best first."""
        from eeg_api.domain.discovery import compare, log_power_of

        ranking: list[dict[str, Any]] = []
        for name in CHANNELS:
            vectors: dict[str, list[FloatArray]] = {label_a: [], label_b: []}
            for label in (label_a, label_b):
                for row in selected[label]:
                    keep = _time_mask(times, float(row["start_time"]), float(row["end_time"]))
                    column = samples[keep, CHANNELS.index(name)]
                    if column.size < 64:
                        continue
                    log_power = log_power_of(np.asarray(column, dtype=np.float64), fs=self.fs)
                    if log_power.size:
                        vectors[label].append(log_power)
            if not vectors[label_a] or not vectors[label_b]:
                continue
            a, b = np.vstack(vectors[label_a]), np.vstack(vectors[label_b])
            result = compare(label_a, a, label_b, b, freqs, permutations=permutations)
            ranking.append(
                {
                    "channel": name,
                    "max_effect": round(float(result.effect.max()), 3)
                    if result.effect.size
                    else 0.0,
                    "best_frequency": round(float(freqs[int(np.argmax(result.effect))]), 2)
                    if result.effect.size and freqs.size
                    else None,
                    "reliable": result.reliable,
                    "n_a": int(a.shape[0]),
                    "n_b": int(b.shape[0]),
                }
            )
        ranking.sort(key=lambda item: item["max_effect"], reverse=True)
        return ranking


def segments_from_payload(raw: list[dict[str, Any]]) -> list[Segment]:
    """Rebuild :class:`Segment` objects from a stored payload (used by tests)."""
    return [
        Segment(
            index=int(item.get("index", 0)),
            label=str(item.get("label", "")),
            cycle=int(item.get("cycle", 0)),
            step_index=int(item.get("step_index", -1)),
            start_time=float(item.get("start_time", 0.0)),
            end_time=float(item.get("end_time", 0.0)),
            start_sample=int(item.get("start_sample", 0)),
            end_sample=int(item.get("end_sample", 0)),
            truncated=bool(item.get("truncated", False)),
            discarded=bool(item.get("discarded", False)),
        )
        for item in raw
    ]


def samples_to_payload(samples: FloatArray, limit: int = 4) -> list[list[float]]:
    """Round a block of samples for JSON, newest ``limit`` rows last."""
    if samples.shape[0] == 0:
        return []
    return [[round(float(v), 2) for v in row] for row in samples[-limit:]]
