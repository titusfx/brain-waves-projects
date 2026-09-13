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


class LibraryError(RuntimeError):
    """A recording or flow that was asked for does not exist, or is out of bounds."""


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
        raise LibraryError(f"no recording called {entry_id!r}")

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

    def preview(self, entry_id: str, points: int = 900) -> dict[str, Any]:
        """Downsampled samples for the dataset browser's chart.

        Decimated rather than averaged: a mean would hide exactly the transient the
        operator is looking for (a blink, a jaw clench) and make a bad recording look
        reassuring.
        """
        csv_file = self.resolve(entry_id)
        samples, times = csvio.read_all(csv_file)
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
        self, entry_id: str, channel: str = "O1", seconds: float | None = None
    ) -> dict[str, Any]:
        """A log power spectrum for one channel, for the dataset detail view."""
        from eeg_api.domain.metrics import spectrogram_row, spectrum_freqs

        csv_file = self.resolve(entry_id)
        samples, _times = csvio.read_all(csv_file)
        if samples.shape[0] == 0 or channel.upper() not in CHANNELS:
            return {"freqs": [], "power": [], "channel": channel.upper()}
        column = samples[:, CHANNELS.index(channel.upper())]
        if seconds is not None:
            column = column[: int(seconds * self.fs)]
        return {
            "freqs": spectrum_freqs(),
            "power": spectrogram_row(np.asarray(column, dtype=np.float64)),
            "channel": channel.upper(),
        }


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
