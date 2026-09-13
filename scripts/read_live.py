#!/usr/bin/env python3
"""
read_live.py - read live EEG from the Emotiv dongle over USB HID, decrypt it,
and decode it into microvolts.

THE LIVE ORACLE
---------------
After decrypting with the right key, byte 1 of every report must be one of a
*tiny* set of values (0x10 = EEG sample, 0x20 = status). With the wrong key,
byte 1 is uniformly random across 0..255.

So the check is instant and unambiguous:
    distinct byte1 values <= ~4   -> key is correct
    distinct byte1 values  > ~50  -> key is wrong

Then we validate with physiology: real EEG is autocorrelated in time
(lag-1 >> 0) and amplitudes are ~5-100 uV.

Usage:
    .venv\\Scripts\\python.exe scripts\\read_live.py            # 10 s
    .venv\\Scripts\\python.exe scripts\\read_live.py 20 out.csv # 20 s -> out.csv
"""

from __future__ import annotations

import csv
import os
import sys
import time
from collections import Counter

import numpy as np

# Windows console defaults to cp1252, which cannot encode the symbols below.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from test_ud2016_crypto import new_crypto_key, decrypt_ecb, crypto_key  # noqa: E402
from decode_to_csv import CHANNELS, decode as decode_reports  # noqa: E402

EMOTIV_VID = 0x1234
EMOTIV_PID = 0xED02
REPORT_LEN = 32


def autocorr(v):
    v = np.asarray(v, dtype=np.float64)
    if v.size < 3 or v.std() == 0:
        return 0.0
    a, b = v[:-1] - v[:-1].mean(), v[1:] - v[1:].mean()
    den = np.sqrt((a * a).sum() * (b * b).sum())
    return float((a * b).sum() / den) if den else 0.0


def find_emotiv(hid):
    out = []
    for d in hid.enumerate():
        if d.get("vendor_id") == EMOTIV_VID and d.get("product_id") == EMOTIV_PID:
            def dec(x):
                return x.decode("utf-8", "replace") if isinstance(x, bytes) else x
            out.append({
                "path": d["path"],
                "product": dec(d.get("product_string")),
                "serial": dec(d.get("serial_number")),
                "interface": d.get("interface_number"),
            })
    return out


def capture(hid, dev, seconds=10.0, verbose=True):
    """Read raw reports from one HID interface for `seconds`."""
    h = hid.device()
    try:
        h.open_path(dev["path"])
    except Exception as exc:
        if verbose:
            print(f"    open failed: {exc}")
        return []
    reports = []
    t0 = time.time()
    try:
        h.set_nonblocking(0)
        while time.time() - t0 < seconds:
            try:
                data = h.read(REPORT_LEN, 500)
            except Exception:
                break
            if data:
                b = bytes(data[:REPORT_LEN])
                if len(b) == REPORT_LEN:
                    reports.append(b)
            else:
                time.sleep(0.001)
    finally:
        try:
            h.close()
        except Exception:
            pass
    return reports


def evaluate(reports, serial):
    """Decrypt and score a capture. Returns (ok, info)."""
    arr = np.frombuffer(b"".join(reports), dtype=np.uint8).reshape(len(reports), REPORT_LEN)
    keys = {
        "new_crypto_key (UD2016+ path)": new_crypto_key(serial),
        "crypto_key(is_research=False) [legacy]": crypto_key(serial, False),
        "crypto_key(is_research=True)  [legacy]": crypto_key(serial, True),
    }
    results = {}
    for label, key in keys.items():
        dec = np.frombuffer(
            b"".join(decrypt_ecb(key, r) for r in reports),
            dtype=np.uint8).reshape(len(reports), REPORT_LEN)
        b1 = Counter(dec[:, 1].tolist())
        results[label] = dec
        print(f"    {label:<40} distinct byte1 values: {len(b1):>3}   "
              f"top: {[(hex(k), v) for k, v in b1.most_common(3)]}")

    best = min(results.items(), key=lambda kv: len(Counter(kv[1][:, 1].tolist())))
    return best, results


def decode(dec):
    """Decrypt -> (eeg reports, microvolt matrix), DC removed."""
    return decode_reports(dec, uv=True, remove_dc=True)["eeg"]


def main() -> int:
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 10.0
    out = sys.argv[2] if len(sys.argv) > 2 else None

    try:
        import hid
    except ImportError:
        print("[!] pip install hidapi")
        return 2

    devs = find_emotiv(hid)
    if not devs:
        print("[!] no Emotiv dongle found. Plugged in?")
        return 1

    print("=" * 92)
    print(f"EMOTIV DONGLE — {len(devs)} HID interface(s)")
    print("=" * 92)
    for d in devs:
        print(f"  interface {d['interface']}  {d['product']!r}  serial={d['serial']!r}")
    serial = devs[0]["serial"]
    print(f"\nserial: {serial}")

    print(f"\nReading {seconds:.0f}s from each interface...\n")
    captures = {}
    for d in devs:
        print(f"  interface {d['interface']} ({d['product']!r}):")
        reps = capture(hid, d, seconds)
        print(f"    reports received: {len(reps)}"
              + (f"   ({len(reps) / seconds:.0f}/s)" if reps else "   <-- NO DATA"))
        if reps:
            captures[d["interface"]] = reps
    print()

    if not captures:
        print("  " + "!" * 84)
        print("  NO DATA FROM EITHER INTERFACE.")
        print("  The dongle is enumerating fine, so this is an RF/pairing issue, not software.")
        print("  Check, in order:")
        print("    1. Is the HEADSET powered on? (press and hold the power button)")
        print("    2. Is the headset charged? (a flat LiPo after years of storage is common)")
        print("    3. Dongle LEDs: left ON + right FAST-flashing == receiving data.")
        print("       Left ON + right SLOW-flashing == paired but not connected.")
        print("       If the right LED never changes, the headset is not reaching the dongle.")
        print("    4. Has the dongle ever been paired with THIS headset? Pairing is")
        print("       remembered dongle-side; an unpaired dongle will not stream.")
        print("  " + "!" * 84)
        return 3

    for iface, reps in captures.items():
        print("=" * 92)
        print(f"INTERFACE {iface}: {len(reps)} reports")
        print("=" * 92)
        (label, dec), _ = evaluate(reps, serial)
        n_b1 = len(Counter(dec[:, 1].tolist()))
        print(f"\n  best key: {label}")
        if n_b1 > 50:
            print(f"  >>> byte1 has {n_b1} distinct values = WRONG KEY (expect <=4)")
            print("      None of the known derivations fit. Time to brute-force.")
            continue
        print(f"  >>> byte1 has only {n_b1} distinct values = KEY CONFIRMED ✅")

        data = decode(dec)
        print(f"\n  EEG samples decoded: {len(data)} / {len(reps)} reports")
        print(f"\n  {'channel':>8} {'amp uV':>9} {'lag-1 AC':>10}")
        print("  " + "-" * 30)
        acs = []
        for i, name in enumerate(CHANNELS):
            c = data[:, i] - data[:, i].mean()
            a = autocorr(c)
            acs.append(a)
            print(f"  {name:>8} {c.std():>9.1f} {a:>10.4f}")
        print(f"\n  mean lag-1 autocorrelation: {np.mean(acs):.3f}")
        print("  (>0.7 == real band-limited signal; ~0 == noise)")

        if out:
            with open(out, "w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow([f"{c}_uV" for c in CHANNELS])
                for row in data:
                    w.writerow([f"{v:.2f}" for v in row])
            print(f"\n  wrote {len(data)} samples -> {out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
