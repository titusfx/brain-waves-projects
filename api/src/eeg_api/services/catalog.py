"""Reading the authored channel catalog.

The prose is data (``domain/catalog/channels.yaml``); this is the adapter that turns
it into domain objects. It is read once at startup, because it cannot change while
the process runs, and because :meth:`ChannelCatalog.check` is worth running exactly
once — loudly — rather than on every request.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from eeg_api.domain.channels import (
    MISSING_MIDLINE_NOTE,
    BandDoc,
    ChannelCatalog,
    ChannelDoc,
    HeadPoint,
    MontageDoc,
)
from eeg_api.domain.models import CHANNELS


class CatalogError(RuntimeError):
    """The catalog file is missing, malformed, or disagrees with the hardware."""


def _as_list(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in value)


def _channel_doc(raw: dict[str, Any]) -> ChannelDoc:
    name = str(raw["name"]).strip().upper()
    head = raw.get("head") or {}
    return ChannelDoc(
        name=name,
        index=CHANNELS.index(name) if name in CHANNELS else -1,
        offset=int(raw.get("offset", 0)) or _default_offset(name),
        lobe=str(raw.get("lobe", "")),
        hemisphere=str(raw.get("hemisphere", "")),
        region=str(raw.get("region", "")),
        placement=" ".join(str(raw.get("placement", "")).split()),
        summary=" ".join(str(raw.get("summary", "")).split()),
        functions=_as_list(raw.get("functions")),
        tasks=_as_list(raw.get("tasks")),
        artefacts=_as_list(raw.get("artefacts")),
        expected=" ".join(str(raw.get("expected", "")).split()),
        head=HeadPoint(x=float(head.get("x", 0.0)), y=float(head.get("y", 0.0))),
        related=tuple(str(r).upper() for r in _as_list(raw.get("related"))),
    )


def _default_offset(name: str) -> int:
    from eeg_api.domain.models import CHANNEL_OFFSETS

    for candidate, offset in CHANNEL_OFFSETS:
        if candidate == name:
            return offset
    return 0


def load_catalog(path: Path) -> ChannelCatalog:
    """Parse and validate the catalog. Raises :class:`CatalogError` if it is wrong."""
    if not path.exists():
        raise CatalogError(f"channel catalog not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise CatalogError(f"{path} is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise CatalogError(f"{path} must contain a mapping at the top level")

    montage_raw = raw.get("montage") or {}
    reference_raw = montage_raw.get("reference") or {}
    montage = MontageDoc(
        name=str(montage_raw.get("name", "")),
        system=str(montage_raw.get("system", "")),
        sampling_hz=float(montage_raw.get("sampling_hz", 0.0)),
        scale=str(montage_raw.get("scale", "")),
        summary=" ".join(str(montage_raw.get("summary", "")).split()),
        reference_name=str(reference_raw.get("name", "")),
        reference_explanation=" ".join(str(reference_raw.get("explanation", "")).split()),
        midline_note=" ".join(str(montage_raw.get("midline_note", MISSING_MIDLINE_NOTE)).split()),
    )

    bands = tuple(
        BandDoc(
            key=str(item.get("key", "")),
            name=str(item.get("name", "")),
            range=str(item.get("range", "")),
            summary=" ".join(str(item.get("summary", "")).split()),
            note=" ".join(str(item.get("note", "")).split()),
        )
        for item in (raw.get("bands") or [])
    )

    channels_raw = raw.get("channels") or []
    if not isinstance(channels_raw, list):
        raise CatalogError("'channels' must be a list")
    docs = [_channel_doc(item) for item in channels_raw]
    # Canonical order is packet order, the same order the CSVs are written in. The
    # YAML may author them any way that reads well; the API serves them consistently.
    docs.sort(key=lambda doc: doc.index if doc.index >= 0 else len(CHANNELS))

    catalog = ChannelCatalog(
        montage=montage,
        bands=bands,
        channels=tuple(docs),
        disclaimer=" ".join(str(raw.get("disclaimer", "")).split()),
    )
    problems = catalog.check()
    if problems:
        raise CatalogError("channel catalog does not match the hardware: " + "; ".join(problems))
    return catalog
