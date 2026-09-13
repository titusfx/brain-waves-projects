"""Saved protocols: create, read, update, delete, validate and preview them."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status

from eeg_api.domain.flows import FlowSpec, FlowStep, validate
from eeg_api.main.api.schemas import (
    FlowInput,
    FlowSpecModel,
    PlanPreviewModel,
    ValidationModel,
)
from eeg_api.main.deps import FlowsDep
from eeg_api.services.library import LibraryError
from eeg_api.services.runner import plan_preview


router = APIRouter(prefix="/flows", tags=["flows"])


def spec_from_input(payload: FlowInput, flow_id: str = "") -> FlowSpec:
    """The one translation from the builder's JSON to the domain's protocol."""
    return FlowSpec(
        id=flow_id,
        name=payload.name.strip(),
        mode=payload.mode,
        countdown_seconds=payload.countdown_seconds,
        repeat=payload.repeat,
        rest_seconds=payload.rest_seconds,
        discard_tail=payload.discard_tail,
        description=payload.description.strip(),
        steps=tuple(
            FlowStep(label=step.label.strip(), seconds=step.seconds, speak=step.speak)
            for step in payload.steps
        ),
    )


@router.get("", response_model=list[FlowSpecModel], summary="Saved flows")
def list_flows(flows: FlowsDep) -> list[dict[str, Any]]:
    return [spec.as_payload() for spec in flows.list()]


@router.post(
    "", response_model=FlowSpecModel, status_code=status.HTTP_201_CREATED, summary="Save a new flow"
)
def create_flow(payload: FlowInput, flows: FlowsDep) -> dict[str, Any]:
    spec = spec_from_input(payload)
    errors, _warnings = validate(spec)
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    return flows.create(spec).as_payload()


@router.post("/validate", response_model=ValidationModel, summary="Check a flow without saving it")
def check_flow(payload: FlowInput) -> dict[str, Any]:
    """Errors make a flow unrunnable; warnings are things worth knowing.

    The rules are the engine's own, so the builder cannot accept something the runner
    will refuse â€” and the messages say what to change, not which field is wrong.
    """
    errors, warnings = validate(spec_from_input(payload))
    return {"valid": not errors, "errors": errors, "warnings": warnings}


@router.post("/preview", response_model=PlanPreviewModel, summary="What this flow will do")
def preview_flow(payload: FlowInput) -> dict[str, Any]:
    """The running order, expanded â€” the builder's timeline strip."""
    spec = spec_from_input(payload)
    errors, _warnings = validate(spec)
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    return plan_preview(spec)


@router.get("/{flow_id}", response_model=FlowSpecModel, summary="One saved flow")
def get_flow(flow_id: str, flows: FlowsDep) -> dict[str, Any]:
    try:
        spec = flows.get(flow_id)
    except LibraryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if spec is None:
        raise HTTPException(status_code=404, detail=f"no flow called {flow_id!r}")
    return spec.as_payload()


@router.put("/{flow_id}", response_model=FlowSpecModel, summary="Update a saved flow")
def update_flow(flow_id: str, payload: FlowInput, flows: FlowsDep) -> dict[str, Any]:
    try:
        if flows.get(flow_id) is None:
            raise HTTPException(status_code=404, detail=f"no flow called {flow_id!r}")
        spec = spec_from_input(payload, flow_id=flow_id)
        errors, _warnings = validate(spec)
        if errors:
            raise HTTPException(status_code=422, detail=errors)
        return flows.save(spec, flow_id).as_payload()
    except LibraryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{flow_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a flow")
def delete_flow(flow_id: str, flows: FlowsDep) -> None:
    try:
        if not flows.delete(flow_id):
            raise HTTPException(status_code=404, detail=f"no flow called {flow_id!r}")
    except LibraryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
