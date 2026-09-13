#!/usr/bin/env python3
"""
check_layout_live.py - verify the UD2016 field layout against the REAL dongle.

Captures live reports, decrypts with new_crypto_key, then reproduces the
byte-level diagnostic that identified the layout in the first place:

  * per-byte distinct-value count -- high bytes should be near-constant,
    low bytes should vary
  * per-byte lag-1 autocorrelation
  * per field: little-endian vs big-endian lag-1 autocorrelation

If the layout holds on this unit, odd bytes should have a handful of distinct
values and low-endian should beat big-endian field by field.

Usage:
    .venv\\Scripts\\python.exe scripts\\check_layout_live.py [seconds]
"""

from __future__ import annotations

import sys
from collections import Counter

import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, "scripts")
from test_ud2016_crypto import new_crypto_key, decrypt_ecb  # noqa: E402
from read_live import find_emotiv, capture, autocorr        # noqa: E402
from decode_to_csv import FIELDS                            # noqa: E402

REPORT_LEN = 32


def main() -> int:
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 8.0

    import hid
    devs = find_emotiv(hid)
    if not devs:
        print("[!] no dongle")
        return 1
    serial = devs[0]["serial"]
    # prefer the interface that actually streams
    target = next((d for d in devs if (d["product"] or "") == "EEG Signals"), devs[-1])
    print(f"serial: {serial}")
    print(f"reading {seconds:.0f}s from interface {target['interface']} "
          f"({target['product']!r})...")

    reports = capture(hid, target, seconds)
    print(f"got {len(reports)} reports ({len(reports) / seconds:.0f}/s)")
    if len(reports) < 50:
        print("[!] not enough data")
        return 1

    dec = np.frombuffer(b"".join(decrypt_ecb(new_crypto_key(serial), r)
                                 for r in reports), dtype=np.uint8).reshape(len(reports), REPORT_LEN)
    eeg = dec[dec[:, 1] == 0x10]
    print(f"EEG packets (byte1==0x10): {len(eeg)}  of {len(dec)}\n")

    print("=" * 88)
    print("PER-BYTE: distinct values / Shannon entropy / lag-1 autocorrelation")
    print("=" * 88)
    print(f"{'byte':>4} {'distinct':>9} {'top 2 values':>26} {'entropy':>8} {'lag-1 AC':>9}")
    print("-" * 62)
    for i in range(REPORT_LEN):
        col = eeg[:, i]
        vals, cnts = np.unique(col, return_counts=True)
        order = np.argsort(-cnts)
        top = " ".join(f"0x{vals[j]:02X}({cnts[j]})" for j in order[:2])
        p = cnts / cnts.sum()
        ent = float(-(p * np.log2(p)).sum())
        mark = ""
        if i > 0 and len(vals) <= 4:
            mark = "  <- marker/high byte"
        print(f"{i:>4} {len(vals):>9} {top:>26} {ent:>8.3f} "
              f"{autocorr(col.astype(float)):>9.4f}{mark}")

    print("\n" + "=" * 88)
    print("PER FIELD: little-endian vs big-endian lag-1 autocorrelation")
    print("=" * 88)

    def u16(off, order):
        if order == "le":
            return (eeg[:, off + 1].astype(np.uint16) << 8) | eeg[:, off].astype(np.uint16)
        return (eeg[:, off].astype(np.uint16) << 8) | eeg[:, off + 1].astype(np.uint16)

    print(f"{'field':>8} {'bytes':>7} {'LE AC':>9} {'BE AC':>9} {'winner':>7}")
    print("-" * 44)
    le_wins = 0
    for name, off in FIELDS:
        le = autocorr(u16(off, "le").astype(float))
        be = autocorr(u16(off, "be").astype(float))
        if le > be:
            le_wins += 1
        print(f"{name:>8} {off:>3}-{off + 1:<3} {le:>9.4f} {be:>9.4f} "
              f"{'LE' if le > be else 'BE':>7}")
    print(f"\nlittle-endian wins {le_wins}/{len(FIELDS)} fields")
    print("(if LE wins most fields, the layout transfers to this dongle unchanged)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
