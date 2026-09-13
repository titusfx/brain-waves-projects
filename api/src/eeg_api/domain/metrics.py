"""Signal analysis — the numbers the monitor displays.

This is a faithful port of the analysis in ``scripts/live_view.py``, deliberately
so: the browser and the terminal must not disagree about whether an electrode is
dry. Nothing here is a clinical measure. Amplitude, mains contamination and
relative band power are *contact and quality* indicators.
"""

from __future__ import annotations

import numpy as np

from eeg_api.domain.models import (
    BANDS,
    CHANNELS,
    FS,
    MAINS_HI_HZ,
    MAINS_LO_HZ,
    NORMAL_HI_UV,
    NORMAL_LO_UV,
    STATUS_ARTEFACT,
    STATUS_DEAD,
    STATUS_DRY,
    STATUS_HIGH,
    STATUS_LOW,
    STATUS_OK,
    ChannelMetrics,
    FloatArray,
)


#: FFT length for the per-channel spectrum. 256 samples is 2 s at 128 Hz, which
#: is the shortest window that still resolves 8-12 Hz alpha from its neighbours.
FFT_N: int = 256

#: Below this, the channel is not measuring anything.
DEAD_UV: float = 1.0
#: Above this, the channel is measuring muscle or movement, not brain.
ARTEFACT_UV: float = 200.0


def _spectrum(x: FloatArray) -> tuple[FloatArray, FloatArray]:
    """Hann-windowed power spectrum of the newest up-to-``FFT_N`` samples."""
    n = int(min(FFT_N, len(x)))
    if n < 64:
        return np.zeros(1), np.zeros(1)
    seg = np.asarray(x[-n:], dtype=np.float64)
    seg = seg - seg.mean()
    power = np.abs(np.fft.rfft(seg * np.hanning(n))) ** 2
    freqs = np.fft.rfftfreq(n, 1.0 / FS)
    return freqs, power


def band_powers(x: FloatArray) -> dict[str, float]:
    """Each band as a percentage of 1-45 Hz total power."""
    freqs, power = _spectrum(x)
    if len(freqs) < 2:
        return dict.fromkeys((name for name, _, _ in BANDS), 0.0)
    total = float(power[(freqs >= 1.0) & (freqs <= 45.0)].sum())
    if total <= 0:
        return dict.fromkeys((name for name, _, _ in BANDS), 0.0)
    out: dict[str, float] = {}
    for name, lo, hi in BANDS:
        mask = (freqs >= lo) & (freqs < hi)
        out[name] = float(power[mask].sum()) / total * 100.0
    return out


def alpha_metrics(x: FloatArray) -> tuple[float, float]:
    """Return ``(alpha share of 1-45 Hz %, alpha peak ratio vs theta/beta)``.

    The peak ratio is the number the alpha test's verdict uses: above **1.5** on
    O1/O2 with the eyes closed is a real alpha rhythm rather than broadband noise.
    """
    freqs, power = _spectrum(x)
    if len(freqs) < 2:
        return 0.0, 0.0

    def band(lo: float, hi: float) -> float:
        return float(power[(freqs >= lo) & (freqs < hi)].sum())

    total = band(1.0, 45.0)
    alpha = band(8.0, 12.0)
    background = (band(4.0, 8.0) + band(13.0, 20.0)) / 2.0
    share = alpha / total * 100.0 if total > 0 else 0.0
    peak = alpha / background if background > 0 else 0.0
    return share, peak


def mains_percent(x: FloatArray) -> float:
    """Power in 48-62 Hz as a percentage of 1-45 Hz — the best dry-electrode proxy."""
    freqs, power = _spectrum(x)
    if len(freqs) < 2:
        return 0.0
    total = float(power[(freqs >= 1.0) & (freqs <= 45.0)].sum())
    if total <= 0:
        return 0.0
    return float(power[(freqs >= MAINS_LO_HZ) & (freqs <= MAINS_HI_HZ)].sum()) / total * 100.0


def status_for(amplitude_uv: float, mains: float) -> str:
    """Plain-English verdict for one channel, in ``live_view.py``'s vocabulary."""
    if amplitude_uv < DEAD_UV:
        return STATUS_DEAD
    if mains > 60.0:
        return STATUS_DRY
    if amplitude_uv > ARTEFACT_UV:
        return STATUS_ARTEFACT
    if amplitude_uv > NORMAL_HI_UV:
        return STATUS_HIGH
    if amplitude_uv < NORMAL_LO_UV:
        return STATUS_LOW
    return STATUS_OK


def channel_metrics(window: FloatArray) -> list[ChannelMetrics]:
    """Per-channel amplitude / current value / mains / bands over ``window``.

    ``window`` is ``(n, 14)`` microvolts, newest sample last.
    """
    out: list[ChannelMetrics] = []
    if window.ndim != 2 or window.shape[1] != len(CHANNELS):
        return out
    for i, name in enumerate(CHANNELS):
        x = np.asarray(window[:, i], dtype=np.float64)
        amplitude = float(x.std()) if len(x) > 1 else 0.0
        current = float(x[-1]) if len(x) else 0.0
        mains = mains_percent(x)
        out.append(
            ChannelMetrics(
                name=name,
                amplitude_uv=amplitude,
                current_uv=current,
                mains_percent=mains,
                status=status_for(amplitude, mains),
                bands=band_powers(x),
            )
        )
    return out


def contact_score(metrics: list[ChannelMetrics]) -> dict[str, object]:
    """A one-line summary of the montage, for the status bar."""
    total = len(metrics) or 1
    ok = sum(1 for m in metrics if m.status == STATUS_OK)
    dead = [m.name for m in metrics if m.status == STATUS_DEAD]
    dry = [m.name for m in metrics if m.status == STATUS_DRY]
    bad = [m.name for m in metrics if m.status in {STATUS_DRY, STATUS_ARTEFACT, STATUS_DEAD}]
    return {
        "ok": ok,
        "total": len(metrics),
        "ok_fraction": ok / total,
        "dead": dead,
        "dry": dry,
        "problem_channels": bad,
    }


def spectrogram_row(x: FloatArray) -> list[float]:
    """A single log-scaled spectrum row, for the per-channel detail view."""
    freqs, power = _spectrum(x)
    if len(freqs) < 2:
        return []
    mask = (freqs >= 1.0) & (freqs <= 45.0)
    return [round(float(v), 6) for v in np.log10(power[mask] + 1e-12)]


def spectrum_freqs() -> list[float]:
    """The frequency axis matching :func:`spectrogram_row`."""
    freqs = np.fft.rfftfreq(FFT_N, 1.0 / FS)
    mask = (freqs >= 1.0) & (freqs <= 45.0)
    return [round(float(v), 3) for v in freqs[mask]]
