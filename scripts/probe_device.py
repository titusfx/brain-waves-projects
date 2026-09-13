#!/usr/bin/env python3
"""
probe_device.py - identify an Emotiv EPOC+ / EPOC X dongle and decide which
crypto path applies.

Phase 1.1 of the roadmap (see eeg-vault/03-project/roadmap.md).
It answers one question: WHICH generation of dongle is plugged in?

WHY IT MATTERS
--------------
emokit's crypto branch is chosen by the dongle's USB serial number, and
emokit only recognises the LITERAL prefix "UD2016". Emotiv serials appear to be

    "UD" + YYYYMMDD + counter          e.g. UD20160103001874  -> 2016-01-03

so a dongle made in 2019 has a serial like "UD2019...", which matches NEITHER
"UD2016" NOR the legacy assumption cleanly. In emokit that serial silently
falls through to the OLD crypto key. This script flags exactly that trap.

KNOWN HARDWARE FACTS
--------------------
  Vendor ID   : 0x1234 (4660)   Emotiv
  Product ID  : 0xED02 (60674)  "Brain Computer Interface USB Receiver/Dongle"
  HID reports : 32 bytes (legacy)  /  64 bytes (UD2016 "new format")
  Interfaces  : the dongle exposes TWO HID interfaces (interface_number 0 and 1).
                emokit's Windows path takes devices[1] - the SECOND match.

Run:
    py scripts/probe_device.py            # probe real hardware
    py scripts/probe_device.py --all      # also list every other HID device
    py scripts/probe_device.py --demo     # no hardware needed

Requires: pip install hidapi
"""

from __future__ import annotations

import argparse
import re
import sys

# --- known Emotiv USB identity --------------------------------------------- #
EMOTIV_VENDOR_ID = 0x1234          # 4660
EMOTIV_PRODUCT_ID = 0xED02         # 60674
EMOTIV_PRODUCT_STRINGS = (
    "brain computer interface usb receiver/dongle",
    "epoc+",
    "epoc x",
    "epoc",
)

# Fallback string matcher, mirroring emokit's device_is_emotiv().
EMOTIV_HINTS = ("emotiv", "epoc", "brain waves", "eeg signals",
                "brain computer interface", "00000000000")

CHANNELS = ["AF3", "F7", "F3", "FC5", "T7", "P7", "O1",
            "O2", "P8", "T8", "FC6", "F4", "F8", "AF4"]

# Serials emokit's own code knows how to handle.
EMOKIT_LITERAL_PREFIX = "UD2016"

# NOTE: the counter suffix can contain LETTERS (e.g. UD20180927003B78), so the
# tail must be alphanumeric, not \d+.
DATE_RE = re.compile(r"^UD(\d{4})(\d{2})(\d{2})([0-9A-Za-z]+)$")


# --------------------------------------------------------------------------- #
# serial parsing
# --------------------------------------------------------------------------- #
def parse_serial(serial: str | None):
    """Return (manufacture_date_str_or_None, counter_or_None)."""
    if not serial:
        return None, None
    m = DATE_RE.match(str(serial).strip())
    if not m:
        return None, None
    yyyy, mm, dd, counter = m.groups()
    return f"{yyyy}-{mm}-{dd}", counter


