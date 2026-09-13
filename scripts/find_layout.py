#!/usr/bin/env python3
"""
find_layout.py - reverse-engineer the 14-bit/16-bit EEG field layout of the
UD2016 "new format" packets.

BACKGROUND
----------
We know (see ud2016-crypto-crack): the key is right, packets are 32 bytes,
byte0 = counter, byte1 = packet type (0x10 = EEG, 0x20 = extra), bytes 2..31 =
30 bytes = 15 x 16-bit fields = 14 channels + 1 quality field.

emokit ships a HYPOTHESIS for this in sensors_16_bytes:

    F3:[2,3] FC5:[4,5] AF3:[6,7] F7:[8,9] T7:[10,11] P7:[12,13] O1:[14,15]
    QUALITY:[16,17]
    O2:[18,19] P8:[20,21] T8:[22,23] F8:[24,25] AF4:[26,27] FC6:[28,29] F4:[30,31]

This script tests that hypothesis, then brute-forces alternatives.

THE OBJECTIVE FUNCTION
----------------------
Lag-1 autocorrelation. Real EEG is band-limited (0.2-45 Hz) and sampled at
128/256 Hz, so consecutive samples are nearly identical: a correctly decoded
channel should score > 0.9. Random/garbage ~0.0. With n=2134 packets the noise
floor is about +/- 0.022, so anything above ~0.3 is already meaningful.

Usage:
    .venv\\Scripts\\python.exe scripts\\find_layout.py
"""

from __future__ import annotations

import glob
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from test_ud2016_crypto import (  # noqa: E402
    SERIAL, load_capture, decrypt_ecb, new_crypto_key,
)

CAPTURE_GLOB = os.path.join("vendor", "emokit", "python",
                            "emotiv_encrypted_data_UD20160103001874_*.csv")

# emokit's hypothesis, from vendor/emokit/python/emokit/sensors.py
EMOKIT_16_BYTES = {
    "F3": 2, "FC5": 4, "AF3": 6, "F7": 8, "T7": 10, "P7": 12, "O1": 14,
    "O2": 18, "P8": 20, "T8": 22, "F8": 24, "AF4": 26, "FC6": 28, "F4": 30,
}
QUALITY_OFFSET = 16


def autocorr(v: np.ndarray) -> float:
    """Lag-1 autocorrelation."""
    v = np.asarray(v, dtype=np.float64)
    if v.size < 3 or v.std() == 0:
        return 0.0
    a, b = v[:-1], v[1:]
    a = a - a.mean()
    b = b - b.mean()
    den = np.sqrt((a * a).sum() * (b * b).sum())
    return float((a * b).sum() / den) if den else 0.0


def load_eeg_packets() -> np.ndarray:
    """Decrypt the first capture and return ONLY the byte1==0x10 (EEG) packets."""
    path = sorted(glob.glob(CAPTURE_GLOB))[0]
    packets = load_capture(path)
    dec = [decrypt_ecb(new_crypto_key(SERIAL), p) for p in packets]
    arr = np.frombuffer(b"".join(dec), dtype=np.uint8).reshape(len(dec), 32)
    eeg = arr[arr[:, 1] == 0x10]
    print(f"capture : {os.path.basename(path)}")
    print(f"packets : {len(arr)} total, {len(eeg)} with byte1==0x10 (EEG)")
    print(f"dtype   : uint8, shape {eeg.shape}")
    return eeg


def fields_be(eeg: np.ndarray, offset: int) -> np.ndarray:
    """Big-endian u16 at a byte offset."""
    return (eeg[:, offset].astype(np.uint16) << 8) | eeg[:, offset + 1].astype(np.uint16)


def fields_le(eeg: np.ndarray, offset: int) -> np.ndarray:
    """Little-endian u16 at a byte offset."""
    return (eeg[:, offset + 1].astype(np.uint16) << 8) | eeg[:, offset].astype(np.uint16)


def to_signed(v: np.ndarray, bits: int = 16) -> np.ndarray:
    v = v.astype(np.int32)
    return np.where(v & (1 << (bits - 1)), v - (1 << bits), v)


def describe(name: str, v: np.ndarray) -> dict:
    s = to_signed(v, 16)
    return {
        "name": name,
        "ac1": autocorr(v),
        "mean": float(s.mean()),
        "p1": float(np.percentile(s, 1)),
        "p50": float(np.percentile(s, 50)),
        "p99": float(np.percentile(s, 99)),
        "std": float(s.std()),
    }


