"""The three sources, and the CSV reader that makes old recordings replayable.

The synthetic source is tested for the properties the app depends on rather than for
its exact waveform: it must produce physiological amplitudes, it must show occipital
alpha that reacts to the eyes, and it must include a weak channel and a dry one so
the contact logic is exercised without a headset.
"""

from __future__ import annotations

import queue
import time
from pathlib import Path

import numpy as np
import pytest

from eeg_api.domain.metrics import alpha_metrics, channel_metrics, status_for
from eeg_api.domain.models import CHANNELS, STATUS_DRY
from eeg_api.eeg import csvio
from eeg_api.eeg.sources import ReplaySource, SyntheticSource, create_source


FS = 128.0


class Collector:
    """A stand-in for the chunk queue that just remembers what it was given."""

    def __init__(self) -> None:
        self.chunks: list[np.ndarray] = []

    def put_nowait(self, chunk: object) -> None:
        self.chunks.append(chunk.uv)  # type: ignore[attr-defined]

    def get_nowait(self) -> None:
        raise AssertionError("the synthetic source must never drop a chunk in tests")

    def drain(self) -> np.ndarray:
        if not self.chunks:
            return np.zeros((0, len(CHANNELS)))
        return np.vstack(self.chunks)


def generate(seconds: float, *, closed: bool | None, seed: int = 7) -> np.ndarray:
    """Run the generator synchronously, without its thread.

    Driving ``_generate``/``_emit`` directly keeps these assertions deterministic and
    fast; the alternative is a five-second sleep for a result that depends on thread
    scheduling. The threaded path is covered separately, below.
    """
    sink = Collector()
    source = SyntheticSource(out=sink, seed=seed)  # type: ignore[arg-type]
    source.set_eyes_closed(closed)
    block = int(FS / 4)
    for _ in range(int(seconds * FS) // block):
        source._emit(source._generate(block))
    return sink.drain()


# --------------------------------------------------------------------------- #
# The synthetic source
# --------------------------------------------------------------------------- #
def test_it_produces_the_right_shape() -> None:
    data = generate(4.0, closed=True)
    assert data.shape == (int(4 * FS), len(CHANNELS))
    assert np.isfinite(data).all()


def test_amplitudes_are_physiological() -> None:
    metrics = {m.name: m for m in channel_metrics(generate(4.0, closed=True))}
    for name in ("F3", "F4", "O1", "O2", "P7", "P8"):
        assert 5.0 < metrics[name].amplitude_uv < 200.0, name
        assert metrics[name].status == "ok", name


def test_alpha_rises_when_the_eyes_close() -> None:
    closed = generate(6.0, closed=True)
    opened = generate(6.0, closed=False)
    closed_share, _ = alpha_metrics(closed[:, CHANNELS.index("O1")])
    open_share, _ = alpha_metrics(opened[:, CHANNELS.index("O1")])
    assert closed_share > 25.0, closed_share
    assert closed_share > open_share * 2, (closed_share, open_share)


def test_the_alpha_peak_ratio_would_pass_the_alpha_test() -> None:
    """The demo has to be able to demonstrate the one test this project still owes."""
    _share, peak = alpha_metrics(generate(6.0, closed=True)[:, CHANNELS.index("O2")])
    assert peak > 1.5, peak


def test_the_demo_includes_a_weak_channel_and_a_dry_one() -> None:
    """Otherwise the contact logic only ever runs on a real head, i.e. never in CI."""
    metrics = {m.name: m for m in channel_metrics(generate(6.0, closed=True))}
    assert metrics["T7"].status in {"low", "DEAD"}
    assert metrics["T8"].status == STATUS_DRY
    assert metrics["T8"].mains_percent > 60.0


def test_the_status_vocabulary_is_plain_english() -> None:
    assert status_for(0.2, 0.0) == "DEAD"
    assert status_for(30.0, 0.0) == "ok"
    assert status_for(30.0, 90.0) == STATUS_DRY
    assert status_for(500.0, 0.0) == "artefact"
    assert status_for(150.0, 0.0) == "high"
    assert status_for(5.0, 0.0) == "low"


def test_the_threaded_source_really_delivers() -> None:
    out: queue.Queue = queue.Queue()
    source = SyntheticSource(out=out)
    source.start()
    try:
        time.sleep(0.45)
    finally:
        source.stop()
    stats = source.stats()
    assert stats.samples > 20
    assert stats.dropped_chunks == 0
    assert stats.key_ok is None  # nothing was decrypted, so there is no key to judge


def test_the_synthetic_source_is_never_reported_as_live() -> None:
    """A demo that could be mistaken for a head is a hazard, not a feature."""
    source = SyntheticSource(out=queue.Queue())
    assert source.mode == "demo"
    assert "synthetic" in source.label


# --------------------------------------------------------------------------- #
# Factory
# --------------------------------------------------------------------------- #
def test_idle_creates_nothing() -> None:
    assert create_source("idle", out=queue.Queue()) is None


def test_replay_needs_a_file() -> None:
    with pytest.raises(ValueError, match="needs a file"):
        create_source("replay", out=queue.Queue())


def test_replay_reconstructs_a_recording(tmp_path: Path) -> None:
    path = write_csv(tmp_path / "recording.csv", rows=600)
    out: queue.Queue = queue.Queue()
    source = ReplaySource(path, out=out, speed=64.0, loop=False)
    assert source.mode == "replay"
    source.start()
    try:
        deadline = time.monotonic() + 5.0
        while source.stats().samples == 0 and time.monotonic() < deadline:
            time.sleep(0.02)
    finally:
        source.stop()
    assert source.stats().samples > 10


# --------------------------------------------------------------------------- #
# CSV reading
# --------------------------------------------------------------------------- #
def write_csv(
    path: Path,
    *,
    prefix: str = "",
    time_values: list[float] | None = None,
    header: bool = True,
    rows: int = 3,
) -> Path:
    """A CSV in one of the three shapes this project has written over its life."""
    lines: list[str] = []
    if header:
        leading = prefix
        lines.append(f"{leading}{','.join(f'{channel}_uV' for channel in CHANNELS)}")
    for index in range(rows):
        leading = ""
        if prefix == "t,":
            value = float(index) if time_values is None else time_values[index]
            leading = f"{value},"
        elif prefix:
            leading = f"{index},{index * 2},"
        lines.append(f"{leading}{','.join(str(float(index + 1)) for _ in CHANNELS)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_the_reader_matches_columns_by_header_not_position(tmp_path: Path) -> None:
    """decode_to_csv.py writes two extra leading columns; live_view.py writes none."""
    path = write_csv(tmp_path / "decode-style.csv", prefix="packet_counter,quality,")
    samples, times = csvio.read_all(path)
    assert samples.shape[1] == len(CHANNELS)
    assert np.allclose(samples[0], 1.0)
    assert times.tolist() == [0.0, 1.0, 2.0]


def test_the_reader_uses_the_time_column_when_there_is_one(tmp_path: Path) -> None:
    path = write_csv(tmp_path / "dataset-style.csv", prefix="t,", time_values=[0.0, 0.5, 1.25])
    samples, times = csvio.read_all(path)
    assert times.tolist() == [0.0, 0.5, 1.25]
    assert samples.shape == (3, len(CHANNELS))


def test_a_file_without_a_header_falls_back_to_the_last_14_columns(tmp_path: Path) -> None:
    path = write_csv(tmp_path / "headerless.csv", header=False)
    samples, times = csvio.read_all(path)
    assert samples.shape == (3, len(CHANNELS))
    assert times.tolist() == [0.0, 1.0, 2.0]


def test_counting_rows_ignores_the_header(tmp_path: Path) -> None:
    path = write_csv(tmp_path / "count.csv", rows=7)
    assert csvio.count_rows(path) == 7
