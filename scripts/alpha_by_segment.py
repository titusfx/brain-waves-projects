"""Alpha by segment — the label-aware version of the alpha test.

Why this exists
---------------
`scripts/alpha_test.py --file <csv>` is NOT label-aware. For any file it does:

    seg = len(data) // 3
    parts = [data[:seg], data[seg:2*seg], data[2*seg:3*seg]]

...and then treats part 1 as "eyes closed" and part 2 as "eyes open". That is correct for the
plain prompted recording `alpha_test.py` writes itself (a fixed 20 s / 15 s / 20 s protocol,
which is why the live branch works). It is **wrong for a labelled dataset**: cutting a 245 s
session of seven alternating pairs into equal thirds produces three windows that each contain
BOTH states, which averages the effect away and can report it inverted.

On `recordings/eyes-closed-eyes-open_2026-09-13_14-56-10` — a real recording with an
unambiguous alpha effect — `alpha_test.py --file` printed `NOT DETECTED (ratio 0.73x)`.

This script reads `labels.csv` and compares every labelled segment against the others carrying
the same label, so the verdict is over the whole session rather than a 20-second slice of it.

Ports: dataset folder path (must contain `eeg.csv` and `labels.csv`)
Exit: 0 when the alpha effect is present, 1 when it is not.

    .venv\\Scripts\\python.exe scripts\\alpha_by_segment.py recordings\\<dataset folder>
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np


FS = 128.0
CHANNELS = ("O1", "O2")
BASELINE_LO, BASELINE_HI = 1.0, 45.0
ALPHA_LO, ALPHA_HI = 8.0, 12.0
# The classic "is there a peak here" measure: the alpha band against its immediate
# neighbours, which removes the 1/f slope without assuming a model for it.
FLANK_LO, FLANK_HI = 6.0, 14.0
PASS_RATIO = 1.5


def load_eeg(path: Path) -> tuple[np.ndarray, dict[str, int]]:
    """Read a dataset/window CSV. The leading `t` column is tolerated and ignored."""
    with path.open(newline="") as handle:
        reader = csv.reader(handle)
        header = [name.replace("_uV", "").strip() for name in next(reader)]
        rows = [[float(value) for value in row] for row in reader]
    return np.asarray(rows, dtype=float), {name: i for i, name in enumerate(header)}


def load_labels(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def welch(x: np.ndarray, fs: float = FS):
    """Averaged periodogram: Hann window, 2 s segments, 50% overlap."""
    n = int(2 * fs)
    if len(x) < n:
        n = len(x)
    step = max(1, n // 2)
    window = np.hanning(n)
    acc = None
    count = 0
    for start in range(0, len(x) - n + 1, step):
        spectrum = np.abs(np.fft.rfft(x[start : start + n] * window)) ** 2
        acc = spectrum if acc is None else acc + spectrum
        count += 1
    return np.fft.rfftfreq(n, 1 / fs), acc / max(count, 1)


def band(freqs, psd, lo: float, hi: float) -> float:
    return float(psd[(freqs >= lo) & (freqs < hi)].sum())


def measures(x: np.ndarray) -> tuple[float, float]:
    """(alpha share of 1-45 Hz as a percentage, alpha band vs its 6-8 + 12-14 Hz flanks)."""
    freqs, psd = welch(x)
    total = band(freqs, psd, BASELINE_LO, BASELINE_HI)
    alpha = band(freqs, psd, ALPHA_LO, ALPHA_HI)
    flanks = band(freqs, psd, FLANK_LO, ALPHA_LO) + band(freqs, psd, ALPHA_HI, FLANK_HI)
    share = 100.0 * alpha / total if total else float("nan")
    peak = alpha / flanks if flanks else float("nan")
    return share, peak


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    folder = Path(argv[0])
    eeg_path, labels_path = folder / "eeg.csv", folder / "labels.csv"
    if not eeg_path.exists() or not labels_path.exists():
        print(f"{folder} needs an eeg.csv and a labels.csv (a dataset folder, not a raw csv)")
        return 2

    print(f"analysing {folder}")
    data, index = load_eeg(eeg_path)
    segments = load_labels(labels_path)
    if not segments:
        print("labels.csv is empty — nothing to compare")
        return 2

    print(f"\n{len(data)} samples = {len(data) / FS:.1f}s @ {FS:.0f} Hz, "
          f"{len(segments)} labelled segments\n")
    header = f"{'seg':>3}  {'label':<14}" + "".join(f"{c + ' share':>10}{c + ' peak':>10}"
                                                    for c in CHANNELS)
    print(header)
    print("-" * len(header))

    rows: list[tuple[str, dict[str, tuple[float, float]]]] = []
    for segment in segments:
        start, stop = int(segment["start_sample"]), int(segment["end_sample"])
        values = {c: measures(data[start:stop, index[c]]) for c in CHANNELS if c in index}
        rows.append((segment["label"], values))
        cells = "".join(
            f"{values[c][0]:>9.1f}%{values[c][1]:>10.2f}" for c in CHANNELS if c in values
        )
        print(f"{segment['segment']:>3}  {segment['label']:<14}{cells}")

    labels = sorted({label for label, _ in rows})
    if len(labels) != 2:
        print(f"\nneed exactly two labels to compare, found {len(labels)}: {labels}")
        return 1
    closed_label = next(
        (name for name in labels if "clos" in name.lower() and "open" not in name.lower()),
        labels[0],
    )
    open_label = next(name for name in labels if name != closed_label)

    print("\n" + "=" * 60)
    print(f"AGGREGATE  {closed_label!r} vs {open_label!r}")
    print("=" * 60)
    passed = False
    for channel in CHANNELS:
        if channel not in index:
            continue
        for position, name, unit in ((0, "alpha share", "%"), (1, "alpha peak", "x")):
            closed = [v[channel][position] for label, v in rows if label == closed_label]
            opened = [v[channel][position] for label, v in rows if label == open_label]
            mean_closed = float(np.nanmean(closed))
            mean_open = float(np.nanmean(opened))
            ratio = mean_closed / mean_open if mean_open else float("nan")
            if position == 0 and ratio > PASS_RATIO:
                passed = True
            print(f"  {channel} {name:<12} {closed_label} {mean_closed:>7.2f}{unit}   "
                  f"{open_label} {mean_open:>7.2f}{unit}   ratio {ratio:.2f}x  "
                  f"({len(closed)} vs {len(opened)} segments)")

    # Pairwise consistency is the part that separates a rhythm from one lucky window: with the
    # labels alternating, every closed segment should beat the segment that follows it.
    print("\n  per-pair, on the channels above (closed vs the next open segment)")
    for channel in CHANNELS:
        if channel not in index:
            continue
        pairs = [
            (v[channel][0], rows[i + 1][1][channel][0])
            for i, (label, v) in enumerate(rows[:-1])
            if label == closed_label and rows[i + 1][0] == open_label
        ]
        if not pairs:
            continue
        wins = sum(1 for closed, opened in pairs if closed > opened)
        print(f"    {channel}: {wins} of {len(pairs)} pairs in the expected direction")

    print()
    if passed:
        print(f"  *** ALPHA CONFIRMED ***  closed/open alpha share > {PASS_RATIO}x.")
        print("  The decoded signal carries a genuine eyes-closed occipital rhythm.")
    else:
        print(f"  NOT DETECTED at the {PASS_RATIO}x threshold on " + " or ".join(CHANNELS) + ".")
        print("  Check contact before doubting the decoder: re-wet all 16 pads, references")
        print("  (CMS/DRL) first. See eeg-vault/04-sessions/2026-02-14-first-live-session.md.")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
