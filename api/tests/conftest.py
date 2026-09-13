"""Shared fixtures.

Every test gets its own recordings folder, its own flows folder and its own hub, so
nothing here can see the developer's real data, and no test can leave a dataset in
``recordings/``. That matters: these files are biometric data (AGENTS.md rule 6).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from eeg_api.config import Settings
from eeg_api.main.run import make_app


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings pointed entirely at ``tmp_path``, and never at the dongle."""
    return Settings(
        environment="test",
        recordings_dir=tmp_path / "recordings",
        flows_dir=tmp_path / "flows",
        web_dist=tmp_path / "web-dist",
        default_source="idle",
        # A fast tick and a short window keep the timing-sensitive tests quick while
        # still exercising the same code path a real 10 Hz tick uses.
        tick_hz=40.0,
        window_seconds=1.0,
    )


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return make_app(settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    """A client with the lifespan running, so the hub and catalog exist."""
    with TestClient(app) as test_client:
        yield test_client
