"""Request and response models.

These exist so that ``web/openapi.json`` is a real contract and the Angular client's
generated ``schema.d.ts`` is worth having. Every field the browser reads is declared
here; the WebSocket frame is the one exception, because it is not an OpenAPI concept
and its type is hand-written on the client alongside the socket code that parses it.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Model(BaseModel):
    """Base: unknown fields are passed through rather than rejected."""

    model_config = ConfigDict(extra="allow")


# --------------------------------------------------------------------------- #
# Channels
# --------------------------------------------------------------------------- #
class HeadPointModel(_Model):
    x: float
    y: float


class ChannelDocModel(_Model):
    name: str
    index: int
    offset: int
    lobe: str
    hemisphere: str
    region: str
    placement: str
    summary: str
    functions: list[str]
    tasks: list[str]
    artefacts: list[str]
    expected: str
    related: list[str]
    head: HeadPointModel


class BandDocModel(_Model):
    key: str
    name: str
    range: str
    summary: str
    note: str


class ReferenceModel(_Model):
    name: str
    explanation: str


class MontageModel(_Model):
    name: str
    system: str
    sampling_hz: float
    scale: str
    summary: str
    reference: ReferenceModel
    midline_note: str


class CatalogModel(_Model):
    montage: MontageModel
    bands: list[BandDocModel]
    channels: list[ChannelDocModel]
    disclaimer: str


# --------------------------------------------------------------------------- #
# Flows
# --------------------------------------------------------------------------- #
class FlowStepModel(_Model):
    label: str
    seconds: float | None = None
    speak: str | None = None
    open_ended: bool = False


class FlowSpecModel(_Model):
    id: str = ""
    name: str
    mode: Literal["linear", "loop"] = "linear"
    countdown_seconds: float = 3.0
    repeat: int | None = None
    cycles: int | None = None
    rest_seconds: float = 0.0
    discard_tail: int = 0
    description: str = ""
    steps: list[FlowStepModel]
    total_seconds: float | None = None


class ValidationModel(_Model):
    valid: bool
    errors: list[str]
    warnings: list[str]


class PlanPhaseModel(_Model):
    kind: str
    label: str
    cycle: int
    duration: float | None = None


class PlanPreviewModel(_Model):
    phases: list[PlanPhaseModel]
    total_seconds: float | None = None
    cycles: int | None = None
    discard_tail: int = 0
    truncated: bool = False


class FlowStepInput(_Model):
    """One state, as authored in the builder."""

    label: str = Field(min_length=1, max_length=120)
    seconds: float | None = Field(default=None, ge=0.1, le=3600)
    speak: str | None = Field(default=None, max_length=200)


class FlowInput(_Model):
    """A protocol, as authored in the builder."""

    name: str = Field(min_length=1, max_length=120)
    mode: Literal["linear", "loop"] = "linear"
    countdown_seconds: float = Field(default=3.0, ge=0, le=60)
    repeat: int | None = Field(default=None, ge=1, le=1000)
    rest_seconds: float = Field(default=0.0, ge=0, le=600)
    discard_tail: int | None = Field(default=None, ge=0, le=20)
    description: str = Field(default="", max_length=2000)
    steps: list[FlowStepInput] = Field(min_length=1, max_length=64)


# --------------------------------------------------------------------------- #
# Library
# --------------------------------------------------------------------------- #
class LabelSummaryModel(_Model):
    label: str
    segments: int
    seconds: float
    samples: int


class SegmentModel(_Model):
    index: int
    label: str
    cycle: int
    step_index: int
    start_time: float
    end_time: float
    duration: float
    start_sample: int
    end_sample: int
    samples: int
    truncated: bool = False
    discarded: bool = False


class LibraryEntryModel(_Model):
    id: str
    name: str
    kind: str
    path: str
    created: str
    samples: int
    duration_s: float
    size_bytes: int
    channels: int
    labels: list[LabelSummaryModel] = Field(default_factory=list)
    flow_name: str | None = None
    segments: int = 0
    source: str | None = None
    notes: str | None = None
    dropped_chunks: int = 0


class LibraryModel(_Model):
    recordings: list[LibraryEntryModel]
    directory: str
    total: int


class PreviewModel(_Model):
    t: list[float]
    data: list[list[float]]
    total_samples: int
    decimation: int = 1


class SpectrumModel(_Model):
    freqs: list[float]
    power: list[float]
    channel: str


# --------------------------------------------------------------------------- #
# System
# --------------------------------------------------------------------------- #
class DeviceInterfaceModel(_Model):
    product: str
    serial: str
    interface: int
    streams: bool


class DeviceModel(_Model):
    hid_available: bool
    present: bool
    serial: str | None = None
    streaming_interface: DeviceInterfaceModel | None = None
    interfaces: list[DeviceInterfaceModel] = Field(default_factory=list)


class SourceStatsModel(_Model):
    mode: str = "idle"
    label: str = ""
    elapsed_s: float = 0.0
    reports_seen: int = 0
    samples: int = 0
    reports_per_second: float = 0.0
    distinct_byte1: int = 0
    key_ok: bool | None = None
    error: str | None = None
    dropped_chunks: int = 0


class RecordingStateModel(_Model):
    id: str
    name: str
    path: str
    samples: int
    duration: float
    segments: int
    current_label: str | None = None
    dropped_chunks: int = 0
    recording: bool = True


class EnginePhaseModel(_Model):
    kind: str
    label: str
    cycle: int
    step_index: int
    start: float
    end: float | None = None
    duration: float | None = None
    remaining: float | None = None
    progress: float = 0.0
    open_ended: bool = False
    recordable: bool = False
    speak: str | None = None


class EngineStateModel(_Model):
    """Where a running protocol is, right now."""

    finished: bool
    stopped: bool
    elapsed: float
    cycle: int
    cycles: int | None = None
    phase: EnginePhaseModel | None = None
    upcoming: list[PlanPhaseModel] = Field(default_factory=list)
    total_seconds: float | None = None


class RecordingSummaryModel(_Model):
    """What a finished dataset contains, and what was deliberately thrown away."""

    id: str
    name: str
    path: str
    fs: float
    samples: int
    duration: float
    dropped_chunks: int = 0
    kept_segments: list[SegmentModel] = Field(default_factory=list)
    discarded_segments: list[SegmentModel] = Field(default_factory=list)
    labels: list[LabelSummaryModel] = Field(default_factory=list)
    removed: bool | None = None


class SessionStateModel(_Model):
    active: bool
    id: str = ""
    flow: FlowSpecModel
    dataset_name: str
    notes: str = ""
    voice: bool = True
    started: str
    recording: bool = False
    engine: EngineStateModel
    recording_state: RecordingStateModel | None = None
    outcome: str | None = None
    error: str | None = None
    summary: RecordingSummaryModel | None = None


class StatusModel(_Model):
    source: str
    source_label: str
    stats: SourceStatsModel
    buffer_seconds: float
    subscribers: int
    device: DeviceModel
    recording: RecordingStateModel | None = None
    session: SessionStateModel | None = None
    recordings_dir: str
    fs: float
    error: str | None = None


# --------------------------------------------------------------------------- #
# Requests
# --------------------------------------------------------------------------- #
class SourceRequest(_Model):
    """Switch the stream: the dongle, a recording, the synthetic signal, or nothing."""

    mode: Literal["idle", "live", "demo", "replay"]
    replay_id: str | None = Field(
        default=None, description="Library id of the recording to replay (mode='replay')."
    )
    replay_speed: float = Field(default=1.0, gt=0, le=64)
    loop: bool = True


class QuickRecordRequest(_Model):
    """The one-button case: name it, press record, it counts 3-2-1 and records."""

    label: str = Field(
        min_length=1, max_length=120, description="What this data is, e.g. 'eyes closed'."
    )
    countdown_seconds: float = Field(default=3.0, ge=0, le=60)
    dataset_name: str | None = Field(default=None, max_length=120)
    notes: str = Field(default="", max_length=2000)
    voice: bool = True


class StartSessionRequest(_Model):
    """Run a saved flow, or an inline one."""

    flow_id: str | None = None
    flow: FlowInput | None = None
    dataset_name: str | None = Field(default=None, max_length=120)
    notes: str = Field(default="", max_length=2000)
    voice: bool = True
    countdown_seconds: float | None = Field(
        default=None,
        ge=0,
        le=60,
        description="Override the flow's countdown for this run only.",
    )


class SampleBlockModel(_Model):
    t0: float
    data: list[list[float]]
