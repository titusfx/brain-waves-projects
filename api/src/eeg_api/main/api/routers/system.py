"""System status and source control."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from eeg_api.main.api.schemas import (
    DeviceModel,
    SourceRequest,
    StatusModel,
)
from eeg_api.main.deps import HubDep, LibraryDep
from eeg_api.services.hub import SessionError
from eeg_api.services.library import LibraryError


router = APIRouter(prefix="/system", tags=["system"])


@router.get("/status", response_model=StatusModel, summary="Everything the header needs")
def status(hub: HubDep) -> dict[str, Any]:
    """The current source, its health, the device, and any running session."""
    return hub.status()


@router.get("/devices", response_model=DeviceModel, summary="HID interfaces on the dongle")
def devices(hub: HubDep) -> dict[str, Any]:
    """What is plugged in. ``streaming_interface`` is the one that actually carries EEG."""
    return hub.device_status()


@router.post("/source", response_model=StatusModel, summary="Switch the stream")
async def set_source(payload: SourceRequest, hub: HubDep, library: LibraryDep) -> dict[str, Any]:
    """Choose the dongle, a recording, the synthetic signal, or nothing.

    Refused with 409 while a dataset is being recorded: changing the signal under a
    running protocol would silently mix two different things into one class.
    """
    replay_path = None
    if payload.mode == "replay":
        if not payload.replay_id:
            raise HTTPException(status_code=400, detail="mode='replay' needs a 'replay_id'.")
        try:
            replay_path = library.resolve(payload.replay_id)
        except LibraryError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        return await hub.set_source(
            payload.mode,
            replay_path=replay_path,
            replay_speed=payload.replay_speed,
            replay_loop=payload.loop,
        )
    except SessionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
