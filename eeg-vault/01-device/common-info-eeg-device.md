---
title: Common Info — EEG Device (Emotiv EPOC+)
aliases: [EPOC+, EPOC Plus, common-info-eeg-device, device-info]
type: device
manufacturer: Emotiv
model_reported: "EMO-EPO-BT9X-03"
family: EPOC+
revision_confirmed: "EPOC+ Model 1.1 (FCC ID XUE-USBD01 dongle) — likely pre-2016"
channels: 14
sample_rate_hz: [128, 256]
resolution_bits: 14
lsb_uv: 0.51
bandwidth_hz: "0.2 – 45"
connectivity: [proprietary-2.4GHz-dongle, BLE, USB-via-Extender]
status: hardware-on-hand
tags: [device, eeg, emotiv, epoc, hardware]
updated: 2026-02-14
---

# Common Info — EEG Device

> Canonical reference for the headset this project is built around.
> Owner-reported part code: **`EMO-EPO-BT9X-03`** (1× EMOTIV EPOC+ headset).
> Anything in this note that is *not* independently verified is explicitly marked ⚠️.

## 1. What it is

The **Emotiv EPOC+** is a 14-channel, saline-felt, mobile EEG headset. It is a consumer/prosumer device that sits between hobbyist gear (NeuroSky, Muse) and true research amplifiers (OpenBCI Cyton, g.tec). Its headline problem for this project is **not** signal quality — it is that Emotiv's software stack gates *raw* EEG behind a paid licence.

- **14 EEG channels** + CMS/DRL reference and P3/P4 locations
- **128 SPS or 256 SPS** (2048 Hz internal, sequential sampling, single ADC)
- **14-bit** effective resolution — 1 LSB ≈ **0.51 µV**
- **0.2 – 45 Hz** bandwidth, built-in 5th-order sinc filter, digital notch at 50/60 Hz
- **AC coupled**, 8400 µV peak-to-peak dynamic range
- **LiPo 680 mAh**, ~12 h typical battery life
- **Real-time contact-quality** (impedance) per electrode, patented
- Standard **Ag/AgCl + felt + saline** sensors

### Hardware revisions
The EPOC+ shipped in at least three revisions, and **this distinction decides which open-source driver works**:

| Version | Sampling | IMU part | Notes |
| --- | --- | --- | --- |
| EPOC v1.0 | 128 SPS | IDG500 (2-axis gyro, no mag) | The original EPOC. Best-supported by `emokit`. |
| EPOC+ v1.1 | 128/256 SPS | LSM9DS0 (9-axis) | The classic EPOC+. |
| EPOC+ v1.1A | 128/256 SPS | ICM-20948, gyro reported as quaternion | Later production. |

> ⚠️ **Important correction to the usual framing:** the headset revision table above is *not* what decides whether open-source drivers work. `emokit` branches on the **USB dongle's serial number**, and **VID/PID is identical across all generations** (`0x1234:0xED02`). The key is derived from the **dongle**, not the headset — *"the encryption happens on the USB KEY, not the headset"* (emokit FAQ). So the revision table matters for *specs*; the serial matters for *compatibility*. → [[identify-your-revision]]

### The physical unit — CONFIRMED 🎯

The dongle is printed:

```
Emotiv EPOC+TM  Model 1.1   USB 001
FCC ID: XUE-USBD01          CB Reg No: JPTUV-029914
```

⚠️ **The printed label turned out to be a RED HERRING for dating. The serial is the truth.**

| | |
| --- | --- |
| **USB serial (decisive)** | **`UD20180927003B78`** |
| Manufacture date | **2018-09-27** (decoded: `UD` + `YYYYMMDD` + counter) |
| Generation | **`UD2018` = post-2016 "new format"** |
| Dongle label / FCC | "Model 1.1", `XUE-USBD01` (2010 grant) |
| Data interface | HID interface **1**, product string **`EEG Signals`** |

**⇒ This is a 2018 unit, NOT pre-2016.** The "Model 1.1" text and the 2010-era FCC ID misled us (the dongle design was reused long after 2010). The label is not a reliable generation indicator; **only the serial is**.

**⇒ Full IDs, keys, and instance paths: [[device-identifiers]].**

Consequence: this unit needs `new_crypto_key()` — the path emokit's literal `startswith("UD2016")` check silently misses. We have already solved and verified that path end-to-end. → [[ud2016-crypto-crack]]

> 🚨 Still true: **do not update the dongle firmware, and do not install Emotiv Launcher.** See [[identify-your-revision]] §0.1. (This unit is already 2018-era so it is likely already "new format" — but there is no reason to risk further changes.)