def classify(serial: str | None) -> dict:
    """Map a dongle serial onto the emokit crypto decision table."""
    if not serial:
        return {
            "generation": "unknown (no serial exposed)",
            "mfg_date": None,
            "packet_length": None,
            "crypto_path": None,
            "packet_class": None,
            "flags": [],
            "verdict": (
                "No serial number. Try the legacy path with is_research=False, "
                "then is_research=True, then force_old_crypto / force_epoc_mode. "
                "If cheap, an older (pre-2016) dongle is the known-good route."
            ),
            "warnings": [],
        }

    s = str(serial).strip()
    mfg_date, counter = parse_serial(s)
    warnings: list[str] = []

    if s.startswith(EMOKIT_LITERAL_PREFIX):
        return {
            "generation": "UD2016 - 'new format' (emokit's recognised branch)",
            "mfg_date": mfg_date,
            "packet_length": 64,
            "crypto_path": "new_crypto_key(serial)",
            "packet_class": "EmotivNewPacket",
            "flags": [],
            "verdict": (
                "emokit has a code path for this. Historically it DECRYPTED "
                "correctly but produced implausible sensor values, capped at "
                "~192 Hz instead of 256, with broken battery and gyro "
                "(openyou/emokit issue #229). So: expect to succeed at "
                "decryption and still have to fix the unpacking."
            ),
            "warnings": warnings,
        }

    # Any other UD<year> serial is NOT handled by emokit.
    if s.startswith("UD") and mfg_date:
        year = int(mfg_date[:4])
        if year >= 2017:
            warnings.append(
                f"CONFIRMED TRAP: emokit only special-cases the literal prefix "
                f"'UD2016'. This is a '{s[:6]}...' dongle, so emokit will SILENTLY "
                f"fall through to the OLD legacy crypto key and the 32-byte "
                f"bit-packed packet layout. That is WRONG for this device."
            )
            warnings.append(
                "No emokit flag covers this (the branch is a literal string compare). "
                "Use new_crypto_key() directly and the little-endian 16-bit layout "
                "from scripts/decode_to_csv.py — see eeg-vault/02-software/"
                "ud2016-crypto-crack.md."
            )
        return {
            "generation": f"post-2016 ('{s[:6]}...') - NOT recognised by emokit",
            "mfg_date": mfg_date,
            "packet_length": 32,
            "crypto_path": "new_crypto_key()  [emokit will NOT pick this automatically]",
            "packet_class": "little-endian 16-bit layout (see decode_to_csv.py)",
            "flags": ["(patch needed - no flag covers this)"],
            "verdict": (
                "Treat as the 2016+ 'new format'. Use new_crypto_key() and the "
                "little-endian 16-bit field layout. Then run the alpha test."
            ),
            "warnings": warnings,
        }

    return {
        "generation": "legacy / pre-2016",
        "mfg_date": mfg_date,
        "packet_length": 32,
        "crypto_path": "crypto_key(serial, is_research)",
        "packet_class": "EmotivOldPacket",
        "flags": ["is_research=False first, then is_research=True"],
        "verdict": (
            "The generation emokit genuinely supports. Best-case scenario. "
            "Start with is_research=False; if the output is high-entropy garbage, "
            "retry with is_research=True."
        ),
        "warnings": warnings,
    }


def is_emotiv(vendor: str | None, product: str | None,
              vid: int = 0, pid: int = 0) -> bool:
    if vid == EMOTIV_VENDOR_ID or pid == EMOTIV_PRODUCT_ID:
        return True
    blob = f"{vendor or ''} {product or ''}".lower()
    if any(p in blob for p in EMOTIV_PRODUCT_STRINGS):
        return True
    return any(h in blob for h in EMOTIV_HINTS)


# --------------------------------------------------------------------------- #
# output helpers
# --------------------------------------------------------------------------- #
def box(title: str) -> None:
    print("\n" + "=" * 76)
    print(title)
    print("=" * 76)


def decode(x):
    if isinstance(x, bytes):
        return x.decode("utf-8", "replace")
    return x


def report(dev: dict, index: int, total: int) -> None:
    info = classify(dev.get("serial_number"))
    print(f"  --- Emotiv device {index + 1} of {total} ---")
    print(f"  Vendor        : {dev.get('vendor')!r}")
    print(f"  Product       : {dev.get('product')!r}")
    print(f"  vendor_id     : 0x{dev['vendor_id']:04X} ({dev['vendor_id']})")
    print(f"  product_id    : 0x{dev['product_id']:04X} ({dev['product_id']})")
    print(f"  serial_number : {dev.get('serial_number')!r}   <-- DECISIVE")
    if info.get("mfg_date"):
        print(f"  manufacture   : {info['mfg_date']}  (decoded from serial)")
    if dev.get("interface_number") is not None:
        print(f"  interface #   : {dev['interface_number']}")
    if dev.get("manufacturer"):
        print(f"  manufacturer  : {dev.get('manufacturer')!r}")
    print()
    print(f"  generation    : {info['generation']}")
    print(f"  packet_length : {info['packet_length']}")
    print(f"  crypto_path   : {info['crypto_path']}")
    print(f"  packet_class  : {info['packet_class']}")
    if info.get("flags"):
        print(f"  emokit flags  : {', '.join(info['flags'])}")
    print(f"  verdict       : {info['verdict']}")
    for w in info.get("warnings", []):
        print(f"  !! WARNING    : {w}")
    print()


