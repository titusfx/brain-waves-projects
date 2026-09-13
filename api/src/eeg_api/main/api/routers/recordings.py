"""Browsing what is on disk: datasets, session recordings and flat CSVs."""

from __future__ import annotations

from typing import Any

import numpy as np
from fastapi import APIRouter, HTTPException, Query

from eeg_api.domain.metrics import alpha_metrics, band_powers
from eeg_api.domain.models import BANDS, CHANNELS
from eeg_api.eeg import csvio
from eeg_api.main.api.schemas import (
    DeletedRecordingModel,
    DiscoveryModel,
    DiscoveryRequest,
    LibraryEntryModel,
    LibraryModel,
    PreviewModel,
    SegmentModel,
    SpectrumModel,
)
from eeg_api.main.deps import HubDep, LibraryDep
from eeg_api.services.library import LibraryError, LibraryInUseError, LibraryNotFoundError


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


@router.delete(
    "/{entry_id}",
    response_model=DeletedRecordingModel,
    summary="Delete a recording, for good",
)
def delete_recording(entry_id: str, library: LibraryDep, hub: HubDep) -> dict[str, Any]:
    """Remove a recording or dataset from ``recordings/``.

    Irreversible, and it removes a whole dataset folder when the id names one — samples,
    labels, metadata and all. The screen puts a confirmation in front of it that names
    what will go and how much disk it holds; this endpoint's job is to be safe about
    *what*, not to ask twice. It refuses anything the current source or recording is
    using, so a live replay cannot be deleted out from under itself.
    """
    try:
        return library.delete(entry_id, blocked=hub.in_use_paths())
    except LibraryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LibraryInUseError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except LibraryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
    start: float | None = Query(default=None, ge=0, description="Window start, seconds."),
    end: float | None = Query(default=None, gt=0, description="Window end, seconds."),
) -> dict[str, Any]:
    """For the chart. Decimated, not averaged, so transients survive.

    ``start``/``end`` narrow it to one state's window — the times in ``labels.csv`` — so
    the screen can show a single instance of a state instead of the whole session.
    """
    try:
        return library.preview(entry_id, points=points, start=start, end=end)
    except LibraryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{entry_id}/spectrum", response_model=SpectrumModel, summary="Log power spectrum")
def get_spectrum(
    entry_id: str,
    library: LibraryDep,
    channel: str = Query(default="O1"),
    seconds: float | None = Query(default=None, gt=0, le=3600),
    start: float | None = Query(default=None, ge=0, description="Window start, seconds."),
    end: float | None = Query(default=None, gt=0, description="Window end, seconds."),
) -> dict[str, Any]:
    """One channel's spectrum, for checking that a dataset contains what it claims."""
    try:
        return library.spectrum(entry_id, channel=channel, seconds=seconds, start=start, end=end)
    except LibraryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/{entry_id}/discovery",
    response_model=DiscoveryModel,
    summary="What repeats within a state, and what separates two states",
)
def discover(entry_id: str, payload: DiscoveryRequest, library: LibraryDep) -> dict[str, Any]:
    """The Discovery screen's analysis, for one dataset and one channel.

    For each selected state: its instances' spectra, how much the instances agree
    (repeatability), and — for two states — which frequency bins actually differ, which
    are the *same in both* and therefore cannot explain the difference, and whether the
    biggest difference survives a label-shuffling test. The channel ranking answers
    "which electrode separates these states?" by measuring all fourteen.
    """
    try:
        return library.discover(
            entry_id,
            channel=payload.channel,
            labels=payload.labels,
            instances=payload.instances,
            window_seconds=payload.window_seconds,
            points=payload.points,
            min_seconds=payload.min_seconds,
            permutations=payload.permutations,
        )
    except LibraryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


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
