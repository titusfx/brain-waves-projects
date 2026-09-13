"""The composition root: settings, the app factory, and the HTTP/WebSocket adapters."""

from __future__ import annotations

from eeg_api.main.run import app, make_app


__all__ = ["app", "make_app"]
