#!/usr/bin/env python3
"""
live_view.py - real-time raw EEG viewer for the Emotiv EPOC+ dongle.

Built to answer one question while you fiddle with electrodes:
    "is this value plausible, or is something wrong?"

It shows, live and refreshed several times a second:
  * the current value and running amplitude (std) for all 14 channels
  * a bar on a fixed 0-400 uV scale, with the NORMAL EEG RANGE (10-100 uV)
    marked, so a bar that shoots past the marker is visibly artefact
  * a plain-English status per channel (ok / HIGH / DEAD / dry)
  * mains contamination, which is the best single proxy for a dry electrode
  * scrolling waveform strips for O1/O2 (the alpha channels)

EVERY RUN IS RECORDED (no flags needed)
    recordings/live_<YYYY-MM-DD_HH-MM-SS>/
        eeg.csv      decoded microvolts, same columns as record.py, so it can be
                     analysed later with  alpha_test.py --file <that file>
        screen.txt   the numbers the viewer showed, once per refresh: amplitude,
                     current value, mains % and status per channel, plus the
                     alpha share/peak for O1/O2

    The folder is printed when the session starts and again on quit. Samples are
    written to eeg.csv as they arrive (not from the sliding display window), so
    the recording is the complete 128 Hz stream with no gaps, and both files are
    flushed on every refresh, so Ctrl-C always leaves usable files. These files
    are biometric data - never commit them (recordings/ is ignored).

REPLAY A RECORDED SESSION
    Point the viewer at a recording and it plays the stored samples back at
    128 Hz, drawing exactly the same screen, so you can watch what happened
    during a session after the headset is off:

        .venv\\Scripts\\python.exe scripts\\live_view.py --replay recordings\\live_2026-02-14_17-21-32
        .venv\\Scripts\\python.exe scripts\\live_view.py --replay alpha_test.csv --speed 4

    A folder works (it picks eeg.csv), and so does any decoded-uV CSV such as
    recordings\\eeg_*.csv or alpha_test.csv. --speed 4 plays 4x faster.

Usage:
    .venv\\Scripts\\python.exe scripts\\live_view.py
    .venv\\Scripts\\python.exe scripts\\live_view.py --window 3 --fps 6
Press Ctrl-C to quit.
"""

from __future__ import annotations

import argparse
import csv
import glob
import os
import sys
import time
from collections import deque

import numpy as np

sys.path.insert(0, "scripts")
from read_live import find_emotiv  # noqa: E402
from test_ud2016_crypto import new_crypto_key, decrypt_ecb  # noqa: E402
from decode_to_csv import CHANNELS, UV_PER_LSB, decode  # noqa: E402
from recording_paths import run_dir  # noqa: E402

FS = 128.0
HP_FC = 0.5                              # Hz, the DC-removal highpass
NORMAL_LO, NORMAL_HI = 10.0, 100.0      # uV, the "supposed range"
BAR_MAX = 400.0                          # uV, full width of the bar
BLOCKS = "▁▂▃▄▅▆▇█"


def enable_ansi() -> None:
    """Turn on VT escape processing so we can redraw the screen."""
    if os.name != "nt":
        return
    try:
        import ctypes
        k = ctypes.windll.kernel32
        h = k.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if k.GetConsoleMode(h, ctypes.byref(mode)):
            k.SetConsoleMode(h, mode.value | 0x0004)
    except Exception:
        pass
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def clear() -> None:
    sys.stdout.write("\033[H\033[J")
    sys.stdout.flush()


def bar(value: float, width: int = 46) -> str:
    """Bar on a fixed 0..BAR_MAX scale with the normal band marked."""
    marker = int(NORMAL_HI / BAR_MAX * width)
    n = int(min(max(value, 0.0), BAR_MAX) / BAR_MAX * width)
    cells = []
    for i in range(width):
        if i < n:
            cells.append("█")
        elif i == marker:
            cells.append("|")
        else:
            cells.append("·")
    if n <= marker and marker < width:
        cells[marker] = "|"
    return "".join(cells)


