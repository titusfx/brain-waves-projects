#!/usr/bin/env python3
"""
decode_to_csv.py - reference decoder for Emotiv EPOC+ "UD2016" HID captures.

THE COMPLETE FORMAT, as reverse-engineered (see eeg-vault/02-software/ud2016-crypto-crack.md):

    HID report = 32 bytes, AES-128-ECB encrypted
    key        = new_crypto_key(dongle_serial)          [see emokit/util.py]

    byte 0        packet counter (0..255)
    byte 1        packet type:  0x10 = EEG sample,  0x20 = extra/status
    bytes 2..31   15 x 16-bit LITTLE-ENDIAN fields:

        offset  2  F3        offset 18  O2
        offset  4  FC5       offset 20  P8
        offset  6  AF3       offset 22  T8
        offset  8  F7        offset 24  F8
        offset 10  T7        offset 26  AF4
        offset 12  P7        offset 28  FC6
        offset 14  O1        offset 30  F4
        offset 16  QUALITY   (not EEG)

    scaling    1 LSB = 0.51 uV   (Emotiv EPOC+ specification)

  NOTE emokit gets the byte OFFSETS right but decodes them BIG-endian.
  The hardware is LITTLE-endian. That single mistake is why emokit's
  "new format" path produced implausible data (issue #229).

  Also: emokit assumes UD2016 dongles send 64-byte reports. They send 32.

Usage:
    .venv\\Scripts\\python.exe scripts\\decode_to_csv.py
    .venv\\Scripts\\python.exe scripts\\decode_to_csv.py path\\to\\capture.csv out.csv
"""

from __future__ import annotations

import csv
import glob
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from test_ud2016_crypto import (  # noqa: E402
    SERIAL, load_capture, decrypt_ecb, new_crypto_key,
)

# (name, byte offset) in packet order
FIELDS = [
    ("F3", 2), ("FC5", 4), ("AF3", 6), ("F7", 8), ("T7", 10), ("P7", 12),
    ("O1", 14), ("O2", 18), ("P8", 20), ("T8", 22), ("F8", 24), ("AF4", 26),
    ("FC6", 28), ("F4", 30),
]
CHANNELS = [n for n, _ in FIELDS]
QUALITY_OFFSET = 16
EEG_PACKET_TYPE = 0x10
UV_PER_LSB = 0.51
CAPTURE_GLOB = os.path.join("vendor", "emokit", "python",
                            "emotiv_encrypted_data_UD20160103001874_*.csv")


# --------------------------------------------------------------------------- #
# decoding
# --------------------------------------------------------------------------- #
def decrypt_reports(packets, serial):
    """raw 32-byte reports -> decrypted 32-byte reports (numpy uint8 n x 32)."""
    dec = [decrypt_ecb(new_crypto_key(serial), p) for p in packets]
    return np.frombuffer(b"".join(dec), dtype=np.uint8).reshape(len(dec), 32)


def u16le(arr, off):
    return (arr[:, off + 1].astype(np.uint16) << 8) | arr[:, off].astype(np.uint16)


def to_counts(v):
    """
    Raw 16-bit ADC counts -> float, UNSIGNED.

    ⚠️ Do NOT interpret these as signed int16. The high byte legitimately flips
    across the 0x7F/0x80 boundary as the signal drifts (e.g. byte3 is 0x7F for
    996 packets and 0x80 for 26). A signed view turns each of those flips into a
    65535-count jump, manufacturing enormous fake spikes -- we measured 5317 uV
    of pure artefact on F8 before spotting this.

    The correct model is an *unsigned* raw ADC reading with a large per-channel
    DC offset (the electrode offset), which is removed with a highpass exactly as
    in any real EEG pipeline.
    """
    return v.astype(np.float64)


def highpass(v, fs=128.0, fc=0.5):
    """Remove the per-channel DC offset with a single-pole highpass."""
    a = float(np.exp(-2.0 * np.pi * fc / fs))
    out = np.empty(len(v), dtype=np.float64)
    prev_in = v[0]
    y = 0.0
    for i in range(len(v)):
        y = a * (y + v[i] - prev_in)
        prev_in = v[i]
        out[i] = y
    return out


def decode(arr, uv=True, remove_dc=True):
    """
    Decrypted reports -> dict with:
      'eeg'      float array (n_eeg, 14)  microvolts (DC-removed by default)
      'raw'      float array (n_eeg, 14)  raw unsigned ADC counts
      'counter'  int array (n_eeg,)
      'quality'  float array (n_eeg,)
      'n_total' / 'n_eeg' / 'n_extra'
    """
    is_eeg = arr[:, 1] == EEG_PACKET_TYPE
    eeg = arr[is_eeg]

    raw = np.column_stack([to_counts(u16le(eeg, off)) for _, off in FIELDS])
    data = np.column_stack([highpass(raw[:, i]) for i in range(raw.shape[1])]) \
        if remove_dc else raw
    if uv:
        data = data * UV_PER_LSB

    return {
        "eeg": data,
        "raw": raw,
        "counter": eeg[:, 0].astype(int),
        "quality": to_counts(u16le(eeg, QUALITY_OFFSET)),
        "n_total": len(arr),
        "n_eeg": int(is_eeg.sum()),
        "n_extra": int((~is_eeg).sum()),
    }


# --------------------------------------------------------------------------- #
def main() -> int:
    args = sys.argv[1:]
    if args:
        capture = args[0]
        out = args[1] if len(args) > 1 else "eeg_decoded.csv"
    else:
        matches = sorted(glob.glob(CAPTURE_GLOB))
        if not matches:
            print("[!] no capture given and none found in vendor/emokit/python/")
            return 2
        capture = matches[0]
        out = "eeg_decoded.csv"

    packets = load_capture(capture)
    serial = SERIAL
    # if the filename encodes a serial, prefer it
    base = os.path.basename(capture)
    if "UD" in base:
        tail = base.split("_")
        for part in tail:
            if part.startswith("UD"):
                serial = part
                break

    print(f"capture : {base}")
    print(f"serial  : {serial}")
    print(f"reports : {len(packets)} x {len(packets[0])} bytes")

    arr = decrypt_reports(packets, serial)
    res = decode(arr)

    print(f"  EEG reports (byte1=0x10) : {res['n_eeg']}")
    print(f"  extra reports (0x20)     : {res['n_extra']}")
    print(f"  counter range            : {res['counter'].min()}..{res['counter'].max()}")
    print(f"\n{'channel':>8} {'mean uV':>10} {'std uV':>9} {'min uV':>10} {'max uV':>10}")
    print("-" * 50)
    for i, name in enumerate(CHANNELS):
        c = res["eeg"][:, i]
        print(f"{name:>8} {c.mean():>10.1f} {c.std():>9.1f} {c.min():>10.1f} {c.max():>10.1f}")

    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["packet_counter", "quality"] + [f"{c}_uV" for c in CHANNELS])
        for i in range(len(res["eeg"])):
            row = [int(res["counter"][i]), float(res["quality"][i])]
            row += [f"{v:.2f}" for v in res["eeg"][i]]
            w.writerow(row)
    print(f"\nwrote {len(res['eeg'])} samples x {len(CHANNELS)} channels -> {out}")
    print("\nSanity: amplitudes should be ~5-100 uV. If you see thousands of uV,")
    print("the key or the layout is wrong for this dongle.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
