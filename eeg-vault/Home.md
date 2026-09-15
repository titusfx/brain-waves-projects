---
title: Home
type: moc
tags: [moc, eeg, bci]
updated: 2026-02-14
---

# 🧠 Brain Waves Projects — Vault Home

Everything about the **Emotiv EPOC+ 14-channel mobile EEG** and the open-source project built around it.

> 🚨 **BEFORE you plug anything in: do NOT update the dongle firmware, and do not install Emotiv Launcher on the machine with the dongle attached.** Firmware updates are what introduced the crypto that broke the community driver. Our route needs no Emotiv software at all. → [[identify-your-revision]] §0.1
>
> ✅ **SOLVED AND WORKING ON REAL HARDWARE (2026-02-14).** Serial `UD20180927003B78` (a **2018** unit — the printed "Model 1.1" label was a red herring). Key and packet layout both cracked; live EEG decodes at sane amplitudes. → [[device-identifiers]] · [[ud2016-crypto-crack]]
>
> ✅ **THE ALPHA RHYTHM IS CONFIRMED (2026-09-13).** With all 16 pads wetted, the eyes-closed 8–12 Hz peak appears over the occipital channels and drops when the eyes open — consistently, in every pair of the session. **The decoded signal is a real brain**, so the last substantive open item is closed. The measured values are deliberately withheld (they are the author's own biometric data) and live in `private/`, which is git-ignored. → [[2026-09-13-alpha-confirmed]]

## Start here

- [[common-info-eeg-device]] — **the canonical device note.** What the hardware is, what it can do, what it cannot.
- [[identify-your-revision]] — the single most important thing to do first: find out *which* EPOC+ you own.
- [[opensource-landscape]] — every route to get data out of this headset, ranked.

## Map of content

### 01 — Device
| Note | Purpose |
| --- | --- |
| [[common-info-eeg-device]] | Canonical spec sheet + capability/limits summary |
| [[device-identifiers]] | ⭐ **All IDs: serial, VID/PID, HID interfaces, AES key, instance paths** |
| [[identify-your-revision]] | HID probe → serial → which crypto path applies |
| [[connection-and-dongle]] | 2.4 GHz dongle vs BLE vs USB Extender |

### 02 — Software
| Note | Purpose |
| --- | --- |
| [[opensource-landscape]] | Decision matrix of all acquisition routes |
| [[ud2016-crypto-crack]] | 🎯 **RESULTS: the crypto is cracked, verified offline** |
| [[why-the-licence]] | Why the licence exists — it's DRM in the dongle firmware |
| [[emokit]] | The community driver — internals, support matrix, crypto |
| [[status-packets-and-battery]] | The `0x20` status packets; battery is still unidentified |
| [[cortex-api]] | Emotiv's official API — what is free, what is paywalled |
| [[ecosystems-without-support]] | BrainFlow / OpenBCI / others that do **not** support Emotiv |
| [[lsl-and-interop]] | LSL — the escape hatch into the wider ecosystem |

### 03 — Project
| Note | Purpose |
| --- | --- |
| [[roadmap]] | Phased build plan |
| [[web-workbench]] | ⭐ **The app: live monitor, channel reference, protocol builder, datasets** |
| [[decisions-log]] | ADR-style record of choices made and why |
| [[glossary]] | EEG/BCI terms as used in this project |

### 04 — Sessions
| Note | Result |
| --- | --- |
| [[2026-02-14-first-live-session]] | ✅ acquisition works · ❌ alpha not detected (poor contact — only 8 of 16 pads wetted) |
| [[2026-09-13-alpha-confirmed]] | ⭐ **✅ alpha CONFIRMED — the signal is a real brain** (every pair; measured values withheld, see `private/`) |

### 99 — Sources
- [[references]] — every external source, with URLs

## The one-paragraph summary

The EPOC+ is a genuinely capable 14-channel, 128/256 Hz headset. Its problem is not hardware, it is the **software gate**: Emotiv's own API exposes *raw* EEG only under a paid licence (**~$1,068/yr**, error `-32006` if you try to activate a free session), while the community reverse-engineering project **`emokit` is archived** (last real commit April 2017) and officially disclaims EPOC+ units from 2016 onwards. Worse, `emokit` decides which crypto to use by testing `serial.startswith("UD2016")` — a **literal string**, though serials encode the build date — so a 2019/2020 dongle like this one would silently pick the **wrong key** and emit garbage without error. So the project's first job is empirical: probe the dongle, patch around the `UD2016` bug if needed, and **prove acquisition with the eyes-closed alpha test** before trusting a single sample — then hide all of it behind a source-agnostic interface so everything built downstream survives.

**The good news:** the free Cortex tier still provides band power, mental commands, facial expressions, motion and contact quality — enough to build a real application for $0.

→ [[opensource-landscape]] · [[identify-your-revision]] · [[roadmap]]
