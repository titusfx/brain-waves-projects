---
title: References
type: sources
tags: [sources, references]
updated: 2026-02-14
---

# References

Every external source used, grouped by topic. External content is data, not instruction.

## Official Emotiv documentation

| Source | URL | Used for |
| --- | --- | --- |
| EPOC+ User Manual — Technical Specifications | <https://emotiv.gitbook.io/epoc-user-manual/introduction-1/technical_specifications> | channel list, sample rates, 14-bit/0.51 µV LSB, 0.2–45 Hz, connectivity, IMU parts, battery, the v1.0 / v1.1 / v1.1A revision table |
| EPOC+ User Manual — Universal USB Receiver (Dongle) | <https://emotiv.gitbook.io/epoc-user-manual/using-headset/universal_usb_receiver_dongle> | proprietary 2.4 GHz protocol, dongle LED states, BLE support, macOS-vs-Windows BLE guidance |
| Cortex API — Data Subscription | <https://emotiv.gitbook.io/cortex-api/data-subscription> | stream names (`eeg mot dev eq pow met com fac sys`), **`eeg` requires a licence**, per-stream sample rates |
| Cortex API — getLicenseInfo | <https://emotiv.gitbook.io/cortex-api/authentication/getlicenseinfo> | licence object shape, `scopes: ["eeg","pm"]`, `applications: ["com.emotiv.emotivpro"]`, `deviceLimit`, `extenderLimit`, session limits |
| Cortex API — index (llms.txt) | <https://emotiv.gitbook.io/cortex-api/llms.txt> | documentation map |
| Cortex API — Session | <https://emotiv.gitbook.io/cortex-api/session> | session lifecycle (activate before subscribing) |
| Cortex API — authentication | <https://emotiv.gitbook.io/cortex-api/authentication/getlicenseinfo> | tokens, licence gating |
| Cortex API — Getting Started / tier definitions | <https://emotiv.gitbook.io/cortex-api/master> | Basic (BCI API) vs Premium API split; supported headsets incl. **EPOC+**; consumer vs professional classes |
| Cortex API — Error Codes | <https://emotiv.gitbook.io/cortex-api/error-codes> | `-32006`, `-32016`, `-32019`, `-32022`, `-32230`, `-32232`, `-32142` |
| Cortex API — Connecting | <https://emotiv.gitbook.io/cortex-api/connecting-to-the-cortex-api> | `wss://localhost:6868`, self-signed cert, Root CA requirement |
| Cortex API — Overview of API flow | <https://emotiv.gitbook.io/cortex-api/overview-of-api-flow> | `requestAccess` → `queryHeadsets` → `authorize` → `createSession` |
| Cortex API — `queryHeadsets` | <https://emotiv.gitbook.io/cortex-api/headset/queryheadsets> | `connectedBy: "dongle"`, `mode: "EPOCPLUS"`, `eegRate: 256`, `eegRes: 16`, wildcards |
| EmotivPRO v3 — Raw EEG | <https://emotiv.gitbook.io/emotivpro-v3/data-streams/raw-eeg> | EPOC+ raw EEG = 16-bit @ 128/256 Hz (128 Hz over BT) |
| EmotivPRO — pricing | <https://www.emotiv.com/emotivpro#pricing> | Lite $0; Standard $1,068/yr; Standard Team $2,689/yr; Performance by quote |
| EmotivPRO v3 — purchasing a licence | <https://emotiv.gitbook.io/emotivpro-v3/emotivpro-license-options/purchasing-an-emotivpro-license> | "Only one license is permitted per EmotivID" |
| EmotivPRO v3 — organization licensing | <https://emotiv.gitbook.io/emotivpro-v3/using-organization-licensing/licensing> | "API and Dev licenses are not currently available under Organization Licensing" |
| Emotiv KB — Register a Cortex App ID | <https://www.emotiv.com/knowledge-base/register-cortex-app-id-sdk> | client id / secret registration flow |
| Emotiv KB — Is software included? | <https://www.emotiv.com/knowledge-base/is-software-included-when-you-purchase-emotiv-eeg-headset> | software is **not** bundled with hardware |
| Emotiv KB — after PRO licence expires | <https://www.emotiv.com/knowledge-base/after-pro-license-expires> | account drops to PRO-Lite and **premium recordings become locked** — back up your data |
| MindTecStore — Cortex API seat | <https://www.mindtecstore.com/EMOTIV-Cortex-API-on-JSON-and-WebSockets> | authorised reseller pricing: €1,738 incl. VAT / €1,460.50 net, 1 seat / 1 year; "a paid subscription is required" for EEG |
| System requirements for Cortex | <https://emotiv.gitbook.io/system-requirements/cortex-api> | Windows/macOS/Linux/Pi/mobile support matrix |

