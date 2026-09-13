#!/usr/bin/env python3
"""
decode_capture.py - decode the decrypted UD2016 capture with emokit's own packet
classes and determine which interpretation yields real EEG.

DECISIVE TESTS
--------------
1. byte[1] distribution must match emokit's is_extra_data() test (== 0x20).
2. Real EEG is strongly autocorrelated in time. Decrypting with the WRONG key
   gives white noise, whose lag-1 autocorrelation is ~0. A correct decode of
   band-limited EEG at 128 Hz gives lag-1 autocorrelation well above 0.9.
   Autocorrelation cannot be faked by structural coincidence - it is the test.

Usage:
    .venv\\Scripts\\python.exe scripts\\decode_capture.py
"""

from __future__ import annotations

import glob
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from test_ud2016_crypto import (  # noqa: E402
    SERIAL, load_capture, decrypt_ecb, new_crypto_key, crypto_key,
)

sys.path.insert(0, os.path.join("vendor", "emokit", "python"))
from emokit.packet import EmotivNewPacket, EmotivOldPacket  # noqa: E402
from emokit.sensors import sensors_mapping  # noqa: E402

CAPTURE_GLOB = os.path.join("vendor", "emokit", "python",
                            "emotiv_encrypted_data_UD20160103001874_*.csv")


def autocorr(series) -> float:
    """Lag-1 Pearson autocorrelation."""
    n = len(series)
    if n < 3:
        return 0.0
    mean = sum(series) / n
    num = sum((series[i] - mean) * (series[i + 1] - mean) for i in range(n - 1))
    den = sum((x - mean) ** 2 for x in series)
    return num / den if den else 0.0


def try_packet_class(cls, packets, limit=1500):
    """Instantiate a packet class over decrypted packets; collect channel series."""
    series = {name: [] for name in sensors_mapping if name not in ("Unknown",)}
    counters, errors, batteries = [], 0, 0
    values_flat = []

    for raw in packets[:limit]:
        try:
            pkt = cls(raw)
        except Exception:
            errors += 1
            continue
        c = getattr(pkt, "counter", None)
        if isinstance(c, int):
            counters.append(c)
        if getattr(pkt, "battery", None) is not None:
            batteries += 1
        for name in series:
            try:
                v = pkt.sensors[name]["value"]
            except Exception:
                continue
            # emokit's sensor dict occasionally carries non-numeric entries.
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                continue
            series[name].append(float(v))
            values_flat.append(float(v))

    stats = {}
    for name, s in series.items():
        if len(s) >= 50:
            stats[name] = {
                "n": len(s),
                "mean": sum(s) / len(s),
                "min": min(s),
                "max": max(s),
                "ac1": autocorr(s),
            }
    mag = sorted(abs(v) for v in values_flat) or [0]
    return {
        "counters": counters,
        "errors": errors,
        "batteries": batteries,
        "stats": stats,
        "median_abs": mag[len(mag) // 2],
        "max_abs": mag[-1],
    }


def summarize(label, res):
    print(f"\n  --- {label} ---")
    print(f"  packets parsed: {len(res['counters'])}   errors: {res['errors']}   "
          f"battery events: {res['batteries']}")
    print(f"  |value| median: {res['median_abs']:.1f} uV   max: {res['max_abs']:.1f} uV")
    if res["counters"]:
        print(f"  counter range: {min(res['counters'])}..{max(res['counters'])}")
    if not res["stats"]:
        print("  (no channel series produced)")
        return
    print(f"\n  {'channel':>8} {'n':>6} {'mean':>10} {'min':>10} {'max':>10} {'lag-1 autocorr':>16}")
    print("  " + "-" * 68)
    for name, s in list(res["stats"].items()):
        print(f"  {name:>8} {s['n']:>6} {s['mean']:>10.1f} {s['min']:>10.1f} "
              f"{s['max']:>10.1f} {s['ac1']:>16.4f}")
    acs = [s["ac1"] for s in res["stats"].values()]
    print(f"\n  mean lag-1 autocorrelation across channels: {sum(acs) / len(acs):.4f}")
    print("  (>0.9 = real band-limited signal; ~0.0 = noise)")


def main() -> int:
    files = sorted(glob.glob(CAPTURE_GLOB))
    if not files:
        print("[!] captures not found; run from the project root")
        return 2
    packets = load_capture(files[0])
    print(f"capture: {os.path.basename(files[0])}")
    print(f"reports: {len(packets)} x {len(packets[0])} bytes")

    correct = [decrypt_ecb(new_crypto_key(SERIAL), p) for p in packets]
    wrong = [decrypt_ecb(crypto_key(SERIAL, False), p) for p in packets]

    print("\n" + "=" * 78)
    print("TEST 1 - byte[1] vs emokit's is_extra_data() (expects 0x20 == 32)")
    print("=" * 78)
    for label, data in (("correct key", correct), ("wrong key (control)", wrong)):
        hist = Counter(p[1] for p in data).most_common(5)
        print(f"  {label:<22} byte[1] top values: {hist}")

    print("\n" + "=" * 78)
    print("TEST 2 - temporal structure (autocorrelation) per packet interpretation")
    print("=" * 78)
    summarize("EmotivNewPacket + CORRECT key",
              try_packet_class(EmotivNewPacket, correct))
    summarize("EmotivOldPacket + CORRECT key",
              try_packet_class(EmotivOldPacket, correct))
    summarize("EmotivNewPacket + WRONG key (control)",
              try_packet_class(EmotivNewPacket, wrong))

    return 0


if __name__ == "__main__":
    sys.exit(main())