def status(amp: float, mains: float) -> str:
    if amp < 1.0:
        return "DEAD (no contact)"
    if mains > 60.0:
        return "DRY? (lots of mains)"
    if mains > 25.0:
        return "noisy contact"
    if amp > 200.0:
        return "!! HIGH - artefact"
    if amp > NORMAL_HI:
        return "high - check contact"
    if amp < NORMAL_LO:
        return "low (weak contact)"
    return "ok"


def sparkline(x: np.ndarray, width: int = 56, full_scale: float = 100.0) -> str:
    if len(x) == 0:
        return ""
    step = max(1, len(x) // width)
    y = x[::step][-width:]
    y = np.clip(y / full_scale, -1.0, 1.0)
    out = []
    for v in y:
        idx = int((v + 1.0) / 2.0 * (len(BLOCKS) - 1))
        out.append(BLOCKS[idx])
    return "".join(out)


def alpha_metrics(x: np.ndarray):
    """Return (alpha share of 1-45 Hz %, alpha peak ratio vs theta/beta)."""
    n = min(512, len(x))
    if n < 128:
        return 0.0, 0.0
    seg = x[-n:] - x[-n:].mean()
    P = np.abs(np.fft.rfft(seg * np.hanning(n))) ** 2
    f = np.fft.rfftfreq(n, 1 / FS)

    def bp(lo, hi):
        m = (f >= lo) & (f < hi)
        return float(P[m].sum())

    tot = bp(1.0, 45.0)
    a = bp(8.0, 12.0)
    bg = (bp(4.0, 8.0) + bp(13.0, 20.0)) / 2.0
    return (a / tot * 100.0 if tot else 0.0), (a / bg if bg else 0.0)


# --------------------------------------------------------------------------- #
class UVStream:
    """
    Raw ADC counts -> microvolts, as a CONTINUOUS stream.

    decode_to_csv.decode() runs the 0.5 Hz highpass over a whole capture at once;
    calling it per HID burst instead would restart the filter every ~0.2 s and
    stamp a step into the signal at each restart. This carries the filter state
    across bursts using the same recurrence, so the recorded stream is exactly
    what decode() would produce for the whole session, with no seams.
    """

    def __init__(self) -> None:
        self.a = float(np.exp(-2.0 * np.pi * HP_FC / FS))
        self.prev = None
        self.y = None

    def push(self, counts: np.ndarray) -> np.ndarray:
        """(n, 14) unsigned ADC counts -> (n, 14) microvolts."""
        out = np.empty(counts.shape, dtype=np.float64)
        if self.prev is None:
            self.prev = counts[0].copy()
            self.y = np.zeros(counts.shape[1], dtype=np.float64)
        for i in range(len(counts)):
            self.y = self.a * (self.y + counts[i] - self.prev)
            self.prev = counts[i].copy()
            out[i] = self.y
        return out * UV_PER_LSB


class RunRecorder:
    """Writes recordings/live_<stamp>/eeg.csv and .../screen.txt for one run."""

    def __init__(self, note: str = "") -> None:
        self.dir = run_dir("live")
        self.csv_path = os.path.join(self.dir, "eeg.csv")
        self.log_path = os.path.join(self.dir, "screen.txt")
        self.samples = 0
        self._csv = open(self.csv_path, "w", newline="", encoding="utf-8")
        self._w = csv.writer(self._csv)
        self._w.writerow([f"{c}_uV" for c in CHANNELS])
        self._log = open(self.log_path, "w", encoding="utf-8")
        self._log.write(f"live_view session  started {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        if note:
            self._log.write(f"{note}\n")
        self._log.write("eeg.csv holds decoded microvolts, 14 channels, "
                        f"'{CHANNELS[0]}_uV'... header, {FS:.0f} Hz nominal\n")
        self._log.write("one block per screen refresh follows:\n\n")

    def sample(self, rows: np.ndarray) -> None:
        """Append newly decoded (n, 14) microvolt rows, in order, exactly once."""
        for r in rows:
            self._w.writerow([f"{v:.3f}" for v in r])
            self.samples += 1

    def screen(self, block: str) -> None:
        self._log.write(block + "\n")

    def flush(self) -> None:
        self._csv.flush()
        self._log.flush()

    def close(self) -> None:
        try:
            self._log.write(f"\nsession ended {time.strftime('%Y-%m-%d %H:%M:%S')}"
                            f"  eeg samples={self.samples}"
                            f" ({self.samples / FS:.1f}s)\n")
        except Exception:
            pass
        for fh in (self._csv, self._log):
            try:
                fh.flush()
                fh.close()
            except Exception:
                pass


# --------------------------------------------------------------------------- #
def resolve_replay(spec: str) -> str:
    """Accept a CSV, or a recordings/live_* folder containing one."""
    if os.path.isdir(spec):
        preferred = os.path.join(spec, "eeg.csv")
        if os.path.exists(preferred):
            return preferred
        found = sorted(glob.glob(os.path.join(spec, "*.csv")))
        if len(found) == 1:
            return found[0]
        if not found:
            raise SystemExit(f"[!] no .csv in {spec}")
        names = ", ".join(os.path.basename(f) for f in found)
        raise SystemExit(f"[!] several .csv in {spec}; name one of: {names}")
    if not os.path.exists(spec):
        raise SystemExit(f"[!] no such file: {spec}")
    return spec


def replay_source(path: str):
    """
    Yield (14,) float microvolt rows from a recorded CSV.

    Tolerates both our own layout (14 x '{channel}_uV') and decode_to_csv.py's
    (packet_counter, quality, then the 14 channels) by matching headers, and
    falls back to the LAST 14 columns when there is no header.
    """
    with open(path, newline="", encoding="utf-8") as fh:
        r = csv.reader(fh)
        idx = None
        for line in r:
            if not line:
                continue
            if idx is None:
                if any(c.strip().endswith("_uV") for c in line):
                    idx = [i for i, c in enumerate(line) if c.strip().endswith("_uV")]
                    if len(idx) >= 14:
                        idx = idx[:14]
                        continue
                idx = list(range(max(0, len(line) - 14), len(line)))
            try:
                vals = [float(line[i]) for i in idx]
            except (ValueError, IndexError):
                continue
            if len(vals) == 14:
                yield np.array(vals, dtype=np.float64)


# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", type=float, default=2.0, help="seconds for amplitude stats")
    ap.add_argument("--fps", type=float, default=5.0, help="screen refresh rate")
    ap.add_argument("--replay", "--file", dest="replay", metavar="CSV|DIR", default=None,
                    help="replay a recording instead of reading the dongle "
                         "(a recordings/live_* folder, or any decoded-uV CSV)")
    ap.add_argument("--speed", type=float, default=1.0,
                    help="replay speed: 1.0 = real time, 4 = 4x faster")
    args = ap.parse_args()

    enable_ansi()

    h = None
    rec = None
    source = None
    stream = UVStream()
    replay_path = resolve_replay(args.replay) if args.replay else None

    if replay_path:
        source = replay_source(replay_path)
        serial = os.path.basename(replay_path)
        key = None
        print(f"replaying {replay_path} at x{args.speed:g} - Ctrl-C to quit")
    else:
        try:
            import hid
        except ImportError:
            print("pip install hidapi")
            return 2

        devs = find_emotiv(hid)
        if not devs:
            print("No Emotiv dongle found. Plug it in and re-run.")
            print("To review an earlier session instead:")
            print("  .venv\\Scripts\\python.exe scripts\\live_view.py "
                  "--replay recordings\\live_<stamp>")
            return 1
        target = next((d for d in devs if (d["product"] or "") == "EEG Signals"), devs[-1])
        serial = target["serial"]
        key = new_crypto_key(serial)

        h = hid.device()
        h.open_path(target["path"])

        rec = RunRecorder(note=f"serial {serial}  interface {target['interface']} "
                               f"({target['product']})  window={args.window:g}s")
        print(f"recording this session to {rec.dir}")
        print("  eeg.csv     decoded microvolts, the complete stream")
        print("  screen.txt  what this screen shows")
        print("(flushed every refresh, so Ctrl-C keeps them)")

    win = int(args.window * FS)
    disp = deque(maxlen=win)                # decoded (14,) microvolt rows
    spark = {c: deque(maxlen=600) for c in ("O1", "O2")}
    b1_seen = {}
    total = 0                               # HID reports seen (live)
    eeg_n = 0                               # EEG samples seen
    t0 = time.time()
    last_draw = 0.0
    waiting_since = None
    sig = None
    replay_done = False
    alpha_max = {"O1": 0.0, "O2": 0.0}
    alpha_min = {"O1": 99.0, "O2": 99.0}

    try:
        while True:
            # ------------------------------------------------ acquire data
            if source is None:
                got = False
                burst = []
                for _ in range(64):                       # drain a burst
                    data = h.read(32, 30)
                    if not data:
                        break
                    b = bytes(data[:32])
                    if len(b) != 32:
                        continue
                    got = True
                    total += 1
                    row = decrypt_ecb(key, b)
                    b1_seen[row[1]] = b1_seen.get(row[1], 0) + 1
                    if row[1] == 0x10:
                        burst.append(np.frombuffer(row, dtype=np.uint8))
                if burst:
                    counts = decode(np.array(burst, dtype=np.uint8),
                                    uv=False, remove_dc=False)["raw"]
                    uv = stream.push(counts)
                    for r in uv:
                        disp.append(r)
                    for c in ("O1", "O2"):
                        spark[c].extend(uv[:, CHANNELS.index(c)])
                    eeg_n += len(uv)
                    if rec is not None:                   # write as they arrive:
                        rec.sample(uv)                    # no display-window gaps
            else:
                due = int((time.time() - t0) * FS * args.speed)
                fed = 0
                while eeg_n < due and fed < 8192:          # keep the clock honest
                    try:
                        row = next(source)
                    except StopIteration:
                        replay_done = True
                        break
                    disp.append(row)
                    for c in ("O1", "O2"):
                        spark[c].append(row[CHANNELS.index(c)])
                    eeg_n += 1
                    fed += 1
                got = fed > 0

            now = time.time()
            if now - last_draw < 1.0 / args.fps:
                if not got:
                    time.sleep(0.005 if source is None else 0.002)
                continue
            last_draw = now

            el = now - t0

            # a correct key collapses byte1 to a handful of values (~2)
            key_ok = (len(b1_seen) <= 6) if b1_seen else None

            # ---------- analyse (the display window, newest `window` seconds) ----
            sig = np.array(disp) if len(disp) > 40 else None

            # ---------- draw ----------
            lines = []
            if source is None:
                rate = total / el if el > 0 else 0
                ktxt = "?" if key_ok is None else ("OK" if key_ok else "WRONG KEY")
                head = (f"  EMOTIV EPOC+  live raw EEG      t={el:6.1f}s   "
                        f"{rate:5.0f} reports/s   {eeg_n:6d} EEG samples   "
                        f"key={ktxt}")
                if rec is not None:
                    lines.append(f"  recording -> {rec.dir}")
            else:
                ktxt = "n/a"
                head = (f"  EMOTIV EPOC+  REPLAY  x{args.speed:g}   t={el:6.1f}s   "
                        f"{eeg_n:6d} samples"
                        f"{'   [END OF RECORDING]' if replay_done else ''}")
                lines.append(f"  file: {replay_path}")
            lines.append(head)
            lines.append("")
            lines.append("  Normal scalp EEG is 10-100 uV.  The | marker is 100 uV.")
            lines.append("  A bar shooting well past the marker = artefact, not brain.")
            lines.append("")
            lines.append("  ch      amp uV   now uV   0        100      200      300   400")
            lines.append("  " + "-" * 74)

            log_block = [f"t={el:7.1f}s  eeg_samples={eeg_n:7d}  "
                         + (f"reports/s={total / el if el > 0 else 0:5.0f}  key={ktxt}"
                            if source is None else f"replay x{args.speed:g}")]

            if sig is not None and len(sig):
                for c in CHANNELS:
                    i = CHANNELS.index(c)
                    x = sig[:, i]
                    amp = float(x.std())
                    cur = float(x[-1])
                    n = min(256, len(x))
                    seg = x[-n:] - x[-n:].mean()
                    P = np.abs(np.fft.rfft(seg * np.hanning(n))) ** 2
                    f = np.fft.rfftfreq(n, 1 / FS)
                    tot = P[(f >= 1) & (f <= 45)].sum()
                    m = (f >= 48) & (f <= 62)
                    mains = (P[m].sum() / tot * 100) if tot > 0 else 0.0
                    st = status(amp, mains)
                    lines.append(f"  {c:<5} {amp:>8.1f} {cur:>8.1f}   {bar(amp)}  {st}")
                    log_block.append(f"  {c:<4} amp={amp:>7.1f} now={cur:>8.1f} "
                                     f"mains={mains:>5.1f}%  {st}")
            else:
                lines.append("  waiting for EEG packets...")
                if waiting_since is None:
                    waiting_since = now
                lines.append("")
                lines.append(f"  no EEG data for {now - waiting_since:.0f}s "
                             f"({total} reports total)")
                lines.append("  -> see the checklist below")
                log_block.append(f"  no EEG data for {now - waiting_since:.0f}s")

            lines.append("")
            lines.append("  " + "=" * 74)
            if sig is not None and len(sig) > 128:
                lines.append("  ALPHA 8-12 Hz  --  CLOSE YOUR EYES: the share should RISE")
                lines.append("  ch   share    peak    range seen   alpha power")
                for c in ("O1", "O2"):
                    x = sig[:, CHANNELS.index(c)]
                    share, ratio = alpha_metrics(x)
                    alpha_max[c] = max(alpha_max[c], share)
                    alpha_min[c] = min(alpha_min[c], share)
                    n = int(min(share, 40.0) / 40.0 * 44)
                    b = "█" * n + "·" * (44 - n)
                    flag = ""
                    if share >= 15:
                        flag = "  <== ALPHA!"
                    elif share >= 10:
                        flag = "  <- elevated"
                    lines.append(f"  {c:<4} {share:>5.1f}% {ratio:>6.2f}  "
                                 f"{alpha_min[c]:>4.1f}-{alpha_max[c]:<4.1f}%  |{b}|{flag}")
                    log_block.append(f"  {c:<4} alpha_share={share:>5.1f}% "
                                     f"peak={ratio:>5.2f}")
                lines.append("  (peak = alpha / mean(theta,beta); >1.5 means a real peak)")
            if sig is not None and len(sig) > 10:
                for c in ("O1", "O2"):
                    lines.append(f"  {c}  +/-100 uV  {sparkline(np.array(spark[c]))}")
            else:
                lines.append("  NO DATA - checklist, in order:")
                lines.append("   1. headset switched ON (slider) and its LED lit")
                lines.append("   2. battery/power: plug the charging cable AND switch on")
                lines.append("   3. dongle LEDs: left ON, right FAST-flashing = receiving")
                lines.append("   4. headset awake, in range, paired to this dongle")
            lines.append("  " + "=" * 74)
            if replay_done:
                lines.append(f"  END OF RECORDING - {eeg_n} samples replayed")
            else:
                lines.append("  Ctrl-C to quit")

            clear()
            sys.stdout.write("\n".join(lines) + "\n")
            sys.stdout.flush()

            if rec is not None:
                rec.screen("\n".join(log_block))
                rec.flush()

            if replay_done:
                break

    except KeyboardInterrupt:
        pass
    finally:
        if h is not None:
            try:
                h.close()
            except Exception:
                pass
        if rec is not None:
            rec.close()

    # ---------------------------------------------------------------- wrap up
    if rec is not None:
        print(f"\nsession recorded: {rec.samples} EEG samples ({rec.samples / FS:.1f}s)")
        if rec.samples == 0:
            print("[!] no EEG samples were captured - only status packets arrived")
        print(f"  {rec.csv_path}")
        print(f"  {rec.log_path}")
        print("  replay it with:")
        print(f"    .venv\\Scripts\\python.exe scripts\\live_view.py --replay {rec.dir}")
    elif replay_path:
        print(f"\nreplay: {eeg_n} samples from {replay_path}"
              f"{' (complete)' if replay_done else ' (stopped early)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
