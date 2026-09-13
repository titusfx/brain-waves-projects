---
title: Identify Your Revision
type: procedure
tags: [device, diagnostic, emokit, crypto, critical-path]
updated: 2026-02-14
---

# Identify Your Revision (do this first)

**Why this is the first task:** `emokit`'s README declares the boundary explicitly —

> **Supported:** Epoc, Epoc+(Pre-2016, limited gyro sensors)
> **Unsupported:** Epoc+(2016+), other models.

— and that boundary is decided by **the USB serial number of the dongle**, which drives *both* the AES key derivation *and* the packet format (32 vs 64 bytes). Nothing else distinguishes the generations: **VID/PID is identical on both** (`0x1234:0xED02`), so it cannot be used to tell them apart.

> 🎯 **UPDATE — the `UD2016` crypto is now CONFIRMED WORKING.** We tested emokit's own captured ciphertext offline and verified that `new_crypto_key()` produces the correct AES-128-ECB key, and the full packet layout is solved. See [[ud2016-crypto-crack]].
>
> 🟢 **BUT THIS MAY NOT EVEN APPLY TO US.** The dongle label reads **"Emotiv EPOC+™ Model 1.1"** with **FCC ID XUE-USBD01** — which points at the **pre-2016** generation, the one `emokit` genuinely supports. See §0 below before doing anything else.

## §0 — ANSWERED: this unit is a **2018** dongle

Measured live on **2026-02-14**. Everything below is settled; the rest of this note is kept as the general procedure.

```
serial : UD20180927003B78     -> UD + 2018-09-27 + 003B78
VID    : 0x1234   PID: 0xED02
data   : HID interface 1, product string "EEG Signals"
gen    : UD2018  = post-2016 "new format"
key    : new_crypto_key("UD20180927003B78") -> b'4778887141771174'
```

**⇒ Full ID registry: [[device-identifiers]].**

### ❌ A wrong inference, corrected

The dongle's printed label says **"Emotiv EPOC+™ Model 1.1"** with **FCC ID `XUE-USBD01`** (a 2010 grant, grantee *Emotiv Systems Inc*). I initially concluded this pointed at the **pre-2016** generation that emokit genuinely supports.

**That was wrong.** The serial proves the unit is **`UD2018`**. The dongle design and FCC ID were simply reused for years. Lesson recorded: **only the serial dates the unit; the printed label does not.**

### ✅ The predicted trap, confirmed on real hardware

`emokit` branches on `serial.startswith("UD2016")` — a **literal** string. `UD20180927003B78` does not match, so emokit **silently uses the legacy key and emits garbage**. Verified live with `scripts/read_live.py`:

| key derivation | distinct `byte1` values | verdict |
| --- | --- | --- |
| **`new_crypto_key()`** | **2** (`0x10`, `0x20`) | ✅ correct |
| `crypto_key(is_research=False)` | 256 | ❌ noise |
| `crypto_key(is_research=True)` | 256 | ❌ noise |

So: use `new_crypto_key()` and the little-endian layout. → [[ud2016-crypto-crack]]

## 🚨 §0.1 — DO NOT UPDATE THE FIRMWARE

This is the single most important warning in this vault.

