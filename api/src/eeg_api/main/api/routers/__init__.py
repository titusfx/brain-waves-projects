"""Inbound HTTP and WebSocket adapters."""

from __future__ import annotations

from eeg_api.main.api.routers import (
    channels,
    flows,
    recordings,
    sessions,
    stream,
    system,
)


__all__ = ["channels", "flows", "recordings", "sessions", "stream", "system"]