### Earlier research: the `EMO-EPO-BT9X-03` part code

Retained for the record — a **weak** identifier, superseded by the serial above.



Research result — this code is **essentially undocumented**:

- A GitHub code search for the exact string returns **exactly one** indexed occurrence worldwide: a peer-reviewed protocol paper — Zhao X. et al., *Front. Psychiatry* **11**:655 (2020), doi:10.3389/fpsyt.2020.00655 — which writes:
  > *"The actual electroencephalogram signals are recorded using a six-channel configuration at F7, F8, T7, T8, O1, and O2 (Emotiv EPOC® Headset -EMO-EPO-BT9X-03)."*
- That study recruited from **March 2019**, placing the unit in the **2016+ era** — contemporaneous with the EPOC X (FCC filing 2020-03).
- **No Emotiv document, shop listing, reseller catalogue, manual, or FCC filing contains the string.** Its internal structure is unverified.

**Working hypothesis (explicitly unverified):** `EMO-EPO` = EPOC family; `BT` = Bluetooth-capable; `9X` = 9-axis IMU; `-03` = revision/region. Note the paper calls it an "Emotiv **EPOC**" headset, not EPOC+, and used only 6 of the 14 channels.

**Consequence for the project:** the unit is almost certainly **not** a pre-2016 EPOC+ — i.e. it is in or near the generation `emokit` disclaims, and possibly old enough that even its serial prefix (`UD2019…`) falls outside emokit's literal `"UD2016"` check. **Plan for Route A to be a fight, not a formality.** → [[opensource-landscape]]

### Emotiv FCC identifiers (for cross-checking any unit)

| FCC product code | Date | Product |
| --- | --- | --- |
| `2ADIH-EPOC02` | 2015-04-26 | Emotiv EPOC+ Neuroheadset (BLE, 2402–2480 MHz DTS) |
| `2ADIH-EPOC03` | 2020-03-13 | "Mobile BCI Headset, Gaming Interface" (EPOC X) |
| `2ADIH-INSIGHT01` / `INSIGHT02` | 2015-07 / 2021-08 | Insight |
| `2ADIH-FLEX01` / `FLEX02` | 2018-11 / 2023-10 | EPOC Flex |
| `2ADIH-MN801` | 2022-05-17 | MN8 |
| `XUE-USBD01` | 2010-07-02 | "USB Dongle for Wireless EEG Headset System", 2404–2479 MHz |

## 2. The 14 channels

10-20 positions, **fixed montage** (no flexibility — this is the key downside vs. OpenBCI):

`AF3 · F7 · F3 · FC5 · T7 · P7 · O1 · O2 · P8 · T8 · FC6 · F4 · F8 · AF4`

Layout = frontal + temporal + occipital coverage, **no central/parietal electrodes** (no C3/C4/Cz, no P3/P4 as EEG). This matters:

- ✅ Good for: **frontal alpha asymmetry**, **engagement/attention**, **cognitive load**, **meditation/alpha-theta**, **SSVEP/occipital work**, **P300-ish oddball** (weakly — limited parietal coverage), **facial-expression / EMG artifact research**.
- ⚠️ Weak for: **motor imagery** (needs C3/C4/Cz — the EPOC+ lacks them), fine-grained **source localisation**, anything needing a flexible montage.

## 3. Connection options

The EPOC+ can be reached three ways. See [[connection-and-dongle]] for detail.

1. **Proprietary 2.4 GHz USB receiver (dongle)** — the recommended PC path. Enumerates as a **USB HID** device, which is exactly what makes the community driver possible. ← the interesting one for this project.
2. **BLE** — supported by the headset. Works reliably with mobile (Android/iOS). On macOS, Emotiv's own software uses the native BLE radio (2015+ machines). On Windows, Emotiv documents BLE as unreliable and recommends the dongle.
3. **USB via the "Extender"** accessory — wired, but an add-on, not the base headset.

## 4. Capability & limits — the honest summary

| Question | Answer |
| --- | --- |
| Can it give raw EEG? | Yes, technically. 128/256 Hz × 14 ch. |
| Can I get raw EEG **for free**? | Via Emotiv's official API: **no** — the `eeg` stream requires a licence with the `eeg` scope. Via the community USB driver: free, but compatibility-dependent. |
| Does official software need a subscription? | Yes for the useful parts. Raw EEG + performance metrics are licensed; several other streams are open to all. |
| Is there a community driver? | Yes — [[emokit]], but **unmaintained since April 2017**. |
| Does the modern open EEG ecosystem support it? | **No.** BrainFlow, OpenBCI GUI etc. have zero Emotiv support. See [[ecosystems-without-support]]. |
| Can I use it offline / without Emotiv's cloud? | Only via the USB dongle + community driver. Emotiv's official API always runs through **Emotiv Launcher** and authenticates against Emotiv's cloud. |
| Is it usable for a serious hobby/research project? | Yes — if acquisition is solved once and then abstracted away. That is precisely this project's plan. |

