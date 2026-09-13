"""The flow state machine.

These are the rules the whole feature rests on, so they are tested against a
simulated clock rather than by sleeping: ``advance(now)`` is handed time, and the
assertions are about what happened, not about how long it took.
"""

from __future__ import annotations

import pytest

from eeg_api.domain.flows import (
    FlowEngine,
    FlowSpec,
    FlowStep,
    eyes_open_closed_flow,
    single_label_flow,
    validate,
)


def linear(*, countdown: float = 5.0) -> FlowSpec:
    """The example from the brief: start with 5, laydown 10, stand up 20."""
    return FlowSpec(
        name="lie down then stand up",
        mode="linear",
        countdown_seconds=countdown,
        steps=(FlowStep("laydown", 10.0), FlowStep("stand up", 20.0)),
    )


def kinds(events: list) -> list[str]:
    return [event.kind for event in events]


def labels_of(events: list) -> list[str]:
    """The states that began in this batch of events."""
    return [
        event.phase.label
        for event in events
        if event.kind == "phase_start" and event.phase is not None
    ]


def counts_of(events: list) -> list[int]:
    """The numbers the countdown spoke in this batch of events."""
    return [event.count or 0 for event in events if event.kind == "countdown"]


def run_for(engine: FlowEngine, seconds: int) -> None:
    """Drive the engine one simulated second at a time."""
    for step in range(seconds + 1):
        engine.advance(float(step))


# --------------------------------------------------------------------------- #
# Linear
# --------------------------------------------------------------------------- #
def test_linear_runs_each_state_once_in_order() -> None:
    engine = FlowEngine(linear())
    seen: list[str] = []

    for step in range(0, 40):
        seen.extend(labels_of(engine.advance(float(step))))

    assert seen == ["get ready", "laydown", "stand up"]
    assert engine.finished


def test_countdown_counts_down_out_loud() -> None:
    engine = FlowEngine(linear(countdown=3.0))
    spoken: list[int] = []
    for step in range(0, 4):
        spoken.extend(counts_of(engine.advance(float(step))))
    assert spoken == [3, 2, 1]


def test_countdown_is_a_phase_before_the_first_state() -> None:
    engine = FlowEngine(linear(countdown=5.0))
    assert engine.phase is not None
    assert engine.phase.kind == "countdown"
    assert engine.phase.duration == 5.0
    assert engine.phase.recordable is False

    engine.advance(5.0)
    assert engine.phase is not None
    assert engine.phase.kind == "step"
    assert engine.phase.label == "laydown"
    assert engine.phase.recordable is True


def test_go_fires_when_the_countdown_ends() -> None:
    engine = FlowEngine(linear(countdown=3.0))
    events = engine.advance(3.0)
    assert "go" in kinds(events)
    go = next(event for event in events if event.kind == "go")
    assert go.at == pytest.approx(3.0)


def test_no_countdown_means_the_first_state_starts_immediately() -> None:
    engine = FlowEngine(linear(countdown=0.0))
    assert engine.phase is not None
    assert engine.phase.kind == "step"
    assert engine.phase.label == "laydown"


def test_repeat_runs_the_whole_list_again() -> None:
    spec = FlowSpec(
        name="three rounds",
        mode="linear",
        countdown_seconds=0.0,
        repeat=3,
        steps=(FlowStep("laydown", 10.0), FlowStep("stand up", 20.0)),
    )
    engine = FlowEngine(spec)
    labels: list[str] = []
    for step in range(0, 100):
        labels.extend(labels_of(engine.advance(float(step))))
    assert labels == ["laydown", "stand up"] * 3
    assert engine.finished


# --------------------------------------------------------------------------- #
# Looping
# --------------------------------------------------------------------------- #
def test_loop_repeats_until_stopped() -> None:
    engine = FlowEngine(
        eyes_open_closed_flow(countdown_seconds=0.0, closed_seconds=20.0, open_seconds=15.0)
    )
    labels: list[str] = []
    for step in range(0, 200):
        labels.extend(labels_of(engine.advance(float(step))))
    # 20 + 15 = 35 s per cycle, 200 s of simulated time → five full cycles and a bit.
    assert labels[:4] == ["eyes closed", "eyes open", "eyes closed", "eyes open"]
    assert labels.count("eyes closed") == 6
    assert not engine.finished


def test_loop_with_a_repeat_count_finishes_on_its_own() -> None:
    spec = eyes_open_closed_flow(
        countdown_seconds=0.0, closed_seconds=1.0, open_seconds=1.0, repeat=2
    )
    engine = FlowEngine(spec)
    for step in range(0, 20):
        engine.advance(float(step))
    assert engine.finished
    assert engine.truncated is False


