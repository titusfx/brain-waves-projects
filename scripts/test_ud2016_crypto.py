#!/usr/bin/env python3
"""
test_ud2016_crypto.py - test emokit's AES key derivations against REAL captured
ciphertext from a UD2016 dongle.

WHY THIS IS POSSIBLE OFFLINE
----------------------------
emokit ships three real encrypted captures in python/, taken 2017-04-05 from a
dongle with serial UD20160103001874:

    emotiv_encrypted_data_UD20160103001874_2017-04-05.17-21-32.384061.csv
    emotiv_encrypted_data_UD20160103001874_2017-04-05.17-39-48.516489.csv
    emotiv_encrypted_data_UD20160103001874_2017-04-05.17-42-23.292665.csv

Each row is one HID report, bytes written as 0b... literals. We know the serial,
so every candidate key is FULLY DETERMINED - no brute force needed. We just
decrypt and look for packet structure.

THE ORACLE
----------
Per emokit's own protocol doc (doc/emotiv_protocol.asciidoc):

  * byte 0 low 7 bits  = packet counter, 0..127, +1 each report, wraps
  * byte 0 high bit    = battery packet, ~once per second (~1 in 128)
  * EEG fields are 14-bit values spread across the packet

A wrong AES key gives uniformly random bytes, so the chance that a random byte 0
increments by exactly 1 (mod 128) is 1/128. A correct key gives ~100%.
That single test is decisive.

Usage:
    .venv\\Scripts\\python.exe scripts\\test_ud2016_crypto.py
"""

from __future__ import annotations

import glob
import os
import sys

from Crypto.Cipher import AES

CAPTURE_GLOB = os.path.join("vendor", "emokit", "python",
                            "emotiv_encrypted_data_UD20160103001874_*.csv")
SERIAL = "UD20160103001874"


# --------------------------------------------------------------------------- #
# key derivations - byte-for-byte ports of emokit/python/emokit/util.py
# --------------------------------------------------------------------------- #
def new_crypto_key(serial: str) -> bytes:
    """emokit's key for serials starting with 'UD2016'."""
    k = ["\0"] * 16
    k[0] = serial[-1]; k[1] = serial[-2]; k[2] = serial[-2]; k[3] = serial[-3]
    k[4] = serial[-3]; k[5] = serial[-3]; k[6] = serial[-2]; k[7] = serial[-4]
    k[8] = serial[-1]; k[9] = serial[-4]; k[10] = serial[-2]; k[11] = serial[-2]
    k[12] = serial[-4]; k[13] = serial[-4]; k[14] = serial[-2]; k[15] = serial[-1]
    return "".join(k).encode("latin-1")


def epoc_plus_crypto_key(serial: str) -> bytes:
    """emokit's key used when force_epoc_mode is set on a UD2016 dongle."""
    k = ["\0"] * 16
    k[0] = serial[-1]; k[1] = "\x00"; k[2] = serial[-2]; k[3] = "\x15"
    k[4] = serial[-3]; k[5] = "\x00"; k[6] = serial[-4]; k[7] = "\x0C"
    k[8] = serial[-3]; k[9] = "\x00"; k[10] = serial[-2]; k[11] = "D"
    k[12] = serial[-1]; k[13] = "\x00"; k[14] = serial[-2]; k[15] = "X"
    return "".join(k).encode("latin-1")


def crypto_key(serial: str, is_research: bool = False) -> bytes:
    """emokit's legacy key (non-UD2016 path)."""
    k = ["\0"] * 16
    k[0] = serial[-1]; k[1] = "\0"; k[2] = serial[-2]
    if is_research:
        k[3] = "H"; k[4] = serial[-1]; k[5] = "\0"; k[6] = serial[-2]; k[7] = "T"
        k[8] = serial[-3]; k[9] = "\x10"; k[10] = serial[-4]; k[11] = "B"
    else:
        k[3] = "T"; k[4] = serial[-3]; k[5] = "\x10"; k[6] = serial[-4]; k[7] = "B"
        k[8] = serial[-1]; k[9] = "\0"; k[10] = serial[-2]; k[11] = "H"
    k[12] = serial[-3]; k[13] = "\0"; k[14] = serial[-4]; k[15] = "P"
    return "".join(k).encode("latin-1")


