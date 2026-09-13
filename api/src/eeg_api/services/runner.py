"""Running a guided protocol.

A session is the only way anything is recorded: the quick single-label case is a
one-state flow, and the "eyes closed / eyes open" case is a looping two-state flow.
Having one path means one place where the countdown is excluded from the data, one
place where state boundaries are stamped, and one place where a stopped loop drops
its tail.

The runner is deliberately thin. It polls the pure :class:`FlowEngine` 50 times a
second, translates the engine's events into stream time, and tells the hub what to
write. All of the protocol logic — and therefore all of the interesting bugs — lives
in ``domain/flows.py``, where it is tested without a clock, a socket or a headset.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from datetime import datetime
from typing import Any

from eeg_api.domain.flows import EngineEvent, FlowEngine, FlowSpec, validate
from eeg_api.services.hub import AcquisitionHub, SessionError


#: How often the engine is polled. 20 ms makes a 3-2-1 countdown feel immediate
#: while costing nothing: the engine does no work when nothing has changed.
POLL_INTERVAL = 0.02

#: Words that mean "the subject's eyes are involved", used to steer the demo source.
_EYES_CLOSED_WORDS = ("close", "closed", "shut")
_EYES_OPEN_WORDS = ("open", "opened")


def eyes_state_for_label(label: str) -> bool | None:
    """Whether a state label means eyes-closed, eyes-open, or neither."""
    lowered = label.lower()
    if any(word in lowered for word in _EYES_CLOSED_WORDS):
        return True
    if any(word in lowered for word in _EYES_OPEN_WORDS):
        return False
    return None


class FlowRunner:
    """One run of one protocol."""

    def __init__(
        self,
        hub: AcquisitionHub,
        spec: FlowSpec,
        *,
        dataset_name: str | None = None,
        notes: str = "",
        speak: bool = True,
    ) -> None:
        self.hub = hub
        self.spec = spec
        self.dataset_name = (dataset_name or spec.name).strip() or "dataset"
        self.notes = notes
        self.speak = speak

        self.engine = FlowEngine(spec)
        self.started_at = time.monotonic()
        self.started_wall = datetime.now()
        self.active = False
        self.outcome: str | None = None
        self.summary: dict[str, Any] | None = None
        self.error: str | None = None
        self._task: asyncio.Task[None] | None = None
        self._begun = False

    # ----------------------------------------------------------------- lifecycle
    @property
    def recording(self) -> bool:
        return self._begun

    async def start(self) -> dict[str, Any]:
        """Validate, check there is a stream, and begin."""
        errors, _warnings = validate(self.spec)
        if errors:
            raise SessionError(" ".join(errors))
        if self.hub.mode == "idle" or self.hub.source is None:
            raise SessionError(
                "Nothing is streaming. Pick a source first — the dongle, a recording, or the demo signal."
            )
        if self.hub.recorder is not None:
            raise SessionError("A dataset is already being recorded.")

        self.started_at = time.monotonic()
        self.started_wall = datetime.now()
        self.active = True
        self.outcome = None
        self.hub.attach_runner(self)
        self._task = asyncio.create_task(self._run(), name=f"flow-{self.spec.id or 'inline'}")
        self._publish(
            {"kind": "started", "at": 0.0, "phase": None, "count": None, "truncated": False}
        )
        return self.state()

    async def stop(self) -> dict[str, Any]:
        """Ask the current state to close, and wait for the run to finish.

        The countdown is excluded from the dataset, so the two ways of stopping are
        genuinely different: stopped during the countdown leaves no dataset at all.
        """
        if not self.active:
            return self.state()
        self.engine.request_stop()
        await self._await_run()
        return self.state()

    async def abort(self) -> dict[str, Any]:
        """Stop and throw the dataset away."""
        if not self.active:
            return self.state()
        self.engine.request_stop()
        self.outcome = "aborted"
        await self._await_run()
        return self.state()

    async def _await_run(self) -> None:
        """Wait for the poll loop to finish and finalise, but never forever.

        The runner finalises itself, so this only has to wait for it. The timeout is a
        backstop: a stuck run must not hold an HTTP request open indefinitely.
        """
        task = self._task
        if task is not None:
            with contextlib.suppress(TimeoutError, asyncio.CancelledError):
                await asyncio.wait_for(asyncio.shield(task), timeout=5.0)

    # ------------------------------------------------------------------ the loop
    async def _run(self) -> None:
        try:
            while True:
                now = time.monotonic() - self.started_at
                for event in self.engine.advance(now):
                    self._handle(event)
                self._publish_state(now)
                if self.engine.finished:
                    break
                await asyncio.sleep(POLL_INTERVAL)
        except asyncio.CancelledError:
            self.outcome = self.outcome or "cancelled"
            raise
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            self.outcome = "failed"
        finally:
            self._finalise()

    def _handle(self, event: EngineEvent) -> None:
        if event.kind == "countdown":
            self._publish(event)
            return

        if event.kind == "go":
            # This is the moment the dataset starts: the countdown is deliberately
            # not part of it.
            try:
                self.hub.begin_recording(
                    self.dataset_name,
                    {
                        "notes": self.notes,
                        "flow": self.spec.as_payload(),
                        "started": self.started_wall.isoformat(timespec="seconds"),
                        "voice": self.speak,
                    },
                )
                self._begun = True
            except SessionError as exc:
                self.error = str(exc)
                self.outcome = "failed"
                self.engine.request_stop()
                return
            self._publish(event)
            return

        if event.phase is not None and event.phase.kind == "step":
            at = self._stream_time(event.at)
            if event.kind == "phase_start":
                self.hub.open_segment(
                    at,
                    event.phase.label,
                    cycle=event.phase.cycle,
                    step_index=event.phase.step_index,
                )
                self.hub.drive_eyes(eyes_state_for_label(event.phase.label))
            elif event.kind == "phase_end":
                self.hub.close_segment(at, truncated=event.truncated)

        self._publish(event)

    def _stream_time(self, at: float) -> float:
        """Engine seconds → stream seconds, as of now.

        An event that fired slightly in the past is still stamped at its own ``at``;
        the recorder applies boundaries as the writer passes them, so this stays
        sample-accurate even when the poll interval straddles the boundary.
        """
        return self.hub.stream_time_at(self.started_at + at)

    def _finalise(self) -> None:
        self.active = False
        if not self._begun:
            # Never got past the countdown: there is nothing on disk to close.
            self.outcome = self.outcome or "cancelled"
            self.hub.drive_eyes(None)
            self._publish_summary()
            self.hub.detach_runner(self)
            return

        discard = self.spec.effective_discard_tail if self.engine.truncated else 0
        outcome = self.outcome or ("stopped" if self.engine.truncated else "completed")
        try:
            self.summary = self.hub.finish_recording(
                discard_tail=discard,
                outcome=outcome,
                keep=outcome != "aborted",
            )
        except SessionError as exc:
            self.error = str(exc)
            self.outcome = "failed"
        else:
            self.outcome = outcome
        self.hub.drive_eyes(None)
        self._publish_summary()
        self.hub.detach_runner(self)

    # -------------------------------------------------------------------- output
    def _publish(self, event: EngineEvent | dict[str, Any]) -> None:
        """Send one event to every subscriber.

        Accepts a plain dict as well as an :class:`EngineEvent`, because the runner has
        two events of its own — ``started`` and ``ended`` — that are not transitions of
        the protocol engine but must reach the browser in the same shape.
        """
        payload = event.as_payload() if isinstance(event, EngineEvent) else event
        self.hub.publish({"type": "session", "event": payload, "state": self.state()})

    def _publish_state(self, now: float) -> None:
        self.hub.publish({"type": "session", "state": self.state(now)})

    def _publish_summary(self) -> None:
        self.hub.publish(
            {
                "type": "session",
                "event": {
                    "kind": "ended",
                    "at": 0.0,
                    "phase": None,
                    "count": None,
                    "truncated": self.engine.truncated,
                },
                "state": self.state(),
                "summary": self.summary,
                "outcome": self.outcome,
                "error": self.error,
            }
        )

    def state(self, now: float | None = None) -> dict[str, Any]:
        """A JSON-ready snapshot. Called from the hub's tick, so it must stay cheap."""
        elapsed = (time.monotonic() - self.started_at) if now is None else now
        recorder = self.hub.recorder
        return {
            "active": self.active,
            "id": self.spec.id,
            "flow": self.spec.as_payload(),
            "dataset_name": self.dataset_name,
            "notes": self.notes,
            "voice": self.speak,
            "started": self.started_wall.isoformat(timespec="seconds"),
            "recording": self._begun,
            "engine": self.engine.state(elapsed),
            "recording_state": recorder.state() if recorder is not None else None,
            "outcome": self.outcome,
            "error": self.error,
            "summary": self.summary,
        }


def plan_preview(spec: FlowSpec, limit: int = 24) -> dict[str, Any]:
    """What this flow will do, without running it. Powers the builder's timeline."""
    engine = FlowEngine(spec)
    phases: list[dict[str, Any]] = []
    if engine.phase is not None:
        phases.append(
            {
                "kind": engine.phase.kind,
                "label": engine.phase.label,
                "cycle": engine.phase.cycle,
                "duration": None if engine.phase.open_ended else round(engine.phase.duration, 3),
            }
        )
    phases.extend(engine.upcoming(0.0, max(0, limit - len(phases))))
    return {
        "phases": phases,
        "total_seconds": spec.total_seconds,
        "cycles": spec.cycles,
        "discard_tail": spec.effective_discard_tail,
        "truncated": len(phases) >= limit,
    }
