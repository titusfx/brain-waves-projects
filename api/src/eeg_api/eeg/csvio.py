"""Reading the CSV files this project writes.

Two layouts exist in the wild and both are read here, by header rather than by
position, exactly as ``scripts/live_view.py --replay`` does:

* ``t, F3_uV, … F4_uV``      — what this API's datasets write
* ``F3_uV, … F4_uV``         — what ``scripts/record.py`` and ``alpha_test.py`` write
* ``packet_counter, quality, F3_uV, …`` — what ``scripts/decode_to_csv.py`` writes

Keeping the reader tolerant is what makes every recording ever made by the CLI
tools replayable from the web UI.
"""

from __future__ import annotations

import csv
from collections.abc import Iterator
from pathlib import Path

import numpy as np

from eeg_api.domain.models import CHANNELS, FloatArray


def uv_column_indices(header: list[str]) -> list[int] | None:
    """Indices of the first 14 ``*_uV`` columns, or ``None`` if the header has none."""
    idx = [i for i, cell in enumerate(header) if cell.strip().endswith("_uV")]
    return idx[:14] if len(idx) >= 14 else None


def time_column_index(header: list[str]) -> int | None:
    """Index of the time column, if the file has one."""
    for i, cell in enumerate(header):
        if cell.strip().lower() in {"t", "time", "seconds", "t_s", "time_s"}:
            return i
    return None


def iter_rows(path: Path) -> Iterator[tuple[float | None, FloatArray]]:
    """Yield ``(t, 14 floats)`` per sample. Malformed rows are skipped, not fatal."""
    with path.open("r", newline="", encoding="utf-8", errors="replace") as handle:
        reader = csv.reader(handle)
        indices: list[int] | None = None
        time_index: int | None = None
        row_number = 0
        for raw in reader:
            if not raw or all(not cell.strip() for cell in raw):
                continue
            row_number += 1
            if indices is None:
                candidate = uv_column_indices(raw)
                if candidate is not None:
                    indices = candidate
                    time_index = time_column_index(raw)
                    continue
                # No header: fall back to the last 14 columns, as live_view.py does.
                indices = list(range(max(0, len(raw) - 14), len(raw)))
            try:
                values = [float(raw[i]) for i in indices]
            except (ValueError, IndexError):
                continue
            if len(values) != len(CHANNELS):
                continue
            timestamp: float | None = None
            if time_index is not None:
                try:
                    timestamp = float(raw[time_index])
                except (ValueError, IndexError):
                    timestamp = None
            yield timestamp, np.asarray(values, dtype=np.float64)


def read_all(path: Path, limit: int | None = None) -> tuple[FloatArray, FloatArray]:
    """Read a whole file into ``(samples (n, 14), times (n,))``."""
    rows: list[FloatArray] = []
    times: list[float] = []
    for index, (timestamp, values) in enumerate(iter_rows(path)):
        if limit is not None and index >= limit:
            break
        rows.append(values)
        times.append(float(index) if timestamp is None else float(timestamp))
    if not rows:
        return np.zeros((0, len(CHANNELS))), np.zeros(0)
    return np.vstack(rows), np.asarray(times, dtype=np.float64)


def count_rows(path: Path) -> int:
    """Cheap line count minus the header, for a library listing."""
    try:
        with path.open("rb") as handle:
            return max(0, sum(1 for _ in handle) - 1)
    except OSError:
        return 0
