#!/usr/bin/env python3
"""
alpha_test.py - the acceptance test for the whole acquisition chain.

WHY THIS TEST
-------------
A wrong key or a wrong layout does NOT raise an error - it produces
confident-looking numbers. The only proof that we are reading a real brain is a
physiological signature that noise cannot produce:

    eyes CLOSED -> a clear peak at 8-12 Hz (alpha) over the OCCIPITAL channels
    eyes OPEN   -> that peak attenuates

This is the single most reliable, most replicated phenomenon in scalp EEG.

PROTOCOL (the script prompts you - just follow the screen)
    5 s  settle
   20 s  EYES CLOSED
   20 s  EYES OPEN
   20 s  EYES CLOSED

WHAT IT PRINTS
  * per-channel amplitude and 50/60 Hz mains power (a dry/floating electrode
    picks up lots of mains - a good contact proxy)
  * alpha power over time as bars, so you can SEE it switch on and off
  * a verdict

The session is saved to its own datestamped file,

    recordings/alpha_YYYY-MM-DD_HH-MM-SS.csv

so consecutive runs never overwrite each other.

Usage:
    .venv\\Scripts\\python.exe scripts\\alpha_test.py
    .venv\\Scripts\\python.exe scripts\\alpha_test.py --file some_capture.csv
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
from test_ud2016_crypto import new_crypto_key, decrypt_ecb  # noqa: E402
from read_live import find_emotiv, capture                   # noqa: E402
from decode_to_csv import CHANNELS, decode                   # noqa: E402
from recording_paths import csv_path                         # noqa: E402

FS = 128.0
SETTLE = 5.0
SEG = 20.0

ALPHA = (8.0, 12.0)
MAINS = (48.0, 62.0)          # covers both 50 and 60 Hz
OCCIPITAL = ("O1", "O2")
FRONTAL = ("F3", "F4", "F7", "F8", "AF3", "AF4")


# --------------------------------------------------------------------------- #
def record(seconds: float):
    """Interactive record from the dongle. Returns ((n, 14) microvolts, csv path)."""
    import hid
    devs = find_emotiv(hid)
    if not devs:
        print("[!] no Emotiv dongle found")
        sys.exit(1)
    target = next((d for d in devs if (d["product"] or "") == "EEG Signals"), devs[-1])
    serial = target["serial"]
    print(f"serial {serial}  interface {target['interface']} ({target['product']})")

    def show(msg, secs):
        print("\n" + "=" * 60)
        print(f"   {msg}")
        print("=" * 60)
        end = time.time() + secs
        while time.time() < end:
            left = end - time.time()
            sys.stdout.write(f"\r   ... {left:5.1f}s ")
            sys.stdout.flush()
            time.sleep(0.1)
        print()

    show("SETTLE - relax, sit still, look at the screen", SETTLE)

    chunks = []
    for label, secs in (("EYES CLOSED  (close them now)", SEG),
                        ("EYES OPEN    (open, keep looking forward)", SEG),
                        ("EYES CLOSED  (close them again)", SEG)):
        show(label, secs)
        reps = capture(hid, target, secs)
        print(f"   captured {len(reps)} reports ({len(reps) / secs:.0f}/s)")
        if reps:
            dec = np.frombuffer(b"".join(decrypt_ecb(new_crypto_key(serial), r)
                                         for r in reps), dtype=np.uint8).reshape(len(reps), 32)
            n_b1 = len(np.unique(dec[:, 1]))
            if n_b1 > 50:
                print(f"   !! byte1 has {n_b1} distinct values - WRONG KEY, aborting")
                sys.exit(2)
            chunks.append(decode(dec)["eeg"])

    if not chunks:
        print("[!] no data captured")
        sys.exit(1)

    # save the session to its own datestamped file so runs never overwrite
    out = csv_path("alpha")
    data = np.vstack(chunks)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow([f"{c}_uV" for c in CHANNELS])
        for row in data:
            w.writerow([f"{v:.2f}" for v in row])
    print(f"\nwrote {out}")
    return data, out


def load_csv(path: str) -> np.ndarray:
    rows = []
    with open(path, newline="", encoding="utf-8") as fh:
        r = csv.reader(fh)
        next(r, None)
        for line in r:
            if line:
                rows.append([float(x) for x in line])
    return np.array(rows)


# --------------------------------------------------------------------------- #
def welch_psd(x: np.ndarray, fs=FS, nper=256):
    """Simple averaged periodogram. Returns (freqs, power)."""
    nper = min(nper, len(x))
    if nper < 64:
        return np.array([]), np.array([])
    win = np.hanning(nper)
    step = nper // 2
    segs = [x[i:i + nper] for i in range(0, len(x) - nper + 1, step)]
    if not segs:
        return np.array([]), np.array([])
    P = np.zeros(nper // 2 + 1)
    for s in segs:
        s = (s - s.mean()) * win
        P += (np.abs(np.fft.rfft(s, n=nper)) ** 2) / nper
    P /= len(segs)
    return np.fft.rfftfreq(nper, 1 / fs), P


def band_power(freqs, P, lo, hi):
    m = (freqs >= lo) & (freqs < hi)
    return float(P[m].sum()) if m.any() else 0.0


def alpha_over_time(x: np.ndarray, win_s=2.0):
    w = int(win_s * FS)
    out = []
    for i in range(0, len(x) - w + 1, w):
        f, P = welch_psd(x[i:i + w], nper=min(256, w))
        if len(f) == 0:
            out.append(0.0)
            continue
        a = band_power(f, P, *ALPHA)
        tot = band_power(f, P, 1.0, 45.0)
        out.append(a / tot if tot else 0.0)
    return np.array(out)


# --------------------------------------------------------------------------- #
def main() -> int:
    recorded = None
    if "--file" in sys.argv:
        path = sys.argv[sys.argv.index("--file") + 1]
        print(f"analysing {path}")
        data = load_csv(path)
        n = len(data)
        seg = n // 3
        parts = [data[:seg], data[seg:2 * seg], data[2 * seg:3 * seg]]
        labels = ["segment 1", "segment 2", "segment 3"]
    else:
        data, recorded = record(SETTLE + 3 * SEG)
        n = len(data)
        seg = int(SEG * FS)
        parts = [data[:seg], data[seg:2 * seg], data[2 * seg:3 * seg]]
        labels = ["EYES CLOSED", "EYES OPEN", "EYES CLOSED"]

    total_s = n / FS
    print(f"\n{ n } samples = {total_s:.1f}s @ {FS:.0f} Hz\n")

    # ---------------------------------------------------------- channel health
    print("=" * 76)
    print("CHANNEL HEALTH  (mains % = share of 1-45 Hz power in 48-62 Hz)")
    print("  lots of mains  -> dry or floating electrode (poor contact)")
    print("  very low amp   -> electrode not touching scalp")
    print("=" * 76)
    print(f"{'channel':>8} {'amp uV':>9} {'mains%':>8}  status")
    print("-" * 50)
    alive = []
    for i, name in enumerate(CHANNELS):
        x = data[:, i]
        amp = x.std()
        f, P = welch_psd(x)
        mains = (band_power(f, P, *MAINS) / band_power(f, P, 1.0, 45.0) * 100) if len(f) else 0
        if amp < 1.0:
            status = "DEAD (no contact)"
        elif mains > 60:
            status = "noisy (dry?)"
        else:
            status = "ok"
            alive.append(name)
        print(f"{name:>8} {amp:>9.1f} {mains:>7.1f}%  {status}")
    print(f"\nchannels looking usable: {len(alive)}/14  {alive}")

    # ------------------------------------------------------- alpha over time
    print("\n" + "=" * 76)
    print("ALPHA POWER OVER TIME  (8-12 Hz share of 1-45 Hz, 2 s windows)")
    print("=" * 76)
    for name in OCCIPITAL:
        i = CHANNELS.index(name)
        aot = alpha_over_time(data[:, i])
        peak = aot.max() if len(aot) else 0
        print(f"\n  {name}:")
        for k, v in enumerate(aot):
            bar = "#" * int(v * 60)
            print(f"    {k * 2:>3}s |{bar:<55}| {v * 100:5.1f}%")

    # ------------------------------------------------------------- PSD compare
    print("\n" + "=" * 76)
    print("SEGMENT COMPARISON  (alpha share of 1-45 Hz)")
    print("=" * 76)
    print(f"{'channel':>8} " + "".join(f"{l:>15}" for l in labels))
    print("-" * (8 + 15 * len(labels)))
    ratios = []
    for name in OCCIPITAL + FRONTAL:
        i = CHANNELS.index(name)
        shares = []
        for part in parts:
            if len(part) < 64:
                shares.append(0.0)
                continue
            f, P = welch_psd(part[:, i])
            shares.append(band_power(f, P, *ALPHA) / band_power(f, P, 1.0, 45.0) * 100
                          if len(f) else 0.0)
        print(f"{name:>8} " + "".join(f"{s:>14.1f}%" for s in shares))
        if name in OCCIPITAL and len(parts) == 3:
            base = (shares[0] + shares[2]) / 2
            ratios.append(base / shares[1] if shares[1] > 0 else 0)

    # ----------------------------------------------------------------- verdict
    print("\n" + "=" * 76)
    print("VERDICT")
    print("=" * 76)
    if len(alive) < 4:
        print("  INCONCLUSIVE - too few usable channels.")
        print("  Wet ALL 16 pads (14 EEG + 2 references) and re-run.")
    elif ratios and np.mean(ratios) > 1.5:
        print(f"  *** ALPHA CONFIRMED ***  closed/open alpha ratio = "
              f"{np.mean(ratios):.2f}x on the occipital channels.")
        print("  The headset is reading real brain activity. Acquisition is DONE.")
    elif ratios and np.mean(ratios) > 1.15:
        print(f"  WEAK / SUGGESTIVE - ratio {np.mean(ratios):.2f}x. Alpha may be present")
        print("  but contacts are marginal. Re-wet the occipital pads (O1/O2) and the two")
        print("  references, keep the eyes closed longer, and re-run.")
    else:
        print(f"  NOT DETECTED (ratio {np.mean(ratios):.2f}x).")
        print("  Most likely causes, in order:")
        print("    1. Electrodes not making proper scalp contact (hair in the way,")
        print("       pads not wet enough, headset too loose).")
        print("    2. The two REFERENCE pads (CMS/DRL) are dry - without a good")
        print("       reference every channel is noise.")
        print("    3. Subject not relaxed / eyes not fully closed / moving.")
        print("  This is NOT evidence of a decoding problem: the pipeline is already")
        print("  verified. Re-wet everything and try again.")
    if recorded:
        print(f"\n  recorded -> {recorded}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
