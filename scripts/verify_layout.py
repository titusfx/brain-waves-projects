#!/usr/bin/env python3
"""
verify_layout.py - confirm the UD2016 new-format layout and characterise the signal.

FINDING SO FAR (see find_layout.py):
  emokit's BYTE OFFSETS are right, but it decodes them BIG-endian.
  The hardware appears to send LITTLE-endian u16.

  offsets: F3=2 FC5=4 AF3=6 F7=8 T7=10 P7=12 O1=14 | QUALITY=16 | O2=18 P8=20
           T8=22 F8=24 AF4=26 FC6=28 F4=30

  mean lag-1 autocorrelation, BE = 0.5553  ->  LE = ~0.80 (best channel 0.922)

VALIDATION
  A correctly decoded channel should show a 1/f ("pink") power spectrum - power
  falling with frequency - because that is what EEG looks like. White noise is
  flat. So we fit log-power vs log-frequency and expect a clearly negative slope.

Usage:
    .venv\\Scripts\\python.exe scripts\\verify_layout.py
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

# byte offset of each field, in packet order
LAYOUT = [
    ("F3", 2), ("FC5", 4), ("AF3", 6), ("F7", 8), ("T7", 10), ("P7", 12),
    ("O1", 14), ("QUALITY", 16), ("O2", 18), ("P8", 20), ("T8", 22),
    ("F8", 24), ("AF4", 26), ("FC6", 28), ("F4", 30),
]

FS = 128.0  # nominal sample rate


def autocorr(v):
    v = np.asarray(v, dtype=np.float64)
    if v.size < 3 or v.std() == 0:
        return 0.0
    a = v[:-1] - v[:-1].mean()
    b = v[1:] - v[1:].mean()
    den = np.sqrt((a * a).sum() * (b * b).sum())
    return float((a * b).sum() / den) if den else 0.0


def spectrum_slope(v, fs=FS):
    """Fit log10(power) vs log10(freq); EEG (pink) should be clearly negative."""
    v = np.asarray(v, dtype=np.float64)
    if v.size < 256:
        return float("nan"), float("nan")
    v = v - v.mean()
    v = v * np.hanning(v.size)
    f = np.fft.rfft(v)
    p = (np.abs(f) ** 2) / v.size
    freqs = np.fft.rfftfreq(v.size, d=1.0 / fs)
    m = (freqs >= 1.0) & (freqs <= 45.0) & (p > 0)
    if m.sum() < 8:
        return float("nan"), float("nan")
    x = np.log10(freqs[m])
    y = np.log10(p[m])
    slope = np.polyfit(x, y, 1)[0]
    # alpha-band share of total power 1-45 Hz
    alpha = (freqs >= 8) & (freqs <= 13)
    share = p[alpha].sum() / p[m].sum()
    return float(slope), float(share)


def u16le(arr, off):
    return (arr[:, off + 1].astype(np.uint16) << 8) | arr[:, off].astype(np.uint16)


def u16be(arr, off):
    return (arr[:, off].astype(np.uint16) << 8) | arr[:, off + 1].astype(np.uint16)


def signed16(v):
    v = v.astype(np.int32)
    return np.where(v & 0x8000, v - 0x10000, v)


def load(arr_path=None):
    path = arr_path or sorted(glob.glob(CAPTURE_GLOB))[0]
    packets = load_capture(path)
    dec = [decrypt_ecb(new_crypto_key(SERIAL), p) for p in packets]
    arr = np.frombuffer(b"".join(dec), dtype=np.uint8).reshape(len(dec), 32)
    return path, arr


def main() -> int:
    if not glob.glob(CAPTURE_GLOB):
        print("[!] captures not found; run from the project root")
        return 2

    path, arr = load()
    eeg = arr[arr[:, 1] == 0x10]
    extra = arr[arr[:, 1] == 0x20]
    print(f"capture: {os.path.basename(path)}")
    print(f"EEG packets (byte1==0x10): {len(eeg)}   extra (byte1==0x20): {len(extra)}")

    # ------------------------------------------------------------------ LE vs BE
    print("\n" + "=" * 100)
    print("LE vs BE, per field offset  (the layout emokit got right - the byte order it got wrong)")
    print("=" * 100)
    print(f"  {'field':>8} {'bytes':>7} {'AC big-endian':>14} {'AC little-endian':>17} {'winner':>8}")
    print("  " + "-" * 62)
    for name, off in LAYOUT:
        be = autocorr(u16be(eeg, off))
        le = autocorr(u16le(eeg, off))
        print(f"  {name:>8} {off:>3}-{off + 1:<3} {be:>14.4f} {le:>17.4f} "
              f"{'LE' if le > be else 'BE':>8}")

    # ------------------------------------------------------------------ LE detail
    print("\n" + "=" * 100)
    print("LITTLE-ENDIAN detail - amplitude and spectral character")
    print("=" * 100)
    print(f"  {'field':>8} {'AC':>8} {'std':>10} {'p1':>8} {'p50':>8} {'p99':>8} "
          f"{'PSD slope':>10} {'alpha%':>8}")
    print("  " + "-" * 78)
    acs, slopes = [], []
    for name, off in LAYOUT:
        if name == "QUALITY":
            continue
        s = signed16(u16le(eeg, off)).astype(np.float64)
        ac = autocorr(s)
        sl, share = spectrum_slope(s)
        acs.append(ac)
        if not np.isnan(sl):
            slopes.append(sl)
        print(f"  {name:>8} {ac:>8.4f} {s.std():>10.1f} {np.percentile(s, 1):>8.0f} "
              f"{np.percentile(s, 50):>8.0f} {np.percentile(s, 99):>8.0f} "
              f"{sl:>10.2f} {share * 100:>7.1f}%")
    print(f"\n  mean lag-1 autocorrelation : {np.mean(acs):.4f}")
    print(f"  mean PSD slope (log-log)   : {np.mean(slopes):.2f}"
          f"   (EEG ~ -1 to -2 ; white noise ~ 0)")
    print("  -> a clearly negative, consistent slope across channels = real band-limited signal")

    # --------------------------------------------------- control: extra packets
    print("\n" + "=" * 100)
    print("CONTROL - same offsets applied to the byte1==0x20 'extra' packets (should NOT look like EEG)")
    print("=" * 100)
    le_ac = [autocorr(signed16(u16le(eeg, off))) for _, off in LAYOUT if _ != "QUALITY"]
    ex_ac = [autocorr(signed16(u16le(extra, off))) for _, off in LAYOUT if _ != "QUALITY"]
    print(f"  EEG packets   mean AC: {np.mean(le_ac):+.4f}")
    print(f"  extra packets mean AC: {np.mean(ex_ac):+.4f}")

    # --------------------------------------------------- wrong key control
    wrong = [decrypt_ecb(crypto_key(SERIAL, False), p) for p in load_capture(path)]
    warr = np.frombuffer(b"".join(wrong), dtype=np.uint8).reshape(len(wrong), 32)
    weeg = warr[warr[:, 1] == 0x10] if (warr[:, 1] == 0x10).sum() > 100 else warr
    w_ac = [autocorr(signed16(u16le(weeg, off))) for _, off in LAYOUT if _ != "QUALITY"]
    print(f"  wrong-key     mean AC: {np.mean(w_ac):+.4f}   (n={len(weeg)})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
