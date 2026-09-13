"""Finding and opening the dongle over USB HID.

Only HID **interface 1** (product string ``"EEG Signals"``) streams. Interface 0
opens perfectly happily and then returns zero reports forever, which is the most
misleading failure this hardware has (AGENTS.md rule 4) — so the interface is
chosen by product string, and the alternative is reported rather than silently
falling back to it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from eeg_api.config import get_settings


#: The dongle's identity. These are the *device* VID/PID, not Emotiv's Cortex API.
EMOTIV_VID = 0x1234
EMOTIV_PID = 0xED02


@dataclass(frozen=True, slots=True)
class DongleInterface:
    """One HID interface exposed by the dongle."""

    path: bytes
    product: str
    serial: str
    interface: int

    @property
    def is_streaming(self) -> bool:
        settings = get_settings()
        return self.product == settings.streaming_product

    def as_payload(self) -> dict[str, Any]:
        return {
            "product": self.product,
            "serial": self.serial,
            "interface": self.interface,
            "streams": self.is_streaming,
        }


def hid_available() -> bool:
    """Whether the ``hidapi`` binding is importable in this interpreter."""
    try:
        import hid  # noqa: F401
    except ImportError:
        return False
    return True


def _decode(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value) if value is not None else ""


def find_interfaces() -> list[DongleInterface]:
    """Every HID interface of an attached Emotiv dongle. Empty when none is attached."""
    try:
        import hid
    except ImportError:
        return []

    found: list[DongleInterface] = []
    try:
        devices = hid.enumerate()
    except Exception:  # pragma: no cover - a broken HID stack is not our error to raise
        return []

    for device in devices:
        if device.get("vendor_id") != EMOTIV_VID or device.get("product_id") != EMOTIV_PID:
            continue
        found.append(
            DongleInterface(
                path=device["path"],
                product=_decode(device.get("product_string")),
                serial=_decode(device.get("serial_number")),
                interface=int(device.get("interface_number") or 0),
            )
        )
    return found


def streaming_interface(interfaces: list[DongleInterface] | None = None) -> DongleInterface | None:
    """The interface that actually carries EEG, or ``None``.

    Preference order is the product string, then "not interface 0" — interface 0 is
    the silent control interface and picking it produces a perfectly healthy-looking
    session with no data.
    """
    candidates = interfaces if interfaces is not None else find_interfaces()
    if not candidates:
        return None
    for candidate in candidates:
        if candidate.is_streaming:
            return candidate
    return next((c for c in candidates if c.interface != 0), None)


def detect() -> dict[str, Any]:
    """A status payload describing what is plugged in, without opening anything."""
    interfaces = find_interfaces()
    streaming = streaming_interface(interfaces)
    return {
        "hid_available": hid_available(),
        "present": bool(interfaces),
        "serial": streaming.serial if streaming else (interfaces[0].serial if interfaces else None),
        "streaming_interface": streaming.as_payload() if streaming else None,
        "interfaces": [i.as_payload() for i in interfaces],
    }
