#!/usr/bin/env python3
"""
monitor.py - watch the dongle and report, every few seconds, whether EEG is flowing.

Use this while physically fiddling with the headset (power button, pairing,
battery, electrode fit). It tells you the moment data starts, and immediately
checks whether the key is right.

Usage:
    .venv\\Scripts\\python.exe scripts\\monitor.py        # runs until Ctrl-C
"""

from __future__ import annotations

import sys
import time

import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, "scripts")
from read_live import find_emotiv  # noqa: E402
from test_ud2016_crypto import new_crypto_key, decrypt_ecb, crypto_key  # noqa: E402
from decode_to_csv import decode, CHANNELS  # noqa: E402


def main() -> int:
    try:
        import hid
    except ImportError:
        print("[!] pip install hidapi")
        return 2

    devs = find_emotiv(hid)
    if not devs:
        print("[!] no Emotiv dongle present at all")
        return 1
    target = next((d for d in devs if (d["product"] or "") == "EEG Signals"), devs[-1])
    serial = target["serial"]
    print(f"serial   : {serial}")
    print(f"listening: interface {target['interface']} ({target['product']!r})")
    print("waiting for data... (Ctrl-C to stop)\n", flush=True)

    h = hid.device()
    h.open_path(target["path"])

    elapsed = 0
    ever = 0
    while True:
        window = []
        t0 = time.time()
        while time.time() - t0 < 3.0:
            try:
                data = h.read(32, 250)
            except Exception as exc:
                print(f"  read error: {exc}", flush=True)
                break
            if data:
                window.append(bytes(data[:32]))
        elapsed += 3
        if window:
            ever += len(window)
            arr = np.frombuffer(b"".join(window), dtype=np.uint8).reshape(len(window), 32)
            n_new = len(np.unique(
                np.frombuffer(b"".join(decrypt_ecb(new_crypto_key(serial), r) for r in window),
                              dtype=np.uint8).reshape(len(window), 32)[:, 1]))
            n_old = len(np.unique(
                np.frombuffer(b"".join(decrypt_ecb(crypto_key(serial, False), r) for r in window),
                              dtype=np.uint8).reshape(len(window), 32)[:, 1]))
            tag = "KEY OK" if n_new <= 6 else f"KEY BAD (byte1 has {n_new} values)"
            print(f"  t={elapsed:>4}s  {len(window):>4} reports/3s  "
                  f"({len(window) / 3:.0f}/s)   new_key byte1={n_new} legacy={n_old}  {tag}",
                  flush=True)
            if len(window) >= 60:
                dec = np.frombuffer(
                    b"".join(decrypt_ecb(new_crypto_key(serial), r) for r in window),
                    dtype=np.uint8).reshape(len(window), 32)
                d = decode(dec)
                amps = [d["eeg"][:, i].std() for i in range(len(CHANNELS))]
                print("           amps uV: " +
                      " ".join(f"{c}={a:.0f}" for c, a in zip(CHANNELS, amps)), flush=True)
        else:
            print(f"  t={elapsed:>4}s  no data (total received so far: {ever})", flush=True)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nstopped")