# --------------------------------------------------------------------------- #
def part1_emokit_hypothesis(eeg: np.ndarray) -> None:
    print("\n" + "=" * 96)
    print("PART 1 - emokit's sensors_16_bytes hypothesis (byte-aligned u16 BE from byte 2)")
    print("=" * 96)
    print(f"  {'channel':>8} {'bytes':>7} {'lag-1 AC':>10} {'mean':>10} {'p1':>9} "
          f"{'p50':>9} {'p99':>9} {'std':>9}")
    print("  " + "-" * 84)
    acs = []
    for name, off in EMOKIT_16_BYTES.items():
        v = fields_be(eeg, off)
        d = describe(name, v)
        acs.append(d["ac1"])
        print(f"  {name:>8} {off:>3}-{off + 1:<3} {d['ac1']:>10.4f} {d['mean']:>10.1f} "
              f"{d['p1']:>9.0f} {d['p50']:>9.0f} {d['p99']:>9.0f} {d['std']:>9.1f}")
    v = fields_be(eeg, QUALITY_OFFSET)
    d = describe("QUALITY", v)
    print(f"  {'QUALITY':>8} {QUALITY_OFFSET:>3}-{QUALITY_OFFSET + 1:<3} "
          f"{d['ac1']:>10.4f} {d['mean']:>10.1f} {d['p1']:>9.0f} {d['p50']:>9.0f} "
          f"{d['p99']:>9.0f} {d['std']:>9.1f}")
    print(f"\n  mean AC across 14 channels: {np.mean(acs):.4f}"
          f"   min={np.min(acs):.4f}  max={np.max(acs):.4f}")
    print("  (>0.9 = correctly decoded EEG;  ~0 = noise;  noise floor +/-0.022)")


# --------------------------------------------------------------------------- #
def part2_byte_aligned_search(eeg: np.ndarray) -> None:
    print("\n" + "=" * 96)
    print("PART 2 - brute force: every byte-aligned u16 window, ranked by autocorrelation")
    print("=" * 96)
    rows = []
    for off in range(2, 31):
        for label, fn in (("BE", fields_be), ("LE", fields_le)):
            v = fn(eeg, off)
            rows.append((autocorr(v), label, off))
    rows.sort(reverse=True)
    print(f"  {'rank':>4} {'AC':>9} {'order':>6} {'bytes':>7}")
    print("  " + "-" * 32)
    for i, (ac, label, off) in enumerate(rows[:24], 1):
        star = "  <== EEG-like" if ac > 0.9 else ("  <- candidate" if ac > 0.3 else "")
        print(f"  {i:>4} {ac:>9.4f} {label:>6} {off:>3}-{off + 1:<3}{star}")


# --------------------------------------------------------------------------- #
def part3_bit_level_search(eeg: np.ndarray, width: int) -> None:
    print("\n" + "=" * 96)
    print(f"PART 3 - bit-level search, field width = {width} bits "
          f"(both bit orders), ranked by autocorrelation")
    print("=" * 96)
    for bitorder in ("big", "little"):
        bits = np.unpackbits(eeg, axis=1, bitorder=bitorder)
        weights = (1 << np.arange(width - 1, -1, -1)).astype(np.int64)
        rows = []
        for off in range(16, 256 - width + 1):   # payload starts after byte 1
            v = bits[:, off:off + width].astype(np.int64) @ weights
            rows.append((autocorr(v), off))
        rows.sort(reverse=True)
        print(f"\n  bitorder='{bitorder}'  (top 10)")
        print(f"  {'rank':>4} {'AC':>9} {'start bit':>10} {'byte.bit':>9}")
        print("  " + "-" * 36)
        for i, (ac, off) in enumerate(rows[:10], 1):
            star = "  <== EEG-like" if ac > 0.9 else ""
            print(f"  {i:>4} {ac:>9.4f} {off:>10} {off // 8}.{off % 8:<6}{star}")


# --------------------------------------------------------------------------- #
def part4_cross_capture() -> None:
    """If the layout is right it must hold on ALL captures, not just the first."""
    print("\n" + "=" * 96)
    print("PART 4 - cross-validation: does emokit's hypothesis hold on every capture?")
    print("=" * 96)
    for path in sorted(glob.glob(CAPTURE_GLOB)):
        packets = load_capture(path)
        dec = [decrypt_ecb(new_crypto_key(SERIAL), p) for p in packets]
        arr = np.frombuffer(b"".join(dec), dtype=np.uint8).reshape(len(dec), 32)
        eeg = arr[arr[:, 1] == 0x10]
        if len(eeg) < 100:
            print(f"  {os.path.basename(path)[:58]:<58} too few EEG packets")
            continue
        acs = [autocorr(fields_be(eeg, off)) for off in EMOKIT_16_BYTES.values()]
        q = autocorr(fields_be(eeg, QUALITY_OFFSET))
        print(f"  {os.path.basename(path)[:58]:<58} n={len(eeg):>5}  "
              f"mean AC={np.mean(acs):+.4f}  min={np.min(acs):+.4f}  "
              f"max={np.max(acs):+.4f}  QUALITY={q:+.4f}")


def main() -> int:
    if not glob.glob(CAPTURE_GLOB):
        print("[!] captures not found; run from the project root")
        return 2
    eeg = load_eeg_packets()
    part1_emokit_hypothesis(eeg)
    part2_byte_aligned_search(eeg)
    part3_bit_level_search(eeg, 14)
    part3_bit_level_search(eeg, 16)
    part4_cross_capture()
    return 0


if __name__ == "__main__":
    sys.exit(main())
