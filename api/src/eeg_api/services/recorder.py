"""Writing a labelled dataset.

The format is designed to stay readable by the tools that already exist. ``eeg.csv``
is a superset of what ``scripts/record.py`` writes — a leading ``t`` column plus the
same 14 ``<channel>_uV`` columns — and ``scripts/live_view.py --replay`` and
``scripts/alpha_test.py --file`` both match columns by header, so a dataset recorded
here can be replayed and alpha-tested from the terminal with no conversion.

Layout of ``recordings/<name>_<stamp>/``::

    eeg.csv      t, F3_uV, … F4_uV     the samples, time in seconds from the start
    labels.csv   one row per kept state: which samples carry which label
    meta.json    the flow that produced it, the source, counts, what was discarded
    events.jsonl every state boundary as it happened, for provenance

Labels are a **segment table**, not a per-sample column, because states are what a
protocol actually produces and a per-sample column would repeat, 128 times a second,
a string that changes a few times a minute. ``[start_sample, end_sample)`` is
half-open and indexes rows of ``eeg.csv``.

The two things worth being careful about here — both of which are the kind of bug
that silently ruins a dataset rather than failing:

* **The countdown is not data.** ``begin(epoch)`` discards everything before the
  countdown ended, so the subject's "3, 2, 1" fidgeting cannot end up in a class.
* **State boundaries are sample-exact.** Boundaries are queued with a stream time and
  applied by the writer as it passes them, instead of being stamped at whatever
  moment the runner happened to notice. See :meth:`DatasetRecorder.request_open`.
"""

from __future__ import annotations

import contextlib
import csv
import json
import math
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

import numpy as np

from eeg_api.domain.models import CHANNELS, FS, FloatArray


#: How often the sample file is pushed to the OS during a run.
FLUSH_SECONDS = 1.0

EEG_FILENAME = "eeg.csv"
LABELS_FILENAME = "labels.csv"
META_FILENAME = "meta.json"
EVENTS_FILENAME = "events.jsonl"


@dataclass(slots=True)
class Segment:
    """One labelled stretch of the recording."""

    index: int
    label: str
    cycle: int
    step_index: int
    start_time: float
    end_time: float
    start_sample: int
    end_sample: int
    truncated: bool = False
    discarded: bool = False
    speak: str | None = None

    @property
    def duration(self) -> float:
        return max(0.0, self.end_time - self.start_time)

    @property
    def samples(self) -> int:
        return max(0, self.end_sample - self.start_sample)

    def as_payload(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "label": self.label,
            "cycle": self.cycle,
            "step_index": self.step_index,
            "start_time": round(self.start_time, 3),
            "end_time": round(self.end_time, 3),
            "duration": round(self.duration, 3),
            "start_sample": self.start_sample,
            "end_sample": self.end_sample,
            "samples": self.samples,
            "truncated": self.truncated,
            "discarded": self.discarded,
        }


@dataclass(slots=True)
class _Boundary:
    at: float
    kind: str  # "open" | "close"
    label: str = ""
    cycle: int = 0
    step_index: int = -1
    speak: str | None = None
    truncated: bool = False


def slugify(name: str) -> str:
    """A filesystem-safe stem that still reads like the name the operator typed."""
    cleaned = [ch if (ch.isalnum() or ch in "-_") else "-" for ch in name.strip().lower()]
    slug = "".join(cleaned).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return (slug or "dataset")[:60]


def unique_dir(root: Path, base: str) -> Path:
    """``root/base``, or ``root/base-2``, … so two runs never overwrite each other."""
    candidate = root / base
    suffix = 1
    while candidate.exists():
        suffix += 1
        candidate = root / f"{base}-{suffix}"
    return candidate


