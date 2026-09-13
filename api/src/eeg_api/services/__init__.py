"""The services layer: the acquisition hub, the recorder, the flow runner and the library.

Use cases live here. They orchestrate the domain and the device layer, and they know
nothing about HTTP — which is what lets the whole recording pipeline be tested by
calling it, rather than by driving a server.
"""

from __future__ import annotations

from eeg_api.services.catalog import CatalogError, load_catalog
from eeg_api.services.hub import AcquisitionHub, SessionError
from eeg_api.services.library import FlowStore, LibraryEntry, LibraryError, RecordingLibrary
from eeg_api.services.recorder import DatasetRecorder, Segment
from eeg_api.services.ring import RingBuffer
from eeg_api.services.runner import FlowRunner, eyes_state_for_label, plan_preview


__all__ = [
    "AcquisitionHub",
    "CatalogError",
    "DatasetRecorder",
    "FlowRunner",
    "FlowStore",
    "LibraryEntry",
    "LibraryError",
    "RecordingLibrary",
    "RingBuffer",
    "Segment",
    "SessionError",
    "eyes_state_for_label",
    "load_catalog",
    "plan_preview",
]
