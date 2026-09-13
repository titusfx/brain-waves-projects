"""The domain layer: the signal, the montage, the analysis and the flow state machine.

Nothing here imports FastAPI, and nothing here performs I/O beyond reading its own
authored catalog. That is enforced by ``import-linter`` and by a ruff banned-api
rule, so it is a build failure rather than a code-review opinion.
"""

from __future__ import annotations

from eeg_api.domain.models import (
    BANDS,
    CHANNEL_OFFSETS,
    CHANNELS,
    EEG_PACKET_TYPE,
    FS,
    OCCIPITAL_CHANNELS,
    QUALITY_OFFSET,
    STATUS_PACKET_TYPE,
    UV_PER_LSB,
    ChannelMetrics,
    Chunk,
    SourceMode,
    SourceStats,
)


__all__ = [
    "BANDS",
    "CHANNELS",
    "CHANNEL_OFFSETS",
    "EEG_PACKET_TYPE",
    "FS",
    "OCCIPITAL_CHANNELS",
    "QUALITY_OFFSET",
    "STATUS_PACKET_TYPE",
    "UV_PER_LSB",
    "ChannelMetrics",
    "Chunk",
    "SourceMode",
    "SourceStats",
]
