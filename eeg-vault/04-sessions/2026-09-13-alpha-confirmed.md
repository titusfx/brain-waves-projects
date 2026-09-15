---
title: "Session 2026-09-13 — Alpha Confirmed"
type: session
result: ✅ ALPHA CONFIRMED — the decoded signal is a real brain
tags: [session, results, alpha-test, milestone, contact-quality]
updated: 2026-09-15
---

# Session 2026-09-13 — Alpha Confirmed

**The last substantive open item in the project is closed.** With all pads wetted, the
eyes-closed alpha rhythm appears over O1 exactly as physiology requires, and it is not a
marginal result.

```
dataset   recordings/eyes-closed-eyes-open_2026-09-13_14-56-10
source    live  ·  dongle UD20180927003B78 · EEG Signals
flow      eyes closed 20 s / eyes open 15 s, looping · 7 cycles kept
length    31 338 samples = 244.8 s @ 128 Hz · 14 labelled segments · 0 dropped chunks
```

## The result

| | eyes closed | eyes open | ratio |
| --- | --- | --- | --- |
| **O1** alpha share (8–12 Hz of 1–45 Hz) | **16.28 %** | **5.89 %** | **2.76×** |
| **O1** alpha peak (8–12 vs 6–8 + 12–14 Hz) | **1.83×** | **1.07×** | **1.72×** |
| O2 alpha share | 8.37 % | 6.34 % | 1.32× |
| O2 alpha peak | 1.81× | 1.41× | 1.29× |

Mean over **all seven** segments of each label, not a selected window. The pass criterion is
> 1.5 on O1 or O2, and O1 clears it on both measures.

### The consistency is what makes it convincing

Every eyes-closed segment beats the eyes-open segment that follows it — **on both channels**:

| cycle | O1 closed → open | O2 closed → open |
| --- | --- | --- |
| 0 | 10.2 % → 2.2 % | 5.0 % → 4.6 % |
| 1 | 7.4 % → 6.4 % | 5.7 % → 5.4 % |
| 2 | 23.8 % → 6.1 % | 8.8 % → 6.4 % |
| 3 | 22.2 % → 4.7 % | 9.2 % → 5.9 % |
| 4 | 16.8 % → 9.6 % | 10.7 % → 8.3 % |
| 5 | 14.9 % → 4.3 % | 9.3 % → 6.3 % |
| 6 | 18.6 % → 7.8 % | 9.9 % → 7.6 % |

**7 of 7 on O1, 7 of 7 on O2.** A chance fluctuation does not do that. O2 does not reach the
1.5× threshold in magnitude (1.32×) but its direction is unanimous, so this reads as an
uneven fit rather than an absent effect — the right occipital pad is presumably making poorer
contact than the left.

## Why this session worked when 2026-02-14 did not

Same decoder, same dongle, same code. The only change was the contacts.

| | 2026-02-14 ✗ | 2026-09-13 ✓ |
| --- | --- | --- |
| pads wetted | 8 of 16 | **16 of 16** |
| O1 amplitude | 20 µV | **45.8 µV** |
| O1 mains contamination | **29.7 %** | **0.1 %** |
| O2 amplitude | 14 µV | **54.1 µV** |
| O2 mains contamination | **46.9 %** | **0.1 %** |
| alpha peak ratio (occipital) | 0.52 | **1.83×** |
| verdict | NOT DETECTED | **ALPHA CONFIRMED** |

Mains falling from ~30–47 % to 0.1 % is the whole story: a floating electrode acts as an
antenna, and a saturated common-mode reference spreads that artefact across every channel.
This is the confirmation of the prediction in [[2026-02-14-first-live-session]] — the fault
was contact, never the decoder.

## ⚠️ `alpha_test.py --file` gives a FALSE NEGATIVE on a labelled dataset

Run on this same recording it prints `NOT DETECTED (ratio 0.73x)` — the opposite of the truth.
The cause is in `main()`:

```python
if "--file" in sys.argv:
    n = len(data)
    seg = n // 3
    parts = [data[:seg], data[seg:2*seg], data[2*seg:3*seg]]
    labels = ["segment 1", "segment 2", "segment 3"]
```

`--file` **never reads `labels.csv`**. It cuts the file into three equal thirds and treats
part 1 as eyes-closed and part 2 as eyes-open. That is correct for the plain prompted recording
`alpha_test.py` writes itself — a fixed 20/15/20 s protocol — and wrong for a dataset: a third
of a 245 s session containing seven alternating pairs holds *both* states, so the comparison is
between two mixtures and the sign can come out either way.

**Consequence for the record:** the 2026-02-14 negative verdict was reached the same way, and
that session genuinely *was* negative (its channels were at 200–280 µV with O1/O2 at 14–20 µV
against 30–47 % mains, which is independently damning). So the earlier conclusion stands — but
it was corroborated by the channel-health table, not by the segment ratio, which was not
measuring what it appeared to measure.

The label-aware replacement is `scripts/alpha_by_segment.py`, which walks every labelled
segment and reports consistency across pairs.

## Reproduce

```powershell
.venv\Scripts\python.exe scripts\alpha_by_segment.py recordings\eyes-closed-eyes-open_2026-09-13_14-56-10
```

Prints the per-segment table, the aggregate ratios and the 7-of-7 pairwise check; exits 0 on a
pass. Read-only — it writes nothing, and the recording stays in `recordings/`, which is
git-ignored because it is biometric data.

## Caveats and what is still open

- **Frontotemporal amplitudes are still high** — F7 393 µV, T7 471 µV, AF3 194 µV, F4 175 µV
  against O1/O2 at 46–54 µV. Sustained values that large over the temporalis are most likely
  EMG (jaw/neck), not brain. It does not touch the occipital alpha result, but it means the
  frontal channels should not be used for anything quantitative yet.
- **P8 is the worst contact** at 6.3 % mains — still "ok", but it is the channel to check next.
- **O2 needs a better seat**; see the 1.32× above.
- **One subject, one session.** "Alpha appears with eyes closed" is now established for this
  person on this unit. It is not a claim about the population, and it is not a clinical result.
- Battery and gyro remain undecoded, and neither blocks anything here.

## Related
[[2026-02-14-first-live-session]] · [[ud2016-crypto-crack]] · [[roadmap]] · [[web-workbench]]
