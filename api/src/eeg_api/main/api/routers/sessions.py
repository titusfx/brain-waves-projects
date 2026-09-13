"""Running a guided protocol, and the one-button "record this label" case."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from fastapi import APIRouter, HTTPException, status

from eeg_api.domain.flows import FlowSpec, single_label_flow
from eeg_api.main.api.routers.flows import spec_from_input
from eeg_api.main.api.schemas import (
    QuickRecordRequest,
    SessionStateModel,
    StartSessionRequest,
)
from eeg_api.main.deps import FlowsDep, HubDep, RunnerDep
from eeg_api.services.hub import AcquisitionHub, SessionError
from eeg_api.services.library import LibraryError
from eeg_api.services.runner import FlowRunner


router = APIRouter(prefix="/sessions", tags=["sessions"])


def _resolve_spec(payload: StartSessionRequest, flows: FlowsDep) -> FlowSpec:
    spec: FlowSpec | None = None
    if payload.flow is not None:
        spec = spec_from_input(payload.flow)
    elif payload.flow_id:
        try:
            spec = flows.get(payload.flow_id)
        except LibraryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if spec is None:
            raise HTTPException(status_code=404, detail=f"no flow called {payload.flow_id!r}")
    if spec is None:
        raise HTTPException(status_code=400, detail="Send either 'flow_id' or an inline 'flow'.")
    if payload.countdown_seconds is not None:
        spec = replace(spec, countdown_seconds=payload.countdown_seconds)
    return spec


async def _begin(
    hub: AcquisitionHub, spec: FlowSpec, dataset_name: str | None, notes: str, voice: bool
) -> dict[str, Any]:
    if hub.runner is not None and hub.runner.state()["active"]:
        raise HTTPException(status_code=409, detail="A session is already running. Stop it first.")
    runner = FlowRunner(hub, spec, dataset_name=dataset_name, notes=notes, speak=voice)
    try:
        return await runner.start()
    except SessionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/current", response_model=SessionStateModel | None, summary="The running session")
def current(runner: RunnerDep) -> dict[str, Any] | None:
    """``null`` when nothing is running â€” which is the normal state."""
    return runner.state() if runner is not None else None


@router.post(
    "", response_model=SessionStateModel, status_code=status.HTTP_201_CREATED, summary="Run a flow"
)
async def start_session(
    payload: StartSessionRequest, hub: HubDep, flows: FlowsDep
) -> dict[str, Any]:
    """Start a protocol.

    The countdown runs first and is **not recorded**; the dataset is created the
    moment it ends. If the operator stops during the countdown there is no dataset at
    all, because there was never any data.
    """
    spec = _resolve_spec(payload, flows)
    return await _begin(hub, spec, payload.dataset_name, payload.notes, payload.voice)


@router.post(
    "/quick",
    response_model=SessionStateModel,
    status_code=status.HTTP_201_CREATED,
    summary="Record one label",
)
async def quick_record(payload: QuickRecordRequest, hub: HubDep) -> dict[str, Any]:
    """Name it, press the button, hear 3-2-1, and record until you stop.

    This is deliberately the same machinery as a flow â€” a one-state, open-ended,
    linear protocol â€” rather than a second code path that could drift from it.
    """
    spec = single_label_flow(payload.label.strip(), payload.countdown_seconds)
    return await _begin(
        hub, spec, payload.dataset_name or payload.label, payload.notes, payload.voice
    )


@router.post("/current/stop", response_model=SessionStateModel, summary="Stop and keep the data")
async def stop_session(runner: RunnerDep) -> dict[str, Any]:
    """Stop the run.

    A looping protocol drops its tail states here â€” the one you interrupted plus the
    completed one before it â€” because reaching for the button is itself a change in
    what the subject is doing. See ``FlowSpec.effective_discard_tail``.
    """
    if runner is None:
        raise HTTPException(status_code=404, detail="No session is running.")
    return await runner.stop()


@router.post("/current/abort", response_model=SessionStateModel, summary="Stop and discard")
async def abort_session(runner: RunnerDep) -> dict[str, Any]:
    """Stop and delete the dataset. For a run that went wrong."""
    if runner is None:
        raise HTTPException(status_code=404, detail="No session is running.")
    return await runner.abort()
