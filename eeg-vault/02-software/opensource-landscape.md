---
title: Open-Source Landscape
type: moc
tags: [software, options, decision]
updated: 2026-02-14
---

# Open-Source Landscape — every route, ranked

**Answer to "is there a way?": yes, but with a real caveat, and the caveat is the project.**

There are three families of routes to get data out of an EPOC+ without paying Emotiv. They differ wildly in legality, legality-in-practice, effort, and what data you actually get.

## The decision matrix

| # | Route | Cost | Raw EEG? | Needs Emotiv cloud? | Maintenance | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| **A** | **USB dongle + community driver** ([[emokit]] lineage) | **free** | ✅ if crypto matches ⚠️ likely needs a patch | ❌ **no — fully offline** | ⚠️ **archived**; broken for `UD2017+` serials | ⭐ **try first, expect a fight** |
| **B** | **Cortex API** ([[cortex-api]]) | free tier; **raw EEG ≈ $1,068/yr** | 💰 **paywalled** | ✅ yes (Launcher + EmotivID + account) | ✅ officially maintained | strong fallback; **free streams are genuinely useful** |
| **C** | **Roll your own** on the HID protocol | free | ✅ potentially | ❌ no | you own it forever | the long game; route A's logic is the map |
| D | Buy/borrow non-Emotiv hardware | 💰 | ✅ | ❌ | ✅ | clean escape hatch |

## Route A — USB dongle + community driver ⭐

**How it works.** The dongle is a **USB HID** device, so `hidapi` can open it from user space with no kernel driver and no Emotiv software installed. The stream is AES-ECB encrypted with a key derived from the dongle's serial number; the community ([[emokit]], 2010–2017) reverse-engineered the key derivation and packet layout.

**Why it's the best route if it works.**
- **Zero cost, zero cloud, zero account.** No Emotiv Launcher, no EmotivID, no licence check, no telemetry.
- Works offline, on a plane, in a Faraday cage.
- Gives the actual raw EEG, uncompressed, at 128/256 Hz.
- You own the whole stack — which is the whole point of an open-source project.

