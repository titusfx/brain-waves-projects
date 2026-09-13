"""Where samples come from: the dongle, a recording, or a synthetic head.

All three produce the same thing — :class:`~eeg_api.domain.models.Chunk` objects on
a bounded queue — so everything downstream (metrics, streaming, recording,
datasets, guided flows) is identical no matter which one is running.

The synthetic source is not a toy. Without it there is no way to develop or test
the UI without a headset on someone's head, and the real hardware needs a person
to sit still for it. It generates a plausible 1/f scalp signal with a genuine
eyes-closed alpha burst over O1/O2, one weak-contact channel and one dry channel,
and it can be driven by a running flow — so a flow that says "close your eyes"
demonstrably raises the alpha meter. What it must never do is pretend to be live
data: the mode is reported as ``demo`` everywhere, and nothing is decoded.
"""

from __future__ import annotations

import contextlib
import queue
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Iterator
from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np

from eeg_api.domain.models import (
    CHANNELS,
    EEG_PACKET_TYPE,
    FS,
    ChannelMetrics,  # noqa: F401 - re-exported for callers importing from here
    Chunk,
    FloatArray,
    SourceMode,
    SourceStats,
)
from eeg_api.eeg import csvio
from eeg_api.eeg.crypto import decrypt_ecb, serial_key
from eeg_api.eeg.decoder import UVStream, decode_reports
from eeg_api.eeg.device import DongleInterface, streaming_interface


#: How many chunks may wait to be consumed before the oldest is dropped. Real time
#: wins over completeness: a monitor that falls behind must lose history, not block
#: the HID reader and corrupt the stream.
CHUNK_QUEUE_SIZE = 512

#: Reports that must be seen before the byte-1 oracle is allowed to judge the key.
KEY_CHECK_MIN_REPORTS = 64

#: How long a single HID read waits for a report before giving up. At ~159 reports/s a
#: report is ~6 ms away, so this is an upper bound that is only ever reached when the
#: headset is off — which is precisely when the loop should be cheap, not busy.
READ_TIMEOUT_MS = 250


class SignalSource(Protocol):
    """Anything that can produce samples."""

    mode: SourceMode
    label: str

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def stats(self) -> SourceStats: ...


@runtime_checkable
class EyesClosedControl(Protocol):
    """A source whose signal can be told to "close its eyes" by a running flow."""

    def set_eyes_closed(self, closed: bool | None) -> None: ...


class ThreadedSource(ABC):
    """Base for the three sources: a daemon thread feeding a bounded queue."""

    mode: SourceMode = "idle"
    label: str = ""
    #: Whether this source decrypts dongle reports, and therefore whether the byte-1
    #: key oracle has anything to say. Only the live source does; a replay or a
    #: synthetic signal has no key, and reporting "key OK" for one would be a lie.
    judges_key: bool = False

    def __init__(self, *, fs: float = FS, out: queue.Queue[Chunk]) -> None:
        self.fs = fs
        self.label = ""
        self._out = out
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._samples = 0
        self._reports = 0
        self._dropped = 0
        self._distinct: dict[int, int] = {}
        self._started_at = time.monotonic()
        self._error: str | None = None

    # ------------------------------------------------------------------ control
    def start(self) -> None:
        if self._thread is not None:
            return
        self._started_at = time.monotonic()
        self._thread = threading.Thread(
            target=self._guard, name=f"eeg-source-{self.mode}", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=2.0)

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    def _guard(self) -> None:
        try:
            self._run()
        except Exception as exc:
            self._error = f"{type(exc).__name__}: {exc}"

    @abstractmethod
    def _run(self) -> None:
        """Acquire until ``self.stopped``."""

    # ------------------------------------------------------------------- output
    def _emit(
        self,
        uv: FloatArray,
        counters: np.ndarray | None = None,
        quality: FloatArray | None = None,
        key_ok: bool | None = None,
    ) -> None:
        if uv.shape[0] == 0:
            return
        with self._lock:
            t0 = self._samples / self.fs
            self._samples += int(uv.shape[0])
        chunk = Chunk(uv=uv, t0=t0, counters=counters, quality=quality, key_ok=key_ok)
        try:
            self._out.put_nowait(chunk)
        except queue.Full:
            # Real time wins over completeness: drop the oldest buffered chunk rather
            # than block the HID reader. The count is reported to the operator, and a
            # dataset that has gaps says so in its metadata.
            try:
                self._out.get_nowait()
                self._out.put_nowait(chunk)
                with self._lock:
                    self._dropped += 1
            except queue.Empty:  # pragma: no cover - raced with the consumer
                pass

    def _note_report(self, byte1: int) -> None:
        self._reports += 1
        self._distinct[byte1] = self._distinct.get(byte1, 0) + 1

    # -------------------------------------------------------------------- stats
    @property
    def key_ok(self) -> bool | None:
        """The oracle: a correct key collapses byte 1 to ~2 values, a wrong one does not."""
        if not self.judges_key or self._reports < KEY_CHECK_MIN_REPORTS:
            return None
        return len(self._distinct) <= 6

    def stats(self) -> SourceStats:
        elapsed = max(1e-6, time.monotonic() - self._started_at)
        with self._lock:
            samples = self._samples
            dropped = self._dropped
        return SourceStats(
            mode=self.mode,
            label=self.label,
            elapsed_s=elapsed,
            reports_seen=self._reports,
            samples=samples,
            reports_per_second=self._reports / elapsed,
            distinct_byte1=len(self._distinct),
            key_ok=self.key_ok,
            error=self._error,
            dropped_chunks=dropped,
        )


