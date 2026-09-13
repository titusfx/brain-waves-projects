"""The acquisition hub: one source, one stream, many consumers.

The dongle is a single USB resource that only one process may open, so this object
is the process's single owner of it. It does four things:

* runs the source on its own thread and drains it on the event loop's clock,
* keeps the newest few seconds in a ring buffer so a late browser still gets data,
* fans one frame per tick out to every WebSocket subscriber,
* feeds the active :class:`~eeg_api.services.recorder.DatasetRecorder`, which is
  the only consumer allowed to see *every* sample rather than the display window.

It is also the clock the guided flows are measured against: ``stream_time_at()``
converts a wall clock instant into the timestamp of the sample that was arriving
then, which is how a state boundary ends up sample-exact instead of "somewhere in
the last 100 ms".
"""

from __future__ import annotations

import asyncio
import contextlib
import queue
import shutil
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from eeg_api.config import Settings
from eeg_api.domain.channels import ChannelCatalog
from eeg_api.domain.metrics import alpha_metrics, channel_metrics, contact_score
from eeg_api.domain.models import (
    CHANNELS,
    OCCIPITAL_CHANNELS,
    Chunk,
    SourceMode,
    SourceStats,
)
from eeg_api.eeg import device as device_module
from eeg_api.eeg.device import DongleInterface
from eeg_api.eeg.sources import (
    CHUNK_QUEUE_SIZE,
    EyesClosedControl,
    SignalSource,
    create_source,
)
from eeg_api.services.recorder import DatasetRecorder
from eeg_api.services.ring import RingBuffer


if TYPE_CHECKING:  # the runner imports this module, so the import is type-only
    from eeg_api.services.runner import FlowRunner


#: How long a HID enumeration is trusted, so /status can be polled cheaply.
DEVICE_CACHE_SECONDS = 3.0


class SessionError(RuntimeError):
    """The requested session transition is not possible in the current state."""


