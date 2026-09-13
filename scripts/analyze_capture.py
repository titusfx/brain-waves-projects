#!/usr/bin/env python3
"""
analyze_capture.py - deeper analysis of the emokit UD2016 captures.

The first pass (test_ud2016_crypto.py) found something surprising:

    new_crypto_key(UD20160103001874)  ->  33.81% sequential counters
    random baseline                   ->   0.78%

43x the chance rate, identical across all three captures, and the first counters
look like [16, 74, 21, 22, 75, 23, 24, 76] - i.e. TWO interleaved incrementing
sequences. That is structure, so the crypto is probably RIGHT and our model of
the packet stream is wrong.

Hypotheses tested here:
  H1  The two HID interfaces are interleaved in the capture (split by parity).
  H2  The counter advances every 2nd report (256 Hz transport / 128 Hz samples).
  H3  Byte 0 is genuinely structured -> per-position entropy will be < 8 bits.
  H4  A wrong key gives ~8.0 bits entropy at every byte position (control).

Usage:
    .venv\\Scripts\\python.exe scripts\\analyze_capture.py
"""

from __future__ import annotations

import glob
import math
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from test_ud2016_crypto import (  # noqa: E402
    SERIAL, load_capture, decrypt_ecb, new_crypto_key, crypto_key,
)

CAPTURE_GLOB = os.path.join("vendor", "emokit", "python",
                            "emotiv_encrypted_data_UD20160103001874_*.csv")


def entropy(values) -> float:
    total = len(values)
    if not total:
        return 0.0
    counts = Counter(values)
    return -sum((c / total) * math.log2(c / total) for c in counts.values())


def seq_ratio(counters, mod=128, step=1) -> float:
    if len(counters) < 2:
        return 0.0
    hits = sum(1 for a, b in zip(counters, counters[1:]) if (b - a) % mod == step)
    return hits / (len(counters) - 1)


def report(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def main() -> int:
    files = sorted(glob.glob(CAPTURE_GLOB))
    if not files:
        print("[!] captures not found; run from the project root")
        return 2

    path = files[0]
    packets = load_capture(path)
    print(f"capture: {os.path.basename(path)}  ({len(packets)} reports of "
          f"{len(packets[0])} bytes)")

    good = [decrypt_ecb(new_crypto_key(SERIAL), p) for p in packets]
    bad = [decrypt_ecb(crypto_key(SERIAL, False), p) for p in packets]

    # ---------------------------------------------------------------- H3/H4
    report("H3/H4  per-byte-position entropy  (8.00 bits = perfectly random)")
    print(f"  {'byte':>4}  {'new_crypto_key':>14}  {'legacy (control)':>16}   delta")
    print("  " + "-" * 52)
    total_drop = 0.0
    for i in range(len(good[0])):
        e_good = entropy([p[i] for p in good])
        e_bad = entropy([p[i] for p in bad])
        drop = e_bad - e_good
        total_drop += drop
        flag = "  <-- structured" if drop > 0.25 else ""
        print(f"  {i:>4}  {e_good:>14.3f}  {e_bad:>16.3f}   {drop:>+6.3f}{flag}")
    print(f"\n  total entropy drop vs control: {total_drop:.2f} bits over "
          f"{len(good[0])} byte positions")
    print("  (a wrong key would give ~0.00 total drop)")

    # ------------------------------------------------------------------ H1
    report("H1  split by parity - are two HID interfaces interleaved?")
    for label, subset in (("even-indexed", good[0::2]), ("odd-indexed", good[1::2])):
        c = [p[0] & 0x7F for p in subset]
        print(f"  {label:<14} n={len(c):>5}  seq(+1)={seq_ratio(c) * 100:6.2f}%  "
              f"first={c[:10]}")

    # ------------------------------------------------------------------ H2
    report("H2  does the counter advance every 2nd report?")
    for label, subset in (("full stream", good),
                          ("even-indexed", good[0::2]),
                          ("odd-indexed", good[1::2])):
        c = [p[0] & 0x7F for p in subset]
        print(f"  {label:<14}  step+1={seq_ratio(c, step=1) * 100:6.2f}%   "
              f"step+2={seq_ratio(c, step=2) * 100:6.2f}%")

    # -------------------------------------------------------- byte0 detail
    report("byte 0 detail (new_crypto_key)")
    raw0 = [p[0] for p in good]
    print(f"  high bit set (battery?) : {sum(1 for b in raw0 if b & 0x80) / len(raw0) * 100:.2f}%"
          f"   (expected ~0.78% if 1/sec at 128Hz)")
    print(f"  low 7 bits (counter) range: {min(b & 0x7F for b in raw0)}..{max(b & 0x7F for b in raw0)}")
    print(f"  byte0 entropy: {entropy(raw0):.3f} of 8.0 bits")
    print(f"  most common byte0 values: {Counter(raw0).most_common(8)}")

    # ------------------------------------------- do consecutive reports repeat?
    report("are consecutive reports duplicated / paired?")
    dup = sum(1 for a, b in zip(good, good[1:]) if a == b)
    dup2 = sum(1 for a, b in zip(good, good[2:]) if a == b)
    print(f"  identical to next      : {dup}")
    print(f"  identical to +2        : {dup2}")

    # ------------------------------------------ EEG field structure (best test)
    report("EEG field sanity - emokit masks applied to byte 0..1 as a 14-bit field")
    for off in range(0, 8):
        vals = []
        for p in good[:1500]:
            w = ((p[off] << 8) | p[off + 1]) if off + 1 < len(p) else 0
            vals.append(w & 0x3FFF)
        mean = sum(vals) / len(vals)
        print(f"  offset {off:>2}: mean={mean:8.1f}  min={min(vals):6d}  "
              f"max={max(vals):6d}  entropy={entropy(vals):.2f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
