---
title: Glossary
type: reference
tags: [glossary, eeg, dsp]
updated: 2026-02-14
---

# Glossary

Terms as used **in this project**, not textbook-complete.

## Hardware & montage

| Term | Meaning here |
| --- | --- |
| **EPOC+** | The Emotiv 14-channel mobile EEG headset this project is built on. |
| **Dongle / universal USB receiver** | The 2.4 GHz USB stick that talks to the headset and enumerates as a **USB HID** device. Crypto lives here, not in the headset. |
| **Montage** | Which electrodes sit where. The EPOC+ is **fixed**: `AF3 F7 F3 FC5 T7 P7 O1 O2 P8 T8 FC6 F4 F8 AF4`. |
| **10-20 system** | Standard electrode-position naming. Letters = region (F frontal, T temporal, P parietal, O occipital, C central), numbers = left/right. |
| **CMS / DRL** | Common Mode Sense / Driven Right Leg — the reference and driven-ground pair. Not EEG channels. |
| **Contact quality / impedance** | How well an electrode touches the scalp. EPOC+ uses saline felt pads; they dry out and quality degrades. Check before trusting data. |
| **Extender** | Emotiv accessory providing a wired USB path. Separate purchase. |

## Signal

| Term | Meaning here |
| --- | --- |
| **µV (microvolt)** | The unit EEG is measured in. Scalp EEG is roughly 10–100 µV. |
| **LSB** | Least significant bit — the smallest ADC step. EPOC+: **1 LSB ≈ 0.51 µV**. `emokit` scales counts by `0.5151515151`. |
| **SPS / Hz** | Samples per second. EPOC+ is **128 or 256**. |
| **14-bit / 16-bit** | EPOC+ ADC is 16-bit but the bottom 2 bits are instrument noise floor, giving 14 effective bits. Settings can change this. |
| **AC coupled** | DC offset is filtered out; slow drifts are attenuated. |
| **Notch filter** | Narrow filter removing mains hum at **50 Hz** (EU) or **60 Hz** (US). The EPOC+ has these built in. |
| **Bandpass** | Keeps a frequency range; typical EEG chain is 0.5–45 Hz. |

## Frequency bands

| Band | Range | Associated with (loosely!) |
| --- | --- | --- |
| **Delta** | 0.5–4 Hz | Deep sleep; also eye movements and drift artefacts |
| **Theta** | 4–8 Hz | Drowsiness, meditation, memory encoding |
| **Alpha** | **8–13 Hz** | **Relaxed wakefulness, eyes closed, occipital.** ⭐ our primary sanity check |
| **Beta** | 13–30 Hz | Active thinking, focus; heavily contaminated by muscle (EMG) |
| **Gamma** | 30+ Hz | High-level processing; at the scalp, mostly EMG artefact. Treat with suspicion. |

> The band→cognition mapping is folklore with a real but *weak* statistical basis. It is fine for a neurofeedback demo; it is not a mind reader.

## Artefacts (the enemy)

| Artefact | Where | Cause |
| --- | --- | --- |
| **Eye blink / EOG** | Frontal (`AF3`, `AF4`, `F7`, `F8`) | Blinks are huge and slow; dominate frontal channels |
| **EMG** | Temporal (`T7`, `T8`) | Jaw clench, swallowing, talking, smiling — broadband, looks like gamma |
| **Line noise** | Everywhere | Mains hum, 50/60 Hz |
| **Motion** | Everywhere | Cable/electrode movement, poor contact |
| **Drift** | Everywhere | Drying saline, sweat, slow electrode polarisation |
| **Cardiac (ECG)** | Near vessels | Heartbeat picked up as a periodic spike |

## Software

| Term | Meaning here |
| --- | --- |
| **emokit** | The community Python USB-HID driver. Abandoned 2017. → [[emokit]] |
| **Cortex API** | Emotiv's official JSON-RPC-over-WebSocket API. Raw EEG requires a paid `eeg`-scoped licence. → [[cortex-api]] |
| **Emotiv Launcher** | Emotiv's desktop app that Cortex API must talk through. Closed source. |
| **EmotivPRO** | Emotiv's paid recording/analysis software; the example licence in the docs is `com.emotiv.emotivpro`. |
| **BrainFlow** | Cross-vendor open EEG library. **No Emotiv support.** → [[ecosystems-without-support]] |
| **LSL** | Lab Streaming Layer — the de-facto standard for real-time streaming between research apps. → [[lsl-and-interop]] |
| **MNE-Python** | The standard Python library for EEG/MEG analysis. File/array-based. |
| **HID** | Human Interface Device — the generic USB class the dongle presents as. |
| **AES-ECB** | Block cipher mode used by the dongle. ECB is cryptographically weak (identical plaintext blocks → identical ciphertext) which is precisely what made reverse-engineering feasible. |
| **Source** | *Our* abstraction over an acquisition backend. → [[roadmap]] Phase 2 |
| **Scope** | A string in an Emotiv licence (e.g. `"eeg"`, `"pm"`) that unlocks a data stream. `eeg` is the paid one. |
| **Session activation** | Cortex's gate: an unactivated session cannot subscribe to `eeg` or create records. Free accounts fail here with error `-32006`. |
| **VID / PID** | USB vendor id / product id. Emotiv dongle = `0x1234` / `0xED02`, **identical** across generations — so it cannot distinguish old from new units. |
| **DTS** | FCC equipment class for Digital Transmission Systems — how the EPOC+ BLE grant (2402–2480 MHz) is filed. |
| **UID / UD serial** | Emotiv dongle serial, `UD` + `YYYYMMDD` + counter. The *date* is what decides which crypto key applies. → [[identify-your-revision]] |

## Related
[[common-info-eeg-device]] · [[roadmap]] · [[references]]
