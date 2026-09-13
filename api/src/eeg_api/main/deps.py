"""Dependencies.

Everything app-scoped is parked on ``app.state`` by the lifespan, and read back here.
That indirection is what lets the tests build an isolated app with its own settings,
its own recordings folder and its own hub, instead of reaching for a process global.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from eeg_api.config import Settings
from eeg_api.domain.channels import ChannelCatalog
from eeg_api.services.hub import AcquisitionHub
from eeg_api.services.library import FlowStore, RecordingLibrary
from eeg_api.services.runner import FlowRunner


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_catalog(request: Request) -> ChannelCatalog:
    catalog: ChannelCatalog = request.app.state.catalog
    return catalog


def get_hub(request: Request) -> AcquisitionHub:
    hub: AcquisitionHub = request.app.state.hub
    return hub


def get_library(request: Request) -> RecordingLibrary:
    library: RecordingLibrary = request.app.state.library
    return library


def get_flows(request: Request) -> FlowStore:
    flows: FlowStore = request.app.state.flows
    return flows


def get_runner(request: Request) -> FlowRunner | None:
    return get_hub(request).runner


SettingsDep = Annotated[Settings, Depends(get_settings)]
CatalogDep = Annotated[ChannelCatalog, Depends(get_catalog)]
HubDep = Annotated[AcquisitionHub, Depends(get_hub)]
LibraryDep = Annotated[RecordingLibrary, Depends(get_library)]
FlowsDep = Annotated[FlowStore, Depends(get_flows)]
RunnerDep = Annotated[FlowRunner | None, Depends(get_runner)]
