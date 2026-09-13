---
title: Ecosystems Without Emotiv Support
type: reference
aliases: [BrainFlow, OpenBCI]
tags: [software, brainflow, openbci, negative-result]
updated: 2026-02-14
---

# Ecosystems Without Emotiv Support

A **negative result** worth recording, because it saves weeks of searching and it shapes the architecture.

## BrainFlow — ❌ no Emotiv support

[BrainFlow](https://brainflow.readthedocs.io/) is the modern lingua franca of open EEG: one API over OpenBCI, Muse, BrainBit, Neurosity, g.tec Unicorn, Mentalab, FreeEEG, EmotiBit, PiEEG, IronBCI, Ant Neuro, Enophone… and **no Emotiv**.

Verified by reading its entire supported-board index — there is no Emotiv/Cortex/EPOC entry anywhere in it. There is no `BoardIds.EMOTIV_*`.

Consequence: you cannot do this, however much you want to:

```python
# ❌ does not exist
board = BoardShim(BoardIds.EMOTIV_EPOC_PLUS, params)
```

**What this costs us:** BrainFlow's genuinely valuable parts — `DataFilter` (bandpass/notch/bandpower/ICA/wavelet denoising), `MLModel`, MNE integration, playback/synthetic/streaming boards, and game-engine bindings — are off the shelf for Emotiv. If we ever want them, the path is to **re-emit our data in BrainFlow's format** or via [[lsl-and-interop|LSL]] and use the playback/streaming boards.

**What we can still steal from it:** its **data model** is a good one to copy, and its dummy boards are a good idea to imitate:

- `SYNTHETIC_BOARD` — generates fake data so you can develop without hardware.
- `PLAYBACK_FILE_BOARD` — replays a recorded CSV through the full pipeline.
- `STREAMING_BOARD` — multicast/`streaming_board://ip:port` so a second process consumes a live stream.

Copy all three concepts. See [[roadmap]] — our `Source` abstraction is deliberately shaped to have a synthetic and a replay implementation, exactly because we cannot rely on BrainFlow providing them.

## OpenBCI — different hardware, not a fallback

OpenBCI (Cyton, Ganglion, Galea) is often suggested as "the open alternative". It is **different hardware**, not a way to use an EPOC+. Worth knowing as:
- the benchmark for what an open EEG stack feels like,
- a future upgrade path if the EPOC+ acquisition fight proves unwinnable.

Note the montage tradeoff: an OpenBCI Cyton has **8 flexible channels** — fewer than 14, but placeable anywhere (including C3/C4/Cz, which the EPOC+ structurally cannot reach). More freedom, fewer channels.

## Others checked

| Project | Emotiv support |
| --- | --- |
| **BrainFlow** | ❌ none |
| **OpenBCI GUI** | ❌ n/a (OpenBCI hardware only) |
| **MNE-Python** | ✅ but **file/array-based** — it is analysis, not acquisition. Consumes whatever we decode. |
| **OpenViBE / BCI2000** | ⚠️ historically had Emotiv acquisition drivers via the old proprietary SDK/Cortex; not an independent open path. *Verify before relying on it.* |
| **Timeflux / LSL tools** | Consume LSL; they do not talk to Emotiv directly. Useful as consumers. |

> ⚠️ **Lesson:** the whole ecosystem assumes you can get a clean sample stream out of your device. Emotiv is one of the few majors with no open path. **Acquisition is the only genuinely hard part of this project; everything downstream is commodity EEG work** (MNE, scipy, scikit-learn, matplotlib).

## Architectural consequence

Because no ecosystem will do acquisition for us, we own exactly one piece of software — the **source** — and we deliberately keep it thin, testable, and swappable:

```
[ dongle ]──HID──>[ Source ]──samples──>[ everything else: filters, features, ML, UI ]
[ Cortex  ]──WS───>   ^
[ synthetic ]────────┘
[ replay CSV ]───────┘
```

→ [[roadmap]] · [[decisions-log]]

## Sources
- BrainFlow supported boards: <https://brainflow.readthedocs.io/en/stable/SupportedBoards.html>
- <https://openbci.com/>

## Related
[[opensource-landscape]] · [[emokit]] · [[cortex-api]] · [[roadmap]]
