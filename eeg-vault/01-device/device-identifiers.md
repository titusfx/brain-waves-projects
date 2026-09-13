---
title: Device Identifiers
aliases: [IDs, serials, device-ids, registry]
type: reference
tags: [device, ids, serial, usb, reference, canonical]
updated: 2026-02-14
---

# Device Identifiers

**Canonical registry of every identifier for this unit.** If a tool, script, or future-you needs an ID, take it from here — do not re-derive it.

Captured live on **2026-02-14** with `scripts/probe_device.py` and Windows PnP.

## The unit

| | |
| --- | --- |
| Headset | Emotiv EPOC+ (14-channel) |
| Dongle label | `Emotiv EPOC+TM  Model 1.1   USB 001` |
| Dongle FCC ID (printed) | **`XUE-USBD01`** |
| Dongle CB Reg No (printed) | `JPTUV-029914` |
| Owner-reported part code | `EMO-EPO-BT9X-03` ⚠️ weak identifier, see [[common-info-eeg-device]] |

> ⚠️ **The printed "Model 1.1" / `XUE-USBD01` is a RED HERRING for dating.** It looked pre-2016 (2010 FCC grant, original dongle design), but the actual USB serial proves the unit is **2018**. Trust the serial, not the label. → §2

## 1. USB identity

| Field | Value |
| --- | --- |
| Vendor ID (VID) | **`0x1234`** = 4660 |
| Product ID (PID) | **`0xED02`** = 60674 |
| Manufacturer string | `Emotiv` |
| Composite device name | *"USB Composite Device"* |

**The dongle exposes TWO HID interfaces.** Only one carries EEG data.

| Interface | `interface_number` | Product string | Data? |
| --- | --- | --- | --- |
| 0 | `0` | `Brain Computer Interface USB Receiver/Dongle` | ❌ **silent** (0 reports in 12 s) |
| 1 | `1` | **`EEG Signals`** | ✅ **streams** (~160 reports/s) |

> ⭐ **Use interface 1 (`EEG Signals`).** This matches [emokit issue #138](https://github.com/openyou/emokit/issues/138), where the user had to add `elif device.product_name == 'EEG Signals':` to make EPOC+ work. emokit's Windows path takes `devices[1]` — the second match — which is this one, by luck of enumeration order.

## 2. ⭐ Serial number — the decisive identifier

```
UD20180927003B78
```

**Decoded:**

| Segment | Value | Meaning |
| --- | --- | --- |
| `UD` | `UD` | dongle prefix |
| `20180927` | **2018-09-27** | **manufacture date** |
| `003B78` | `003B78` | unit counter — ⚠️ **contains letters**, it is not decimal |

**Generation: `UD2018` → post-2016 "new format" dongle.**

### 🚨 Why this specific serial is a trap for emokit

`emokit` selects its crypto with a **literal** string compare:

```python
if self.serial_number.startswith("UD2016"):   # <-- literal, not a date test
```

`UD20180927003B78` does **not** start with `UD2016`, so emokit **silently falls through to the legacy key path** and produces garbage — no error. This is the exact bug predicted in [[identify-your-revision]]; this unit is a confirmed instance of it.

**Verified live:** the legacy keys give 255–256 distinct `byte1` values (noise); the correct key gives **2**.

## 3. AES key

| | |
| --- | --- |
| Derivation | `new_crypto_key(serial)` |
| Cipher | **AES-128-ECB**, two independent 16-byte blocks |
| Key bytes | `b'4778887141771174'` |
| Key length | 16 bytes (128-bit) |

Reproduce:

```python
from emokit.util import new_crypto_key
new_crypto_key("UD20180927003B78")   # -> '4778887141771174'
```

(If the serial changes — new dongle, same code path — the key changes with it.)

## 4. Windows device instance IDs

Captured via `Get-PnpDevice | Where-Object { $_.InstanceId -match 'VID_1234' }`:

```
USB\VID_1234&PID_ED02\UD20180927003B78              USB Composite Device
USB\VID_1234&PID_ED02&MI_00\6&8417E44&0&0000        USB Input Device   (interface 0)
USB\VID_1234&PID_ED02&MI_01\6&8417E44&0&0001        USB Input Device   (interface 1)
HID\VID_1234&PID_ED02&MI_00\7&E7460B0&0&0000        HID-compliant device
HID\VID_1234&PID_ED02&MI_01\7&21A47CEE&0&0000       HID-compliant vendor-defined device
```

Notes:
- The **serial is visible in the composite-device instance ID** (`USB\VID_1234&PID_ED02\<serial>`) — a handy way to read it without any HID code:
  ```powershell
  Get-PnpDevice | Where-Object { $_.InstanceId -match 'VID_1234' } | Select-Object InstanceId
  ```
- `MI_00` / `MI_01` are the two interfaces.
- The `HID\...\7&XXXX&0&0000` suffixes are **Windows-generated**, not hardware serials — don't mistake them for the real one.
- `&6&8417E44&0&000X` is a Windows bus-relative instance path; it can change if the dongle moves to another USB port.

## 5. Live capture evidence (2026-02-14)

```
interface 1 'EEG Signals': 1914 reports in 12 s  (~160/s)

new_crypto_key (correct)   byte1 distinct values =  2   {0x10: 1532, 0x20: 382}
crypto_key(is_research=F)  byte1 distinct values = 256   <- noise
crypto_key(is_research=T)  byte1 distinct values = 255   <- noise
```

- **EEG packets: 1532 / 1914 (80 %)**; status packets (`0x20`): 382 (20 %).
- Report rate ~160/s ⇒ EEG sample rate **≈128 Hz**. ✅ Consistent with the EPOC+ spec.
- **Decoded amplitudes 7–16 µV across all 14 channels** — textbook EEG scale.
- Lag-1 autocorrelation is **low (~0.1)**, which is *expected*: the headset was on a desk with **dry electrodes**, so this is noise floor, not brain signal.

This is a **positive control**: the wrong keys produce ~256 distinct values, the right one produces 2. Use this test before ever trusting a stream.

> ⬜ **Still to do:** the alpha test — headset on a head, saline-wetted pads, eyes-closed 8–12 Hz peak in O1/O2. Until that passes, we have proven the *pipeline*, not the *signal*. → [[roadmap]] §1.4


## 6. Reproduce everything

```powershell
# Read the serial straight from Windows, no Python needed:
Get-PnpDevice | Where-Object { $_.InstanceId -match 'VID_1234' } | Select-Object InstanceId

# Full HID probe (VID/PID/serial/per-interface + classification):
.venv\Scripts\python.exe scripts\probe_device.py

# Live read + decrypt + decode:
.venv\Scripts\python.exe scripts\read_live.py 12 live_capture.csv
```

## Related
[[common-info-eeg-device]] · [[identify-your-revision]] · [[ud2016-crypto-crack]] · [[connection-and-dongle]] · [[references]]