class LiveSource(ThreadedSource):
    """The real thing: the dongle's HID interface 1, decrypted and decoded."""

    mode: SourceMode = "live"
    judges_key = True

    def __init__(
        self,
        interface: DongleInterface,
        *,
        out: queue.Queue[Chunk],
        fs: float = FS,
        highpass_hz: float = 0.5,
        report_len: int = 32,
    ) -> None:
        super().__init__(fs=fs, out=out)
        self.interface = interface
        self.label = f"dongle {interface.serial} · {interface.product}"
        self._report_len = report_len
        self._key = serial_key(interface.serial)
        self._stream = UVStream(fs, highpass_hz)

    def _run(self) -> None:
        import hid

        device = hid.device()
        device.open_path(self.interface.path)
        try:
            # Blocking reads with a timeout, exactly as scripts/read_live.py does. The
            # timeout is only an upper bound — a read returns as soon as a report arrives
            # — so a generous one costs nothing when data flows and keeps the loop from
            # spinning when the headset is off.
            device.set_nonblocking(0)
            while not self.stopped:
                burst: list[np.ndarray] = []
                for _ in range(64):  # drain a burst, as live_view.py does
                    data = device.read(self._report_len, READ_TIMEOUT_MS)
                    if not data:
                        break
                    raw = bytes(data[: self._report_len])
                    if len(raw) != self._report_len:
                        continue
                    row = decrypt_ecb(self._key, raw)
                    self._note_report(row[1])
                    if row[1] == EEG_PACKET_TYPE:
                        burst.append(np.frombuffer(row, dtype=np.uint8))
                if burst:
                    reports = np.array(burst, dtype=np.uint8)
                    uv, counters, quality = decode_reports(reports, self._stream)
                    self._emit(uv, counters=counters, quality=quality)
                else:
                    time.sleep(0.002)
        finally:
            with contextlib.suppress(Exception):
                # Closing a handle whose dongle was unplugged must not raise: the
                # session is over either way.
                device.close()


