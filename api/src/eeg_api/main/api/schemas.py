"""Request and response models.

These exist so that ``web/openapi.json`` is a real contract and the Angular client's
generated ``schema.d.ts`` is worth having. Every field the browser reads is declared
here; the WebSocket frame is the one exception, because it is not an OpenAPI concept
and its type is hand-written on the client alongside the socket code that parses it.

**Response models declare no defaults on purpose.** A default makes the field optional
in the generated TypeScript, so the client has to treat every field as maybe-missing —
which is exactly the uncertainty this contract exists to remove. Every field below is
therefore required; where a field can legitimately be *null* it is typed ``T | None``
without a default, which means "always present, possibly null". FastAPI validates every
response against these models, so a payload that forgot a key fails its test rather
than producing an `undefined` in the browser three layers away.

Request models keep their defaults, because that is where optionality belongs: the
client may omit them.
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
    seconds: float | None
    speak: str | None
    open_ended: bool


class FlowSpecModel(_Model):
    id: str
    name: str
    mode: Literal["linear", "loop"]
    countdown_seconds: float
    repeat: int | None
    cycles: int | None
    rest_seconds: float
    discard_tail: int
    description: str
    steps: list[FlowStepModel]
    total_seconds: float | None


class ValidationModel(_Model):
    valid: bool
    errors: list[str]
    warnings: list[str]


class PlanPhaseModel(_Model):
    kind: str
    label: str
    cycle: int
    duration: float | None


class PlanPreviewModel(_Model):
    phases: list[PlanPhaseModel]
    total_seconds: float | None
    cycles: int | None
    discard_tail: int
    truncated: bool


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
    truncated: bool
    discarded: bool


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
    labels: list[LabelSummaryModel]
    flow_name: str | None
    segments: int
    source: str | None
    notes: str | None
    dropped_chunks: int


class LibraryModel(_Model):
    recordings: list[LibraryEntryModel]
    directory: str
    total: int


class PreviewModel(_Model):
    t: list[float]
    data: list[list[float]]
    total_samples: int
    decimation: int


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
    serial: str | None
    streaming_interface: DeviceInterfaceModel | None
    interfaces: list[DeviceInterfaceModel]


class SourceStatsModel(_Model):
    mode: str
    label: str
    elapsed_s: float
    reports_seen: int
    samples: int
    reports_per_second: float
    distinct_byte1: int
    key_ok: bool | None
    error: str | None
    dropped_chunks: int


class RecordingStateModel(_Model):
    id: str
    name: str
    path: str
    samples: int
    duration: float
    segments: int
    current_label: str | None
    dropped_chunks: int
    recording: bool


class EnginePhaseModel(_Model):
    kind: str
    label: str
    cycle: int
    step_index: int
    start: float
    end: float | None
    duration: float | None
    remaining: float | None
    progress: float
    open_ended: bool
    recordable: bool
    speak: str | None


class EngineStateModel(_Model):
    """Where a running protocol is, right now."""

    finished: bool
    stopped: bool
    elapsed: float
    cycle: int
    cycles: int | None
    phase: EnginePhaseModel | None
    upcoming: list[PlanPhaseModel]
    total_seconds: float | None


class RecordingSummaryModel(_Model):
    """What a finished dataset contains, and what was deliberately thrown away."""

    id: str
    name: str
    path: str
    fs: float
    samples: int
    duration: float
    dropped_chunks: int
    kept_segments: list[SegmentModel]
    discarded_segments: list[SegmentModel]
    labels: list[LabelSummaryModel]
    #: Only sent when the dataset was thrown away, so this one really may be absent.
    removed: bool | None = None


class SessionStateModel(_Model):
    active: bool
    id: str
    flow: FlowSpecModel
    dataset_name: str
    notes: str
    voice: bool
    started: str
    recording: bool
    engine: EngineStateModel
    recording_state: RecordingStateModel | None
    outcome: str | None
    error: str | None
    summary: RecordingSummaryModel | None


class StatusModel(_Model):
    source: str
    source_label: str
    stats: SourceStatsModel
    buffer_seconds: float
    subscribers: int
    device: DeviceModel
    recording: RecordingStateModel | None
    session: SessionStateModel | None
    recordings_dir: str
    fs: float
    error: str | None


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