CANDIDATES = [
    ("new_crypto_key (emokit's UD2016 branch)", lambda s: new_crypto_key(s)),
    ("epoc_plus_crypto_key (force_epoc_mode)", lambda s: epoc_plus_crypto_key(s)),
    ("crypto_key(is_research=False) [legacy]", lambda s: crypto_key(s, False)),
    ("crypto_key(is_research=True)  [legacy]", lambda s: crypto_key(s, True)),
]


# --------------------------------------------------------------------------- #
# capture parsing
# --------------------------------------------------------------------------- #
def load_capture(path: str, limit: int | None = None) -> list[bytes]:
    """Parse a capture into a list of raw encrypted report byte-strings."""
    packets: list[bytes] = []
    with open(path, "r", encoding="latin-1") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            fields = [f for f in line.split(",") if f.startswith("0b") or f.isdigit()]
            if not fields:
                continue
            try:
                raw = bytes(int(f, 2) if f.startswith("0b") else int(f) for f in fields)
            except ValueError:
                continue
            packets.append(raw)
            if limit and len(packets) >= limit:
                break
    return packets


def decrypt_ecb(key: bytes, data: bytes) -> bytes:
    """emokit's decrypt_data(): ECB, block by block."""
    cipher = AES.new(key, AES.MODE_ECB)
    return b"".join(cipher.decrypt(data[i:i + 16]) for i in range(0, len(data) - 15, 16))


# --------------------------------------------------------------------------- #
# scoring
# --------------------------------------------------------------------------- #
def score(decrypted: list[bytes]) -> dict:
    """Grade a decryption using the packet-counter oracle."""
    if not decrypted:
        return {}

    counters = [p[0] & 0x7F for p in decrypted]
    battery_flags = sum(1 for p in decrypted if p[0] & 0x80)

    sequential = sum(
        1 for a, b in zip(counters, counters[1:]) if (b - a) % 128 == 1
    )
    transitions = max(len(counters) - 1, 1)

    # Second, independent oracle: EEG words should be small, signed 14-bit
    # values, not uniformly random 16-bit junk.
    words = []
    for p in decrypted[:2000]:
        for off in range(2, min(len(p) - 1, 30), 2):
            w = int.from_bytes(p[off:off + 2], "big")
            if w & 0x8000:
                w -= 0x10000
            words.append(w)
    plausible = sum(1 for w in words if -1500 <= w <= 1500) / max(len(words), 1)

    return {
        "n": len(decrypted),
        "seq_ratio": sequential / transitions,
        "battery_flags": battery_flags,
        "battery_ratio": battery_flags / len(decrypted),
        "plausible_words": plausible,
        "first_counter": counters[0],
        "first_8_counters": counters[:8],
    }


def main() -> int:
    files = sorted(glob.glob(CAPTURE_GLOB))
    if not files:
        print(f"[!] no captures matched {CAPTURE_GLOB!r}")
        print("    run this from the project root (where vendor/emokit lives)")
        return 2

    print("=" * 78)
    print(f"SERIAL UNDER TEST: {SERIAL}   (from the capture filename)")
    print("=" * 78)

    for path in files:
        packets = load_capture(path)
        widths = {len(p) for p in packets}
        print(f"\n{os.path.basename(path)}")
        print(f"  packets={len(packets)}  report_width(s)={sorted(widths)}")
        if not packets:
            continue

        results = []
        for label, derive in CANDIDATES:
            key = derive(SERIAL)
            dec = [decrypt_ecb(key, p) for p in packets]
            s = score(dec)
            results.append((label, key, s))

        print(f"\n  {'candidate':<42} {'seq%':>7} {'batt%':>7} {'eeg%':>7}  first counters")
        print("  " + "-" * 92)
        for label, key, s in results:
            print(f"  {label:<42} {s['seq_ratio'] * 100:6.2f}% "
                  f"{s['battery_ratio'] * 100:6.2f}% "
                  f"{s['plausible_words'] * 100:6.2f}%  {s['first_8_counters']}")

        best = max(results, key=lambda r: r[2]["seq_ratio"])
        print(f"\n  KEY BYTES for best candidate ({best[0]}):")
        print(f"    {best[1]!r}")
        if best[2]["seq_ratio"] > 0.9:
            print(f"  >>> DECRYPTION CONFIRMED - packet counter advances "
                  f"{best[2]['seq_ratio'] * 100:.1f}% of the time (random = 0.78%)")
        else:
            print(f"  >>> NO candidate produced a coherent counter. "
                  f"Best was {best[2]['seq_ratio'] * 100:.2f}% (random ~0.78%).")
            print(f"      The key derivation for this dongle is NOT one of emokit's four.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