`toniorte`, [issue #138](https://github.com/openyou/emokit/issues/138), 2015-06-02, verbatim:

> *"you will be able to read raw data with Emokit **as long as you don't update device's firmware** (when Emotiv tricksters — sorry, developers — release the update… this summer?)"*

The firmware update is precisely what introduced the `UD2016` crypto that broke emokit. A working pre-2016 dongle plus a firmware update equals a broken setup — **irreversibly**, since dongle firmware is not downgradable by us.

**Therefore:**
- ❌ **Do not install or run Emotiv Launcher on the machine with the dongle attached.** It is the delivery mechanism for firmware updates.
- ❌ Do not run EmotivPRO / Testbench / the old Emotiv Control Panel.
- ✅ Our route needs **none** of them — `hidapi` talks to the dongle directly.
- ⚠️ If the unit has *already* been updated at some point, we are back on the `UD2016` path — which we have now also solved. Either way we can proceed; we just must not make it worse.

> Note: this is a *risk-prevention* instruction, not a claim that the unit is un-updated. The serial number will tell us definitively.


## The serial number encodes the manufacture date ⭐

Emotiv dongle serials follow:

```
U D 2 0 1 6 0 1 0 3 0 0 1 8 7 4
└─┘ └───────┘ └───────────────┘
"UD"  YYYYMMDD   unit counter
      = 2016-01-03
```

Confirmed by a real case: an owner reported a headset with a *"manufactured date of Jan 03, 2016"*, and the `hid_info` dump in the same thread shows serial **`UD20160103001874`**. ([emokit issue #229](https://github.com/openyou/emokit/issues/229))

**So the serial tells you the dongle's build date outright.** This is a far better discriminator than the marketing name, and it is exactly why the README says "2016".

## The trap: emokit only matches the literal string `"UD2016"` ⚠️

```python
# python/emokit/emotiv.py
if self.serial_number.startswith("UD2016") and not self.force_epoc_mode:
    self.new_format = True
```

That is a **literal string comparison**, not a date test. Consequences:

| Serial | emokit's behaviour | Reality |
| --- | --- | --- |
| `UD2016…` | ✅ takes the `new_format` branch: 64-byte packets, `new_crypto_key()` | matches |
| `UD2017…`, `UD2018…`, `UD2019…`, `UD2020…` | ❌ **falls through to the legacy branch**: 32-byte packets, `crypto_key()` | **wrong** — these are also "new format" dongles |
| anything else | legacy branch | maybe right |

A GitHub issue search for `UD2017`/`UD2018`/`UD2019` in the emokit repo returns **zero results** — nobody ever reported or fixed this. It is a silent, unhandled case.

> ℹ️ **This is inference from the code, not a documented fact.** But the code is unambiguous: `startswith("UD2016")` is a literal compare, and the author's own commit messages are hedged (*"Fixed epoc+ sensor data**?**"*). Treat it as a very strong hypothesis to test.

**Why it matters here:** the owner's unit (`EMO-EPO-BT9X-03`) appears in a 2020 protocol paper and was in use **2019–2020** — the `UD2019…`/`UD2020…` era. **If that is the serial prefix, stock emokit will silently pick the wrong key and emit garbage without erroring.** → see §"What to do about it".

## Full decision table

| Serial pattern | Packet length | Crypto function | Packet class | emokit handles it? |
| --- | --- | --- | --- | --- |
| `UD2016…` | 64 | `new_crypto_key()` | `EmotivNewPacket` | ✅ yes (poorly — see below) |
| `UD2016…` + `force_epoc_mode=True` | 64 | `epoc_plus_crypto_key()` | `EmotivOldPacket` | partial |
| `UD2017…`–`UD202x…` | 64 | *should be* `new_crypto_key()` | `EmotivNewPacket` | ❌ **silently falls through to legacy** |
| anything else | 32 | `crypto_key(serial, is_research)` | `EmotivOldPacket` | ✅ yes — the genuinely supported generation |

### How well does the `UD2016` path actually work?

Not well. From [issue #229](https://github.com/openyou/emokit/issues/229), where a user tested a real 2016 dongle:

- ✅ **Decryption worked**: *"The good news, decryption is working it seems."*
- ❌ sensor values were **implausible**
- ❌ sampling **capped at ~192 Hz** instead of 256
- ❌ **battery** had to be hardcoded to 0
- ❌ **X/Y gyro "were still moving" while stationary**

Issue closed 2017-04-14. The maintainer's own final commits are hedged: *"Fixed epoc+ sensor data**?**"*, *"…set old epoc get_level to something reasonable, maybe."*

**Expect to fix the unpacking yourself even when the crypto works.**

## Good news: emokit is read-only

A recurring worry is that using a community driver might disturb the dongle's pairing or the licence. It will not. Maintainer `olorin`, [issue #145](https://github.com/openyou/emokit/issues/145), verbatim:

> "Emokit will not change the dongle settings in any way (that I've been able to detect or find remotely plausible); the interface is read-only."

Running emokit is non-destructive. Try it without fear.

> 📝 **Correction to common lore:** issue **#146 is *not* about the EPOC+** — its title is *"is the emotiv insight supported?"*, opened and closed the same day (2015-07-14). Don't cite it as EPOC+ evidence.

## Procedure

### Step 1 — Plug in the dongle and probe HID

```powershell
pip install hidapi
py scripts\probe_device.py --all
```

The script enumerates USB HID, matches Emotiv (`0x1234`, `0xED02`, or a matching product string), and prints VID/PID/serial plus:

- the **decoded manufacture date** from the serial
- the inferred crypto path and packet length
- an explicit **warning if the serial is `UD2017…`+** (the unhandled case)

Known identity to look for:

| Field | Value |
| --- | --- |
| vendor_id | `0x1234` (4660) |
| product_id | `0xED02` (60674) |
| product_string | `Brain Computer Interface USB Receiver/Dongle` |
| manufacturer | `Emotiv` |
| interfaces | **two** HID interfaces (`interface_number` 0 and 1) |

> ⚠️ **Two interfaces.** emokit's Windows path does `device = devices[1]` — it takes the **second** match. If reads return nothing on one interface, try the other.

### Step 2 — Record the result

```yaml
serial_number: "?"
mfg_date: ?            # decoded from UD + YYYYMMDD
vendor_id: 0x1234
product_id: 0xED02
packet_length: ?       # 32 or 64
crypto_path: ?         # crypto_key | new_crypto_key | epoc_plus_crypto_key
generation: ?          # legacy | UD2016 | UD20xx-unhandled
probe_date: ?
```

### Step 3 — Fill in the gaps by hand

```python
# py -c "..."  or a scratch script
from emokit.util import crypto_key, new_crypto_key, epoc_plus_crypto_key, is_old_model

serial = "UD2019..."                     # <- paste yours
print(new_crypto_key(serial))            # inspect the 16-byte key
print(crypto_key(serial, is_research=False))
print(epoc_plus_crypto_key(serial))
print("old_model:", is_old_model(serial))
```

Note `is_old_model(serial)` returns `False` **iff the serial ends in `"GM"`**, else `True`.

### Step 4 — ⭐ THE ALPHA TEST (the real acceptance test)

**Do not skip this.** A wrong AES key does **not** raise an error — it silently produces meaningless numbers. You can build an elaborate pipeline on noise and never notice. Metadata cannot save you; only physiology can.

Protocol:
1. Wet all 14 felt pads with saline, headset on, all contacts reading **Good/Excellent**.
2. Subject relaxed, still, eyes **closed** for ~30 s, then eyes **open** for ~30 s.
3. Compute a PSD of `O1`/`O2`.

**Pass criteria:**
- eyes **closed** → clear peak at **8–12 Hz** (alpha)
- eyes **open** → that peak **attenuates**
- packet rate steady at **128 or 256 Hz**

| Symptom | Diagnosis |
| --- | --- |
| Alpha peak appears/disappears correctly | ✅ acquisition works — proceed |
| High-entropy, structureless signal; PSD is flat-ish | ❌ **wrong AES key** — try the next crypto path |
| Signal looks like a slow drift / huge slow waves | poor contact, drying saline, or motion |
| ~10 Hz everywhere regardless of eyes | probably mains artefact or aliasing — check the notch and rate |
| Sample rate ~192 Hz when set to 256 | known `UD2016` unpacking bug (issue #229) |

## What to do about the `UD2017+` trap

Since the branch is a literal `startswith`, **no flag fixes it.** Options, cheapest first:

1. **Monkey-patch / subclass** `Emotiv` (or, better, our vendored decoder) so `new_format` is set and `new_crypto_key()` is used for *any* `UD20xx` serial, not just `UD2016`.
   ```python
   import emokit.emotiv as em
   _orig = em.Emotiv.run
   # ...or simply construct with serial_number=... and force the flag
   ```
   The cleanest form: vendor the decode logic and choose the path on the *date*, not the literal string. → [[decisions-log]] ADR-003.
2. **`force_epoc_mode=True`** → uses `epoc_plus_crypto_key()` and `EmokitOldPacket`. Its introducing commit says *"not functional yet"*, so this is a long shot, but it is free to try.
3. **Try an older dongle.** Because the key derives from **the dongle**, not the headset, a pre-2016 dongle would take the well-supported code path. ⚠️ **Whether an old dongle can pair with a newer headset is unverified** — pairing state lives on the dongle. Untested, but a cheap experiment if one turns up.
4. **Fall back to Cortex API** for the free streams, accepting raw EEG is paywalled. → [[cortex-api]]
5. **Develop against synthetic data** and treat this as a hardware-agnostic project. → [[roadmap]] Phase 2.

## Related
[[common-info-eeg-device]] · [[emokit]] · [[connection-and-dongle]] · [[cortex-api]] · [[opensource-landscape]] · [[roadmap]] · [[references]]
