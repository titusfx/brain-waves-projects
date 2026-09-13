#!/usr/bin/env python3
"""
recording_paths.py - one place that decides where recordings are written.

Every recording tool puts its output under `recordings/` (git-ignored: EEG is
biometric data, see AGENTS.md rule 6) with a datestamp in the name, so two runs
never overwrite each other:

    record.py      -> recordings/eeg_<YYYY-MM-DD_HH-MM-SS>.csv
    alpha_test.py  -> recordings/alpha_<YYYY-MM-DD_HH-MM-SS>.csv
    live_view.py   -> recordings/live_<YYYY-MM-DD_HH-MM-SS>/
                          eeg.csv      decoded microvolts, same format as record.py
                          screen.txt   what the viewer showed, once per refresh

Run scripts from the project root: the paths are relative to the working
directory, like everything else in scripts/.
"""

from __future__ import annotations

import os
from datetime import datetime

ROOT = "recordings"


def stamp() -> str:
    """Local timestamp, filename-safe and sortable: 2026-02-14_17-21-32."""
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def csv_path(prefix: str) -> str:
    """recordings/<prefix>_<stamp>.csv, creating recordings/ if needed."""
    os.makedirs(ROOT, exist_ok=True)
    return os.path.join(ROOT, f"{prefix}_{stamp()}.csv")


def run_dir(prefix: str) -> str:
    """recordings/<prefix>_<stamp>/, creating it if needed."""
    path = os.path.join(ROOT, f"{prefix}_{stamp()}")
    os.makedirs(path, exist_ok=True)
    return path
