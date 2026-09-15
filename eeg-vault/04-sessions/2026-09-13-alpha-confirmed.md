---
title: "Session 2026-09-13 — Alpha Confirmed"
type: session
result: ✅ ALPHA CONFIRMED — the decoded signal is a real brain
tags: [session, results, alpha-test, milestone, contact-quality]
updated: 2026-09-15
---

# Session 2026-09-13 — Alpha Confirmed

**The last substantive open item in the project is closed.** With all 16 pads wetted, the
eyes-closed alpha rhythm appears over the occipital channels exactly as physiology requires — and
the effect is not marginal.

> **The measured values are not in this note.** Band shares, peak ratios and per-channel amplitudes
> are derived from the author's own brain activity, which is biometric data, so they are kept in
> `private/real-session-evidence.md` (git-ignored). This note states the result and the reasoning;
> the numbers stay on the machine that produced them. `PUBLISHING.md` §1 is the rule.

```
dataset   recordings/eyes-closed-eyes-open_2026-09-13_14-56-10
source    live  ·  dongle UD20180927003B78 · EEG Signals
flow      eyes closed 20 s / eyes open 15 s, looping · 7 cycles kept
length    31 338 samples = 244.8 s @ 128 Hz · 14 labelled segments · 0 dropped chunks
```

## The result

The eyes-closed alpha share rose well clear of the eyes-open level on **O1**, meaned over all seven
segments of each label rather than over a selected window — passing the closed/open criterion of
1.5× on both measures used:

- **alpha share** — the 8–12 Hz fraction of 1–45 Hz power
- **alpha peak** — the 8–12 Hz band against its 6–8 + 12–14 Hz flanks, which removes the 1/f slope
  without assuming a model for it

O2 moved the same way but less strongly: it did not reach the 1.5× threshold in magnitude. Its
*direction* was unanimous, though, which is why this reads as an uneven fit rather than an absent
effect — the right occipital pad is presumably making poorer contact than the left.

### The consistency is what makes it convincing

Every eyes-closed segment beat the eyes-open segment that followed it — **seven pairs out of seven,
on O1 and on O2.** A chance fluctuation does not do that. This pairwise consistency, not the size of
the average, is what separates a rhythm from one lucky window.

## Why this session worked when 2026-02-14 did not

Same decoder, same dongle, same code. The only meaningful change was the contacts.

| | 2026-02-14 ✗ | 2026-09-13 ✓ |
| --- | --- | --- |
| pads wetted | 8 of 16 | **16 of 16** |
| occipital amplitudes | at or below the noise floor | **in the normal range** |
| occipital mains contamination | **severe** | **negligible** |
| occipital alpha peak | none | **clear** |
| verdict | NOT DETECTED | **ALPHA CONFIRMED** |

That collapse in mains contamination is the whole story: a floating electrode acts as an antenna,
and a saturated common-mode reference spreads the artefact across every channel. This confirms the
prediction in [[2026-02-14-first-live-session]] — the fault was contact, never the decoder.

## ⚠️ `alpha_test.py --file` gives a FALSE NEGATIVE on a labelled dataset

Run on this same recording it prints `NOT DETECTED` — the opposite of the truth. The cause is in
`main()`:

```python
if "--file" in sys.argv:
    n = len(data)
    seg = n // 3
    parts = [data[:seg], data[seg:2*seg], data[2*seg:3*seg]]
    labels = ["segment 1", "segment 2", "segment 3"]
```

`--file` **never reads `labels.csv`**. It cuts the file into three equal thirds and treats part 1 as
eyes-closed and part 2 as eyes-open. That is correct for the plain prompted recording
`alpha_test.py` writes itself — a fixed 20/15/20 s protocol — and wrong for a dataset: a third of
this session contains *both* states, so the comparison is between two mixtures and the sign can come
out either way.

**Consequence for the record:** the 2026-02-14 negative verdict was reached the same way, and that
session genuinely *was* negative. So the earlier conclusion stands — but it was corroborated by the
channel-health pattern, not by the segment ratio, which was not measuring what it appeared to
measure.

The label-aware replacement is `scripts/alpha_by_segment.py`, which walks every labelled segment and
reports consistency across pairs.

## Reproduce

```powershell
.venv\Scripts\python.exe scripts\alpha_by_segment.py recordings\eyes-closed-eyes-open_2026-09-13_14-56-10
```

Prints the per-segment table, the aggregate ratios and the per-pair consistency check; exits 0 on a
pass. Read-only — it writes nothing, and the recording stays in `recordings/`, which is git-ignored
because it is biometric data.

## Caveats and what is still open

- **Frontotemporal amplitudes are still far above the physiological range.** Sustained values that
  large over the temporalis are most likely EMG (jaw/neck), not brain. It does not touch the
  occipital alpha result, but the frontal channels should not be used for anything quantitative yet.
- **One channel is the worst contact** of the fourteen — still acceptable, but it is the one to
  check next.
- **O2 needs a better seat than O1**; see the magnitude note above.
- **One subject, one session.** "Alpha appears with eyes closed" is now established for this person
  on this unit. It is not a claim about the population, and it is not a clinical result.
- Battery and gyro remain undecoded, and neither blocks anything here.

## Related
[[2026-02-14-first-live-session]] · [[ud2016-crypto-crack]] · [[roadmap]] · [[web-workbench]]