def probe(show_all: bool) -> int:
    try:
        import hid
    except ImportError:
        print("[!] 'hidapi' is not installed.\n")
        print("      pip install hidapi\n")
        print("    Linux:  sudo apt install libhidapi-hidraw0")
        print("    macOS:  brew install hidapi")
        print("    Windows fallback:  pip install pywinusb")
        return 2

    raw = hid.enumerate()
    if not raw:
        print("[!] hidapi returned no devices at all. Is the dongle plugged in?")
        return 1

    emotiv, others = [], []
    for d in raw:
        vid = d.get("vendor_id", 0) or 0
        pid = d.get("product_id", 0) or 0
        vendor = decode(d.get("manufacturer_string"))
        product = decode(d.get("product_string"))
        serial = decode(d.get("serial_number"))
        item = {
            "vendor_id": vid,
            "product_id": pid,
            "vendor": vendor,
            "product": product,
            "serial_number": serial,
            "interface_number": d.get("interface_number"),
            "path": decode(d.get("path")),
        }
        if is_emotiv(vendor, product, vid, pid):
            emotiv.append(item)
        else:
            others.append(item)

    box(f"EMOTIV MATCHES ({len(emotiv)})")
    if emotiv:
        for i, d in enumerate(emotiv):
            report(d, i, len(emotiv))
        if len(emotiv) > 1:
            print("  NOTE: the dongle exposes TWO HID interfaces. emokit's Windows")
            print("  path uses devices[1] - the SECOND match. If reads return")
            print("  nothing on one interface, try the other.\n")
    else:
        print("  none found.\n")
        print("  Checklist:")
        print("    - dongle plugged in? LEFT LED on?")
        print("      (left on + right fast-flashing == receiving data)")
        print("    - paired but not connected -> RIGHT LED flashes slowly")
        print("    - headset powered and awake, battery charged?")
        print("    - try --all to dump every HID device and look by hand")
        print("    - Linux: add a udev rule or run as root")
        print("    - Windows: WinUSB may be bound to the dongle, hiding it")
        print("      from hidapi; check Device Manager for a driver warning")

    if show_all:
        box(f"ALL OTHER HID DEVICES ({len(others)})")
        for d in others:
            print(f"  0x{d['vendor_id']:04X}:0x{d['product_id']:04X}  "
                  f"{(d['vendor'] or '?')[:26]:<26} | {(d['product'] or '?')[:36]}")

    print()
    print("Next: copy serial_number + crypto_path into")
    print("  eeg-vault/01-device/identify-your-revision.md")
    print("Then run the ALPHA TEST (roadmap 1.4) before trusting any data:")
    print("  eyes closed -> 8-12 Hz peak in O1/O2;  eyes open -> it attenuates.")
    return 0


# --------------------------------------------------------------------------- #
def demo() -> int:
    box("DECISION TABLE DEMO (no hardware needed)")
    samples = [
        "UD20160103001874",   # the real serial from openyou/emokit issue #229
        "UD20190512000421",   # the trap: 2019 dongle, emokit will NOT handle it
        "UD20201130000099",   # EPOC X era
        "SN201311223344",     # legacy
    ]
    for s in samples:
        info = classify(s)
        print(f"  serial {s!r}")
        print(f"    mfg_date={info['mfg_date']}  {info['generation']}")
        print(f"    -> {info['packet_length']}-byte packets, {info['crypto_path']}")
        for w in info.get("warnings", []):
            print(f"    !! {w}")
        print()
    print(f"  Expected montage (14 ch): {' '.join(CHANNELS)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true",
                    help="also list every non-Emotiv HID device")
    ap.add_argument("--demo", action="store_true",
                    help="show the serial->crypto decision table, no hardware needed")
    args = ap.parse_args()
    return demo() if args.demo else probe(args.all)


if __name__ == "__main__":
    sys.exit(main())