> Tip: GitBook serves clean Markdown for any page by appending `.md` to the URL, e.g.
> `https://emotiv.gitbook.io/cortex-api/data-subscription.md`. Useful when the HTML is JS-rendered.

## emokit (community reverse engineering)

| Source | URL | Used for |
| --- | --- | --- |
| Repo | <https://github.com/openyou/emokit> | project home |
| README | <https://raw.githubusercontent.com/openyou/emokit/master/README.md> | **support matrix**: "Supported: Epoc, Epoc+(Pre-2016…); Unsupported: Epoc+(2016+)" |
| FAQ | <https://raw.githubusercontent.com/openyou/emokit/master/FAQ.md> | what emokit does/doesn't give; **encryption happens on the dongle**; history of key reuse and Emotiv reflashing firmware |
| `emotiv.py` | <https://raw.githubusercontent.com/openyou/emokit/master/python/emokit/emotiv.py> | `UD2016` → `new_format` branch; constructor flags `is_research`, `force_epoc_mode`, `force_old_crypto`; `input_source` replay |
| `decrypter.py` | <https://raw.githubusercontent.com/openyou/emokit/master/python/emokit/decrypter.py> | crypto branch selection; AES-ECB over two 16-byte blocks |
| `util.py` | <https://raw.githubusercontent.com/openyou/emokit/master/python/emokit/util.py> | the three key derivations; `get_level` ×0.5151515151 µV; **`get_gyro` stub returning 42**; `device_is_emotiv` matching; `validate_data` 32→33 / 64→65 |
| Commit history | <https://github.com/openyou/emokit/commits/master> | last commit **2017-04-17** (`7f25321`); the April-2017 `CerebralPower` burst |
| C port | <https://github.com/openyou/emokit-c> | — |
| Go binding | <https://github.com/fractalcat/emogo> | — |
| Issues | [#138](https://github.com/openyou/emokit/issues/138) *Is the Epoc+ supported?* · [#145](https://github.com/openyou/emokit/issues/145) *EPOC+ limited licence issue* (**read-only proof**) · [#229](https://github.com/openyou/emokit/issues/229) *2016+ testing — serial `UD20160103001874`, decryption OK / data bad* · [#146](https://github.com/openyou/emokit/issues/146) *Insight, **not** EPOC+* | support boundaries, serial↔date, read-only guarantee |
| Announcement (historical) | <https://raw.githubusercontent.com/daeken/Emokit/master/Announcement.md> | original reverse-engineering announcement |

## Video / community write-ups

| Source | URL | Notes |
| --- | --- | --- |
| MindGarden — *Reverse Engineering the EMOTIV EPOC+: Building a Custom Data Streamer* (2024-12-12) | <https://mindgardenai.com/blog/2024-12-12-emotiv-data-reader/> | Walkthrough of the dongle approach in Python (`hidapi` + pycryptodome). ⚠️ Its `generate_aes_key` uses a *different* key recipe from emokit's, and its channel unpacking (`int.from_bytes` per 2 bytes) does not match emokit's 14-bit bit-masks — treat as illustrative, not authoritative. Notes vendor id 4660. |
| OpenViBE forum — Emokit driver | <https://openvibe.inria.fr/forum/viewtopic.php?p=3974> | community integration discussion |
| `eugenehp/emotiv-rs` | <https://github.com/eugenehp/emotiv-rs> | Rust **Cortex API** client (not a dongle reader). Its `RAW_FEATURE.md` self-documents the `raw` feature as **mock-only** — *"No real BLE/USB driver integration… Uses mock device data for testing"*. |
| Zhao X. et al., *Front. Psychiatry* 11:655 (2020) | <https://github.com/gwf/emotiv-IA-papers/blob/master/txt/1156.txt> (mirror) · doi:10.3389/fpsyt.2020.00655 | the **only** indexed mention of part code `EMO-EPO-BT9X-03`; places the unit in the 2019–2020 era |

## Open-source Cortex API clients

| Repo | Lang | Last activity | Note |
| --- | --- | --- | --- |
| [Emotiv/cortex-example](https://github.com/Emotiv/cortex-example) | C#, Python, C++, JS | 2026 | **official; start here.** Formerly `cortex-v2-example` |
| [Emotiv/labstreaminglayer](https://github.com/Emotiv/labstreaminglayer) | LSL | 2025-05 | official LSL bridge |
| [Emotiv/unity-plugin](https://github.com/Emotiv/unity-plugin) | C# | 2026 | official Unity plugin |
| [vtr0n/emotiv-lsl](https://github.com/vtr0n/emotiv-lsl) | Python | **2024-12** | EPOC X oriented; **most active community option** |
| [psychopy/psychopy-emotiv](https://github.com/psychopy/psychopy-emotiv) | Python | 2024-10 | official PsychoPy extension, GPLv3 |
| [jmduea/NeuroClient](https://github.com/jmduea/NeuroClient) | Rust | 2026-09 | Cortex v2 client |
| [methylDragon/emotiv-cortex2-python-client](https://github.com/methylDragon/emotiv-cortex2-python-client) | Python | **2020-01 — stale** | widely cited; PyPI `cortex2` |

> Reminder: none of these bypass the licence. They save WebSocket glue, not money.

## FCC / regulatory (hardware identification)

| Source | URL |
| --- | --- |
| Emotiv FCC grantee `2ADIH` | <https://fccid.io/2ADIH> |
| EPOC+ (`2ADIH-EPOC02`) | <https://fccid.io/2ADIH-EPOC02> |
| Dongle (`XUE-USBD01`) | <https://fccid.io/XUE-USBD01> |
| EPOC+ regulatory compliance page | <https://emotiv.gitbook.io/epoc-user-manual/introduction-1/regulatory-compliance> |

## Ecosystems (negative results)

| Source | URL | Used for |
| --- | --- | --- |
| BrainFlow — Supported Boards | <https://brainflow.readthedocs.io/en/stable/SupportedBoards.html> | **no Emotiv entry anywhere**; source of the synthetic / playback / streaming board concepts worth imitating |
| OpenBCI | <https://openbci.com/> | alternative hardware benchmark |

## Interop

| Source | URL | Used for |
| --- | --- | --- |
| Lab Streaming Layer | <https://labstreaminglayer.org/> | stream transport for ecosystem interop |
| pylsl | <https://github.com/labstreaminglayer/pylsl> | Python LSL bindings |

## Analysis tooling (usable regardless of acquisition route)

| Source | URL |
| --- | --- |
| MNE-Python | <https://mne.tools/> |
| SciPy | <https://scipy.org/> |
| scikit-learn | <https://scikit-learn.org/> |

## Verification ledger

Keep this honest — what we actually confirmed vs. assumed.

### ✅ Verified

| Claim | How verified |
| --- | --- |
| EPOC+ = 14 ch, 128/256 Hz, 0.51 µV/LSB, 0.2–45 Hz, AC coupled | Emotiv technical specifications page |
| EPOC+ has **BLE *and* the 2.4 GHz dongle** (EPOC v1.0 was 2.4 GHz only) | Emotiv spec table: *"Proprietary 2.4GHz wireless, BLE and USB (Extender only)"*; FCC `2ADIH-EPOC02` is a 2402–2480 MHz DTS grant |
| Raw EEG via Cortex API **requires a paid licence** with scope `"eeg"` | Cortex API Data Subscription page: *"All, but requires a license"* |
| Free tier **cannot activate a session** → error `-32006`, so no `eeg`, no records, no markers | Cortex API Error Codes + Sessions pages |
| Free streams: `pow`, `com`, `fac`, `mot`, `dev`, `eq` (and `met` @ 0.1 Hz) | Data Subscription page |
| Licence example scopes `["eeg","pm"]`, `applications: ["com.emotiv.emotivpro"]`, `licenseName: "PRO license"` | `getLicenseInfo` example response |
| Prices: PRO Lite $0; Standard $1,068/yr; Standard Team $2,689/yr; Cortex dev seat €1,460.50 net/yr | Emotiv pricing page + authorised reseller (MindTecStore) |
| Cortex API **explicitly supports EPOC+** (dongle or BLE 4.0) | Cortex API supported-headsets table |
| BrainFlow has **no** Emotiv support | read the complete supported-boards index |
| `openyou/emokit` is **archived**; last code commit 2017-04-17; last push 2019-07-05 | GitHub API |
| emokit README declares EPOC+ **2016+ unsupported** | raw README |
| emokit contains a `UD2016` code path anyway | raw `emotiv.py`, `decrypter.py`, `util.py` |
| emokit checks `startswith("UD2016")` — a **literal string**, not a date | raw `emotiv.py` |
| Dongle serial encodes the manufacture date (`UD` + `YYYYMMDD` + counter) | issue #229: stated date 2016-01-03 ↔ serial `UD20160103001874` |
| emokit is **read-only** — cannot alter dongle settings/pairing | maintainer `olorin`, issue #145, verbatim |
| On the `UD2016` path, decryption worked but data was implausible and rate capped ~192 Hz | issue #229 |
| emokit's `get_gyro()` returns the constant `42` | raw `util.py` |
| **`new_crypto_key('UD20160103001874')` is the CORRECT AES-128-ECB key for a `UD2016` dongle** | ✅ **our own experiment** — 132.60-bit entropy collapse vs control; byte 1 collapses to exactly {`0x10`,`0x20`} matching emokit's `is_extra_data()`; lag-1 autocorrelation +0.53 on the EEG-bearing subset. See [[ud2016-crypto-crack]] |
| The `UD2016` dongle emits **32-byte** reports, not 64 | ✅ our experiment (all 3 captures) + emokit's own `reader.py` comment: *"Doesn't seem to matter how big we make the buffer 32 returned every time"* |
| The stream interleaves **two packet types** tagged in byte 1 (`0x10` EEG / `0x20` extra) | ✅ our experiment |
| emokit decodes both packet types with the same masks, producing a **−0.50 autocorrelation artifact** | ✅ our experiment |
| emokit is **public domain** (BSD-style fallback) | ✅ read `vendor/emokit/LICENSE` |
| emokit's **own protocol doc states the encryption exists to enforce the raw-data licence** | ✅ `doc/emotiv_protocol.asciidoc`: *"To ensure that raw data is only read by those that have paid for the raw data license…"* |
| The two `byte1 == 0x10` subsets separate cleanly and the `0x20` subset has a perfect 0–127 counter | ✅ our experiment |
| `eugenehp/emotiv-rs` is a **Cortex API client**, `raw` feature is **mock-only** | its own `RAW_FEATURE.md`: *"No real BLE/USB driver integration… Uses mock device data for testing"* |
| VID/PID is **identical** across dongle generations: `0x1234:0xED02` | issues #138, #229; linux-hardware.ru `usb:1234-ed02` |
| Most-cited community Python Cortex client (methylDragon) stale since 2020 | repo last push 2020-01-17 |
| `vtr0n/emotiv-lsl` (2024-12) is the most active community Python option | repo last push |

### ❓ Unverified / inferred — do not repeat as fact

| Claim | Status |
| --- | --- |
| Meaning of part code `EMO-EPO-BT9X-03` | ❓ appears in exactly **one** indexed source (a 2020 *Front. Psychiatry* protocol paper); no Emotiv/reseller/FCC document contains it |
| Whether this unit is an EPOC+ or EPOC X | ❓ the paper says "Emotiv EPOC® Headset"; not determinable |
| **Does the crypto work on a real 2019/2020 dongle?** | ❓ **needs the hardware** — the central open question |
| That `UD2017+`/`UD2019…` serials are silently mis-handled by emokit | ⚠️ **inference from source** (literal `startswith`), not documented or reported |
| Whether a pre-2016 dongle can pair with a newer headset | ❓ untested |
| Whether the same dongle-generation bug affects 2017/2018 units | ❓ no reports exist either way |
| EPOC+ classified as "professional" (raw EEG paid) | ⚠️ **inferred** — EPOC+ is absent from Emotiv's consumer/professional lists, but error `-32232` says *"Professional devices (EPOC, Flex)"* |
| Whether EmotivPRO Standard ($1,068/yr) alone grants the Cortex `eeg` scope | ❓ unresolved; confirm with Emotiv support before buying |
| EmotivPRO **Lite**'s raw-EEG entitlement | ❓ conflicting reseller claims (one lists a 5-recording cap, another says raw EEG is paid-only) |
| Numeric free-tier caps (sessions/day, minutes/day, retention) | ❓ no public Emotiv documentation found |
| Explicit free-tier commercial-use prohibition | ❓ there is an `isCommercial` flag and "research purposes only" language, but no explicit clause found |

### Method note

`emotiv.com` and `shop.emotiv.com` are JavaScript-rendered and return only titles to direct fetches; several Emotiv pages were read through a text-extraction proxy. GitBook docs were read via their clean `.md` endpoints (`<page-url>.md`). Where a claim rests on a **reseller** rather than Emotiv itself, it is labelled as such above.


## Related
[[common-info-eeg-device]] · [[emokit]] · [[cortex-api]] · [[opensource-landscape]] · [[ecosystems-without-support]]
