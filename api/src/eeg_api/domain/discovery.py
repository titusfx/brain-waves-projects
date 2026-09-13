"""Discovery: what repeats within a state, and what actually separates two states.

This answers the question you ask after labelling a dataset — *is there anything here
that tells these two states apart, or am I looking at noise?* — and it is built in the
order that question is actually asked.

**Within a state (repeatability).** For one label, take every instance of it and compare
the instances to each other. Frequency bins where the instances agree are the signature
of that state. Bins where they disagree cannot be leaned on, however striking a single
instance looks, and saying so is the whole value of having more than one instance.

**Between states (discrimination).** For two labels, ask at each frequency bin whether
the gap between the class means is larger than the spread *within* the classes. A bin
where the two states differ by less than their own scatter is **shared**: it is the same
in both, so it cannot explain the difference. Those bins are reported explicitly, under
"shared", rather than quietly dropped — they are the ones that look like findings in a
single-instance comparison and mean nothing.

**And the part that keeps it honest.** Scanning ~110 frequency bins for the largest
difference will find one by chance, especially with three instances per class. So the
largest observed effect is compared against a null distribution built by shuffling the
labels: *"the biggest difference you see is X; shuffling the labels reaches X or more in
p of trials"*. With a handful of segments that p is normally unimpressive, which is the
correct answer, and far better than a number presented as a discovery.

Nothing here trains a model or claims to decode anything. It measures whether the
labelled instances of a state resemble each other more than they resemble another state,
and it reports how much of that could be luck.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import comb
from typing import Any

import numpy as np
from numpy.typing import NDArray

from eeg_api.domain.metrics import welch_log_power
from eeg_api.domain.models import BANDS, FS, FloatArray


#: Periodogram window for the analysis, in samples (2 s at 128 Hz). Two seconds resolves
#: 0.5 Hz, which separates the alpha band from its neighbours; the averaging over
#: overlapping windows is what supplies the statistical stability, not the window length.
WELCH_N = 256

#: Floor on the pooled within-class spread, in decades of power. Two classes with
#: identical instances would otherwise divide by zero, and a single instance has no
#: spread at all — which :func:`compare` reports as unreliable rather than as an
#: infinitely large effect.
SPREAD_FLOOR = 0.05

#: An effect below this means the classes differ by less than their own scatter, i.e.
#: the bin is the same in both. That is 1.0 by construction of the effect size: it is
#: measured in units of the pooled within-class standard deviation.
SHARED_EFFECT = 1.0

#: How many bins to report in each list. The screen has room for a ranking, not a table.
TOP_BINS = 10

#: Frequency bins used by the separability readout. Five is deliberately small: with six
#: segments, a classifier fed 110 bins will fit the noise, and the point of the readout
#: is to show that a *few* consistent bins do better than all of them.
SEPARATOR_BINS = 5


@dataclass(frozen=True, slots=True)
class SegmentFeatures:
    """One instance of a state: its spectrum, its band shares, and its opening seconds."""

    index: int
    label: str
    cycle: int
    step_index: int
    start_time: float
    end_time: float
    duration: float
    samples: int
    #: log10 mean power per frequency bin (1-45 Hz).
    log_power: FloatArray
    bands: dict[str, float]
    #: Microvolts from the start of the state, decimated for drawing.
    trace: FloatArray
    #: Decimation factor applied to the trace, so the axis can be labelled in seconds.
    trace_step: int

    def as_payload(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "label": self.label,
            "cycle": self.cycle,
            "step_index": self.step_index,
            "start_time": round(self.start_time, 3),
            "end_time": round(self.end_time, 3),
            "duration": round(self.duration, 3),
            "samples": self.samples,
            "log_power": [round(float(v), 4) for v in self.log_power],
            "bands": {k: round(v, 2) for k, v in self.bands.items()},
            "trace": [round(float(v), 2) for v in self.trace],
            "trace_step": self.trace_step,
        }


@dataclass(frozen=True, slots=True)
class ClassSummary:
    """Every instance of one label, and how much they agree with each other."""

    label: str
    n: int
    mean: FloatArray
    sd: FloatArray
    #: Per bin: how repeatable this state is, 0-1. 1 means the instances are identical.
    stability: FloatArray

    @property
    def reliability(self) -> str:
        if self.n < 2:
            return "single"
        if self.n < 3:
            return "thin"
        return "ok"

    @property
    def mean_stability(self) -> float | None:
        """Average repeatability across the whole spectrum. A summary, not a verdict."""
        if self.n < 2:
            return None
        return round(float(self.stability.mean()), 3)

    @property
    def median_sd(self) -> float | None:
        """Typical spread between instances, in decades of power."""
        if self.n < 2:
            return None
        return round(float(np.median(self.sd)), 4)

    def as_payload(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "n": self.n,
            "reliability": self.reliability,
            "mean": [round(float(v), 4) for v in self.mean],
            "sd": [round(float(v), 4) for v in self.sd],
            "stability": [round(float(v), 3) for v in self.stability],
            "mean_stability": self.mean_stability,
            "median_sd": self.median_sd,
        }


@dataclass(frozen=True, slots=True)
class Comparison:
    """Two labels, bin by bin: where they differ, and where they are the same."""

    label_a: str
    label_b: str
    n_a: int
    n_b: int
    effect: FloatArray
    shared: NDArray[np.bool_]
    #: How many bins are the same in both states — the part that cannot explain the
    #: difference. ``shared_bins`` lists the most-equal few; this is the total.
    shared_count: int
    shared_fraction: float
    #: False when either class has a single instance: with no within-class spread there
    #: is nothing to measure a difference against, and any effect would be meaningless.
    reliable: bool
    observed_max: float
    null_p95: float
    p_value: float | None
    permutations: int
    #: The smallest p this test could possibly produce, given how many ways the instances
    #: can be split. With three per state there are 20 arrangements, so nothing can come
    #: out below ~0.048 however clean the separation looks — which is the answer to "why
    #: is my obvious difference not significant?".
    min_attainable_p: float | None
    top_bins: list[dict[str, Any]]
    shared_bins: list[dict[str, Any]]
    shared_band_names: list[str]
    separability: dict[str, Any]

    def as_payload(self, freqs: list[float]) -> dict[str, Any]:
        return {
            "label_a": self.label_a,
            "label_b": self.label_b,
            "n_a": self.n_a,
            "n_b": self.n_b,
            "reliable": self.reliable,
            "effect": [round(float(v), 3) for v in self.effect],
            "shared": [bool(v) for v in self.shared],
            "shared_count": self.shared_count,
            "shared_fraction": round(self.shared_fraction, 3),
            "observed_max_effect": round(self.observed_max, 3),
            "null_p95_effect": round(self.null_p95, 3),
            "p_value": None if self.p_value is None else round(self.p_value, 4),
            "permutations": self.permutations,
            "min_attainable_p": (
                None if self.min_attainable_p is None else round(self.min_attainable_p, 4)
            ),
            "top_bins": self.top_bins,
            "shared_bins": self.shared_bins,
            "shared_band_names": self.shared_band_names,
            "bands": _band_effects(self.effect, np.asarray(freqs, dtype=np.float64)),
            "separability": self.separability,
            "freqs": freqs,
        }


# --------------------------------------------------------------------------- #
# Within one state
# --------------------------------------------------------------------------- #
def summarise(label: str, vectors: FloatArray) -> ClassSummary:
    """Summarise the instances of one label: mean, spread, and repeatability per bin."""
    n = int(vectors.shape[0])
    mean = vectors.mean(axis=0) if n else np.zeros(0)
    sd = vectors.std(axis=0, ddof=1) if n > 1 else np.zeros(vectors.shape[1] if n else 0)
    # Stability as a bounded score rather than a coefficient of variation, which blows up
    # when a class mean sits near zero: 0.5 decades of spread (a factor of three in power)
    # scores 0.5, and identical instances score 1.
    stability = 1.0 / (1.0 + sd / 0.5) if n > 1 else np.zeros_like(mean)
    return ClassSummary(label=label, n=n, mean=mean, sd=sd, stability=stability)


# --------------------------------------------------------------------------- #
# Between two states
# --------------------------------------------------------------------------- #
def _effects(a: FloatArray, b: FloatArray) -> FloatArray:
    """Per-bin standardised difference between two groups of spectra."""
    if a.shape[0] == 0 or b.shape[0] == 0:
        return np.zeros(0)
    mu_a, mu_b = a.mean(axis=0), b.mean(axis=0)
    var_a = a.var(axis=0, ddof=1) if a.shape[0] > 1 else np.zeros(a.shape[1])
    var_b = b.var(axis=0, ddof=1) if b.shape[0] > 1 else np.zeros(b.shape[1])
    pooled = np.sqrt((var_a + var_b) / 2.0)
    return np.abs(mu_a - mu_b) / np.maximum(pooled, SPREAD_FLOOR)


def _centroid_accuracy(
    a: FloatArray, b: FloatArray, bins: NDArray[np.int_] | slice
) -> float | None:
    """Leave-one-out nearest-centroid accuracy on the given bins.

    Transparent on purpose: there is no model to trust, just "which class mean is this
    instance closer to, when it is not part of the mean". Reported next to the number of
    segments it was computed from, because with six segments one right answer is worth
    seventeen percent.
    """
    pooled = np.vstack([a, b])
    labels = np.array([0] * a.shape[0] + [1] * b.shape[0])
    if pooled.shape[0] < 3 or a.shape[0] == 0 or b.shape[0] == 0:
        return None
    correct = 0
    for i in range(pooled.shape[0]):
        rest = np.delete(pooled, i, axis=0)
        rest_labels = np.delete(labels, i)
        own, other = labels[i], 1 - labels[i]
        if not ((rest_labels == own).any() and (rest_labels == other).any()):
            return None
        centre_own = rest[rest_labels == own][:, bins].mean(axis=0)
        centre_other = rest[rest_labels == other][:, bins].mean(axis=0)
        point = pooled[i, bins]
        if np.linalg.norm(point - centre_own) <= np.linalg.norm(point - centre_other):
            correct += 1
    return float(correct) / float(int(pooled.shape[0]))


def _band_effects(effect: FloatArray, freqs: FloatArray) -> list[dict[str, Any]]:
    """Aggregate the per-bin effect into the named bands, as a summary."""
    out: list[dict[str, Any]] = []
    for name, lo, hi in BANDS:
        mask = (freqs >= lo) & (freqs < hi)
        if not mask.any():
            continue
        out.append(
            {
                "band": name,
                "effect": round(float(effect[mask].mean()), 3),
                "max_effect": round(float(effect[mask].max()), 3),
                "shared": bool(effect[mask].mean() < SHARED_EFFECT),
            }
        )
    return out


def compare(
    label_a: str,
    a: FloatArray,
    label_b: str,
    b: FloatArray,
    freqs: FloatArray,
    *,
    permutations: int = 200,
    seed: int = 7,
) -> Comparison:
    """Compare two labels bin by bin, with a permutation test on the largest effect."""
    effect = _effects(a, b)
    reliable = a.shape[0] >= 2 and b.shape[0] >= 2
    shared = effect < SHARED_EFFECT
    shared_count = int(shared.sum())
    shared_fraction = shared_count / effect.size if effect.size else 0.0

    observed = float(effect.max()) if effect.size else 0.0
    p_value: float | None = None
    null_p95 = 0.0

    # How small a p this test can even produce: the instances can only be split
    # C(n_a + n_b, n_a) ways, and the p-value is a rank among those arrangements. Three
    # per state is 20 ways, so the floor is 1/21 - meaning a *perfect* separation of six
    # three-a-side instances still cannot clear 0.05 convincingly. Worth saying out loud,
    # because the alternative is an operator concluding their effect is not real when the
    # real problem is that they recorded three states.
    min_attainable_p = (
        1.0 / (comb(int(a.shape[0] + b.shape[0]), int(a.shape[0])) + 1) if reliable else None
    )

    if reliable and permutations > 0 and effect.size:
        pooled = np.vstack([a, b])
        sizes = (a.shape[0], b.shape[0])
        rng = np.random.default_rng(seed)
        null = np.empty(permutations, dtype=np.float64)
        for k in range(permutations):
            order = rng.permutation(pooled.shape[0])
            null[k] = float(_effects(pooled[order[: sizes[0]]], pooled[order[sizes[0] :]]).max())
        null_p95 = float(np.percentile(null, 95))
        # +1 on both sides: the observed arrangement is itself one of the possible ones,
        # so a p of exactly 0 is not attainable from a finite number of shuffles.
        p_value = float((1 + int((null >= observed).sum())) / (permutations + 1))

    order = np.argsort(effect)[::-1] if effect.size else np.zeros(0, dtype=int)
    top_bins = [
        {
            "frequency": round(float(freqs[i]), 2),
            "effect": round(float(effect[i]), 3),
            "mean_a": round(float(a[:, i].mean()), 3),
            "mean_b": round(float(b[:, i].mean()), 3),
            "shared": bool(shared[i]),
        }
        for i in order[:TOP_BINS]
    ]

    # The bins that are the *same* in both states: the ones that cannot explain a
    # difference, and the reason a single-instance comparison misleads.
    same = np.where(shared)[0] if effect.size else np.zeros(0, dtype=int)
    shared_bins = [
        {
            "frequency": round(float(freqs[i]), 2),
            "effect": round(float(effect[i]), 3),
            "mean_a": round(float(a[:, i].mean()), 3),
            "mean_b": round(float(b[:, i].mean()), 3),
            "shared": True,
        }
        for i in same[np.argsort(effect[same])][:TOP_BINS]
    ]
    shared_band_names = [band["band"] for band in _band_effects(effect, freqs) if band["shared"]]

    # Always the complete shape, so the response model can require every field instead of
    # hiding "this dataset is too small to say" behind a missing key.
    separability: dict[str, Any] = {
        "available": False,
        "n_test": int(a.shape[0] + b.shape[0]),
        "chance": 0.5,
        "bins_used": [],
        "accuracy_top_bins": None,
        "accuracy_all_bins": None,
    }
    if reliable and effect.size > SEPARATOR_BINS:
        chosen = order[:SEPARATOR_BINS]
        top_accuracy = _centroid_accuracy(a, b, chosen)
        all_accuracy = _centroid_accuracy(a, b, slice(None))
        separability = {
            "available": top_accuracy is not None,
            "n_test": int(a.shape[0] + b.shape[0]),
            "chance": 0.5,
            "bins_used": [round(float(freqs[i]), 2) for i in chosen],
            "accuracy_top_bins": None if top_accuracy is None else round(top_accuracy, 3),
            "accuracy_all_bins": None if all_accuracy is None else round(all_accuracy, 3),
        }

    return Comparison(
        label_a=label_a,
        label_b=label_b,
        n_a=int(a.shape[0]),
        n_b=int(b.shape[0]),
        effect=effect,
        shared=shared,
        shared_count=shared_count,
        shared_fraction=shared_fraction,
        reliable=reliable,
        observed_max=observed,
        null_p95=null_p95,
        p_value=p_value,
        permutations=permutations,
        min_attainable_p=min_attainable_p,
        top_bins=top_bins,
        shared_bins=shared_bins,
        shared_band_names=shared_band_names,
        separability=separability,
    )


def band_effects(effect: FloatArray, freqs: FloatArray) -> list[dict[str, Any]]:
    """Public form of :func:`_band_effects`, for the API payload."""
    return _band_effects(effect, freqs)


def log_power_of(x: FloatArray, fs: float = FS) -> FloatArray:
    """The analysis feature for one state, or an empty array if it is too short."""
    _freqs, log_power = welch_log_power(x, fs=fs, n=WELCH_N)
    return log_power