def test_a_loop_can_still_be_stopped_early() -> None:
    engine = FlowEngine(
        eyes_open_closed_flow(
            countdown_seconds=0.0, closed_seconds=1.0, open_seconds=1.0, repeat=50
        )
    )
    engine.advance(2.5)  # mid-way through the third state
    engine.request_stop()
    events = engine.advance(2.5)
    assert "stopped" in kinds(events)
    assert engine.finished
    assert engine.truncated is True
    end = next(event for event in events if event.kind == "phase_end")
    assert end.truncated is True


# --------------------------------------------------------------------------- #
# Open-ended states ("record until I stop")
# --------------------------------------------------------------------------- #
def test_open_ended_state_never_ends_by_itself() -> None:
    engine = FlowEngine(single_label_flow("eyes closed", countdown_seconds=0.0))
    for step in range(0, 600):
        engine.advance(float(step))
    assert not engine.finished
    assert engine.phase is not None
    assert engine.phase.open_ended is True
    assert engine.phase.remaining(300.0) is None


def test_open_ended_state_ends_when_stopped() -> None:
    engine = FlowEngine(single_label_flow("eyes closed", countdown_seconds=0.0))
    engine.advance(30.0)
    engine.request_stop()
    events = engine.advance(30.0)
    assert "stopped" in kinds(events)
    assert engine.finished


def test_stopping_during_the_countdown_ends_before_anything_is_recorded() -> None:
    engine = FlowEngine(linear(countdown=5.0))
    engine.advance(1.0)
    engine.request_stop()
    events = engine.advance(1.0)
    assert "stopped" in kinds(events)
    # Crucially, no `go`: that event is what opens the dataset, and the countdown
    # never finished, so cancelling here must leave nothing behind.
    assert "go" not in kinds(events)
    assert engine.finished
    assert all(event.phase is None or event.phase.kind != "step" for event in engine.events)


def test_upcoming_lists_what_is_next() -> None:
    engine = FlowEngine(linear(countdown=5.0))
    upcoming = engine.upcoming(0.0, 2)
    assert [item["label"] for item in upcoming] == ["laydown", "stand up"]


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
def test_a_valid_flow_has_no_errors() -> None:
    errors, warnings = validate(linear())
    assert errors == []
    assert warnings == []


def test_open_ended_state_must_be_last() -> None:
    spec = FlowSpec(
        name="bad",
        mode="linear",
        steps=(FlowStep("record", None), FlowStep("after", 5.0)),
    )
    errors, _ = validate(spec)
    assert any("last state" in message for message in errors)


def test_a_loop_cannot_contain_an_open_ended_state() -> None:
    spec = FlowSpec(name="bad", mode="loop", steps=(FlowStep("record", None),))
    errors, _ = validate(spec)
    assert any("never advance" in message for message in errors)


def test_an_empty_flow_is_rejected() -> None:
    errors, _ = validate(FlowSpec(name="nothing", steps=()))
    assert any("at least one state" in message for message in errors)


def test_a_state_needs_a_name_and_a_sensible_duration() -> None:
    spec = FlowSpec(name="bad", steps=(FlowStep("", 0.0),))
    errors, _ = validate(spec)
    assert any("no name" in message for message in errors)
    assert any("duration" in message for message in errors)


# --------------------------------------------------------------------------- #
# Discard-tail policy
# --------------------------------------------------------------------------- #
def test_a_loop_discards_two_trailing_states_by_default() -> None:
    assert eyes_open_closed_flow().effective_discard_tail == 2


def test_a_linear_protocol_discards_nothing_by_default() -> None:
    assert linear().effective_discard_tail == 0


def test_discard_tail_can_be_set_explicitly() -> None:
    spec = FlowSpec(name="x", steps=(FlowStep("a", 1.0),), discard_tail=0)
    assert spec.effective_discard_tail == 0


# --------------------------------------------------------------------------- #
# Plan summary
# --------------------------------------------------------------------------- #
def test_total_seconds_of_a_linear_flow() -> None:
    assert linear().total_seconds == pytest.approx(5.0 + 10.0 + 20.0)


def test_total_seconds_is_none_when_open_ended_or_unbounded() -> None:
    assert single_label_flow("x").total_seconds is None
    assert eyes_open_closed_flow().total_seconds is None
    assert eyes_open_closed_flow(repeat=2).total_seconds == pytest.approx(3.0 + (20.0 + 15.0) * 2)
