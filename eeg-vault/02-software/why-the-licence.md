---
title: Why Is There a Licence?
type: explainer
tags: [licensing, drm, business, history]
updated: 2026-02-14
---

# Why Is There a Licence?

This note exists because of a natural question: **if the community project is dead and unmaintained, why does Emotiv still demand a licence?**

The question contains a mix-up worth untangling, and the real answer is more interesting than "because they can".

## First: two different "projects"

The confusion comes from running two unrelated things together.

| | **emokit** | **Emotiv (the company)** |
| --- | --- | --- |
| What | volunteer reverse-engineering project | the manufacturer |
| Status | **archived**, dead since 2017 | **alive and shipping** (EPOC X, Flex, MN8, Insight, Cortex API) |
| Asks for money? | **never** | yes |
| Maintained? | no | **yes** — Cortex API and the Unity/LSL plugins are actively updated |

**emokit's death has no effect on Emotiv's licensing.** emokit was never Emotiv's product, never authorised, and never a substitute for what Emotiv sells. It was a bypass. A bypass project dying does not cause the lock to open.

Emotiv's licence revenue comes from **software** — EmotivPRO, BrainViz, the Cortex SDK — which are all still developed. The EPOC+ being an old model is irrelevant; the software business is current.

## Second: the licence is not just a contract — it is enforced in hardware

This is the part that actually answers the question. From emokit's protocol documentation, verbatim:

> **"To ensure that raw data is only read by those that have paid for the raw data license, each USB dongle encrypts incoming wireless data via AES against a key composed of the Serial Number of the dongle before emitting it as an HID report."**

Read that again, because it is unusually candid: **the encryption exists for the sole purpose of enforcing the licence.**

So the design is:

```
headset ──(unencrypted 2.4 GHz)──> dongle ──AES──> USB HID ──> host
                                       ▲
                          key derived from dongle serial;
                          the derivation ships only in the PAID SDK
```

- The data leaving the headset is **not** encrypted — *"It is assumed that data coming to the dongle from the wireless protocol is unencrypted, and all encryption happens on the dongle."*
- The dongle encrypts on the way out.
- The host must know the key derivation to read anything.
- That derivation was **only in the paid product**.

This is DRM. The dongle is the lock; the licence is the key. It is not a legal fiction layered on top of open hardware — it is a technical measure implemented in the device.

**Which means: abandoning emokit changes nothing, because the lock lives in the dongle's firmware, not in emokit.** There is no switch to flip.

## Third: the arms race is documented

emokit's FAQ describes the history plainly:

> "We managed to get lucky with the method for a while, because **Emotiv was reusing keys on USB dongles**, so one key would work for many headsets. Once Emotiv learned of this, they just had to **switch out the firmware flashing on their keys**, and emokit no longer worked."

And the protocol doc:

> "While one would figure that dongles would have unique serials, this was not necessarily the case for the first year or so… cracked decryption keys could be passed around as long as serials for USB dongles matched. **However, later headsets now have unique serials per USB dongle.**"

So the sequence was:

1. Emotiv reuses keys across dongles → one cracked key opens many headsets.
2. The community notices and shares keys.
3. Emotiv reflashes dongle firmware to give every dongle a unique serial → the shared keys stop working.
4. Daeken works out the *general* key-derivation algorithm (late 2011), restoring access.
5. Emotiv later changes the derivation again for 2016+ dongles (`UD2016…`), which is where emokit gave up.

**This is a deliberate, ongoing anti-circumvention effort** — not an accident of proprietary software. That is why the licence is asked for even now, and why it will keep being asked for.

## Fourth: what the licence actually buys today

| You want | Free tier | Paid |
| --- | --- | --- |
| Raw EEG via Emotiv's own API | ❌ | ✅ (scope `"eeg"`) |
| Band power, mental commands, facial expressions, motion, contact quality | ✅ | ✅ |
| Emotiv's recording/analysis app (EmotivPRO) | Lite only | ✅ |
| Cloud records, no expiring | ❌ (premium recordings **lock** when a licence lapses) | ✅ |
| Support, multi-seat, commercial terms | ❌ | ✅ |

The historical version of this was the **"raw data license"** the protocol doc refers to — Emotiv sold EPOC hardware with raw-data access as a separately-purchased entitlement, which is exactly what the OpenViBE-era forum threads about needing the *"Emotiv SDK Research Edition"* were about. The mechanism changed; the model did not.

## So — can it be bypassed?

**Yes, and it already has been.** [[ud2016-crypto-crack]] documents us verifying, offline, that emokit's `new_crypto_key` correctly decrypts real captured traffic from a `UD2016` dongle.

The important framing: bypassing the encryption on **hardware you own**, to read **your own brain data**, for **interoperability**, is a different act from piracy of Emotiv's software. What we are doing is reimplementing a data format. It is what emokit did publicly for seven years, and what the interoperability reverse-engineering tradition is built on.

Two honest caveats, neither of which is legal advice:

- Emotiv's EULA and website terms may prohibit reverse engineering. Contract terms and statutory interoperability rights can conflict, and the outcome is jurisdiction-dependent. **If this ever becomes commercial or public, get real advice.**
- The **paid software** (EmotivPRO, their cloud, their SDK binaries) is a different matter from the wire protocol. Don't redistribute their code. Vendoring **emokit** is fine — it is public domain (see `vendor/README.md`).

## The one-line answer

> The licence is asked for because **the encryption that enforces it lives in the dongle's firmware**, put there explicitly for that purpose, and Emotiv is still an active company selling software. emokit dying removes a *bypass*, not a *lock* — and a bypass is not a licence.

## Related
[[ud2016-crypto-crack]] · [[emokit]] · [[cortex-api]] · [[common-info-eeg-device]] · [[references]]