class ReplaySource(ThreadedSource):
    """A recording played back at ``speed``x real time, optionally on a loop."""

    mode: SourceMode = "replay"

    def __init__(
        self,
        path: Path,
        *,
        out: queue.Queue[Chunk],
        fs: float = FS,
        speed: float = 1.0,
        loop: bool = True,
    ) -> None:
        super().__init__(fs=fs, out=out)
        self.path = path
        self.speed = max(0.05, float(speed))
        self.loop = loop
        self.label = f"replay {path.name} x{self.speed:g}"
        self.finished = False
        self._slice = max(1, round(fs * 0.05))

    def _file_blocks(self) -> Iterator[FloatArray]:
        buffer: list[FloatArray] = []
        for _timestamp, values in csvio.iter_rows(self.path):
            buffer.append(values)
            if len(buffer) >= self._slice:
                yield np.vstack(buffer)
                buffer = []
        if buffer:
            yield np.vstack(buffer)

    def _run(self) -> None:
        started = time.monotonic()
        produced = 0
        while not self.stopped:
            empty = True
            for block in self._file_blocks():
                empty = False
                if self._stop.is_set():
                    return
                self._emit(block)
                self._reports += int(block.shape[0]) * 2
                produced += int(block.shape[0])
                # Pace against the same clock every slice, so a slow filesystem
                # causes a catch-up rather than a permanent lag.
                due = started + produced / (self.fs * self.speed)
                delay = due - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
            if empty:
                self.finished = True
                return
            if not self.loop:
                self.finished = True
                return
            started = time.monotonic()
            produced = 0


# --------------------------------------------------------------------------- #
# Synthetic source
# --------------------------------------------------------------------------- #
#: Per-channel amplitude of the two things that matter: broadband noise, and the
#: 10 Hz alpha rhythm that must collapse when the eyes open.
_NOISE_UV: dict[str, float] = dict.fromkeys(CHANNELS, 24.0)
_ALPHA_UV: dict[str, float] = {
    **dict.fromkeys(CHANNELS, 4.0),
    "O1": 30.0,
    "O2": 34.0,
    "P7": 16.0,
    "P8": 16.0,
}
_THETA_UV: dict[str, float] = {
    **dict.fromkeys(CHANNELS, 4.0),
    "F3": 8.0,
    "F4": 8.0,
    "AF3": 10.0,
    "AF4": 10.0,
}
_BETA_UV: dict[str, float] = {**dict.fromkeys(CHANNELS, 3.0), "FC5": 7.0, "FC6": 7.0}
_MAINS_UV: dict[str, float] = {**dict.fromkeys(CHANNELS, 3.0), "T8": 40.0, "P8": 6.0}

# One channel with weak contact and one that is dry, so the contact logic in the
# UI is exercised by the demo rather than only by a real head.
_NOISE_UV["T7"] = 3.0
_NOISE_UV["T8"] = 18.0

#: Channels that see eye blinks, and how big they are.
_BLINK_CHANNELS = {"AF3": 130.0, "AF4": 130.0, "F7": 90.0, "F8": 90.0}

#: The theoretical standard deviation of the unit-variance noise mixture below,
#: so the per-channel amplitudes above are actually µV.
_NOISE_UNIT_STD = 1.071

ALPHA_HZ = 10.0
THETA_HZ = 6.0
BETA_HZ = 18.0
MAINS_HZ = 50.0


