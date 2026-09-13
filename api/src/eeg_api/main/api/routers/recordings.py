"""Browsing what is on disk: datasets, session recordings and flat CSVs."""

from __future__ import annotations

from typing import Any

import numpy as np
from fastapi import APIRouter, HTTPException, Query

from eeg_api.domain.metrics import alpha_metrics, band_powers
from eeg_api.domain.models import BANDS, CHANNELS
from eeg_api.eeg import csvio
from eeg_api.main.api.schemas import (
    LibraryEntryModel,
    LibraryModel,
    PreviewModel,
    SegmentModel,
    SpectrumModel,
)
from eeg_api.main.deps import LibraryDep
from eeg_api.services.library import LibraryError


router = APIRouter(prefix="/recordings", tags=["recordings"])


@router.get("", response_model=LibraryModel, summary="Everything in recordings/")
def list_recordings(library: LibraryDep) -> dict[str, Any]:
    """Newest first.

    Three kinds are listed together because they are the same thing to a user:
    ``dataset`` (written by a guided flow, so it has labels), ``session`` (a
    ``live_view.py`` folder) and ``recording`` (a flat CSV from ``record.py``).
    """
    entries = library.scan()
    return {
        "recordings": [entry.as_payload() for entry in entries],
        "directory": str(library.root),
        "total": len(entries),
    }


@router.get("/{entry_id}", response_model=LibraryEntryModel, summary="One recording")
def get_recording(entry_id: str, library: LibraryDep) -> dict[str, Any]:
    try:
        return library.get(entry_id).as_payload()
    except LibraryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{entry_id}/segments", response_model=list[SegmentModel], summary="Its labels")
def get_segments(entry_id: str, library: LibraryDep) -> list[dict[str, Any]]:
    """The state table of a dataset. Empty for a recording that has no labels."""
    try:
        return library.segments(entry_id)
    except LibraryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{entry_id}/preview", response_model=PreviewModel, summary="Decimated samples")
def get_preview(
    entry_id: str,
    library: LibraryDep,
    points: int = Query(default=900, ge=16, le=8000),
) -> dict[str, Any]:
    """For the chart. Decimated, not averaged, so transients survive."""
    try:
        return library.preview(entry_id, points=points)
    except LibraryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{entry_id}/spectrum", response_model=SpectrumModel, summary="Log power spectrum")
def get_spectrum(
    entry_id: str,
    library: LibraryDep,
    channel: str = Query(default="O1"),
    seconds: float | None = Query(default=None, gt=0, le=3600),
) -> dict[str, Any]:
    """One channel's spectrum, for checking that a dataset contains what it claims."""
    try:
        return library.spectrum(entry_id, channel=channel, seconds=seconds)
    except LibraryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{entry_id}/bands", summary="Per-channel band power, whole recording")
def get_bands(entry_id: str, library: LibraryDep) -> dict[str, Any]:
    """A quick summary of a dataset: which bands dominate on which channel.

    This is the endpoint that answers "did the eyes-closed protocol actually produce
    more occipital alpha than the eyes-open one?" without opening a notebook.
    """
    try:
        path = library.resolve(entry_id)
    except LibraryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    samples, _times = csvio.read_all(path)
    if samples.shape[0] == 0:
        return {"channels": [], "band_names": [name for name, _, _ in BANDS]}
    out = []
    for i, name in enumerate(CHANNELS):
        column = np.asarray(samples[:, i], dtype=np.float64)
        share, peak = alpha_metrics(column)
        out.append(
            {
                "name": name,
                "amplitude_uv": round(float(column.std()), 2),
                "bands": {k: round(v, 1) for k, v in band_powers(column).items()},
                "alpha_share": round(share, 2),
                "alpha_peak": round(peak, 3),
            }
        )
    return {"channels": out, "band_names": [name for name, _, _ in BANDS]}
