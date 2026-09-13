"""The signal model: channels, packet layout, and the frames that move through the app.

Every constant here is a *fact about the hardware*, verified on this unit and
recorded in ``AGENTS.md`` §3. Nothing in this module guesses.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
from numpy.typing import NDArray


#: EEG sample rate. The dongle emits ~159 reports/s, ~128 of which are EEG
#: samples and ~31 status packets.
FS: float = 128.0

#: Emotiv EPOC+ scaling: 1 raw ADC count = 0.51 µV.
UV_PER_LSB: float = 0.51

#: byte 1 of a decrypted report: 0x10 is an EEG sample, 0x20 a status packet.
EEG_PACKET_TYPE: int = 0x10
STATUS_PACKET_TYPE: int = 0x20

#: The 14 channels **in packet order**, which is also the column order of every
#: CSV this project has ever written (``scripts/decode_to_csv.py``).
CHANNELS: tuple[str, ...] = (
    "F3",
    "FC5",
    "AF3",
    "F7",
    "T7",
    "P7",
    "O1",
    "O2",
    "P8",
    "T8",
    "F8",
    "AF4",
    "FC6",
    "F4",
)

#: (name, byte offset) of each 16-bit little-endian field in a decrypted report.
#: emokit gets these offsets right and the endianness wrong; the hardware is
#: little-endian.
CHANNEL_OFFSETS: tuple[tuple[str, int], ...] = (
    ("F3", 2),
    ("FC5", 4),
    ("AF3", 6),
    ("F7", 8),
    ("T7", 10),
    ("P7", 12),
    ("O1", 14),
    ("O2", 18),
    ("P8", 20),
    ("T8", 22),
    ("F8", 24),
    ("AF4", 26),
    ("FC6", 28),
    ("F4", 30),
)

#: Offset 16 is the rotating contact-quality field, not EEG.
QUALITY_OFFSET: int = 16

#: The two channels the alpha test reads. Alpha is maximal over the occipital
#: pole; if the signal is a real brain, this is where it shows first.
OCCIPITAL_CHANNELS: tuple[str, ...] = ("O1", "O2")

#: Frequency bands the UI reports, as (name, low Hz, high Hz). Bands stop at
#: 45 Hz: the EPOC+'s 128 Hz sampling puts Nyquist at 64 Hz, and 48-62 Hz is
#: reserved for the mains measurement.
BANDS: tuple[tuple[str, float, float], ...] = (
    ("delta", 1.0, 4.0),
    ("theta", 4.0, 8.0),
    ("alpha", 8.0, 12.0),
    ("beta", 13.0, 30.0),
    ("gamma", 30.0, 45.0),
)

#: Mains window. 50 Hz (EU) and 60 Hz (US) both land inside it.
MAINS_LO_HZ: float = 48.0
MAINS_HI_HZ: float = 62.0

SourceMode = Literal["idle", "live", "demo", "replay"]

#: Plain-English contact verdicts, in the same words ``scripts/live_view.py``
#: prints, so the screen and the terminal cannot disagree.
STATUS_OK = "ok"
STATUS_LOW = "low"
STATUS_HIGH = "high"
STATUS_DEAD = "DEAD"
STATUS_DRY = "DRY?"
STATUS_ARTEFACT = "artefact"

NORMAL_LO_UV: float = 10.0
NORMAL_HI_UV: float = 100.0

FloatArray = NDArray[np.float64]


def channel_index(name: str) -> int:
    """Position of a channel in :data:`CHANNELS` (raises ``KeyError`` if unknown)."""
    return CHANNELS.index(name)


def channel_offset(name: str) -> int:
    """Byte offset of a channel inside a decrypted report."""
    for candidate, offset in CHANNEL_OFFSETS:
        if candidate == name:
            return offset
    raise KeyError(name)


@dataclass(frozen=True, slots=True)
class Chunk:
    """A contiguous block of decoded samples, tagged with where it starts.

    ``t0`` is seconds since the acquisition session started, so a recording's
    time column is a property of the stream rather than of the wall clock.
    """

    uv: FloatArray  # (n, 14) microvolts, DC removed
    t0: float
    counters: NDArray[np.int64] | None = None
    quality: FloatArray | None = None
    key_ok: bool | None = None

    @property
    def n(self) -> int:
        return int(self.uv.shape[0])


@dataclass(frozen=True, slots=True)
class ChannelMetrics:
    """What the monitor shows for one channel, computed over the display window."""

    name: str
    amplitude_uv: float
    current_uv: float
    mains_percent: float
    status: str
    bands: dict[str, float]

    def as_payload(self) -> dict[str, object]:
        return {
            "name": self.name,
            "amplitude_uv": round(self.amplitude_uv, 2),
            "current_uv": round(self.current_uv, 2),
            "mains_percent": round(self.mains_percent, 1),
            "status": self.status,
            "bands": {k: round(v, 1) for k, v in self.bands.items()},
        }


@dataclass(frozen=True, slots=True)
class SourceStats:
    """Live counters for the acquisition thread, for the header of the UI."""

    mode: SourceMode = "idle"
    label: str = ""
    started_at: float = 0.0
    elapsed_s: float = 0.0
    reports_seen: int = 0
    samples: int = 0
    reports_per_second: float = 0.0
    distinct_byte1: int = 0
    key_ok: bool | None = None
    error: str | None = None
    #: Chunks the source had to throw away because the consumer fell behind. Reported
    #: rather than hidden: a recording with a gap that does not admit it is worse
    #: than one that does.
    dropped_chunks: int = 0

    def as_payload(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "label": self.label,
            "elapsed_s": round(self.elapsed_s, 1),
            "reports_seen": self.reports_seen,
            "samples": self.samples,
            "reports_per_second": round(self.reports_per_second, 1),
            "distinct_byte1": self.distinct_byte1,
            "key_ok": self.key_ok,
            "error": self.error,
            "dropped_chunks": self.dropped_chunks,
        }
