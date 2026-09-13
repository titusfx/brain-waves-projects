"""Discovery: does it find a difference that is there, and stay quiet when there is none?

Both halves matter, and the second more. An analysis that reports a finding on noise is
worse than no analysis, because it is *actionable* — you would go and build a classifier
on it. So the tests are in this order: the same signal must be found in two states, the
shuffle test must not fire on identical states, and a state with one instance must be
refused rather than scored.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from eeg_api.domain.discovery import compare, log_power_of, summarise
from eeg_api.domain.metrics import log_power_freqs, welch_log_power
from eeg_api.domain.models import CHANNELS
from eeg_api.services.library import LibraryError, RecordingLibrary
from eeg_api.services.recorder import DatasetRecorder


FS_LOCAL = 128.0
TONED = CHANNELS.index("O1")


def tone(seconds: float, hz: float, amplitude: float, rng: np.random.Generator) -> np.ndarray:
    """Broadband noise with a sine buried in it, in microvolts."""
    n = int(seconds * FS_LOCAL)
    t = np.arange(n) / FS_LOCAL
    return amplitude * np.sin(2 * np.pi * hz * t) + rng.standard_normal(n) * 8.0


def spectra(vectors: list[np.ndarray]) -> np.ndarray:
    return np.vstack([log_power_of(v, fs=FS_LOCAL) for v in vectors])


def freqs() -> np.ndarray:
    return np.asarray(log_power_freqs(fs=FS_LOCAL), dtype=np.float64)


# --------------------------------------------------------------------------- #
# The estimator
# --------------------------------------------------------------------------- #
def test_welch_averages_the_windows_it_has() -> None:
    rng = np.random.default_rng(1)
    long = tone(20.0, 10.0, 30.0, rng)
    short = tone(2.0, 10.0, 30.0, rng)
    _f_long, power_long = welch_log_power(long, fs=FS_LOCAL)
    _f_short, power_short = welch_log_power(short, fs=FS_LOCAL)
    assert len(power_long) == len(power_short)
    axis = freqs()
    at_ten = int(np.argmin(np.abs(axis - 10.0)))
    # Averaging nineteen windows instead of one makes the estimate steadier, and both
    # find the tone, so the averaged estimate is the one worth comparing classes with.
    assert power_long[at_ten] == pytest.approx(power_short[at_ten], abs=1.5)


def test_a_state_shorter_than_a_window_has_no_spectrum() -> None:
    rng = np.random.default_rng(2)
    _freqs, power = welch_log_power(tone(1.0, 10.0, 30.0, rng), fs=FS_LOCAL)
    assert power.size == 0


# --------------------------------------------------------------------------- #
# Repeatability
# --------------------------------------------------------------------------- #
def test_identical_instances_are_perfectly_repeatable() -> None:
    one = np.zeros(8)
    summary = summarise("same", np.vstack([one, one, one]))
    assert summary.n == 3
    assert summary.reliability == "ok"
    assert float(summary.sd.max()) == 0.0
    assert float(summary.stability.min()) == 1.0


def test_a_state_that_varies_between_instances_is_not_repeatable() -> None:
    rng = np.random.default_rng(4)
    noisy = rng.standard_normal((4, 8))
    summary = summarise("scattered", noisy)
    assert float(summary.sd.mean()) > 0.2
    assert float(summary.mean_stability or 1.0) < 0.8


def test_one_instance_is_reported_as_thin_not_as_certain() -> None:
    summary = summarise("lonely", np.zeros((1, 8)))
    assert summary.reliability == "single"
    assert summary.mean_stability is None
    assert summary.median_sd is None


# --------------------------------------------------------------------------- #
# Finding a difference that is there
# --------------------------------------------------------------------------- #
def test_a_buried_tone_is_found_in_the_right_bin() -> None:
    rng = np.random.default_rng(5)
    closed = spectra([tone(6.0, 10.0, 26.0, rng) for _ in range(3)])
    opened = spectra([tone(6.0, 10.0, 0.0, rng) for _ in range(3)])
    result = compare("eyes closed", closed, "eyes open", opened, freqs(), permutations=200)

    best = int(np.argmax(result.effect))
    assert 9.0 <= freqs()[best] <= 11.0, f"the biggest difference is at {freqs()[best]} Hz"
    assert result.observed_max > 2.0
    assert result.reliable
    # Three instances per state can be split 20 ways, so the p-value cannot go below
    # 1/21 however clean the separation is. The analysis reports that ceiling instead of
    # pretending the sample is bigger than it is; the next test shows what more states do.
    assert result.min_attainable_p == pytest.approx(1 / 21, abs=1e-6)
    assert result.p_value is not None and result.p_value < 0.2
    assert result.p_value >= result.min_attainable_p


def test_more_instances_can_reach_significance() -> None:
    """The same buried tone with five states each: 252 ways to split them, not 20."""
    rng = np.random.default_rng(51)
    closed = spectra([tone(6.0, 10.0, 26.0, rng) for _ in range(5)])
    opened = spectra([tone(6.0, 10.0, 0.0, rng) for _ in range(5)])
    result = compare("closed", closed, "open", opened, freqs(), permutations=400)

    assert result.min_attainable_p is not None and result.min_attainable_p < 0.01
    assert result.p_value is not None and result.p_value < 0.05


def test_the_p_ceiling_is_reported_because_it_is_often_the_answer() -> None:
    rng = np.random.default_rng(52)
    two = compare(
        "a",
        spectra([tone(4.0, 10.0, 20.0, rng) for _ in range(2)]),
        "b",
        spectra([tone(4.0, 10.0, 0.0, rng) for _ in range(2)]),
        freqs(),
        permutations=100,
    )
    # Two per state: six ways to split them, so p can never beat 1/7.
    assert two.min_attainable_p == pytest.approx(1 / 7, abs=1e-6)
    assert two.p_value is None or two.p_value >= two.min_attainable_p


def test_bins_far_from_the_difference_are_reported_as_shared() -> None:
    """The whole point: what the two states have in common cannot explain the difference."""
    rng = np.random.default_rng(6)
    closed = spectra([tone(6.0, 10.0, 26.0, rng) for _ in range(3)])
    opened = spectra([tone(6.0, 10.0, 0.0, rng) for _ in range(3)])
    result = compare("closed", closed, "open", opened, freqs(), permutations=200)

    axis = freqs()
    far = int(np.argmin(np.abs(axis - 32.0)))
    near = int(np.argmin(np.abs(axis - 10.0)))
    assert result.shared[far], "a bin with no tone in either state should be shared"
    assert not result.shared[near], "the bin carrying the difference should not be shared"
    assert result.shared.sum() > result.effect.size // 2
    assert result.shared_bins, "the shared bins should be listed, not dropped"
    assert all(bin_["shared"] for bin_ in result.shared_bins)
    assert "alpha" not in result.shared_band_names


def test_bands_carry_the_same_story_as_the_bins() -> None:
    rng = np.random.default_rng(7)
    closed = spectra([tone(6.0, 10.0, 26.0, rng) for _ in range(3)])
    opened = spectra([tone(6.0, 10.0, 0.0, rng) for _ in range(3)])
    payload = compare("closed", closed, "open", opened, freqs(), permutations=50).as_payload(
        list(freqs())
    )
    bands = {entry["band"]: entry for entry in payload["bands"]}
    assert bands["alpha"]["shared"] is False
    assert bands["alpha"]["effect"] > bands["delta"]["effect"]


def test_a_few_good_bins_beat_all_of_them() -> None:
    rng = np.random.default_rng(8)
    closed = spectra([tone(6.0, 10.0, 30.0, rng) for _ in range(3)])
    opened = spectra([tone(6.0, 10.0, 0.0, rng) for _ in range(3)])
    result = compare("closed", closed, "open", opened, freqs(), permutations=100)

    separability = result.separability
    assert separability["available"] is True
    assert separability["n_test"] == 6
    assert separability["accuracy_top_bins"] == 1.0
    # Feeding every bin to a nearest-centroid rule fits the noise; the point of the
    # readout is that picking the consistent bins first is what makes it work.
    assert (separability["accuracy_all_bins"] or 0) <= separability["accuracy_top_bins"]
    assert 10.0 in [round(value) for value in separability["bins_used"]]


# --------------------------------------------------------------------------- #
# Staying quiet when there is nothing
# --------------------------------------------------------------------------- #
def test_identical_states_are_not_reported_as_a_difference() -> None:
    rng = np.random.default_rng(9)
    a = spectra([tone(6.0, 10.0, 12.0, rng) for _ in range(3)])
    b = spectra([tone(6.0, 10.0, 12.0, rng) for _ in range(3)])
    result = compare("a", a, "b", b, freqs(), permutations=200)
    assert result.p_value is not None
    assert result.p_value > 0.05, "two samples of the same signal must not look different"
    assert result.observed_max <= result.null_p95
    # Most of the spectrum is genuinely the same in both, and the payload says how much
    # rather than listing all of it.
    assert result.shared_count == int(result.shared.sum())
    assert result.shared_count > result.effect.size // 2
    assert result.shared_fraction > 0.5
    assert len(result.shared_bins) == 10


def test_the_shuffle_test_is_not_trigger_happy() -> None:
    """Twenty draws from one distribution: at most a couple may reach p < 0.05.

    With ~110 bins scanned and three instances per class the largest difference between
    two random halves is routinely a couple of standard deviations. If this test fails,
    the p-value is decoration rather than a check.
    """
    rng = np.random.default_rng(11)
    false_positives = 0
    for trial in range(20):
        pool = [tone(4.0, 10.0, 10.0, rng) for _ in range(6)]
        vectors = spectra(pool)
        result = compare("a", vectors[:3], "b", vectors[3:], freqs(), permutations=150, seed=trial)
        if result.p_value is not None and result.p_value < 0.05:
            false_positives += 1
    assert false_positives <= 4, f"{false_positives}/20 false positives from one distribution"


def test_one_instance_per_state_cannot_be_compared() -> None:
    rng = np.random.default_rng(12)
    a = spectra([tone(4.0, 10.0, 20.0, rng)])
    b = spectra([tone(4.0, 10.0, 0.0, rng)])
    result = compare("a", a, "b", b, freqs(), permutations=100)
    assert result.reliable is False
    assert result.p_value is None
    assert result.separability["available"] is False
    assert result.separability["n_test"] == 2


# --------------------------------------------------------------------------- #
# End to end, over a real dataset on disk
# --------------------------------------------------------------------------- #
@pytest.fixture
def spectral_dataset(tmp_path: Path) -> tuple[RecordingLibrary, str]:
    """Three 4-second 'eyes closed' states carrying a 10 Hz tone in O1, three without.

    Only O1 has the tone, so the per-channel ranking has one right answer to find. The
    last state is a half-second fragment, which the analysis must exclude rather than
    average into a class.
    """
    recorder = DatasetRecorder(tmp_path, "spectral", fs=FS_LOCAL)
    recorder.begin(0.0)
    rng = np.random.default_rng(13)
    total = int(24.5 * FS_LOCAL)
    t = np.arange(total) / FS_LOCAL
    data = rng.standard_normal((total, len(CHANNELS))) * 8.0

    for cycle in range(3):
        start = cycle * 8.0
        closed = (t >= start) & (t < start + 4.0)
        data[closed, TONED] += 28.0 * np.sin(2 * np.pi * 10.0 * t[closed])
        recorder.request_open(start, "eyes closed", cycle=cycle, step_index=0)
        recorder.request_close(start + 4.0)
        recorder.request_open(start + 4.0, "eyes open", cycle=cycle, step_index=1)
        recorder.request_close(start + 8.0)

    # A fragment: long enough to be a state, too short to analyse.
    recorder.request_open(24.0, "eyes open", cycle=3, step_index=1)
    recorder.request_close(24.5, truncated=True)

    recorder.append(data, t0=0.0)
    recorder.finalize(discard_tail=0, outcome="completed")
    return RecordingLibrary(tmp_path, fs=FS_LOCAL), recorder.dir.name


def test_discovery_over_a_real_dataset(spectral_dataset) -> None:
    library, entry_id = spectral_dataset
    result = library.discover(
        entry_id,
        channel="O1",
        labels=["eyes closed", "eyes open"],
        permutations=200,
        min_seconds=2.0,
    )

    assert result["channel"] == "O1"
    assert result["labels"] == ["eyes closed", "eyes open"]
    assert result["analysed_labels"] == ["eyes closed", "eyes open"]

    classes = {entry["label"]: entry for entry in result["classes"]}
    assert classes["eyes closed"]["summary"]["n"] == 3
    assert classes["eyes open"]["summary"]["n"] == 3
    assert len(classes["eyes closed"]["instances"]) == 3

    comparison = result["comparison"]
    assert comparison["label_a"] == "eyes closed"
    assert comparison["label_b"] == "eyes open"
    axis = np.asarray(comparison["freqs"])
    best = axis[int(np.argmax(comparison["effect"]))]
    assert 9.0 <= best <= 11.0, f"the difference was found at {best} Hz"
    # Three states a side cannot reach 0.05; the ceiling is reported so the number is
    # read as "not enough states yet" rather than "no effect".
    assert comparison["p_value"] < 0.2
    # Rounded to four decimals on the way out, hence the tolerance.
    assert comparison["min_attainable_p"] == pytest.approx(1 / 21, abs=1e-4)
    assert comparison["separability"]["accuracy_top_bins"] == 1.0

    # The tone is the same every time, so 'closed' is the more repeatable state *at the
    # bin carrying it* — which is the per-bin stability curve's job, not the average's.
    alpha = int(np.argmin(np.abs(axis - 10.0)))
    closed_stability = np.asarray(classes["eyes closed"]["summary"]["stability"])[alpha]
    open_stability = np.asarray(classes["eyes open"]["summary"]["stability"])[alpha]
    assert closed_stability > open_stability
    assert "alpha" not in comparison["shared_band_names"]

    # Only O1 carries the tone, so it should be the channel that separates the states.
    assert result["channel_ranking"][0]["channel"] == "O1"

    # The fragment was left out, and the analysis says so.
    assert len(result["excluded"]) == 1
    assert "shorter than" in result["excluded"][0]["reason"]


def test_discovery_can_use_only_some_instances(spectral_dataset) -> None:
    library, entry_id = spectral_dataset
    result = library.discover(
        entry_id,
        channel="O1",
        labels=["eyes closed", "eyes open"],
        instances={"eyes closed": [0], "eyes open": [1]},
        permutations=0,
        min_seconds=2.0,
    )
    classes = {entry["label"]: entry for entry in result["classes"]}
    assert classes["eyes closed"]["summary"]["n"] == 1
    assert classes["eyes open"]["summary"]["n"] == 1
    assert result["comparison"]["reliable"] is False
    assert result["comparison"]["p_value"] is None


def test_discovery_reorders_the_labels_to_what_was_asked(spectral_dataset) -> None:
    library, entry_id = spectral_dataset
    result = library.discover(
        entry_id,
        channel="O1",
        labels=["eyes open", "eyes closed"],
        permutations=0,
    )
    assert result["comparison"]["label_a"] == "eyes open"
    assert result["comparison"]["label_b"] == "eyes closed"


def test_discovery_refuses_a_recording_with_no_labels(tmp_path: Path) -> None:
    recorder = DatasetRecorder(tmp_path, "unlabelled", fs=FS_LOCAL)
    recorder.begin(0.0)
    recorder.request_open(0.0, "labelled", step_index=0)
    recorder.request_close(1.0)
    recorder.append(np.zeros((int(FS_LOCAL), len(CHANNELS))), t0=0.0)
    recorder.finalize(discard_tail=0)
    library = RecordingLibrary(tmp_path, fs=FS_LOCAL)

    # A flat recording has labels but no signal, so it fails on the signal instead.
    with pytest.raises(LibraryError):
        library.discover(recorder.dir.name, channel="O1", labels=["labelled"], min_seconds=2.0)


def test_discovery_reports_states_that_are_too_short(spectral_dataset) -> None:
    library, entry_id = spectral_dataset
    with pytest.raises(LibraryError, match="no state long enough"):
        library.discover(
            entry_id,
            channel="O1",
            labels=["eyes closed"],
            instances={"eyes closed": []},
            min_seconds=2.0,
        )
