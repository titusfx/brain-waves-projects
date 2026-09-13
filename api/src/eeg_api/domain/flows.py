"""Guided protocols: a small, pure state machine over wall-clock time.

Two shapes, exactly as they were asked for:

**Linear** — every state runs once, in order::

    start with 5, laydown for 10, stand up for 20
    → countdown 5 · "laydown" 10 s · "stand up" 20 s · done

**Looping** — the state list repeats until you press stop::

    start with 3, close your eyes for 20, open your eyes for 15
    → countdown 3 · close 20 · open 15 · close 20 · open 15 · … until stopped

"Start with N" is a *countdown before recording*, narrated aloud (3, 2, 1) and
mutable, not a recorded state.

Why a loop discards its tail
----------------------------
When you stop a looping protocol you are pressing a button, and the seconds you
spend reaching for it are not the state you were trying to capture. So a stopped
loop drops its trailing segments: the partial one you interrupted **and** the
completed one before it, because that one was already compromised by the
decision to stop. That is ``FlowSpec.effective_discard_tail`` — 2 for a loop,
0 for a linear protocol, where every state was scripted and every second counts.

The engine owns no clock and no I/O. It is handed ``advance(now)`` and returns
what happened; that makes every rule below testable without sleeping.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Literal


FlowMode = Literal["linear", "loop"]
PhaseKind = Literal["countdown", "step", "rest"]
EventKind = Literal[
    "countdown",  # one narrated number: 3, 2, 1
    "go",  # the countdown finished; recording starts here
    "phase_start",
    "phase_end",
    "cycle_start",  # first state of a new repetition
    "finished",  # the plan ran out on its own
    "stopped",  # the operator stopped it
]

#: An open-ended state ("record until I say stop") has no end time.
OPEN_ENDED = math.inf

MAX_STEPS = 64
MAX_SECONDS = 3600.0


@dataclass(frozen=True, slots=True)
class FlowStep:
    """One state of a protocol.

    ``seconds=None`` means *until you press stop* — that is the single-label case
    ("give it a name, press the button, and it counts 3-2-1 and records"), where
    the operator decides when the state ends.
    """

    label: str
    seconds: float | None = None
    #: What to say when the state begins. Defaults to the label.
    speak: str | None = None

    @property
    def duration(self) -> float:
        return OPEN_ENDED if self.seconds is None else float(self.seconds)

    @property
    def open_ended(self) -> bool:
        return self.seconds is None

    @property
    def spoken(self) -> str:
        return (self.speak or self.label).strip()

    def as_payload(self) -> dict[str, object]:
        return {
            "label": self.label,
            "seconds": self.seconds,
            "speak": self.speak,
            "open_ended": self.open_ended,
        }


@dataclass(frozen=True, slots=True)
class FlowSpec:
    """A protocol definition. ``id`` is assigned when it is saved."""

    name: str
    steps: tuple[FlowStep, ...]
    mode: FlowMode = "linear"
    #: "Start with N": the narrated countdown before anything is recorded.
    countdown_seconds: float = 3.0
    #: How many times the state list runs. ``None`` = until stopped.
    repeat: int | None = None
    #: Optional gap between repetitions (recorded, but not part of a label).
    rest_seconds: float = 0.0
    #: Segments dropped from the dataset when stopped early. ``None`` = the mode's
    #: default (loop 2, linear 0).
    discard_tail: int | None = None
    description: str = ""
    id: str = ""

    @property
    def cycles(self) -> int | None:
        """Number of repetitions the plan runs. ``None`` = until stopped."""
        if self.mode == "loop":
            return self.repeat
        return max(1, self.repeat or 1)

    @property
    def effective_discard_tail(self) -> int:
        if self.discard_tail is not None:
            return max(0, self.discard_tail)
        return 2 if self.mode == "loop" else 0

    @property
    def unbounded(self) -> bool:
        return self.cycles is None

    def as_payload(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "mode": self.mode,
            "countdown_seconds": self.countdown_seconds,
            "repeat": self.repeat,
            "cycles": self.cycles,
            "rest_seconds": self.rest_seconds,
            "discard_tail": self.effective_discard_tail,
            "description": self.description,
            "steps": [s.as_payload() for s in self.steps],
            "total_seconds": self.total_seconds,
        }

    @property
    def total_seconds(self) -> float | None:
        """Planned duration, or ``None`` when the plan is open-ended."""
        cycles = self.cycles
        if cycles is None or any(s.open_ended for s in self.steps):
            return None
        per_cycle = sum(s.duration for s in self.steps)
        if self.rest_seconds > 0:
            per_cycle += self.rest_seconds * (cycles - 1)
        return self.countdown_seconds + per_cycle * cycles


@dataclass(frozen=True, slots=True)
class Phase:
    """A stretch of the timeline: the countdown, one state, or a rest."""

    kind: PhaseKind
    label: str
    cycle: int
    step_index: int
    start: float
    end: float
    speak: str | None = None

    @property
    def open_ended(self) -> bool:
        return math.isinf(self.end)

    @property
    def duration(self) -> float:
        return OPEN_ENDED if self.open_ended else max(0.0, self.end - self.start)

    @property
    def recordable(self) -> bool:
        """Whether this phase carries a label a model could learn."""
        return self.kind == "step"

    def remaining(self, now: float) -> float | None:
        return None if self.open_ended else max(0.0, self.end - now)

    def progress(self, now: float) -> float:
        if self.open_ended:
            return 0.0
        total = self.duration
        if total <= 0:
            return 1.0
        return min(1.0, max(0.0, (now - self.start) / total))

    def as_payload(self, now: float) -> dict[str, object]:
        return {
            "kind": self.kind,
            "label": self.label,
            "cycle": self.cycle,
            "step_index": self.step_index,
            "start": round(self.start, 3),
            "end": None if self.open_ended else round(self.end, 3),
            "duration": None if self.open_ended else round(self.duration, 3),
            "remaining": None
            if self.remaining(now) is None
            else round(self.remaining(now) or 0.0, 2),
            "progress": round(self.progress(now), 4),
            "open_ended": self.open_ended,
            "recordable": self.recordable,
            "speak": self.speak,
        }


@dataclass(frozen=True, slots=True)
class EngineEvent:
    kind: EventKind
    at: float
    phase: Phase | None = None
    count: int | None = None
    #: True when a state was cut short by a stop rather than finishing on plan.
    truncated: bool = False

    def as_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "kind": self.kind,
            "at": round(self.at, 3),
            "count": self.count,
            "truncated": self.truncated,
        }
        if self.phase is not None:
            payload["phase"] = {
                "kind": self.phase.kind,
                "label": self.phase.label,
                "cycle": self.phase.cycle,
                "step_index": self.phase.step_index,
                "duration": None if self.phase.open_ended else round(self.phase.duration, 3),
                "speak": self.phase.speak,
            }
        return payload


@dataclass(frozen=True, slots=True)
class _Blueprint:
    kind: PhaseKind
    label: str
    cycle: int
    step_index: int
    duration: float
    speak: str | None


def validate(spec: FlowSpec) -> tuple[list[str], list[str]]:
    """Return ``(errors, warnings)``. Errors make a spec unrunnable."""
    errors: list[str] = []
    warnings: list[str] = []

    if not spec.name.strip():
        errors.append("The flow needs a name.")
    if not spec.steps:
        errors.append("A flow needs at least one state.")
    if len(spec.steps) > MAX_STEPS:
        errors.append(f"A flow can have at most {MAX_STEPS} states.")

    for i, step in enumerate(spec.steps, start=1):
        if not step.label.strip():
            errors.append(f"State {i} has no name.")
        if step.seconds is not None and not (0 < step.seconds <= MAX_SECONDS):
            errors.append(
                f"State {i} ({step.label!r}) needs a duration between 0 and {MAX_SECONDS:.0f} s."
            )

    if not 0 <= spec.countdown_seconds <= 60:
        errors.append("The countdown must be between 0 and 60 seconds.")
    if spec.rest_seconds < 0:
        errors.append("The rest between repetitions cannot be negative.")
    if spec.repeat is not None and spec.repeat < 1:
        errors.append("The number of repetitions must be at least 1.")

    open_ended = [i for i, s in enumerate(spec.steps, start=1) if s.open_ended]
    if open_ended:
        last = len(spec.steps)
        if open_ended != [last]:
            errors.append(
                "An open-ended state ('until I stop') must be the last state — "
                "nothing after it could ever run."
            )
        if spec.mode == "loop":
            errors.append(
                "A looping flow cannot contain an open-ended state: the loop would never advance."
            )
        if (spec.cycles or 1) > 1:
            errors.append("An open-ended state can only run once.")

    cycles = spec.cycles
    if spec.mode == "loop" and cycles is not None and cycles < 2:
        warnings.append("A loop that runs once is just a linear flow.")
    if (
        spec.effective_discard_tail
        and cycles is not None
        and spec.effective_discard_tail >= cycles * max(len(spec.steps), 1)
    ):
        warnings.append("Discarding the tail would remove every recorded state.")

    if spec.mode == "loop" and spec.rest_seconds > 0 and not spec.effective_discard_tail:
        warnings.append(
            "A rest between repetitions is stored unlabelled; models usually ignore it."
        )

    return errors, warnings


class FlowEngine:
    """Walks a :class:`FlowSpec` as time passes.

    Call :meth:`advance` with the elapsed seconds since the run started; it returns
    the events that fell in the interval since the previous call. The engine is
    monotonic — time never goes backwards — and idempotent for a repeated ``now``.
    """

    def __init__(self, spec: FlowSpec, start_at: float = 0.0) -> None:
        self.spec = spec
        self._has_countdown = spec.countdown_seconds > 0
        self._index = 0
        self._spoken: set[int] = set()
        self._stop_requested = False
        self._announced = False
        self.truncated = False
        self.finished = False
        self.events: list[EngineEvent] = []

        blueprint = self._blueprint(0)
        self.phase: Phase | None = self._materialise(blueprint, start_at) if blueprint else None
        if self.phase is None:
            self.finished = True

    # ---------------------------------------------------------------- planning
    def _blueprint(self, index: int) -> _Blueprint | None:
        """The ``index``-th phase of the (possibly infinite) plan."""
        if index < 0:
            return None
        if self._has_countdown:
            if index == 0:
                return _Blueprint(
                    kind="countdown",
                    label="get ready",
                    cycle=0,
                    step_index=-1,
                    duration=float(self.spec.countdown_seconds),
                    speak=None,
                )
            index -= 1

        steps = self.spec.steps
        per_cycle = len(steps) + (1 if self.spec.rest_seconds > 0 else 0)
        cycle, offset = divmod(index, per_cycle)

        cycles = self.spec.cycles
        if cycles is not None and cycle >= cycles:
            return None

        if offset < len(steps):
            step = steps[offset]
            return _Blueprint(
                kind="step",
                label=step.label,
                cycle=cycle,
                step_index=offset,
                duration=step.duration,
                speak=step.spoken,
            )
        return _Blueprint(
            kind="rest",
            label="rest",
            cycle=cycle,
            step_index=-1,
            duration=float(self.spec.rest_seconds),
            speak=None,
        )

    @staticmethod
    def _materialise(blueprint: _Blueprint | None, start: float) -> Phase | None:
        if blueprint is None:
            return None
        end = OPEN_ENDED if math.isinf(blueprint.duration) else start + blueprint.duration
        return Phase(
            kind=blueprint.kind,
            label=blueprint.label,
            cycle=blueprint.cycle,
            step_index=blueprint.step_index,
            start=start,
            end=end,
            speak=blueprint.speak,
        )

    def upcoming(self, now: float, count: int = 3) -> list[dict[str, object]]:
        """The next ``count`` phases, for the "up next" strip in the UI."""
        out: list[dict[str, object]] = []
        index = self._index
        start = self.phase.end if self.phase is not None and not self.phase.open_ended else now
        for _ in range(count):
            index += 1
            blueprint = self._blueprint(index)
            if blueprint is None:
                break
            phase = self._materialise(blueprint, start)
            if phase is None:  # pragma: no cover - blueprint guards this
                break
            out.append(
                {
                    "kind": phase.kind,
                    "label": phase.label,
                    "cycle": phase.cycle,
                    "duration": None if phase.open_ended else round(phase.duration, 3),
                }
            )
            start = phase.end
        return out

    # ----------------------------------------------------------------- control
    def request_stop(self) -> None:
        """Ask the current state to close. The next :meth:`advance` honours it."""
        self._stop_requested = True

    # ------------------------------------------------------------------ cursor
    def advance(self, now: float) -> list[EngineEvent]:
        """Consume every phase boundary at or before ``now``."""
        produced: list[EngineEvent] = []

        # The very first phase is already in progress when the engine is built, so its
        # `phase_start` (and `cycle_start`) is announced on the first poll. Without this
        # a flow with no countdown would never open its first state at all — the runner
        # opens a recording segment on `phase_start`, so the opening state would be
        # silently unlabelled.
        if not self._announced:
            self._announced = True
            if self.phase is not None:
                produced.append(EngineEvent("phase_start", self.phase.start, self.phase))
                if self.phase.kind == "step" and self.phase.step_index == 0:
                    produced.append(EngineEvent("cycle_start", self.phase.start, self.phase))

        while not self.finished:
            phase = self.phase
            if phase is None:
                self.finished = True
                produced.append(EngineEvent("finished", now))
                break

            if phase.kind == "countdown":
                remaining = phase.end - now
                number = math.ceil(remaining - 1e-9)
                if number >= 1 and number not in self._spoken:
                    self._spoken.add(number)
                    produced.append(EngineEvent("countdown", now, phase, number))

            over = now >= phase.end or self._stop_requested
            if not over:
                break

            stopped = self._stop_requested
            produced.append(EngineEvent("phase_end", min(now, phase.end), phase, truncated=stopped))
            # `go` means "the countdown finished, start recording". A countdown cut
            # short by the operator did not finish, so it must not start one — otherwise
            # cancelling during the count still writes a dataset.
            if phase.kind == "countdown" and not stopped:
                produced.append(EngineEvent("go", phase.end, phase))
            if stopped:
                self.truncated = True
                self.finished = True
                produced.append(EngineEvent("stopped", now))
                break

            self._index += 1
            blueprint = self._blueprint(self._index)
            if blueprint is None:
                self.phase = None
                self.finished = True
                produced.append(EngineEvent("finished", now))
                break

            self.phase = self._materialise(blueprint, phase.end)
            if self.phase is None:  # pragma: no cover - blueprint guards this
                self.finished = True
                break
            produced.append(EngineEvent("phase_start", phase.end, self.phase))
            if blueprint.kind == "step" and blueprint.step_index == 0:
                produced.append(EngineEvent("cycle_start", phase.end, self.phase))

        self.events.extend(produced)
        return produced

    # ------------------------------------------------------------------- state
    def state(self, now: float) -> dict[str, object]:
        """A JSON-ready snapshot of the run, for the UI."""
        cycles = self.spec.cycles
        phase = self.phase
        return {
            "finished": self.finished,
            "stopped": self.truncated,
            "elapsed": round(now, 2),
            "cycle": phase.cycle if phase else (cycles or 0),
            "cycles": cycles,
            "phase": phase.as_payload(now) if phase else None,
            "upcoming": self.upcoming(now),
            "total_seconds": self.spec.total_seconds,
        }


def single_label_flow(
    label: str, countdown_seconds: float = 3.0, speak: str | None = None
) -> FlowSpec:
    """The "name it, press record, it counts 3-2-1" case as a one-state flow."""
    return FlowSpec(
        name=label,
        mode="linear",
        countdown_seconds=countdown_seconds,
        discard_tail=0,
        steps=(FlowStep(label=label, seconds=None, speak=speak),),
    )


def eyes_open_closed_flow(
    *,
    closed_seconds: float = 20.0,
    open_seconds: float = 15.0,
    countdown_seconds: float = 3.0,
    repeat: int | None = None,
    closed_label: str = "eyes closed",
    open_label: str = "eyes open",
) -> FlowSpec:
    """The canonical alternating protocol, looping until stopped."""
    return FlowSpec(
        name="Eyes closed / eyes open",
        mode="loop",
        countdown_seconds=countdown_seconds,
        repeat=repeat,
        description=(
            "Alternates eyes-closed and eyes-open. Alpha (8-12 Hz) rises over the "
            "occipital channels with the eyes closed; that contrast is the signal."
        ),
        steps=(
            FlowStep(label=closed_label, seconds=closed_seconds, speak="close your eyes"),
            FlowStep(label=open_label, seconds=open_seconds, speak="open your eyes"),
        ),
    )


def with_id(spec: FlowSpec, flow_id: str) -> FlowSpec:
    """Return a copy tagged with its stored id."""
    return replace(spec, id=flow_id)