class AcquisitionHub:
    """Owns the source, the stream, the ring buffer and the active recording."""

    def __init__(self, settings: Settings, catalog: ChannelCatalog | None = None) -> None:
        self.settings = settings
        self.catalog = catalog
        self.fs = float(settings.fs)

        self._queue: queue.Queue[Chunk] = queue.Queue(maxsize=CHUNK_QUEUE_SIZE)
        self._source: SignalSource | None = None
        self._mode: SourceMode = "idle"
        self._error: str | None = None
        self._buffer = RingBuffer(settings.max_samples_window, len(CHANNELS))

        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._pending_rows: list[np.ndarray] = []
        self._seq = 0
        self._stream_t = 0.0
        self._stream_wall = time.monotonic()

        self._recorder: DatasetRecorder | None = None
        self._runner: FlowRunner | None = None

        self._lock = asyncio.Lock()
        self._tasks: list[asyncio.Task[None]] = []
        self._closing = False
        self._device_cache: tuple[float, dict[str, Any]] | None = None

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        """Start the ticker and, for ``auto``, the dongle if one is attached."""
        self._closing = False
        self._tasks.append(asyncio.create_task(self._ticker(), name="hub-ticker"))
        wanted = (self.settings.default_source or "idle").strip().lower()
        if wanted == "auto":
            wanted = "live" if device_module.streaming_interface() is not None else "idle"
        if wanted != "idle":
            await self.set_source(wanted, reason="startup")

    async def shutdown(self) -> None:
        self._closing = True
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                # Shutdown must complete: a task that will not stop is a reason to
                # keep going with the rest of the teardown, not to abort it.
                await task
        self._tasks.clear()
        if self._recorder is not None and not self._recorder.finalised:
            self._recorder.finalize(discard_tail=0, outcome="interrupted")
            self._recorder = None
        await self._stop_source()

    # --------------------------------------------------------------------- source
    @property
    def mode(self) -> SourceMode:
        return self._mode

    @property
    def source(self) -> SignalSource | None:
        return self._source

    async def set_source(
        self,
        mode: str,
        *,
        replay_path: Path | None = None,
        replay_speed: float | None = None,
        replay_loop: bool = True,
        interface: DongleInterface | None = None,
        reason: str = "operator",
    ) -> dict[str, Any]:
        """Switch the stream. Refused while a session is running.

        Both cases are refused for the same reason: changing the signal halfway through
        a protocol would mix two different things into one class, and resetting the
        stream would move the clock the state boundaries are measured against.
        """
        async with self._lock:
            if self._recorder is not None and not self._recorder.finalised:
                raise SessionError(
                    "A dataset is being recorded — stop the session before switching source."
                )
            if self._runner is not None and self._runner.state().get("active"):
                raise SessionError("A session is running — stop it before switching source.")
            await self._stop_source()
            self._error = None
            normalised = (mode or "idle").strip().lower()

            if normalised in {"idle", "stop", "none"}:
                self._mode = "idle"
                self._publish_source(reason)
                return self.status()

            try:
                source = create_source(
                    normalised,
                    out=self._queue,
                    fs=self.fs,
                    highpass_hz=self.settings.highpass_hz,
                    replay_path=replay_path,
                    replay_speed=replay_speed
                    if replay_speed is not None
                    else self.settings.replay_speed,
                    replay_loop=replay_loop,
                    interface=interface,
                )
            except ValueError as exc:
                self._mode = "idle"
                self._error = str(exc)
                self._publish_source(reason)
                return self.status()

            if source is None:
                self._mode = "idle"
                self._error = (
                    "No Emotiv dongle found. Plug it in, or switch to the demo source "
                    "or a recording."
                )
                self._publish_source(reason)
                return self.status()

            self._reset_stream()
            self._source = source
            self._mode = source.mode
            source.start()
            self._publish_source(reason)
            return self.status()

    async def _stop_source(self) -> None:
        source, self._source = self._source, None
        self._mode = "idle"
        if source is not None:
            await asyncio.to_thread(source.stop)

    def _reset_stream(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        self._buffer.clear()
        self._pending_rows.clear()
        self._stream_t = 0.0
        self._stream_wall = time.monotonic()
        self._seq = 0

    def stats(self) -> SourceStats:
        return self._source.stats() if self._source is not None else SourceStats(mode="idle")

    # ------------------------------------------------------------------- ticking
    async def _ticker(self) -> None:
        interval = 1.0 / max(1.0, float(self.settings.tick_hz))
        next_at = time.monotonic()
        while not self._closing:
            next_at += interval
            try:
                self._drain()
                if self._subscribers or self._recorder is not None:
                    self.publish(self.frame())
            except Exception as exc:
                self._error = f"{type(exc).__name__}: {exc}"
            delay = next_at - time.monotonic()
            if delay <= 0:
                next_at = time.monotonic()  # fell behind: resynchronise rather than spin
                delay = 0.0
            await asyncio.sleep(delay)

    def _drain(self) -> None:
        """Move everything the source produced into the buffer and the recorder."""
        drained: list[np.ndarray] = []
        while True:
            try:
                chunk = self._queue.get_nowait()
            except queue.Empty:
                break
            if self._recorder is not None and not self._recorder.finalised:
                self._recorder.append(chunk.uv, chunk.t0)
            drained.append(chunk.uv)
            self._stream_t = chunk.t0 + chunk.n / self.fs
        if not drained:
            return
        block = drained[0] if len(drained) == 1 else np.vstack(drained)
        self._buffer.extend(block)
        self._pending_rows.append(block)
        self._stream_wall = time.monotonic()

    def stream_time_at(self, wall: float) -> float:
        """The stream timestamp of the sample arriving at ``wall`` (monotonic seconds).

        Interpolated between the last drained sample and now, so a state boundary is
        accurate to a sample rather than to a tick. Clamped, because a stalled source
        must not push a boundary into the future.
        """
        if self._source is None:
            return 0.0
        return self._stream_t + max(0.0, min(wall - self._stream_wall, 0.5))

    # -------------------------------------------------------------------- frames
    def frame(self) -> dict[str, Any]:
        """One broadcast tick: new samples, the display metrics, and the session state."""
        self._seq += 1
        stats = self.stats()
        window = self._buffer.latest(int(self.settings.window_seconds * self.fs))
        enough = window.shape[0] >= 64
        metrics = channel_metrics(window) if enough else []

        alpha: dict[str, dict[str, float]] = {}
        if window.shape[0] >= 128:
            for name in OCCIPITAL_CHANNELS:
                share, peak = alpha_metrics(
                    np.asarray(window[:, CHANNELS.index(name)], dtype=np.float64)
                )
                alpha[name] = {"share": round(share, 2), "peak": round(peak, 3)}

        pending = self._pending_rows
        self._pending_rows = []
        samples = np.vstack(pending) if pending else np.zeros((0, len(CHANNELS)))
        max_rows = int(self.fs * 2)
        if samples.shape[0] > max_rows:
            samples = samples[-max_rows:]

        return {
            "type": "tick",
            "seq": self._seq,
            "t": round(self._stream_t, 3),
            "fs": self.fs,
            "channels": list(CHANNELS),
            "source": stats.as_payload(),
            "samples": {
                "t0": round(self._stream_t - samples.shape[0] / self.fs, 4),
                "data": [[round(float(v), 2) for v in row] for row in samples],
            },
            "metrics": [m.as_payload() for m in metrics],
            "alpha": alpha,
            "contact": contact_score(metrics) if metrics else None,
            "window_seconds": self.settings.window_seconds,
            "session": self._runner.state() if self._runner is not None else None,
            "recording": self._recorder.state() if self._recorder is not None else None,
            "error": self._error,
        }

    def snapshot(self, seconds: float = 6.0, points: int = 900) -> dict[str, Any]:
        """Historical samples for a chart, decimated. Used by REST and on WS connect."""
        window = self._buffer.latest(int(seconds * self.fs))
        total = int(window.shape[0])
        if total == 0:
            return {"t0": 0.0, "fs": self.fs, "step": 1, "data": [], "total_samples": 0}
        step = max(1, total // max(1, points))
        picks = np.arange(0, total, step)
        t0 = self._stream_t - total / self.fs
        return {
            "t0": round(t0 + float(picks[0]) / self.fs, 4),
            "fs": self.fs,
            "step": int(step),
            "total_samples": total,
            "data": [[round(float(v), 2) for v in window[i]] for i in picks],
        }

    def hello(self) -> dict[str, Any]:
        """The first message on a WebSocket: what this stream is."""
        return {
            "type": "hello",
            "fs": self.fs,
            "channels": list(CHANNELS),
            "occipital": list(OCCIPITAL_CHANNELS),
            "source": self.stats().as_payload(),
            "device": self.device_status(),
            "recording": self._recorder.state() if self._recorder is not None else None,
            "session": self._runner.state() if self._runner is not None else None,
            "window_seconds": self.settings.window_seconds,
        }

    # --------------------------------------------------------------- subscribers
    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue_: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=64)
        self._subscribers.add(queue_)
        return queue_

    def unsubscribe(self, queue_: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue_)

    def publish(self, message: dict[str, Any]) -> None:
        """Send to every subscriber. A slow browser loses frames; it never blocks the hub."""
        for subscriber in list(self._subscribers):
            try:
                subscriber.put_nowait(message)
            except asyncio.QueueFull:
                try:
                    subscriber.get_nowait()
                    subscriber.put_nowait(message)
                except (asyncio.QueueEmpty, asyncio.QueueFull):  # pragma: no cover
                    pass

    def _publish_source(self, reason: str) -> None:
        self.publish(
            {
                "type": "source",
                "reason": reason,
                "state": self.status(),
            }
        )

    # ------------------------------------------------------------------ recording
    @property
    def recorder(self) -> DatasetRecorder | None:
        return self._recorder

    def begin_recording(self, name: str, meta: dict[str, Any]) -> DatasetRecorder:
        """Create the dataset and start writing at the current stream time.

        Called at the moment the countdown ends, which is what keeps the countdown
        itself out of the data.
        """
        if self._recorder is not None and not self._recorder.finalised:
            raise SessionError("a recording is already running")
        recorder = DatasetRecorder(
            self.settings.recordings_dir,
            name,
            fs=self.fs,
            meta={**meta, "source": self._mode, "source_label": self.stats().label},
        )
        recorder.begin(self.stream_time_at(time.monotonic()))
        self._recorder = recorder
        self.publish({"type": "recording", "state": "started", "recording": recorder.state()})
        return recorder

    def open_segment(self, at: float, label: str, *, cycle: int = 0, step_index: int = -1) -> None:
        if self._recorder is not None and not self._recorder.finalised:
            self._recorder.request_open(at, label, cycle=cycle, step_index=step_index)

    def close_segment(self, at: float, *, truncated: bool = False) -> None:
        if self._recorder is not None and not self._recorder.finalised:
            self._recorder.request_close(at, truncated=truncated)

    def finish_recording(
        self, *, discard_tail: int = 0, outcome: str = "completed", keep: bool = True
    ) -> dict[str, Any]:
        """Close the dataset. ``keep=False`` throws it away after closing it."""
        recorder, self._recorder = self._recorder, None
        if recorder is None:
            raise SessionError("no recording is running")
        stats = self.stats()
        if stats.dropped_chunks:
            recorder.note_dropped_chunk()
        # Drain once more before closing: the last fraction of a second is still sitting
        # in the queue, and the recorder's own truncation will cut anything that arrived
        # after the final state ended.
        self._drain()
        summary = recorder.finalize(discard_tail=discard_tail, outcome=outcome)
        if not keep:
            shutil.rmtree(recorder.dir, ignore_errors=True)
            summary = {**summary, "removed": True, "path": str(recorder.dir)}
        self.publish({"type": "recording", "state": "finished", "summary": summary})
        return summary

    # --------------------------------------------------------------------- runner
    @property
    def runner(self) -> FlowRunner | None:
        return self._runner

    def attach_runner(self, runner: FlowRunner) -> None:
        self._runner = runner

    def detach_runner(self, runner: FlowRunner) -> None:
        if self._runner is runner:
            self._runner = None

    def drive_eyes(self, closed: bool | None) -> None:
        """Let a running flow steer the demo source, so the alpha meter reacts to it.

        Only the synthetic source implements this. On real hardware the alpha must
        come from the subject, and this is a no-op — which is the point.
        """
        source = self._source
        if source is not None and isinstance(source, EyesClosedControl):
            source.set_eyes_closed(closed)

    # --------------------------------------------------------------------- status
    def device_status(self) -> dict[str, Any]:
        """What is plugged in, cached for a few seconds (a HID scan is not free)."""
        now = time.monotonic()
        if self._device_cache is not None and now - self._device_cache[0] < DEVICE_CACHE_SECONDS:
            return self._device_cache[1]
        status = device_module.detect()
        self._device_cache = (now, status)
        return status

    def status(self) -> dict[str, Any]:
        stats = self.stats()
        return {
            "source": self._mode,
            "source_label": stats.label,
            "stats": stats.as_payload(),
            "buffer_seconds": round(len(self._buffer) / self.fs, 2),
            "subscribers": len(self._subscribers),
            "device": self.device_status(),
            "recording": self._recorder.state() if self._recorder is not None else None,
            "session": self._runner.state() if self._runner is not None else None,
            "recordings_dir": str(self.settings.recordings_dir),
            "fs": self.fs,
            "error": self._error,
        }