## 5. Licensing reality (the thing that blocked the previous attempt)

This is the crux of the original frustration, and it is **confirmed** from Emotiv's own API docs:

- Cortex API is JSON-RPC over WebSocket, and requires **Emotiv Launcher** running + an **EmotivID** + a registered **App ID (client id/secret)**.
- Data streams are gated by licence scopes returned by `getLicenseInfo`:
  - **`eeg` (raw EEG) → "All [headsets], but requires a license."** The licence must contain the scope `"eeg"`.
  - The documentation's own example licence is `["eeg","pm"]`, attached to `com.emotiv.emotivpro`, named **"PRO license"**.
- Streams that appear **not** to require a licence scope: `mot` (motion), `dev` (battery / signal / contact quality), `eq` (EEG quality), `pow` (band power), `com` (mental commands), `fac` (facial expressions). `met` (performance metrics) drops to 0.1 Hz without the `pm` scope.
- **The blocker is session activation, not just subscription.** An unactivated session cannot subscribe to `eeg` at all and cannot create records or markers. Free users hit **error `-32006`: "You have a paid EMOTIV license to activate a session."**

**The bottom line on cost** (verified 2026):

| Option | Price |
| --- | --- |
| EmotivPRO **Lite** | **$0** — but no raw EEG |
| EmotivPRO **Standard** | **$89/mo billed annually = $1,068/year** |
| EmotivPRO **Standard Team** | **$224.08/mo billed annually = $2,689/year** |
| **Cortex API developer seat** | **€1,738 incl. VAT (€1,460.50 net) / 1 seat / 1 year** |
| EmotivPRO **Performance** | contact sales |

⚠️ It is **unresolved** whether EmotivPRO Standard alone grants the Cortex `eeg` scope or whether the dedicated developer seat is also required — the `getLicenseInfo` example suggests a "PRO license" carries `scopes: ["eeg","pm"]`. **Confirm with Emotiv support before buying anything.** Also note *"API and Dev licenses are not currently available under Organization Licensing."*

**Important nuance:** the **free** tier still gives `pow`, `com`, `fac`, `mot`, `dev`, `eq`. Emotiv gives away the *derived* data and sells the *raw* data. So a band-power neurofeedback app is buildable for $0 — see [[roadmap]] Phase 5.

→ Full detail, error codes, and setup steps in [[cortex-api]].

## 6. Why this device specifically is awkward for open source

Honest framing, because it shapes the whole roadmap:

1. **The dongle is the only free hardware path** — and it is a closed HID protocol that the community had to reverse-engineer.
2. **That reverse-engineering effort stopped in 2017.** Signal quality is fine; maintenance is not.
3. **Emotiv deliberately rotated the crypto.** `emokit`'s own FAQ documents that when Emotiv learned keys were being reused across dongles, they reflashed dongle firmware and broke the driver. The modern serial prefix `UD2016…` uses a *different* key derivation and a *different packet length* (64 bytes vs 32).
4. **The modern open ecosystem skipped Emotiv entirely.** BrainFlow never added it, so you cannot just `BoardShim(EMOTIV_BOARD)`.

None of this makes the device useless. It makes **acquisition** the hard part and **everything after acquisition** normal, ordinary EEG work.

## 7. Related notes

- [[identify-your-revision]] — do this first
- [[connection-and-dongle]] — dongle vs BLE vs Extender
- [[opensource-landscape]] — the routes, ranked
- [[emokit]] — the community driver
- [[cortex-api]] — the official API
- [[roadmap]] — the plan

## 8. Sources

Full list in [[references]]. Primary sources for this note:
- Emotiv EPOC+ User Manual — Technical Specifications: <https://emotiv.gitbook.io/epoc-user-manual/introduction-1/technical_specifications>
- Emotiv EPOC+ User Manual — Universal USB Receiver (Dongle): <https://emotiv.gitbook.io/epoc-user-manual/using-headset/universal_usb_receiver_dongle>
- Cortex API — Data Subscription: <https://emotiv.gitbook.io/cortex-api/data-subscription>
- Cortex API — getLicenseInfo: <https://emotiv.gitbook.io/cortex-api/authentication/getlicenseinfo>
