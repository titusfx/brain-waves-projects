---
title: Connection and Dongle
type: reference
tags: [device, hardware, dongle, ble, usb]
updated: 2026-02-14
---

# Connection and Dongle

Three physical paths into the EPOC+. Only one of them is interesting for open source.

## 1. Proprietary 2.4 GHz USB receiver ("dongle") — ⭐ the open-source path

The universal USB receiver streams from the headset over a **proprietary 2.4 GHz protocol**. It remembers the headset's serial number once paired, and lets multiple headsets co-exist.

Why it matters: **the dongle enumerates as a standard USB HID device**, so it can be opened from user space with `hidapi` — no kernel driver, no Emotiv software, on Windows/Linux/macOS alike. Everything `emokit` does depends on this.

Known facts:
- Emotiv USB **vendor id = 4660** (`0x1234`) — used by the community probe code.
- **Encryption happens on the dongle, not the headset.** `emokit`'s FAQ: *"the encryption happens on the USB KEY, not the headset. So it's actually tied to whatever you have plugged in regardless of the headset."* Consequence: the AES key is derived from the **dongle's** serial number.
- **Packet sizes:** 32 bytes (legacy) or 64 bytes (`UD2016…` dongles). `emokit`'s `validate_data()` normalises 32→33 and 64→65 by prepending a byte, because the sensor bit-masks are indexed from 1.
- **LED diagnostics** — genuinely useful for debugging a dead stream:

| State | Left LED (power icon) | Right LED |
| --- | --- | --- |
| Powered up, looking for headsets | Off | Slow flashing |
| **Receiving data** | **On** | **Fast flashing** |
| Paired but not connected | On | Slow flashing |

If the right LED never goes to fast flashing, the problem is RF/pairing/battery — **not** software. Check this before blaming the driver; it separates "protocol problem" from "hardware problem" in one glance.

## 2. BLE (Bluetooth Low Energy)

The EPOC+ headset **does support BLE**, and Emotiv's docs say the dongle's pairing *"provides a reliable high speed connection over Bluetooth Low Energy (BLE)"* — i.e. the 2.4 GHz link is BLE-flavoured.

Practical caveats:
- Intended for **mobile** (Android/iOS) and for **macOS** — EmotivPRO supports the native BLE radio on macOS 2015+.
- On **PC/Windows**, Emotiv explicitly says Bluetooth implementations vary by manufacturer and are not guaranteed; they recommend the dongle.
- BLE traffic is still a closed protocol with Emotiv's own GATT profile and crypto. There is **no known open-source BLE client** for the EPOC+, and `emokit` is a **USB-HID-only** driver. Do not expect `bleak` + a bit of poking to work.

> ⚠️ **Unverified:** whether the `BT` in the owner's part code `EMO-EPO-BT9X-03` indicates a specific Bluetooth kit variant. See [[identify-your-revision]].

## 3. USB via the "Extender"

Emotiv's spec table lists connectivity as *"Proprietary 2.4GHz wireless, BLE and USB (Extender only)"*. The **Extender is a separate accessory** that provides a wired path; it is not part of the base headset. Unless one is on hand, this route is unavailable — and note the licence example in the API returns an `extenderLimit` field, implying the Extender is itself licence-governed.

## Decision

```
Is the dongle present?
├── yes → try the USB-HID / emokit route first. Free, offline, no account.
│         → [[identify-your-revision]] → [[emokit]]
└── no  → the only remaining route is Emotiv Launcher + BLE/dongle + Cortex API.
          → [[cortex-api]]
```

## Sources
- <https://emotiv.gitbook.io/epoc-user-manual/using-headset/universal_usb_receiver_dongle>
- <https://emotiv.gitbook.io/epoc-user-manual/introduction-1/technical_specifications>
- <https://raw.githubusercontent.com/openyou/emokit/master/FAQ.md>

## Related
[[common-info-eeg-device]] · [[identify-your-revision]] · [[emokit]] · [[cortex-api]]
