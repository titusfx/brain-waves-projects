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

### Evidence 1 — the amplitudes were wrong on ten of fourteen channels

The per-channel amplitudes and mains contamination are recorded in
`private/real-session-evidence.md` (git-ignored — they are derived from a real person's brain).
The *pattern* is what carries the diagnosis, and that is preserved here:

- **Ten of the fourteen channels** sustained amplitudes far above the physiological range for the
  whole three minutes — consistent with muscle (EMG), drift, or a bad common reference.
- **The occipital and parietal channels (O1, O2, P7) read in the normal range** — but with very
  high mains contamination, which is the signature of an electrode barely touching.

Normal scalp EEG is **10–100 µV**.

**This is the key diagnostic argument:** if the *decode* were wrong, the error would hit all 14
channels equally. Instead the good channels and the bad channels were *different channels*. A
decoding bug cannot produce a per-channel difference — a physical contact difference can.
**The decoder is fine; the electrodes are not.**

### Evidence 2 — the spectrum has no alpha peak

The O2 spectrum was dominated by two features: strong **1–2 Hz drift** (electrode/DC settling) and
a **narrow peak around 27–28 Hz** — not mains (50/60 Hz), so likely EMG or an electrode artefact.
That peak is still an open question (see `AGENTS.md` §8). The whole 8–12 Hz alpha band sat flat,
with **no bump above the 1/f background**: there was no alpha peak to find.

The occipital-over-frontal alpha gradient *was* in the right direction — alpha is genuinely
occipital-dominant — so that was weak evidence of real signal. It was nowhere near conclusive and
should not have been quoted as a result. The ratios themselves are in `private/`.

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
