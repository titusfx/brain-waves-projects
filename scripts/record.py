#!/usr/bin/env python3
"""
record.py - record N seconds of live EEG from the dongle to a CSV.

Unlike read_live.py this reads ONLY the streaming interface, so the requested
duration is the real duration.

Output file:
    Omit the filename and the recording is written to its own datestamped file,

        recordings/eeg_YYYY-MM-DD_HH-MM-SS.csv

    so consecutive runs never overwrite each other. Pass a filename to force one.

Usage:
    .venv\\Scripts\\python.exe scripts\\record.py 180
    .venv\\Scripts\\python.exe scripts\\record.py 180 my_capture.csv
"""

from __future__ import annotations

import csv
import sys
import time

import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, "scripts")
from read_live import find_emotiv  # noqa: E402
from test_ud2016_crypto import new_crypto_key, decrypt_ecb  # noqa: E402
from decode_to_csv import decode, CHANNELS  # noqa: E402
from recording_paths import csv_path  # noqa: E402


def main() -> int:
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 120.0

    import hid
    devs = find_emotiv(hid)
    if not devs:
        print("[!] no dongle")
        return 1
    target = next((d for d in devs if (d["product"] or "") == "EEG Signals"), devs[-1])
    serial = target["serial"]

    # no filename given -> one datestamped file per run, never overwritten
    out = sys.argv[2] if len(sys.argv) > 2 else csv_path("eeg")

    print(f"serial {serial}  interface {target['interface']} ({target['product']})")
    print(f"recording {seconds:.0f}s -> {out}", flush=True)

    h = hid.device()
    h.open_path(target["path"])

    chunks = []
    all_reports = 0
    t0 = time.time()
    last_report = 0.0

    while time.time() - t0 < seconds:
        data = h.read(32, 200)
        if data:
            b = bytes(data[:32])
            if len(b) == 32:
                chunks.append(b)
                all_reports += 1
                last_report = time.time()
        el = time.time() - t0
        if int(el) % 10 == 0 and int(el) != getattr(main, "_last", -1):
            main._last = int(el)
            print(f"  t={el:5.0f}s  reports={all_reports:6d} ({all_reports / max(el, 1):5.0f}/s)",
                  flush=True)

    try:
        h.close()
    except Exception:
        pass

    print(f"done: {all_reports} reports in {time.time() - t0:.0f}s", flush=True)
    if not chunks:
        print("[!] nothing captured")
        return 1

    dec = np.frombuffer(b"".join(decrypt_ecb(new_crypto_key(serial), r) for r in chunks),
                        dtype=np.uint8).reshape(len(chunks), 32)
    n_b1 = len(np.unique(dec[:, 1]))
    print(f"byte1 distinct values: {n_b1}  ({'KEY OK' if n_b1 <= 6 else 'KEY BAD'})")
    d = decode(dec)
    data = d["eeg"]
    print(f"EEG samples: {len(data)}")

    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow([f"{c}_uV" for c in CHANNELS])
        for row in data:
            w.writerow([f"{v:.3f}" for v in row])
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
