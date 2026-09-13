"""The API as the browser sees it, driven through the demo source.

These are the tests that answer "does the whole thing actually work". They run the
real hub, the real recorder and the real runner against the synthetic source, so no
headset is needed and no timing assumption is hidden: everything waits for a
condition rather than sleeping a fixed amount.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
from fastapi.testclient import TestClient

from eeg_api.domain.models import CHANNELS
from eeg_api.services.recorder import DatasetRecorder


#: Generous, because CI machines are slow; the point is to fail loudly, not quickly.
TIMEOUT = 12.0


def wait_for(
    predicate: Callable[[], Any], timeout: float = TIMEOUT, what: str = "condition"
) -> Any:
    """Poll until ``predicate`` is truthy. Returns its value, or fails the test."""
    deadline = time.monotonic() + timeout
    last: Any = None
    while time.monotonic() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(0.02)
    raise AssertionError(f"timed out after {timeout:.0f}s waiting for {what} (last={last!r})")


def start_demo(client: TestClient) -> None:
    response = client.post("/api/system/source", json={"mode": "demo"})
    assert response.status_code == 200, response.text
    assert response.json()["source"] == "demo"


def wait_for_samples(client: TestClient, minimum: int = 64) -> dict[str, Any]:
    def check() -> dict[str, Any] | None:
        body = client.get("/api/system/status").json()
        return body if body["stats"]["samples"] >= minimum else None

    return wait_for(check, what=f"{minimum} samples from the demo source")


# --------------------------------------------------------------------------- #
# Ops and documentation
# --------------------------------------------------------------------------- #
def test_health(client: TestClient) -> None:
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["environment"] == "test"


def test_the_app_starts_idle_when_no_headset_is_attached(client: TestClient) -> None:
    """Never invent data. If nothing is streaming, say so."""
    body = client.get("/api/system/status").json()
    assert body["source"] == "idle"
    assert body["stats"]["samples"] == 0
    assert "hid_available" in body["device"]


def test_channels_endpoint_documents_all_fourteen(client: TestClient) -> None:
    body = client.get("/api/channels").json()
    assert len(body["channels"]) == 14
    assert len(body["bands"]) == 5
    assert body["montage"]["reference"]["name"]
    assert body["channels"][0]["name"] == "F3"


def test_a_single_channel_is_readable_by_name(client: TestClient) -> None:
    o1 = client.get("/api/channels/O1").json()
    assert o1["name"] == "O1"
    assert "alpha" in o1["summary"].lower()
    assert client.get("/api/channels/o2").json()["name"] == "O2"  # case-insensitive
    assert client.get("/api/channels/nope").status_code == 404


# --------------------------------------------------------------------------- #
# Sources
# --------------------------------------------------------------------------- #
def test_switching_to_the_demo_source_starts_a_stream(client: TestClient) -> None:
    start_demo(client)
    status = wait_for_samples(client)
    assert status["stats"]["mode"] == "demo"
    assert status["stats"]["reports_per_second"] > 0


def test_replaying_an_unknown_recording_is_a_404(client: TestClient) -> None:
    response = client.post("/api/system/source", json={"mode": "replay", "replay_id": "nope"})
    assert response.status_code == 404


def test_replay_without_an_id_is_a_400(client: TestClient) -> None:
    assert client.post("/api/system/source", json={"mode": "replay"}).status_code == 400


def test_going_back_to_idle_drops_the_stream(client: TestClient) -> None:
    start_demo(client)
    wait_for_samples(client)
    assert client.post("/api/system/source", json={"mode": "idle"}).json()["source"] == "idle"
    assert client.get("/api/system/status").json()["source"] == "idle"


# --------------------------------------------------------------------------- #
# Flows
# --------------------------------------------------------------------------- #
def test_the_three_flow_shapes_are_seeded(client: TestClient) -> None:
    flows = client.get("/api/flows").json()
    names = {flow["name"] for flow in flows}
    assert "Eyes closed / eyes open" in names
    assert "Lie down, then stand up" in names
    assert any(flow["mode"] == "loop" for flow in flows)
    assert any(step["open_ended"] for flow in flows for step in flow["steps"])


def test_a_loop_with_an_open_ended_state_is_rejected_with_a_reason(client: TestClient) -> None:
    body = {
        "name": "bad loop",
        "mode": "loop",
        "steps": [{"label": "record forever", "seconds": None}],
    }
    result = client.post("/api/flows/validate", json=body).json()
    assert result["valid"] is False
    assert any("never advance" in message for message in result["errors"])


def test_a_preview_expands_the_running_order(client: TestClient) -> None:
    body = {
        "name": "eyes",
        "mode": "loop",
        "countdown_seconds": 3,
        "steps": [
            {"label": "close your eyes", "seconds": 20},
            {"label": "open your eyes", "seconds": 15},
        ],
    }
    preview = client.post("/api/flows/preview", json=body).json()
    kinds = [phase["kind"] for phase in preview["phases"]]
    labels = [phase["label"] for phase in preview["phases"]]
    assert kinds[0] == "countdown"
    assert labels[:5] == [
        "get ready",
        "close your eyes",
        "open your eyes",
        "close your eyes",
        "open your eyes",
    ]
    assert preview["total_seconds"] is None  # loops until stopped
    assert preview["discard_tail"] == 2


def test_a_flow_can_be_created_edited_and_deleted(client: TestClient) -> None:
    body = {
        "name": "My protocol",
        "mode": "linear",
        "countdown_seconds": 5,
        "repeat": 1,
        "steps": [
            {"label": "lie down", "seconds": 10, "speak": "lie down"},
            {"label": "stand up", "seconds": 20},
        ],
    }
    created = client.post("/api/flows", json=body)
    assert created.status_code == 201, created.text
    flow = created.json()
    assert flow["id"] == "my-protocol"
    assert flow["total_seconds"] == 35.0

    edited = client.put(
        f"/api/flows/{flow['id']}",
        json={**body, "name": "My protocol v2", "steps": [{"label": "lie down", "seconds": 12}]},
    )
    assert edited.status_code == 200
    assert edited.json()["steps"][0]["seconds"] == 12

    assert client.get(f"/api/flows/{flow['id']}").json()["name"] == "My protocol v2"
    assert client.delete(f"/api/flows/{flow['id']}").status_code == 204
    assert client.get(f"/api/flows/{flow['id']}").status_code == 404
    assert client.delete(f"/api/flows/{flow['id']}").status_code == 404


def test_saving_an_invalid_flow_is_refused(client: TestClient) -> None:
    response = client.post("/api/flows", json={"name": "", "steps": [{"label": "", "seconds": 0}]})
    assert response.status_code == 422
    assert response.json()["detail"]


# --------------------------------------------------------------------------- #
# Sessions
# --------------------------------------------------------------------------- #
def test_a_session_needs_a_stream(client: TestClient) -> None:
    """Recording silence would produce a dataset that looks fine and means nothing."""
    client.post("/api/system/source", json={"mode": "idle"})
    response = client.post("/api/sessions/quick", json={"label": "eyes closed"})
    assert response.status_code == 409
    assert "streaming" in response.json()["detail"]


def test_quick_record_produces_a_labelled_dataset(client: TestClient, settings: Any) -> None:
    start_demo(client)
    wait_for_samples(client)

    created = client.post(
        "/api/sessions/quick",
        json={"label": "eyes closed", "countdown_seconds": 0.3, "notes": "from the test"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["active"] is True

    def recording_started() -> bool:
        current = client.get("/api/sessions/current").json()
        return bool(current and current["recording"] and current["recording_state"]["samples"] > 32)

    wait_for(recording_started, what="the countdown to finish and samples to be written")

    stopped = client.post("/api/sessions/current/stop").json()
    assert stopped["active"] is False
    assert stopped["outcome"] == "stopped"
    summary = stopped["summary"]
    assert len(summary["kept_segments"]) == 1
    assert summary["kept_segments"][0]["label"] == "eyes closed"
    assert summary["samples"] > 32

    # The dataset is on disk, in the standard layout, and lists itself.
    dataset = Path(summary["path"])
    assert (dataset / "eeg.csv").exists()
    assert (dataset / "labels.csv").exists()
    assert (dataset / "meta.json").exists()
    assert (dataset / "events.jsonl").exists()

    meta = json.loads((dataset / "meta.json").read_text(encoding="utf-8"))
    assert meta["notes"] == "from the test"
    assert meta["outcome"] == "stopped"
    assert meta["flow"]["name"] == "eyes closed"

    listing = client.get("/api/recordings").json()
    entry = next(item for item in listing["recordings"] if item["id"] == dataset.name)
    assert entry["kind"] == "dataset"
    assert entry["labels"][0]["label"] == "eyes closed"

    segments = client.get(f"/api/recordings/{dataset.name}/segments").json()
    assert len(segments) == 1
    assert segments[0]["end_sample"] > segments[0]["start_sample"]

    preview = client.get(f"/api/recordings/{dataset.name}/preview?points=64").json()
    assert preview["total_samples"] > 0
    assert len(preview["data"]) == len(preview["t"])


def test_the_countdown_is_not_in_the_dataset(client: TestClient) -> None:
    """A three-second countdown must not appear as data in the class."""
    start_demo(client)
    wait_for_samples(client)
    created = client.post(
        "/api/sessions/quick",
        json={"label": "counted", "countdown_seconds": 1.5},
    ).json()
    # Stop while still counting down.
    time.sleep(0.4)
    stopped = client.post("/api/sessions/current/abort").json()
    assert stopped["outcome"] == "aborted"
    assert stopped["recording"] is False
    assert stopped["summary"] is None  # nothing was ever written

    assert created["engine"]["phase"]["kind"] == "countdown"


def test_a_completed_loop_keeps_its_tail(client: TestClient) -> None:
    """A loop that ran its planned number of repetitions was never compromised."""
    start_demo(client)
    wait_for_samples(client)

    flow = {
        "name": "short alternating",
        "mode": "loop",
        "countdown_seconds": 0.2,
        "repeat": 2,
        "steps": [
            {"label": "close your eyes", "seconds": 0.4},
            {"label": "open your eyes", "seconds": 0.4},
        ],
    }
    created = client.post("/api/sessions", json={"flow": flow, "dataset_name": "completed loop"})
    assert created.status_code == 201, created.text

    # The runner detaches itself when the plan runs out, so a null current session is
    # the signal that it finished on its own rather than being stopped.
    wait_for(lambda: client.get("/api/sessions/current").json() is None, what="the loop to finish")

    listing = client.get("/api/recordings").json()
    entry = next(item for item in listing["recordings"] if item["name"] == "completed loop")
    # Two cycles of two states, nothing compromised, so all four are kept.
    assert entry["segments"] == 4
    assert {label["label"] for label in entry["labels"]} == {"close your eyes", "open your eyes"}


def test_a_stopped_loop_discards_its_tail(client: TestClient) -> None:
    start_demo(client)
    wait_for_samples(client)

    flow = {
        "name": "looping forever",
        "mode": "loop",
        "countdown_seconds": 0.2,
        "steps": [
            {"label": "close your eyes", "seconds": 0.3},
            {"label": "open your eyes", "seconds": 0.3},
        ],
    }
    created = client.post("/api/sessions", json={"flow": flow, "dataset_name": "stopped loop"})
    assert created.status_code == 201, created.text
    assert created.json()["flow"]["discard_tail"] == 2

    def enough_states() -> bool:
        current = client.get("/api/sessions/current").json()
        return bool(current and current["engine"]["cycle"] >= 2)

    wait_for(enough_states, what="several loop cycles")
    stopped = client.post("/api/sessions/current/stop").json()
    assert stopped["outcome"] == "stopped"
    discarded = stopped["summary"]["discarded_segments"]
    kept = stopped["summary"]["kept_segments"]
    assert len(discarded) == 2
    assert all(segment["label"] != "" for segment in kept)
    # The file was physically cut, not merely annotated.
    assert stopped["summary"]["samples"] == (kept[-1]["end_sample"] if kept else 0)


def test_abort_removes_the_dataset(client: TestClient) -> None:
    start_demo(client)
    wait_for_samples(client)
    created = client.post(
        "/api/sessions", json={"flow": _one_state_flow(), "dataset_name": "to be thrown away"}
    )
    assert created.status_code == 201

    def recording_started() -> bool:
        current = client.get("/api/sessions/current").json()
        return bool(current and current["recording"] and current["recording_state"]["samples"] > 16)

    wait_for(recording_started, what="the recording to start")
    aborted = client.post("/api/sessions/current/abort").json()
    assert aborted["outcome"] == "aborted"
    assert aborted["summary"]["removed"] is True
    assert not Path(aborted["summary"]["path"]).exists()


def test_two_sessions_cannot_run_at_once(client: TestClient) -> None:
    start_demo(client)
    wait_for_samples(client)
    first = client.post("/api/sessions", json={"flow": _one_state_flow()})
    assert first.status_code == 201
    second = client.post("/api/sessions", json={"flow": _one_state_flow()})
    assert second.status_code == 409
    client.post("/api/sessions/current/abort")


def test_stopping_when_nothing_is_running_is_a_404(client: TestClient) -> None:
    assert client.post("/api/sessions/current/stop").status_code == 404
    assert client.post("/api/sessions/current/abort").status_code == 404


def test_the_source_cannot_be_switched_under_a_recording(client: TestClient) -> None:
    start_demo(client)
    wait_for_samples(client)
    client.post("/api/sessions", json={"flow": _one_state_flow()})

    def recording_started() -> bool:
        current = client.get("/api/sessions/current").json()
        return bool(current and current["recording"] and current["recording_state"]["samples"] > 16)

    wait_for(recording_started, what="the recording to start")
    response = client.post("/api/system/source", json={"mode": "idle"})
    assert response.status_code == 409
    client.post("/api/sessions/current/abort")


def test_the_source_cannot_be_switched_during_the_countdown_either(client: TestClient) -> None:
    """Switching mid-countdown would reset the clock the boundaries are measured against."""
    start_demo(client)
    wait_for_samples(client)
    client.post("/api/sessions", json={"flow": _one_state_flow(countdown=5.0)})
    response = client.post("/api/system/source", json={"mode": "idle"})
    assert response.status_code == 409
    assert client.post("/api/sessions/current/abort").status_code == 200


# --------------------------------------------------------------------------- #
# WebSocket
# --------------------------------------------------------------------------- #
def test_the_socket_greets_then_streams(client: TestClient) -> None:
    start_demo(client)
    wait_for_samples(client)
    with client.websocket_connect("/ws/stream") as socket:
        hello = socket.receive_json()
        assert hello["type"] == "hello"
        assert hello["channels"][0] == "F3"
        assert hello["occipital"] == ["O1", "O2"]

        history = socket.receive_json()
        assert history["type"] == "history"

        # The first tick may arrive before the source has produced anything.
        for _ in range(60):
            message = socket.receive_json()
            if message["type"] == "tick" and message["samples"]["data"]:
                break
        assert message["type"] == "tick"
        assert len(message["samples"]["data"][0]) == 14
        assert message["fs"] == 128.0


def test_the_socket_reports_a_session_starting_and_ending(client: TestClient) -> None:
    start_demo(client)
    wait_for_samples(client)
    with client.websocket_connect("/ws/stream") as socket:
        socket.receive_json()  # hello
        socket.receive_json()  # history
        response = client.post(
            "/api/sessions", json={"flow": _one_state_flow(countdown=0.4), "dataset_name": "socket"}
        )
        assert response.status_code == 201

        events: list[str] = []
        deadline = time.monotonic() + TIMEOUT
        while time.monotonic() < deadline:
            message = socket.receive_json()
            if message["type"] != "session":
                continue
            events.append(message["event"]["kind"] if "event" in message else "")
            if "go" in events:
                break
        assert "started" in events
        assert "countdown" in events
        assert "go" in events

        client.post("/api/sessions/current/stop")


def _one_state_flow(countdown: float = 0.2) -> dict[str, Any]:
    """The shape the quick-record button sends: one open-ended state."""
    return {
        "name": "until stopped",
        "mode": "linear",
        "countdown_seconds": countdown,
        "discard_tail": 0,
        "steps": [{"label": "moving", "seconds": None}],
    }


# --------------------------------------------------------------------------- #
# Deleting
# --------------------------------------------------------------------------- #
def _write_dataset(settings: Any, name: str = "to delete") -> str:
    """A dataset on disk, so deletion has something real to remove."""
    recorder = DatasetRecorder(settings.recordings_dir, name, fs=settings.fs)
    recorder.begin(0.0)
    recorder.request_open(0.0, "eyes closed", step_index=0)
    recorder.request_close(2.0)
    recorder.append(np.zeros((256, len(CHANNELS))), t0=0.0)
    recorder.finalize(discard_tail=0, outcome="completed")
    return recorder.dir.name


def test_deleting_a_recording_removes_it_from_disk_and_the_listing(
    client: TestClient, settings: Any
) -> None:
    entry_id = _write_dataset(settings)
    assert entry_id in [item["id"] for item in client.get("/api/recordings").json()["recordings"]]

    response = client.delete(f"/api/recordings/{entry_id}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == entry_id
    assert body["name"] == "to delete"
    assert body["kind"] == "dataset"
    assert body["bytes_freed"] > 0
    assert body["labels"] == ["eyes closed"]

    assert not (settings.recordings_dir / entry_id).exists()
    assert client.get("/api/recordings").json()["recordings"] == []
    assert client.delete(f"/api/recordings/{entry_id}").status_code == 404


def test_deleting_an_unknown_recording_is_a_404(client: TestClient) -> None:
    assert client.delete("/api/recordings/no-such-thing").status_code == 404


def test_deleting_something_out_of_bounds_is_refused(client: TestClient, settings: Any) -> None:
    """Nothing outside ``recordings/`` may be reachable, however the id is spelled.

    Asserting the *property* rather than a status code: an HTTP client resolves `..` in
    the URL before it is ever sent, so several of these never reach the server's own
    guard at all, and the answer that matters is "the sentinel is still there and this
    was not reported as a success".
    """
    outside = settings.recordings_dir.parent
    sentinel = outside / "sentinel.txt"
    sentinel.write_text("do not delete me", encoding="utf-8")

    for bad in ("..", ".", "..%2F..", "%2e%2e", "....", "..%5C.."):
        response = client.delete(f"/api/recordings/{bad}")
        assert response.status_code >= 400, f"{bad} returned {response.status_code}"
        assert sentinel.exists(), f"{bad} removed a file outside recordings/"
    assert outside.exists()


def test_a_recording_cannot_be_deleted_while_it_is_being_recorded(
    client: TestClient, settings: Any
) -> None:
    """The session's own folder must survive the session that is writing it."""
    start_demo(client)
    wait_for_samples(client)
    client.post("/api/sessions", json={"flow": _one_state_flow(), "dataset_name": "in progress"})

    def recording_started() -> bool:
        current = client.get("/api/sessions/current").json()
        return bool(current and current["recording"] and current["recording_state"]["samples"] > 16)

    wait_for(recording_started, what="the recording to start")
    folder = client.get("/api/sessions/current").json()["recording_state"]["id"]
    response = client.delete(f"/api/recordings/{folder}")
    assert response.status_code == 409, response.text
    assert (settings.recordings_dir / folder).exists()

    client.post("/api/sessions/current/abort")
