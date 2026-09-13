"""The channel documentation model.

The prose lives in ``catalog/channels.yaml``; this module is only the shape it is
read into and the lookups the API needs. Keeping the two apart means the text can
be corrected by someone who knows the neurophysiology without touching Python.

The catalog is checked against the hardware: every documented channel must be a
real channel of the montage, at the offset :mod:`eeg_api.domain.models` says it is.
A doc for a channel that does not exist is worse than no doc.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from eeg_api.domain.models import CHANNEL_OFFSETS, CHANNELS


#: The EPOC+ has no midline electrode, so this is what the montage *cannot* do.
MISSING_MIDLINE_NOTE = (
    "The EPOC+ has no midline electrode (no Fz, Cz or Pz), so midline-maximal "
    "components are only available here in their lateralised form."
)


@dataclass(frozen=True, slots=True)
class HeadPoint:
    """A top-down position in a unit circle: -x is the subject's left, +y is anterior."""

    x: float
    y: float

    def as_payload(self) -> dict[str, float]:
        return {"x": round(self.x, 3), "y": round(self.y, 3)}


@dataclass(frozen=True, slots=True)
class ChannelDoc:
    """Everything the UI shows when a channel is clicked."""

    name: str
    lobe: str
    hemisphere: str
    region: str
    placement: str
    summary: str
    functions: tuple[str, ...]
    tasks: tuple[str, ...]
    artefacts: tuple[str, ...]
    expected: str
    head: HeadPoint
    related: tuple[str, ...] = ()
    index: int = 0
    offset: int = 0

    def as_payload(self) -> dict[str, object]:
        return {
            "name": self.name,
            "index": self.index,
            "offset": self.offset,
            "lobe": self.lobe,
            "hemisphere": self.hemisphere,
            "region": self.region,
            "placement": self.placement,
            "summary": self.summary,
            "functions": list(self.functions),
            "tasks": list(self.tasks),
            "artefacts": list(self.artefacts),
            "expected": self.expected,
            "related": list(self.related),
            "head": self.head.as_payload(),
        }


@dataclass(frozen=True, slots=True)
class BandDoc:
    """A frequency band, for the legend beside the spectrum."""

    key: str
    name: str
    range: str
    summary: str
    note: str

    def as_payload(self) -> dict[str, str]:
        return {
            "key": self.key,
            "name": self.name,
            "range": self.range,
            "summary": self.summary,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class MontageDoc:
    """The headset as a whole: the montage, the reference pair, and the caveat."""

    name: str = ""
    system: str = ""
    sampling_hz: float = 0.0
    scale: str = ""
    summary: str = ""
    reference_name: str = ""
    reference_explanation: str = ""
    midline_note: str = MISSING_MIDLINE_NOTE

    def as_payload(self) -> dict[str, object]:
        return {
            "name": self.name,
            "system": self.system,
            "sampling_hz": self.sampling_hz,
            "scale": self.scale,
            "summary": self.summary,
            "reference": {
                "name": self.reference_name,
                "explanation": self.reference_explanation,
            },
            "midline_note": self.midline_note,
        }


@dataclass(frozen=True, slots=True)
class ChannelCatalog:
    """The whole authored catalog: montage, bands and the 14 channel docs."""

    montage: MontageDoc
    bands: tuple[BandDoc, ...]
    channels: tuple[ChannelDoc, ...]
    disclaimer: str = ""
    _by_name: Mapping[str, ChannelDoc] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_by_name", MappingProxyType({c.name: c for c in self.channels}))

    def get(self, name: str) -> ChannelDoc | None:
        """Case-insensitive lookup, so ``?channel=o1`` works from a URL."""
        return self._by_name.get(name.strip().upper())

    def names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.channels)

    def check(self) -> list[str]:
        """Problems with the catalog itself. Empty means it matches the hardware."""
        problems: list[str] = []
        documented = self.names()
        if set(documented) != set(CHANNELS):
            missing = sorted(set(CHANNELS) - set(documented))
            extra = sorted(set(documented) - set(CHANNELS))
            if missing:
                problems.append(f"undocumented channels: {', '.join(missing)}")
            if extra:
                problems.append(f"documented channels that do not exist: {', '.join(extra)}")
        if len(documented) != len(set(documented)):
            problems.append("a channel is documented twice")

        offsets = dict(CHANNEL_OFFSETS)
        for doc in self.channels:
            if doc.offset != offsets.get(doc.name):
                problems.append(
                    f"{doc.name}: catalog offset {doc.offset} != packet offset {offsets.get(doc.name)}"
                )
            if doc.name in CHANNELS and doc.index != CHANNELS.index(doc.name):
                problems.append(
                    f"{doc.name}: catalog index {doc.index} does not match packet order"
                )
            if not (0.0 <= abs(doc.head.x) <= 1.0 and 0.0 <= abs(doc.head.y) <= 1.0):
                problems.append(f"{doc.name}: head map position is outside the unit circle")
            problems.extend(
                f"{doc.name}: 'related' names unknown channel {related}"
                for related in doc.related
                if related not in offsets
            )
        if not self.disclaimer:
            problems.append("the catalog carries no disclaimer")
        return problems

    def as_payload(self) -> dict[str, Any]:
        return {
            "montage": self.montage.as_payload(),
            "bands": [b.as_payload() for b in self.bands],
            "channels": [c.as_payload() for c in self.channels],
            "disclaimer": self.disclaimer,
        }
