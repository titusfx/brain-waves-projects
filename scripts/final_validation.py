#!/usr/bin/env python3
"""
final_validation.py - the decisive test of whether the UD2016 decode is REAL EEG.

Two things a correct decode must show that a lucky artifact cannot:

  1. CROSS-CHANNEL CORRELATION. Electrodes on a scalp pick up overlapping
     sources. Neighbouring channels (F3/F4, O1/O2, T7/T8) are strongly
     correlated. Independently-decoded noise gives ~0. If our 14 channels are
     mutually correlated at plausible levels, the layout is right.

  2. SMOOTH AUTOCORRELATION DECAY. Real band-limited signal decays gradually
     (AC1 > AC2 > AC5 ...). A misaligned decode often shows a spike at one lag
     and nothing elsewhere.

Controls: the same decode with (a) the wrong key, (b) the byte1==0x20 'extra'
packets, and (c) big-endian instead of little-endian.

Usage:
    .venv\\Scripts\\python.exe scripts\\final_validation.py
"""

from __future__ import annotations

import glob
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from test_ud2016_crypto import (  # noqa: E402
    SERIAL, load_capture, decrypt_ecb, new_crypto_key, crypto_key,
)

CAPTURE_GLOB = os.path.join("vendor", "emokit", "python",
                            "emotiv_encrypted_data_UD20160103001874_*.csv")

# emokit's field order and byte offsets (the ordering it got right)
FIELDS = [
    ("F3", 2), ("FC5", 4), ("AF3", 6), ("F7", 8), ("T7", 10), ("P7", 12),
    ("O1", 14), ("O2", 18), ("P8", 20), ("T8", 22), ("F8", 24), ("AF4", 26),
    ("FC6", 28), ("F4", 30),
]

# neighbouring pairs, for the correlation check
NEIGHBOURS = [
    ("F3", "F4"), ("FC5", "FC6"), ("AF3", "AF4"), ("F7", "F8"),
    ("T7", "T8"), ("P7", "P8"), ("O1", "O2"),
]

FS = 128.0
UV_PER_LSB = 0.51


def u16le(arr, off):
    return (arr[:, off + 1].astype(np.uint16) << 8) | arr[:, off].astype(np.uint16)


def u16be(arr, off):
    return (arr[:, off].astype(np.uint16) << 8) | arr[:, off + 1].astype(np.uint16)


def signed(v):
    v = v.astype(np.int32)
    return np.where(v & 0x8000, v - 0x10000, v).astype(np.float64)


def ac(v, lag=1):
    v = np.asarray(v, dtype=np.float64)
    if v.size < lag + 2 or v.std() == 0:
        return 0.0
    a, b = v[:-lag] - v[:-lag].mean(), v[lag:] - v[lag:].mean()
    den = np.sqrt((a * a).sum() * (b * b).sum())
    return float((a * b).sum() / den) if den else 0.0


def highpass(v, fs=FS, fc=0.5):
    """Crude single-pole highpass, to remove per-channel DC offset."""
    a = np.exp(-2 * np.pi * fc / fs)
    out = np.empty_like(v)
    y = v[0]
    for i, x in enumerate(v):
        y = a * (y + x - (v[i - 1] if i else x))
        out[i] = y
    return out


def decode(arr, subset, order="le"):
    """-> dict name -> signal array (u16 signed, cast to float)."""
    fn = u16le if order == "le" else u16be
    out = {}
    for name, off in FIELDS:
        out[name] = signed(fn(subset, off))
    return out