class SyntheticSource(ThreadedSource):
    """A plausible scalp signal, generated locally. ``mode`` is ``demo``, never ``live``."""

    mode: SourceMode = "demo"

    def __init__(self, *, out: queue.Queue[Chunk], fs: float = FS, seed: int = 7) -> None:
        super().__init__(fs=fs, out=out)
        self.label = "synthetic signal (no headset)"
        self._rng = np.random.default_rng(seed)
        self._slow = np.zeros(len(CHANNELS))
        self._mid = np.zeros(len(CHANNELS))
        self._phase = self._rng.uniform(0, 2 * np.pi, size=len(CHANNELS))
        self._phase2 = self._rng.uniform(0, 2 * np.pi, size=len(CHANNELS))
        self._phase3 = self._rng.uniform(0, 2 * np.pi, size=len(CHANNELS))
        self._phase_mains = self._rng.uniform(0, 2 * np.pi, size=len(CHANNELS))
        self._eyes_closed: bool | None = None
        self._next_blink = 1.5
        self._last_blink = -10.0
        self._index = {name: i for i, name in enumerate(CHANNELS)}

    # ------------------------------------------------------------------ control
    def set_eyes_closed(self, closed: bool | None) -> None:
        """Drive the alpha rhythm from a running flow. ``None`` restores the free schedule."""
        self._eyes_closed = closed

    @property
    def eyes_closed(self) -> bool | None:
        return self._eyes_closed

    # ---------------------------------------------------------------- synthesis
    def _alpha_gate(self, t: FloatArray) -> FloatArray:
        if self._eyes_closed is not None:
            return np.full(t.shape, 1.0 if self._eyes_closed else 0.15)
        # Left to itself, the demo subject closes their eyes for 20 s then opens
        # them for 15 s — the protocol the alpha test actually uses.
        return np.where((t % 35.0) < 20.0, 1.0, 0.15)

    def _generate(self, n: int) -> FloatArray:
        start = self._samples
        t = (start + np.arange(n)) / self.fs
        white = self._rng.standard_normal((n, len(CHANNELS)))
        gate = self._alpha_gate(t)
        out = np.empty((n, len(CHANNELS)), dtype=np.float64)

        blinking = t[-1] >= self._next_blink
        if blinking:
            self._last_blink = float(t[-1])
            self._next_blink = float(t[-1]) + 2.8 + 1.6 * float(self._rng.random())
        blink_age = t - self._last_blink

        for name in CHANNELS:
            i = self._index[name]
            slow = float(self._slow[i])
            mid = float(self._mid[i])
            for j in range(n):
                sample = white[j, i]
                slow = 0.998 * slow + 0.035 * sample
                mid = 0.90 * mid + 0.32 * sample
                out[j, i] = 0.55 * sample + 1.6 * slow + mid
            self._slow[i] = slow
            self._mid[i] = mid
            column = out[:, i] * (_NOISE_UV[name] / _NOISE_UNIT_STD)

            column += _ALPHA_UV[name] * gate * np.sin(2 * np.pi * ALPHA_HZ * t + self._phase[i])
            column += _THETA_UV[name] * np.sin(2 * np.pi * THETA_HZ * t + self._phase2[i])
            column += _BETA_UV[name] * np.sin(2 * np.pi * BETA_HZ * t + self._phase3[i])
            column += _MAINS_UV[name] * np.sin(2 * np.pi * MAINS_HZ * t + self._phase_mains[i])

            amplitude = _BLINK_CHANNELS.get(name)
            if amplitude is not None:
                window = (blink_age >= 0) & (blink_age < 0.5)
                column += np.where(
                    window,
                    amplitude * np.exp(-blink_age / 0.12) * (1 - np.exp(-blink_age / 0.015)),
                    0.0,
                )
            out[:, i] = column
        return out

    def _run(self) -> None:
        block = max(1, round(self.fs * 0.1))
        while not self.stopped:
            self._emit(self._generate(block))
            # Keep the report counter in the same ballpark as the hardware (the dongle
            # sends ~159 reports/s for ~128 EEG samples) so the header reads normally,
            # while `mode` stays honestly "demo".
            self._reports += round(block * 1.242)
            time.sleep(block / self.fs)


# --------------------------------------------------------------------------- #
def create_source(
    mode: str,
    *,
    out: queue.Queue[Chunk],
    fs: float = FS,
    highpass_hz: float = 0.5,
    replay_path: Path | None = None,
    replay_speed: float = 1.0,
    replay_loop: bool = True,
    interface: DongleInterface | None = None,
) -> SignalSource | None:
    """Build a source for ``mode``. ``None`` when the requested hardware is absent."""
    normalised = mode.strip().lower()
    if normalised == "demo":
        return SyntheticSource(out=out, fs=fs)
    if normalised == "replay":
        if replay_path is None:
            raise ValueError("replay mode needs a file to play")
        return ReplaySource(replay_path, out=out, fs=fs, speed=replay_speed, loop=replay_loop)
    if normalised == "live":
        chosen = interface or streaming_interface()
        if chosen is None:
            return None
        return LiveSource(chosen, out=out, fs=fs, highpass_hz=highpass_hz)
    return None
