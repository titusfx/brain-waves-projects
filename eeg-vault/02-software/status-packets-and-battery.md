---
title: Status Packets and Battery
type: reference
status: battery NOT yet identified
tags: [protocol, battery, status-packets, open-question]
updated: 2026-02-14
---

# Status Packets (`0x20`) and Battery

## Can we read the battery level?

**Not yet.** emokit never implemented it for the "new format" — `EmotivNewPacket` literally sets `self.battery = None` and never fills it in (`vendor/emokit/python/emokit/packet.py` line 111). The old `EmotivOldPacket` *did* decode battery, but via a scheme that does not appear in the new format.

## What the `0x20` status packets actually contain

Analysed from the archived 2016 capture (1067 status packets, 2134 EEG packets):

| byte(s) | finding |
| --- | --- |
| 0 | counter, 0–127, AC 0.955 |
| 1 | **constant `0x20`** — the packet-type marker |
| **20–31** | **always zero** — the status packet only uses bytes 0–19 |
| 3, 5, 7, 9, 11, 13, 15, 17, 19 | 1–3 distinct values → markers / high bytes |
| 2, 4, 6, 8, 10, 12, 14, 16, 18 | many distinct values → the payload |

So the status packet is structured as **16-bit little-endian fields** at offsets 0-1, 2-3, 4-5, … 18-19 — nine fields. Consistent with the rotating contact-quality scheme in [[emokit]]'s protocol doc (quality rotates per sensor as the counter advances).

## Battery candidates

Two fields are plausible. **Neither is confirmed.**

### Candidate 1 — byte 13 (moderate)

Take only two values in practice: **`243` (834×), `244` (232×)**, once `242`.

The old-format battery table from emokit's protocol doc maps:

| byte13 | old table says |
| --- | --- |
| 242 | 81.89 % |
| **243** | **85.23 %** |
| 244 | 89.45 % |

A ~85 % reading that jitters by ±1 is exactly what a noisy battery-voltage ADC looks like.

⚠️ **Counter-argument:** it toggles 232 times in 25 s. Real battery level should not move that fast — unless this is a raw *voltage* reading with noise rather than a smoothed percentage. Also, byte 13 in **EEG** packets is a constant `125`, so this field only exists in status packets.

### Candidate 2 — bytes 6-7 (weaker)

A 16-bit LE field with **range 13–100** across 72 distinct values. A 0–100 range *looks* like a percentage. But it varies far too quickly for a battery, so it is more likely the rotating contact-quality field.

## How to settle it definitively

**Run a long capture on battery power and find the field that decreases monotonically.**

```powershell
.venv\Scripts\python.exe scripts\record.py 1800 battery_hunt.csv
```

Then compare the *first* and *last* 2 minutes: the battery field will have moved in one direction; everything else will be stationary or noisy.

A raw-packet recorder is needed for this (the current `record.py` saves decoded µV). **TODO: add `--raw` to save the decrypted 32-byte reports so byte 13 and friends can be inspected.**

## Also worth trying

- **HID feature report.** emokit's protocol doc says the host *"request[s] a feature report from the device that contains whether the device is a consumer or research headset"* — so feature reports carry device metadata. Battery may be exposed there. Test with `hid.device().get_feature_report(0, 64)`.
- **The headset's own LED** remains the simplest battery indicator (blinking ≈ low).

## Practical note

If the headset is left on a USB power bank while recording, **the battery level is irrelevant to the project**. That is the recommended setup for sessions: it removes the single biggest source of dropouts we have hit (the headset cutting out mid-recording after 30 s).

## Why this matters less than it sounds

Battery affects *session length*, not *data correctness*. The acquisition chain is already verified. This is a nice-to-have.

## Related
[[device-identifiers]] · [[ud2016-crypto-crack]] · [[emokit]] · [[roadmap]]
