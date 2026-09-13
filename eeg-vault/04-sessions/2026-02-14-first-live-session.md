---
title: "Session 2026-02-14 — First Live EEG"
type: session
result: acquisition WORKS / alpha NOT detected (poor contact)
tags: [session, results, alpha-test, contact-quality]
updated: 2026-02-14
---

# Session 2026-02-14 — First Live EEG

Serial `UD20180927003B78` · 180 s recording · 22 933 EEG samples · `alpha_test.csv`

## ✅ What worked

| | |
| --- | --- |
| Dongle + interface | HID interface 1 (`EEG Signals`), interface 0 silent |
| Stream rate | **159 reports/s** steady for the full 180 s |
| EEG sample rate | **127.4 Hz** ⇒ the 128 Hz spec ✅ |
| Key | `new_crypto_key()` — `byte1` had **2** distinct values throughout (legacy keys: 218 → noise) |
| Decoder | all 14 channels produced finite µV values, no errors |

**Conclusion: the acquisition chain is fully working.** Dongle → AES → little-endian layout → µV, over a 3-minute continuous run, with zero dropouts.

## ❌ Alpha not detected — and the reason is contact, not code

### Evidence 1 — amplitudes are 2–3× too large on 10 of 14 channels

| channel | amp µV | mains % | reading |
| --- | --- | --- | --- |
| F3 | 194 | 2.8 | ⚠️ too large |
| FC5 | 215 | 2.0 | ⚠️ too large |
| AF3 | 215 | 2.1 | ⚠️ too large |
| F7 | 203 | 2.2 | ⚠️ too large |
| T7 | 231 | 1.7 | ⚠️ too large |
| **P7** | **103** | 6.0 | borderline |
| **O1** | **20** | 29.7 | low amp + high mains = poor contact |
| **O2** | **14** | 46.9 | low amp + high mains = poor contact |
| P8 | 206 | 2.4 | ⚠️ too large |
| T8 | 206 | 2.1 | ⚠️ too large |
| F8 | 282 | 1.7 | ⚠️ too large |
| AF4 | 213 | 2.6 | ⚠️ too large |
| FC6 | 209 | 2.3 | ⚠️ too large |
| F4 | 229 | 1.7 | ⚠️ too large |

Normal scalp EEG is **10–100 µV**. 200–280 µV sustained across three minutes is artefact — muscle (EMG), drift, or a bad common reference.

**This is the key diagnostic argument:** if the *decode* were wrong, the error would hit all 14 channels equally. Instead, **O1/O2/P7 read normal (14–103 µV) while the other ten read 200+ µV.** A decoding bug cannot produce a per-channel difference — a physical contact difference can. **The decoder is fine; the electrodes are not.**

### Evidence 2 — the spectrum has no alpha peak

O2 power by 1 Hz bin: 1–2 Hz = **199.6**, 27–28 Hz = **209.0**, and the whole 8–12 Hz alpha band sits flat at ~30–32. There is **no bump above the 1/f background** in the alpha band.

Two things dominate instead:
- **1–2 Hz drift** — electrode/DC settling.
- **A strong narrow peak at 27–28 Hz** — not mains (50/60 Hz), so likely EMG or an electrode artefact. Worth noting for later.

Alpha "peak ratio" (alpha ÷ mean of theta & beta):

| region | mean ratio |
| --- | --- |
| occipital (O1, O2) | **0.52** |
| frontal | 0.29 |
| occipital/frontal | **1.80×** |

A ratio **below 1.0 means there is no alpha peak at all**. The 1.80× occipital/frontal gradient is in the *right direction* (alpha is genuinely occipital-dominant) — weak evidence of real signal, but nowhere near conclusive.

## Root cause: only 8 of 16 pads were wetted

The EPOC+ has **16 felt pads — 14 EEG + 2 references (CMS/DRL)**. This session used **8**.

If the **reference pads are dry**, common-mode rejection fails and *every* channel shows a large common artefact — which matches the 200 µV seen on ten channels. Meanwhile the occipital pads appear poorly connected in their own right (low amplitude + high mains).

## Next session — protocol

1. **Wet all 16 pads.** Soak them through, not damp. Saline or the Emotiv solution.
2. **References first.** The two pads beyond the 14 named channels. Non-negotiable.
3. **O1 / O2 next** — the alpha channels (back of the head).
4. Part the hair away from each pad; seat the headset firmly.
5. **Wait 2–3 minutes** after fitting for the saline to settle before recording.
6. Sit still, jaw relaxed, no talking.
7. Record 180 s while alternating eyes closed / open every ~20 s.

**Target for a pass:** alpha peak ratio **> 1.5** on O1/O2, and amplitudes in the **10–100 µV** band.

## Related
[[device-identifiers]] · [[ud2016-crypto-crack]] · [[roadmap]] · [[common-info-eeg-device]]
