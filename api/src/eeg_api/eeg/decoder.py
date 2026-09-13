"""Decoding a decrypted report into microvolts.

Two rules in here were learned by getting them wrong, and both are load-bearing
(AGENTS.md §4):

1. **Read the fields as UNSIGNED.** They are raw ADC counts with a large per-channel
   DC offset. Interpreting them as signed int16 manufactures a 65535-count spike
   every time the high byte crosses 0x7F/0x80 — a measured fake 5317 µV on F8.
2. **Carry the highpass state across bursts.** The 0.5 Hz highpass must run over the
   whole session. Restarting it per HID burst stamps a step into the signal several
   times a second, which shows up as a spectral mess that looks like the decoder is
   broken. :class:`UVStream` is the same recurrence as
   ``scripts/decode_to_csv.highpass`` with the state kept between calls.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from eeg_api.domain.models import (
    CHANNEL_OFFSETS,
    EEG_PACKET_TYPE,
    FS,
    QUALITY_OFFSET,
    UV_PER_LSB,
    FloatArray,
)


REPORT_LEN = 32


def u16le(arr: NDArray[np.uint8], offset: int) -> NDArray[np.uint16]:
    """16-bit little-endian field. emokit decodes these BIG-endian; the hardware is LE.

    The shift is done in ``uint32`` because shifting a ``uint16`` promotes it, and the
    result is cast back down explicitly so the array stays 16-bit all the way out.
    """
    low = arr[:, offset].astype(np.uint32)
    high = arr[:, offset + 1].astype(np.uint32)
    return np.asarray((high << 8) | low, dtype=np.uint16)


def raw_counts(reports: NDArray[np.uint8]) -> FloatArray:
    """Decrypted reports -> ``(n, 14)`` unsigned ADC counts (no DC removal, no scaling)."""
    return np.column_stack(
        [u16le(reports, offset).astype(np.float64) for _, offset in CHANNEL_OFFSETS]
    )


def qualities(reports: NDArray[np.uint8]) -> FloatArray:
    """The rotating contact-quality field (offset 16), which is not EEG."""
    return u16le(reports, QUALITY_OFFSET).astype(np.float64)


class UVStream:
    """Raw ADC counts -> microvolts, as one continuous highpassed stream."""

    def __init__(self, fs: float = FS, highpass_hz: float = 0.5) -> None:
        self.fs = fs
        self.highpass_hz = highpass_hz
        self._a = float(np.exp(-2.0 * np.pi * highpass_hz / fs))
        self._prev: FloatArray | None = None
        self._y: FloatArray | None = None

    def reset(self) -> None:
        self._prev = None
        self._y = None

    def push(self, counts: FloatArray) -> FloatArray:
        """``(n, 14)`` counts -> ``(n, 14)`` microvolts, DC removed."""
        out = np.empty(counts.shape, dtype=np.float64)
        if self._prev is None:
            self._prev = counts[0].copy()
            self._y = np.zeros(counts.shape[1], dtype=np.float64)
        assert self._y is not None
        for i in range(counts.shape[0]):
            self._y = self._a * (self._y + counts[i] - self._prev)
            self._prev = counts[i].copy()
            out[i] = self._y
        return out * UV_PER_LSB


def decode_reports(
    reports: NDArray[np.uint8],
    stream: UVStream | None = None,
) -> tuple[FloatArray, NDArray[np.int64], FloatArray]:
    """Decrypted 32-byte reports -> ``(uv, counters, quality)``.

    Only EEG packets (byte 1 == 0x10) contribute samples; status packets exist but
    carry no EEG (offset 16 is contact quality).
    """
    is_eeg = reports[:, 1] == EEG_PACKET_TYPE
    eeg = reports[is_eeg]
    if eeg.shape[0] == 0:
        return np.zeros((0, len(CHANNEL_OFFSETS))), np.zeros(0, dtype=np.int64), np.zeros(0)
    counts = raw_counts(eeg)
    stream = stream if stream is not None else UVStream()
    uv = stream.push(counts)
    return uv, eeg[:, 0].astype(np.int64), qualities(eeg)


def decode_and_split(
    data: bytes, key: bytes, stream: UVStream | None = None
) -> tuple[FloatArray, int]:
    """Decrypt a concatenated buffer of 32-byte reports and decode the EEG ones.

    Returns ``(uv, n_reports)``. Used by the offline replay of the emokit captures.
    """
    from eeg_api.eeg.crypto import decrypt_ecb  # local: keeps this module import-light

    reports = [
        decrypt_ecb(key, data[i : i + REPORT_LEN])
        for i in range(0, len(data) - (REPORT_LEN - 1), REPORT_LEN)
    ]
    if not reports:
        return np.zeros((0, len(CHANNEL_OFFSETS))), 0
    arr = np.frombuffer(b"".join(reports), dtype=np.uint8).reshape(len(reports), REPORT_LEN)
    uv, _counters, _quality = decode_reports(arr, stream)
    return uv, len(reports)