def report(title, sigs, expect_eeg=True):
    names = list(sigs)
    M = np.vstack([sigs[n] for n in names])
    # correlation matrix on highpassed signals
    H = np.vstack([highpass(sigs[n]) for n in names])
    C = np.corrcoef(H)

    off_diag = C[np.triu_indices(len(names), 1)]
    nb = []
    for a, b in NEIGHBOURS:
        if a in names and b in names:
            nb.append(C[names.index(a), names.index(b)])

    print(f"\n  --- {title} ---")
    print(f"  mean |cross-channel correlation| : {np.abs(off_diag).mean():+.4f}")
    print(f"  mean neighbouring-pair correlation: {np.mean(nb):+.4f}")
    print(f"  max  neighbouring-pair correlation: {np.max(nb):+.4f}")
    acs = [ac(sigs[n], 1) for n in names]
    acs2 = [ac(sigs[n], 2) for n in names]
    acs10 = [ac(sigs[n], 10) for n in names]
    print(f"  mean AC lag 1 / 2 / 10           : {np.mean(acs):+.3f} / "
          f"{np.mean(acs2):+.3f} / {np.mean(acs10):+.3f}")
    print(f"  mean amplitude (highpassed)      : "
          f"{np.mean([H[i].std() for i in range(len(names))]) * UV_PER_LSB:6.1f} uV")
    return np.abs(off_diag).mean(), np.mean(nb)


def main() -> int:
    files = sorted(glob.glob(CAPTURE_GLOB))
    if not files:
        print("[!] captures not found; run from the project root")
        return 2
    path = files[0]
    packets = load_capture(path)
    arr = np.frombuffer(b"".join(decrypt_ecb(new_crypto_key(SERIAL), p)
                                 for p in packets), dtype=np.uint8).reshape(len(packets), 32)
    wrong = np.frombuffer(b"".join(decrypt_ecb(crypto_key(SERIAL, False), p)
                                   for p in packets), dtype=np.uint8).reshape(len(packets), 32)

    eeg = arr[arr[:, 1] == 0x10]
    extra = arr[arr[:, 1] == 0x20]

    print("=" * 88)
    print("DECISIVE VALIDATION - is the UD2016 decode real EEG?")
    print("=" * 88)
    print(f"capture: {os.path.basename(path)}")
    print(f"EEG packets: {len(eeg)}   extra packets: {len(extra)}")

    print("\n" + "=" * 88)
    print("CROSS-CHANNEL CORRELATION  (real scalp EEG: neighbouring pairs strongly positive)")
    print("=" * 88)
    report("LITTLE-endian, EEG packets   <- our hypothesis", decode(arr, eeg, "le"))
    report("BIG-endian, EEG packets      (what emokit does)", decode(arr, eeg, "be"))
    report("LITTLE-endian, extra packets (control)", decode(arr, extra, "le"))
    report("LITTLE-endian, WRONG key     (control)", decode(wrong, wrong, "le"),
           expect_eeg=False)

    # per-channel detail for the winning interpretation
    print("\n" + "=" * 88)
    print("PER-CHANNEL DETAIL - little-endian, EEG packets, highpass 0.5 Hz")
    print("=" * 88)
    sigs = decode(arr, eeg, "le")
    print(f"  {'channel':>8} {'bytes':>7} {'DC offset':>11} {'amp uV':>9} "
          f"{'AC1':>7} {'AC2':>7} {'AC10':>7} {'alpha%':>8}")
    print("  " + "-" * 70)
    for name, off in FIELDS:
        s = sigs[name]
        h = highpass(s)
        # alpha share
        hw = (h - h.mean()) * np.hanning(h.size)
        P = np.abs(np.fft.rfft(hw)) ** 2
        f = np.fft.rfftfreq(h.size, 1 / FS)
        band = (f >= 1) & (f <= 45)
        alpha = (f >= 8) & (f <= 13)
        share = P[alpha].sum() / P[band].sum() if P[band].sum() else 0
        print(f"  {name:>8} {off:>3}-{off + 1:<3} {s.mean():>11.0f} "
              f"{h.std() * UV_PER_LSB:>9.1f} {ac(s, 1):>7.3f} {ac(s, 2):>7.3f} "
              f"{ac(s, 10):>7.3f} {share * 100:>7.1f}%")

    print("\n" + "=" * 88)
    print("CORRELATION MATRIX (highpassed, x100) - neighbours should be clearly positive")
    print("=" * 88)
    names = [n for n, _ in FIELDS]
    H = np.vstack([highpass(sigs[n]) for n in names])
    C = np.corrcoef(H)
    print("        " + "".join(f"{n:>7}" for n in names))
    for i, n in enumerate(names):
        print(f"  {n:>6}" + "".join(f"{C[i, j] * 100:>7.0f}" for j in range(len(names))))

    return 0


if __name__ == "__main__":
    sys.exit(main())
