"""The channel documentation, as data."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from eeg_api.main.api.schemas import CatalogModel, ChannelDocModel
from eeg_api.main.deps import CatalogDep


router = APIRouter(prefix="/channels", tags=["channels"])


@router.get("", response_model=CatalogModel, summary="The whole montage, with documentation")
def catalog(catalog: CatalogDep) -> dict[str, Any]:
    """Montage, frequency bands, and a documented entry for each of the 14 channels.

    The prose is authored in ``domain/catalog/channels.yaml``; the loader refuses to
    start if a documented channel is not a real channel of this montage.
    """
    return catalog.as_payload()


@router.get("/{name}", response_model=ChannelDocModel, summary="One channel")
def channel(name: str, catalog: CatalogDep) -> dict[str, Any]:
    """Case-insensitive: ``/api/channels/o1`` and ``/api/channels/O1`` are the same."""
    doc = catalog.get(name)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"no channel called {name!r}")
    return doc.as_payload()
