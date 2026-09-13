---
title: Cortex API (official)
type: software
docs: https://emotiv.gitbook.io/cortex-api
transport: JSON-RPC 2.0 over WebSocket (wss://localhost:6868)
status: official, actively maintained
raw_eeg: PAYWALLED
price_of_raw_eeg: "~$1,068/yr (EmotivPRO Standard) or ~EUR 1,460.50 net/yr (Cortex API developer seat)"
tags: [software, cortex, emotiv, api, licensing, pricing]
updated: 2026-02-14
---

# Cortex API

Emotiv's official developer interface. **Maintained, documented, and reliable** — the opposite of [[emokit]] — but it runs through Emotiv's closed Launcher, authenticates against Emotiv's cloud, and **gates raw EEG behind a paid licence.** This is the "subscription" that made the headset feel unusable, now fully documented and priced.

## Architecture

```
your app ──wss://localhost:6868 (JSON-RPC 2.0)──> Emotiv Launcher ──> Emotiv cloud (auth + licence)
                                                         │
                                                  dongle / BLE
                                                         │
                                                     headset
```

Three consequences:
1. **Emotiv Launcher must be installed and running.** Closed source, not optional.
2. **Auth and licence checks go through Emotiv's cloud.** Not usable offline.
3. **Licence-bound**: `deviceLimit`, `devicesPerSeat`, `seatCount`, session quotas.

## The commercial model — in one table

Emotiv splits access into two tiers:

| Tier | What it includes | Cost |
| --- | --- | --- |
| **Basic (BCI API)** | Mental commands (`com`), facial expressions (`fac`), frequency/band power (`pow`), motion (`mot`), **low-res** performance metrics (`met` @ 0.1 Hz), contact quality & battery (`dev`, `eq`) | **free** |
| **Premium API** | **Raw EEG (`eeg`)**, **high-res performance metrics (`met` @ 2 Hz)** | **paid licence** |

And the tier you get free depends on the **headset class**:

| Headset class | Devices | Free access |
| --- | --- | --- |
| **Consumer** | Insight, MN8 | **all** data streams, free |
| **Professional** | EPOC X, EPOC Flex | **Basic BCI API only** — raw EEG needs a paid licence |

> ⚠️ **EPOC+ is not listed in either bucket** in Emotiv's own docs. But error code **`-32232` refers to "Professional devices (EPOC, Flex)"**, EPOC+ sits above Insight in the range, and Emotiv's authorised reseller states plainly that raw EEG requires a paid subscription. **Treat "EPOC+ raw EEG = paid" as a strong inference, not a verbatim Emotiv statement.** The definitive test is free: authenticate and call `getLicenseInfo` — see what `scopes` your EmotivID actually has.

## Prices (verified, 2026)

**EmotivPRO** — monthly, annual, 3-year and 5-year billing:

| Tier | Price |
| --- | --- |
| **Lite** | **$0 — "free forever"** |
| **Standard** | **$89.00/month billed annually = $1,068/year** |
| **Standard Team** | **$224.08/month billed annually = $2,689/year** |
| **Performance** | "Let's talk" — contact sales |

Also: **Cortex API developer seat licence — EUR 1,738.00 incl. 19% VAT (€1,460.50 net) for 1 seat / 1 year** (via authorised resellers).

Notes:
- **"API and Dev licenses are not currently available under Organization Licensing."**
- **"Only one license is permitted per EmotivID."**
- Software is **not** bundled with hardware: *"Access to EMOTIV's software platforms — such as EmotivPRO, BrainViz or Cortex SDK — must be purchased or subscribed to separately."*
- ⚠️ **Unresolved:** whether **EmotivPRO Standard ($1,068/yr)** alone grants the Cortex `eeg` scope, or whether the dedicated **Cortex API seat (€1,460.50/yr)** is separately required. The `getLicenseInfo` example shows a licence named `"PRO license"` with `applications: ["com.emotiv.emotivpro"]` and `scopes: ["eeg","pm"]`, which *suggests* EmotivPRO PRO carries the scope. **Confirm with Emotiv support before paying either.**
- ⚠️ Conflicting third-party claims about whether EmotivPRO **Lite** includes any raw-EEG recording inside the app (one reseller lists a 5-recording cap; another says raw EEG is paid-only).
- 🚨 **Your recordings can be held hostage.** Records are cloud-synced under a paid PRO licence, and when it expires the account drops to PRO-Lite and **premium recordings become locked/inaccessible.** If you ever go this route, **export everything regularly** — do not let Emotiv's cloud be the only copy of your data.

## Data streams

| Stream | Description | Licence | Rate |
| --- | --- | --- | --- |
| **`eeg`** | **raw EEG** | 💰 **scope `"eeg"` required** | 128 or 256 Hz |
| `mot` | motion / IMU | free | disabled / 32 / 64 / 128 Hz |
| `dev` | battery, wireless signal, contact quality | free | 2 Hz |
| `eq` | EEG quality per sensor | free | 2 Hz |
| `pow` | **band power**: alpha, low beta, high beta, gamma, theta | free | 8 Hz |
| `met` | performance metrics | free @ 0.1 Hz; scope `"pm"` for 2 Hz | 2 or 0.1 Hz |
| `com` | **mental commands** (needs a loaded profile) | free | 8 Hz |
| `fac` | **facial expressions** | free | 32 Hz |
| `sys` | training / system events | free | event-driven |

**The asymmetry is the whole story:** Emotiv gives away the *derived* data and sells the *raw* data. Every stream except `eeg` is free.

### What the free tier is actually good for

| Goal | Free enough? |
| --- | --- |
| Band-power neurofeedback (alpha training, focus meter) | ✅ via `pow` |
| Expression- or mental-command-driven demo | ✅ via `fac` / `com` |
| Contact-quality logging, signal-quality dashboards | ✅ via `dev` / `eq` |
| Motion / head-pose tracking | ✅ via `mot` |
| Your own filtering, artefact rejection, epoching | ❌ needs `eeg` 💰 |
| Novel features, ICA, source analysis, publication-grade DSP | ❌ needs `eeg` 💰 |
| Working offline / without Emotiv software | ❌ impossible |

> **This matters for the roadmap:** [[roadmap]] Phase 5's alpha neurofeedback app can be built on `pow` alone, for **free**, without ever touching raw EEG. Keep that as the fallback plan.

## The activation gate — where free users actually stop

The blocker is **not** just subscribing to `eeg`; it is **activating a session**.

- An **unactivated** session **cannot subscribe to `eeg`**, is limited to **0.1 Hz** performance metrics, and **cannot create records or markers**.
- Activating a session consumes a paid licence and debits session quota → free users get **`-32006`: "You have a paid EMOTIV license to activate a session"**.

### Error codes worth knowing before writing code

| Code | Meaning |
| --- | --- |
| `-32006` | No paid licence → cannot activate a session |
| `-32016` | `"The stream is 'eeg' but the license doesn't allow you to access this stream."` |
| `-32230` | Licence restricts which **headset types** may use `eeg`/`met` |
| `-32232` | `"License requires EEG"` — hit if you enable *"Enable EEG for Professional devices"* on the app without a licence. Emotiv's stated remedy: **buy a licence**, or recreate the app with the option off (and then never get raw EEG) |
| `-32019` | Session limit reached (raise via `authorize` with `debit`) |
| `-32022` | Device limit reached |
| `-32142` | **Unpublished apps are usable only by their creator.** Publishing requires contacting Emotiv support |

**Consequence of `-32142`:** an app you build is for *you* only until Emotiv agrees to publish it. Relevant if this ever becomes something other people run.

## Concrete setup for a hobbyist

**All of these are required:**

1. Create an **EmotivID** and activate it via the emailed link.
2. Install **EMOTIV Launcher** — it installs the Cortex service that serves `wss://localhost:6868`.
   - Supported: Windows 10 64-bit v1809+ / Win11, macOS 12+, Ubuntu 22.04+ (beta), iOS 16+/Android 9+ (beta), Raspberry Pi OS Debian 12 on Pi 4B/5 (beta).
3. Register a **Cortex App** to get **Client ID + Client Secret**.
4. Connect your code to **`wss://localhost:6868`** — **WebSocket Secure only**. Cortex uses a **self-signed certificate**, so Python/Android clients generally need Emotiv's **Root CA** (`rootCA.pem` from the official example repo). *This is a classic first-hour stumbling block.*
5. API flow:
   ```
   log into EMOTIV Launcher with your EmotivID
   requestAccess              -> then ACCEPT IT INSIDE THE LAUNCHER
   controlDevice "refresh"
   queryHeadsets              -> get the headset id
   controlDevice "connect"
   authorize (clientId, clientSecret)  -> cortexToken (valid 48 h, reusable ~2 days)
   createSession / updateSession status:"active"   <-- free users blocked here (-32006)
   subscribe [ "eeg", "pow", ... ]
   ```

### `queryHeadsets` on a dongle-connected EPOC+

The documented example response looks like:

```json
{ "connectedBy": "dongle",
  "id": "EPOCPLUS-3B9AXXXX",
  "firmware": "625",
  "sensors": [ ... 14 ... ],
  "settings": { "eegRate": 256, "eegRes": 16, "memsRate": 64, "memsRes": 16,
                "mode": "EPOCPLUS" } }
```

Wildcards for `queryHeadsets`: `EPOC-*`, `EPOCPLUS-*`, `INSIGHT-*`. Confirms the dongle path is officially supported — *conditional on licence*.

## Headset support & specs

Officially supported: **EPOC, EPOC+, EPOC X, EPOC Flex, Insight, Insight 2.0, MN8, Flex** (all firmware).

- **EPOC+ connects via USB dongle or BLE 4.0.**
- **EPOC+ raw EEG: 14 channels, 16-bit, 128 or 256 Hz** (128 Hz over Bluetooth).
  - ⚠️ Note this differs from the hardware spec sheet's *14-bit effective* figure ([[common-info-eeg-device]]). 16-bit is the transport/API resolution; 14-bit is the effective resolution after the noise floor. Not a contradiction, but don't mix them up.
- Cortex on Raspberry Pi: only one connected headset and one remote websocket at a time; EPOC Flex / MN8 not supported on Pi.

## Open-source clients

**Official (Emotiv):**
| Repo | Lang | Last push |
| --- | --- | --- |
| [Emotiv/cortex-example](https://github.com/Emotiv/cortex-example) | C#, Python, C++, JS | active (2026) — **start here** |
| [Emotiv/labstreaminglayer](https://github.com/Emotiv/labstreaminglayer) | C++/LSL | 2025-05 |
| [Emotiv/unity-plugin](https://github.com/Emotiv/unity-plugin) | C# | active (2026) |

**Community:**
| Repo | Lang | Last push | Note |
| --- | --- | --- | --- |
| [vtr0n/emotiv-lsl](https://github.com/vtr0n/emotiv-lsl) | Python | **2024-12** | LSL server, aimed at EPOC X. **Most actively maintained community option.** |
| [psychopy/psychopy-emotiv](https://github.com/psychopy/psychopy-emotiv) | Python | 2024-10 | Official PsychoPy extension; GPLv3; marking + recording components |
| [jmduea/NeuroClient](https://github.com/jmduea/NeuroClient) | Rust | 2026-09 | Cortex v2 client |
| [eugenehp/emotiv-rs](https://github.com/eugenehp/emotiv-rs) | Rust | 2026-04 | Cortex client; its `raw` feature is **mock-only** |
| [methylDragon/emotiv-cortex2-python-client](https://github.com/methylDragon/emotiv-cortex2-python-client) | Python | **2020-01 (stale)** | Widely cited; on PyPI as `cortex2`. Unmaintained. |

> **Structural trap:** an open-source *client* does not make the *service* open. Every one of these still needs **Emotiv Launcher + a paid `eeg` licence** for raw EEG. They save you WebSocket glue, not money.

## Verdict

| Use Cortex API when | Don't when |
| --- | --- |
| The USB-HID route fails on this unit | You need offline operation |
| You only need `pow` / `fac` / `com` / `mot` (**free**) | You want to own the whole stack |
| You want officially-supported reliability | You object to closed local middleware |
| You need multi-headset / multi-seat | You're doing novel raw-signal research (unless you pay) |

**Priority: strong fallback and the free-stream workhorse — not first choice.** Route A in [[opensource-landscape]] is free and offline; try it first.

## Sources
- <https://emotiv.gitbook.io/cortex-api/master> (tier definitions, supported headsets)
- <https://emotiv.gitbook.io/cortex-api/data-subscription>
- <https://emotiv.gitbook.io/cortex-api/session>
- <https://emotiv.gitbook.io/cortex-api/error-codes>
- <https://emotiv.gitbook.io/cortex-api/authentication/getlicenseinfo>
- <https://emotiv.gitbook.io/cortex-api/connecting-to-the-cortex-api>
- <https://emotiv.gitbook.io/emotivpro-v3/data-streams/raw-eeg>
- <https://www.emotiv.com/emotivpro#pricing>
- <https://www.mindtecstore.com/EMOTIV-Cortex-API-on-JSON-and-WebSockets> (reseller pricing)

## Related
[[opensource-landscape]] · [[emokit]] · [[common-info-eeg-device]] · [[lsl-and-interop]] · [[roadmap]] · [[references]]
