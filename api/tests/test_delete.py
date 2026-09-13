"""Deleting a recording.

This is the only operation in the project that cannot be undone, so the tests are mostly
about what it *refuses*: an id that walks out of the recordings folder, the folder itself,
something a live replay is streaming, a folder a session is still writing.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from eeg_api.domain.models import CHANNELS
from eeg_api.services.library import (
    LibraryError,
    LibraryInUseError,
    LibraryNotFoundError,
    RecordingLibrary,
)
from eeg_api.services.recorder import DatasetRecorder


FS_LOCAL = 128.0


def make_dataset(root: Path, name: str = "to-delete") -> DatasetRecorder:
    recorder = DatasetRecorder(root, name, fs=FS_LOCAL)
    recorder.begin(0.0)
    recorder.request_open(0.0, "eyes closed", step_index=0)
    recorder.request_close(2.0)
    recorder.append(np.zeros((int(2.0 * FS_LOCAL), len(CHANNELS))), t0=0.0)
    recorder.finalize(discard_tail=0, outcome="completed")
    return recorder


def test_it_removes_a_dataset_folder_and_reports_what_went(tmp_path: Path) -> None:
    recorder = make_dataset(tmp_path)
    library = RecordingLibrary(tmp_path, fs=FS_LOCAL)

    summary = library.delete(recorder.dir.name)

    assert summary["id"] == recorder.dir.name
    assert summary["name"] == "to-delete"
    assert summary["kind"] == "dataset"
    assert summary["samples"] == int(2.0 * FS_LOCAL)
    assert summary["labels"] == ["eyes closed"]
    assert summary["bytes_freed"] > 0
    assert not recorder.dir.exists()
    assert library.scan() == []


def test_it_removes_a_flat_csv(tmp_path: Path) -> None:
    flat = tmp_path / "eeg_2026-01-01_00-00-00.csv"
    flat.write_text(
        "t," + ",".join(f"{c}_uV" for c in CHANNELS) + "\n0," + ",".join(["1"] * 14) + "\n"
    )
    library = RecordingLibrary(tmp_path, fs=FS_LOCAL)
    assert [entry.id for entry in library.scan()] == [flat.name]

    summary = library.delete(flat.name)
    assert summary["kind"] == "recording"
    assert not flat.exists()


def test_the_entry_disappears_from_the_listing_immediately(tmp_path: Path) -> None:
    """The library caches descriptions, so a deletion has to invalidate it."""
    recorder = make_dataset(tmp_path)
    library = RecordingLibrary(tmp_path, fs=FS_LOCAL)
    assert len(library.scan()) == 1

    library.delete(recorder.dir.name)
    assert library.scan() == []


def test_it_refuses_a_name_that_walks_out_of_the_folder(tmp_path: Path) -> None:
    library = RecordingLibrary(tmp_path / "recordings", fs=FS_LOCAL)
    library.root.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "important"
    outside.mkdir()
    (outside / "keep.txt").write_text("do not delete me")

    for bad in ("../important", "..", ".", "a/../../important", ""):
        with pytest.raises(LibraryError):
            library.delete(bad)
    assert outside.exists()
    assert (outside / "keep.txt").exists()


def test_it_refuses_the_recordings_folder_itself(tmp_path: Path) -> None:
    library = RecordingLibrary(tmp_path / "recordings", fs=FS_LOCAL)
    library.root.mkdir(parents=True, exist_ok=True)
    with pytest.raises(LibraryError):
        library.delete(".")
    assert library.root.exists()


def test_deleting_something_that_is_not_there_says_so(tmp_path: Path) -> None:
    library = RecordingLibrary(tmp_path, fs=FS_LOCAL)
    with pytest.raises(LibraryNotFoundError):
        library.delete("no-such-recording")


def test_it_refuses_a_recording_a_replay_is_streaming(tmp_path: Path) -> None:
    recorder = make_dataset(tmp_path)
    csv_file = recorder.eeg_path
    library = RecordingLibrary(tmp_path, fs=FS_LOCAL)

    with pytest.raises(LibraryInUseError, match="in use"):
        library.delete(recorder.dir.name, blocked=[csv_file])
    assert recorder.dir.exists()

    # Once the source has stopped, the same delete goes through.
    library.delete(recorder.dir.name, blocked=[])
    assert not recorder.dir.exists()


def test_it_refuses_a_folder_a_session_is_writing_into(tmp_path: Path) -> None:
    recorder = make_dataset(tmp_path, "unfinished")
    library = RecordingLibrary(tmp_path, fs=FS_LOCAL)

    with pytest.raises(LibraryInUseError):
        library.delete(recorder.dir.name, blocked=[recorder.dir])
    assert recorder.dir.exists()


def test_describing_for_deletion_touches_nothing(tmp_path: Path) -> None:
    recorder = make_dataset(tmp_path)
    library = RecordingLibrary(tmp_path, fs=FS_LOCAL)

    described = library.describe_for_deletion(recorder.dir.name)

    assert described["name"] == "to-delete"
    assert described["bytes_freed"] > 0
    assert recorder.dir.exists()
    assert (recorder.dir / "eeg.csv").exists()
