"""Settings, read once from the environment.

Paths default to locations *inside the repository* rather than the process working
directory, so ``uv --directory api run …`` and a bare ``uvicorn`` behave the same
and neither can accidentally create a second, empty ``recordings/`` folder.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _project_root() -> Path:
    """The repository root: ``<root>/api/src/eeg_api/config.py`` → ``<root>``."""
    return Path(__file__).resolve().parents[3]


PROJECT_ROOT = _project_root()
PACKAGE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    """Environment-driven configuration (all variables prefixed ``EEG_``)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="EEG_",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "EPOC+ EEG Workbench API"
    version: str = "0.1.0"
    environment: str = "local"

    # --- acquisition -------------------------------------------------------
    #: EEG sample rate. The EPOC+ emits ~159 reports/s, of which ~128 are EEG
    #: samples and ~31 are status packets (AGENTS.md §3).
    fs: float = 128.0
    #: The 0.5 Hz single-pole highpass that removes the per-channel DC offset.
    highpass_hz: float = 0.5
    #: HID identity of the dongle.
    device_vid: int = 0x1234
    device_pid: int = 0xED02
    report_len: int = 32
    #: The dongle's HID product string for the interface that actually streams.
    #: Interface 0 ("Brain Computer Interface USB Receiver/Dongle") is silent;
    #: only interface 1 ("EEG Signals") carries data (AGENTS.md rule 4).
    streaming_product: str = "EEG Signals"

    #: idle | live | demo | replay | auto. ``auto`` starts the dongle when one is
    #: plugged in and stays idle otherwise, so the API never invents data that
    #: looks like a brain unless it was asked to.
    default_source: str = "auto"

    # --- streaming ---------------------------------------------------------
    #: How often a frame of samples + metrics is pushed to the browser.
    tick_hz: float = 10.0
    #: The window the amplitude / mains / band metrics are computed over.
    window_seconds: float = 2.0
    #: Replay speed multiplier when the source is a recording.
    replay_speed: float = 1.0

    # --- storage -----------------------------------------------------------
    recordings_dir: Path = PROJECT_ROOT / "recordings"
    #: Saved flow definitions (the "screen where we create flows").
    flows_dir: Path = PROJECT_ROOT / "api" / "var" / "flows"
    #: Authored channel documentation.
    catalog_file: Path = PACKAGE_DIR / "domain" / "catalog" / "channels.yaml"
    #: The built Angular app, served at / when it exists.
    web_dist: Path = PROJECT_ROOT / "web" / "dist" / "web" / "browser"

    # --- http --------------------------------------------------------------
    #: Origins allowed to call this API directly from a browser.
    #:
    #: The dev server proxies `/api` and `/ws` server-side, so it does not *need* an entry
    #: here — but a page opened against the dev server that calls the API cross-origin
    #: does, and a CORS failure is a confusing way to discover that.
    #:
    #: 4200 was Angular's default and 4300 is what this project first used; both are
    #: already taken by other projects on the author's machine, which is why the dev
    #: server here runs on **4301** (see the root `package.json`).
    cors_origins: list[str] = [
        "http://localhost:4301",
        "http://127.0.0.1:4301",
        "http://localhost:4200",
        "http://127.0.0.1:4200",
        "http://localhost:4300",
        "http://127.0.0.1:4300",
    ]

    @property
    def max_samples_window(self) -> int:
        """Rows retained in memory for REST previews and metric windows."""
        return int(self.fs * max(self.window_seconds, 10.0) * 4)


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()