**Why it might not work — and it probably won't be easy.**
- `emokit`'s README: **"Unsupported: Epoc+(2016+)"**, and the **repo is now ARCHIVED** (last functional commit 2017-04-17, last push 2019-07-05).
- ⚠️ **The `UD2016` bug.** `emokit` checks `serial.startswith("UD2016")` — a *literal string*, not a date test. A 2019/2020 dongle (`UD2019…`) silently falls through to the **wrong (legacy) key**. No flag fixes this; it needs a patch. Since this unit appears to be **2019–2020 vintage**, this is the most likely failure mode. → [[identify-your-revision]]
- Even on the *supported* `UD2016` path, testing showed decryption worked but sensor values were implausible and the rate capped at **~192 Hz** instead of 256 ([issue #229](https://github.com/openyou/emokit/issues/229)).
- **No verified working maintained open-source dongle reader for 2016+ exists.** `eugenehp/emotiv-rs` is a *Cortex API* client whose `raw` feature self-documents as **mock-only**.
- Risk of **silent failure**: a wrong AES key produces meaningless numbers rather than an error. → the alpha test in [[identify-your-revision]] is mandatory.
- Python 2/3 rot, `pycrypto` CVEs, Windows/Linux using different HID backends.

**The one piece of good news:** emokit is **read-only** — it cannot alter the dongle's pairing or consume a licence (maintainer, [issue #145](https://github.com/openyou/emokit/issues/145)). Trying costs only time.

**Action:** run `scripts/probe_device.py`, then classify with [[identify-your-revision]].

## Route B — Cortex API (official)

**How it works.** Emotiv Launcher runs locally; your app connects to its **JSON-RPC-over-WebSocket** endpoint, authenticates with an **EmotivID** and a registered **App ID (client id/secret)**, opens a session, and subscribes to data streams.

**What's free vs. paid** (confirmed from Emotiv's own docs):

| Stream | What it is | Licence needed? |
| --- | --- | --- |
| `eeg` | **raw EEG** | 💰 **yes — licence must contain scope `"eeg"`** |
| `mot` | motion / IMU | no |
| `dev` | battery, wireless signal, contact quality | no |
| `eq` | EEG quality per sensor | no |
| `pow` | **band power** (alpha, low/high beta, gamma, theta) | no |
| `met` | performance metrics | 0.1 Hz free; 2 Hz with scope `"pm"` |
| `com` | **mental commands** | no (needs a loaded profile to be meaningful) |
| `fac` | **facial expressions** | no |
| `sys` | training/system events | no |

**The honest read:** the free tier is more generous than the original frustration suggests — but the one thing you actually want for building your own DSP, **raw EEG**, is exactly the thing behind the paywall. Band power (`pow`) is free, which is a nice consolation prize (you can build a neurofeedback or attention app on it without touching raw samples), but you cannot do your own filtering, artefact rejection, epoching, or novel feature extraction on pre-computed band powers.

**What raw EEG costs, concretely** (verified 2026):

| Option | Price |
| --- | --- |
| EmotivPRO **Lite** | **$0** — no raw EEG |
| EmotivPRO **Standard** | **$89/mo billed annually = $1,068/year** |
| EmotivPRO **Standard Team** | **$224.08/mo billed annually = $2,689/year** |
| **Cortex API developer seat** | **€1,460.50 net (~€1,738 incl. VAT) / seat / year** |

⚠️ Which of these actually grants the Cortex `"eeg"` scope is **unresolved** — confirm with Emotiv support before paying. Also: *"API and Dev licenses are not currently available under Organization Licensing."*

Full detail, error codes, setup steps: → [[cortex-api]].

## Route C — Roll your own

Treat `emokit` not as a dependency but as **documentation of a protocol**. The knowledge needed is finite and already public:

1. Find the HID device (vendor `0x1234`, or a product string matching Emotiv hints).
2. Read 32- or 64-byte reports.
3. Derive the 16-byte AES key from the last 4 characters of the dongle serial ([[emokit]] has all three derivations).
4. AES-ECB decrypt; the 32-byte legacy case is two independent 16-byte blocks.
5. Unpack 14-bit little-field values from the bit-masks; scale by **≈0.51 µV/LSB**.

The licensing question for re-implementing from a public protocol description is *your* call — note emokit's own repo licence before copying code verbatim (see [[decisions-log]] ADR-003, which covers vendoring).

## Route D — Different hardware

Only if A and B both fail and the project must ship. OpenBCI Cyton = 8 **flexible** channels (including C3/C4/Cz, which the EPOC+ cannot reach) for a few hundred dollars. Not a fix for the EPOC+, a replacement for it. → [[ecosystems-without-support]]

## What the wider ecosystem gives you — and doesn't

- **BrainFlow / OpenBCI: no Emotiv support at all.** No `BoardIds.EMOTIV_*`. Verified. → [[ecosystems-without-support]]
- **MNE-Python, scipy, scikit-learn, matplotlib: fully usable** — they consume arrays/files, and don't care where the data came from.
- **LSL is the escape hatch.** Emit one LSL stream and OpenViBE, Timeflux, Brainstorm, LabRecorder, and Unity all become available. → [[lsl-and-interop]]

## Recommended sequence

```
1. probe_device.py                          -> serial -> manufacture date -> packet length
2. is the serial "UD2016..." or "UD20xx..."?
     yes -> PATCH emokit (or our vendored decoder) to treat UD20xx as new format
     no  -> use the stock legacy path
3. try the crypto paths in order:
     new_crypto_key()  ->  crypto_key(is_research=False)  ->  crypto_key(is_research=True)
     ->  epoc_plus_crypto_key() via force_epoc_mode
4. ALPHA TEST (eyes-closed 8-12 Hz peak in O1/O2)   <- do NOT skip
5. if it works -> vendor the logic (ADR-003), build the Source abstraction
   if it fails -> Cortex API free streams (pow/com/fac), or synthetic-only development
6. regardless  -> everything downstream depends only on the Source interface
```

## Related
[[common-info-eeg-device]] · [[identify-your-revision]] · [[emokit]] · [[cortex-api]] · [[ecosystems-without-support]] · [[lsl-and-interop]] · [[roadmap]] · [[references]]
