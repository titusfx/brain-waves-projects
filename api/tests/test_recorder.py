"""The dataset writer.

Two behaviours here are the kind that ruin a dataset silently rather than failing, so
they are asserted against exact sample indices rather than against "roughly":

* the countdown before recording is **excluded**, and
* stopping a loop **physically removes** its trailing states from ``eeg.csv``.
"""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import pytest

from eeg_api.domain.models import CHANNELS
from eeg_api.services.recorder import DatasetRecorder


FS = 128.0


def rows(seconds: float) -> np.ndarray:
    """A block of distinguishable samples: row i is filled with i."""
    count = int(seconds * FS)
    return np.repeat(np.arange(count, dtype=np.float64).reshape(-1, 1), len(CHANNELS), axis=1)


def data_rows(path: Path) -> list[list[str]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.reader(handle))[1:]


def read_labels(recorder: DatasetRecorder) -> list[dict[str, str]]:
    with recorder.labels_path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


@pytest.fixture
def recorder(tmp_path: Path) -> DatasetRecorder:
    return DatasetRecorder(tmp_path, "eyes closed", fs=FS, meta={"flow": {"name": "test"}})


def test_it_creates_its_own_folder_and_never_overwrites(tmp_path: Path) -> None:
    first = DatasetRecorder(tmp_path, "same name", fs=FS)
    second = DatasetRecorder(tmp_path, "same name", fs=FS)
    assert first.dir != second.dir
    assert first.dir.name.startswith("same-name_")
    assert second.dir.name.endswith("-2")


def test_nothing_is_written_before_the_countdown_ends(recorder: DatasetRecorder) -> None:
    recorder.begin(epoch_stream_time=1.0)
    recorder.append(rows(1.0), t0=0.0)  # the countdown second
    assert recorder.state()["samples"] == 0
    recorder.append(rows(1.0), t0=1.0)  # the first recorded second
    assert recorder.state()["samples"] == int(FS)


def test_time_starts_at_zero_when_recording_starts(recorder: DatasetRecorder) -> None:
    recorder.begin(epoch_stream_time=100.0)
    recorder.request_open(100.0, "labelled", step_index=0)
    recorder.append(rows(0.5), t0=100.0)
    recorder.finalize()
    first = data_rows(recorder.eeg_path)[0]
    assert float(first[0]) == pytest.approx(0.0, abs=1e-6)


def test_state_boundaries_are_sample_exact(recorder: DatasetRecorder) -> None:
    recorder.begin(0.0)
    recorder.request_open(1.0, "close your eyes", cycle=0, step_index=0)
    recorder.request_close(3.0)
    recorder.request_open(3.0, "open your eyes", cycle=0, step_index=1)
    recorder.request_close(5.0)
    recorder.append(rows(6.0), t0=0.0)
    summary = recorder.finalize()

    kept = summary["kept_segments"]
    assert [segment["label"] for segment in kept] == ["close your eyes", "open your eyes"]
    assert (kept[0]["start_sample"], kept[0]["end_sample"]) == (128, 384)
    assert (kept[1]["start_sample"], kept[1]["end_sample"]) == (384, 640)
    assert kept[0]["duration"] == pytest.approx(2.0)
    assert data_rows(recorder.eeg_path)[128][1] == "128.000"


def test_stopping_a_loop_removes_its_tail_from_the_file(tmp_path: Path) -> None:
    """Three full cycles, then a fourth state interrupted by the operator.

    With the loop's default tail of 2, the interrupted state *and* the completed one
    before it are dropped — those are the two the operator compromised by reaching for
    the button.
    """
    recorder = DatasetRecorder(tmp_path, "loop", fs=FS)
    recorder.begin(0.0)
    for cycle in range(3):
        start = cycle * 4.0
        recorder.request_open(start, "close", cycle=cycle, step_index=0)
        recorder.request_close(start + 2.0)
        recorder.request_open(start + 2.0, "open", cycle=cycle, step_index=1)
        recorder.request_close(start + 4.0)
    recorder.request_open(12.0, "close", cycle=3, step_index=0)
    recorder.request_close(13.0, truncated=True)
    recorder.append(rows(13.0), t0=0.0)

    summary = recorder.finalize(discard_tail=2, outcome="stopped")

    assert [segment["label"] for segment in summary["kept_segments"]] == [
        "close",
        "open",
        "close",
        "open",
        "close",
    ]
    assert len(summary["discarded_segments"]) == 2
    assert summary["discarded_segments"][-1]["truncated"] is True
    # The last kept state ended at 10 s, so the file must stop at sample 1280 — the
    # rows that arrived afterwards are gone, not merely unlabelled.
    assert summary["samples"] == 1280
    assert len(data_rows(recorder.eeg_path)) == 1280
    assert len(read_labels(recorder)) == 5
    assert read_labels(recorder)[-1]["label"] == "close"