class DatasetRecorder:
    """Streams one recording to disk, with sample-exact state boundaries."""

    def __init__(
        self,
        root: Path,
        name: str,
        *,
        fs: float = FS,
        channels: tuple[str, ...] = CHANNELS,
        meta: dict[str, Any] | None = None,
    ) -> None:
        self.fs = fs
        self.channels = channels
        stamp = time.strftime("%Y-%m-%d_%H-%M-%S")
        self.dir = unique_dir(root, f"{slugify(name)}_{stamp}")
        self.dir.mkdir(parents=True, exist_ok=False)

        self.eeg_path = self.dir / EEG_FILENAME
        self.labels_path = self.dir / LABELS_FILENAME
        self.meta_path = self.dir / META_FILENAME
        self.events_path = self.dir / EVENTS_FILENAME

        self.name = name
        self.scope_id = self.dir.name
        self.meta: dict[str, Any] = dict(meta or {})
        self.started_wall = time.time()

        self._csv: TextIO = self.eeg_path.open("w", newline="", encoding="utf-8")
        self._writer = csv.writer(self._csv)
        self._writer.writerow(["t", *[f"{c}_uV" for c in channels]])
        self._events: TextIO = self.events_path.open("w", encoding="utf-8")

        self._epoch = math.inf  # nothing is written until begin() is called
        self._written = 0
        self._pending: list[_Boundary] = []
        self._segments: list[Segment] = []
        self._open: Segment | None = None
        self._last_flush = time.monotonic()
        self._dropped_chunks = 0
        self.finalised = False
        self._write_meta(state="armed")

    # ------------------------------------------------------------------ writing
    def begin(self, epoch_stream_time: float) -> None:
        """Start recording at this stream time. Everything before it is discarded."""
        self._epoch = float(epoch_stream_time)
        self._event("begin", {"epoch": round(self._epoch, 4)})
        self._write_meta(state="recording")

    def note_dropped_chunk(self) -> None:
        """A chunk reached the recorder too late to be written.

        Counted and reported rather than hidden: a dataset with gaps that does not
        say so is worse than one that admits it.
        """
        self._dropped_chunks += 1

    def request_open(
        self,
        at: float,
        label: str,
        *,
        cycle: int = 0,
        step_index: int = -1,
        speak: str | None = None,
    ) -> None:
        """Queue a state boundary, in absolute stream seconds.

        Applied by the writer as it passes ``at``, so a boundary is sample-exact even
        though the runner can only ask for it between two polls.
        """
        self._pending.append(
            _Boundary(
                at=float(at),
                kind="open",
                label=label,
                cycle=cycle,
                step_index=step_index,
                speak=speak,
            )
        )
        self._pending.sort(key=lambda b: b.at)

    def request_close(self, at: float, *, truncated: bool = False) -> None:
        """Queue the end of the current state."""
        self._pending.append(_Boundary(at=float(at), kind="close", truncated=truncated))
        self._pending.sort(key=lambda b: b.at)

    def append(self, uv: FloatArray, t0: float) -> int:
        """Write the rows of a chunk that fall at or after the recording epoch.

        Row times and queued boundaries are both compared in **absolute stream seconds**
        — the same clock the source stamps chunks with. Only the ``t`` column written to
        the file is relative to the epoch. Comparing a relative row time against an
        absolute boundary silently shifts every state by the length of the stream so
        far, which is exactly the kind of bug that produces a plausible-looking dataset
        with the wrong labels on it.
        """
        if self.finalised or uv.shape[0] == 0:
            return 0
        written = 0
        n = int(uv.shape[0])
        absolute = t0 + np.arange(n) / self.fs
        for i in range(n):
            t_abs = float(absolute[i])
            if t_abs < self._epoch:
                continue
            self._apply_pending(t_abs)
            self._writer.writerow(
                [f"{t_abs - self._epoch:.4f}", *[f"{float(v):.3f}" for v in uv[i]]]
            )
            self._written += 1
            written += 1
        now = time.monotonic()
        if now - self._last_flush >= FLUSH_SECONDS:
            self.flush()
        return written

    def _apply_pending(self, upto: float) -> None:
        while self._pending and self._pending[0].at <= upto:
            boundary = self._pending.pop(0)
            if boundary.kind == "open":
                self._open_segment(boundary)
            else:
                self._close_segment(boundary)

    def _open_segment(self, boundary: _Boundary) -> None:
        if self._open is not None:  # a state that was never closed; close it here
            self._close_segment(_Boundary(at=boundary.at, kind="close"))
        self._open = Segment(
            index=len(self._segments),
            label=boundary.label,
            cycle=boundary.cycle,
            step_index=boundary.step_index,
            start_time=max(0.0, boundary.at - self._epoch),
            end_time=max(0.0, boundary.at - self._epoch),
            start_sample=self._written,
            end_sample=self._written,
            speak=boundary.speak,
        )
        self._event("open", self._open.as_payload())

    def _close_segment(self, boundary: _Boundary) -> None:
        if self._open is None:
            return
        self._open.end_time = max(self._open.start_time, boundary.at - self._epoch)
        self._open.end_sample = self._written
        self._open.truncated = boundary.truncated
        if self._open.samples > 0:
            self._segments.append(self._open)
            self._event("close", self._open.as_payload())
        else:
            self._event("close-empty", {"label": self._open.label})
        self._open = None

    # ------------------------------------------------------------------- output
    def _event(self, kind: str, payload: dict[str, Any]) -> None:
        record = {"at": round(time.time(), 4), "kind": kind, **payload}
        self._events.write(json.dumps(record) + "\n")

    def flush(self) -> None:
        if self.finalised or self._csv.closed:
            return
        try:
            self._csv.flush()
            self._events.flush()
            os.fsync(self._csv.fileno())
        except (OSError, ValueError):
            pass
        self._last_flush = time.monotonic()

    def _write_meta(self, *, state: str, extra: dict[str, Any] | None = None) -> None:
        payload = {
            "id": self.scope_id,
            "name": self.name,
            "kind": "dataset",
            "state": state,
            "fs": self.fs,
            "channels": list(self.channels),
            "started": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self.started_wall)),
            "samples": self._written,
            "segments": len(self._segments),
            "dropped_chunks": self._dropped_chunks,
            **self.meta,
        }
        if extra:
            payload.update(extra)
        with contextlib.suppress(OSError):
            # Metadata is nice to have; a dataset whose meta could not be written is
            # still a dataset, and failing the session over it would be worse.
            self.meta_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def state(self) -> dict[str, Any]:
        return {
            "id": self.scope_id,
            "name": self.name,
            "path": str(self.dir),
            "samples": self._written,
            "duration": round(self._written / self.fs, 2),
            "segments": len(self._segments),
            "current_label": self._open.label if self._open else None,
            "dropped_chunks": self._dropped_chunks,
            "recording": not self.finalised,
        }

    # ---------------------------------------------------------------- finalising
    def finalize(self, *, discard_tail: int = 0, outcome: str = "completed") -> dict[str, Any]:
        """Close the file, drop the trailing states, and write labels and metadata.

        ``discard_tail`` marks that many trailing *recordable* states as discarded —
        the interrupted one and the ones before it that the operator has already
        compromised by reaching for the stop button. Discarded rows are physically
        removed from ``eeg.csv``, not merely annotated.
        """
        if self.finalised:
            return self.summary()
        self._apply_pending(math.inf)
        if self._open is not None:
            self._close_segment(
                _Boundary(at=self._epoch + self._written / self.fs, kind="close", truncated=True)
            )

        recordable = [s for s in self._segments if s.step_index >= 0]
        if discard_tail > 0 and recordable:
            cutoff = recordable[max(0, len(recordable) - discard_tail)].index
            for segment in self._segments:
                if segment.index >= cutoff:
                    segment.discarded = True

        kept = [s for s in self._segments if not s.discarded]
        keep_rows = kept[-1].end_sample if kept else 0

        # Close the streams in the right order: the events file is still written to
        # once more (the finalize record), and the sample file is truncated afterwards.
        self._event(
            "finalize",
            {
                "outcome": outcome,
                "kept": len(kept),
                "kept_rows": keep_rows,
                "discard_tail": discard_tail,
            },
        )
        self.flush()
        try:
            self._csv.close()
            self._events.close()
        except (OSError, ValueError):
            pass

        if keep_rows < self._written:
            self._truncate(keep_rows)
        self._written = keep_rows
        self.finalised = True

        self._write_labels(kept)
        self._write_meta(
            state=outcome,
            extra={
                "outcome": outcome,
                "samples": keep_rows,
                "duration": round(keep_rows / self.fs, 2),
                "kept_segments": [s.as_payload() for s in kept],
                "discarded_segments": [s.as_payload() for s in self._segments if s.discarded],
                "labels": self.label_summary(kept),
            },
        )
        return self.summary()

    def _truncate(self, keep_rows: int) -> None:
        """Drop everything after row ``keep_rows`` from the sample file."""
        temp = self.eeg_path.with_suffix(".csv.part")
        with (
            self.eeg_path.open("r", encoding="utf-8") as source,
            temp.open("w", encoding="utf-8") as target,
        ):
            for index, line in enumerate(source):
                if index > keep_rows:  # index 0 is the header
                    break
                target.write(line)
        shutil.move(str(temp), str(self.eeg_path))

    def _write_labels(self, kept: list[Segment]) -> None:
        with self.labels_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "segment",
                    "label",
                    "cycle",
                    "step",
                    "start_sample",
                    "end_sample",
                    "start_time",
                    "end_time",
                    "duration_s",
                    "truncated",
                ]
            )
            for segment in kept:
                writer.writerow(
                    [
                        segment.index,
                        segment.label,
                        segment.cycle,
                        segment.step_index,
                        segment.start_sample,
                        segment.end_sample,
                        f"{segment.start_time:.3f}",
                        f"{segment.end_time:.3f}",
                        f"{segment.duration:.3f}",
                        int(segment.truncated),
                    ]
                )

    @staticmethod
    def label_summary(segments: list[Segment]) -> list[dict[str, Any]]:
        """Per-label totals, which is what the dataset browser shows."""
        totals: dict[str, dict[str, Any]] = {}
        for segment in segments:
            entry = totals.setdefault(
                segment.label,
                {"label": segment.label, "segments": 0, "seconds": 0.0, "samples": 0},
            )
            entry["segments"] += 1
            entry["seconds"] = round(entry["seconds"] + segment.duration, 3)
            entry["samples"] += segment.samples
        return sorted(totals.values(), key=lambda e: -e["seconds"])

    def summary(self) -> dict[str, Any]:
        kept = [s for s in self._segments if not s.discarded]
        return {
            "id": self.scope_id,
            "name": self.name,
            "path": str(self.dir),
            "fs": self.fs,
            "samples": self._written,
            "duration": round(self._written / self.fs, 2),
            "dropped_chunks": self._dropped_chunks,
            "kept_segments": [s.as_payload() for s in kept],
            "discarded_segments": [s.as_payload() for s in self._segments if s.discarded],
            "labels": self.label_summary(kept),
        }