def test_discard_tail_zero_keeps_everything(tmp_path: Path) -> None:
    recorder = DatasetRecorder(tmp_path, "quick", fs=FS)
    recorder.begin(0.0)
    recorder.request_open(0.0, "eyes closed", step_index=0)
    recorder.append(rows(2.0), t0=0.0)
    summary = recorder.finalize(discard_tail=0, outcome="stopped")
    assert summary["samples"] == int(2 * FS)
    assert len(summary["kept_segments"]) == 1
    assert summary["kept_segments"][0]["truncated"] is True


def test_a_state_still_open_at_the_end_is_closed_and_flagged(tmp_path: Path) -> None:
    recorder = DatasetRecorder(tmp_path, "quick", fs=FS)
    recorder.begin(0.0)
    recorder.request_open(0.5, "moving", step_index=0)
    recorder.append(rows(2.0), t0=0.0)
    summary = recorder.finalize(discard_tail=0)
    kept = summary["kept_segments"]
    assert len(kept) == 1
    assert kept[0]["truncated"] is True
    # Only the half-second before the state opened is excluded.
    assert kept[0]["start_sample"] == 64
    assert kept[0]["end_sample"] == 256


def test_labels_summarise_seconds_per_class(tmp_path: Path) -> None:
    recorder = DatasetRecorder(tmp_path, "two classes", fs=FS)
    recorder.begin(0.0)
    recorder.request_open(0.0, "closed", step_index=0)
    recorder.request_close(2.0)
    recorder.request_open(2.0, "open", cycle=0, step_index=1)
    recorder.request_close(3.0)
    recorder.request_open(3.0, "closed", cycle=1, step_index=0)
    recorder.request_close(5.0)
    recorder.append(rows(5.0), t0=0.0)
    summary = recorder.finalize()
    labels = {entry["label"]: entry for entry in summary["labels"]}
    assert labels["closed"]["seconds"] == pytest.approx(4.0)
    assert labels["closed"]["segments"] == 2
    assert labels["open"]["seconds"] == pytest.approx(1.0)


def test_metadata_records_the_flow_and_what_was_discarded(tmp_path: Path) -> None:
    import json

    recorder = DatasetRecorder(
        tmp_path, "meta", fs=FS, meta={"flow": {"name": "Eyes"}, "notes": "hello"}
    )
    recorder.begin(0.0)
    recorder.request_open(0.0, "closed", step_index=0)
    recorder.append(rows(1.0), t0=0.0)
    recorder.finalize(discard_tail=1, outcome="stopped")

    meta = json.loads(recorder.meta_path.read_text(encoding="utf-8"))
    assert meta["state"] == "stopped"
    assert meta["outcome"] == "stopped"
    assert meta["kind"] == "dataset"
    assert meta["flow"]["name"] == "Eyes"
    assert meta["notes"] == "hello"
    assert meta["channels"][0] == "F3"
    assert meta["kept_segments"] == []
    assert len(meta["discarded_segments"]) == 1


def test_the_header_is_the_same_shape_the_cli_tools_write(tmp_path: Path) -> None:
    """So that live_view.py --replay and alpha_test.py --file can read a dataset."""
    recorder = DatasetRecorder(tmp_path, "shape", fs=FS)
    recorder.begin(0.0)
    recorder.append(rows(0.1), t0=0.0)
    recorder.finalize()
    with recorder.eeg_path.open("r", encoding="utf-8") as handle:
        header = next(csv.reader(handle))
    assert header[0] == "t"
    assert header[1:] == [f"{channel}_uV" for channel in CHANNELS]
