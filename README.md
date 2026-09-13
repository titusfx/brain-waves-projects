# brain-waves-projects

Open-source tooling for the **Emotiv EPOC+** 14-channel mobile EEG headset
(owner's part code `EMO-EPO-BT9X-03`) — getting raw EEG out of a device whose
vendor gates it behind a paid licence.

> **Project knowledge lives in an Obsidian vault: [`eeg-vault/`](eeg-vault/Home.md).**
> Start there. It is the durable memory of this project.

## TL;DR

| | |
| --- | --- |
| **The problem** | Emotiv's official API (Cortex) requires a **paid licence** (~$1,068/yr) for **raw** EEG, and blocks free accounts at session activation with error `-32006`. The community USB driver (`emokit`) is free and offline but **archived** (last real commit April 2017) and officially does not support EPOC+ units from **2016 onwards**. The modern open ecosystem (BrainFlow, OpenBCI) has **zero** Emotiv support. |
| **The sharp edge** | `emokit` picks its crypto with `serial.startswith("UD2016")` — a *literal string*, though serials encode the build date (`UD2016`+`0103`+counter). This unit is `UD20180927003B78` (**2018-09-27**), which fails that test too, so stock emokit silently uses the **wrong key**. The decoder here picks the crypto path from the *parsed date* instead. |
| **The plan** | Determine empirically which acquisition route works on *this* unit, prove it with the alpha test, hide it behind a `Source` interface, and build everything downstream to be device-agnostic. |
| **Where we are** | The protocol is solved and **verified on this unit**: 32-byte AES-128-ECB reports, 16-bit little-endian fields, `1 LSB = 0.51 µV`, **159 reports/s** sustained over 180 s, 14/14 channels in the 10–85 µV physiological range. The one substantive task left is proving the signal is a real brain — the **alpha test**. |
| **The consolation prize** | The **free** Cortex tier still gives band power, mental commands, facial expressions, motion and contact quality — enough to ship a real app for $0. |
| **The first step** | `.venv\Scripts\python.exe scripts\live_view.py` — plug the dongle in and watch. Every run is recorded, and `--replay` re-watches it later. |

## Layout

```
brain-waves-projects/
├── eeg-vault/                     # Obsidian vault — open this folder as a vault
│   ├── Home.md                    # map of content, start here
│   ├── 01-device/
│   │   ├── common-info-eeg-device.md   # canonical spec + capability/limits
│   │   ├── identify-your-revision.md   # ⭐ do this first
│   │   └── connection-and-dongle.md
│   ├── 02-software/
│   │   ├── opensource-landscape.md     # decision matrix of all routes
│   │   ├── ud2016-crypto-crack.md      # 🎯 RESULTS: crypto verified offline
│   │   ├── why-the-licence.md          # why the licence exists (DRM in firmware)
│   │   ├── emokit.md                   # the community driver
│   │   ├── cortex-api.md               # the official API + what's paywalled
│   │   ├── ecosystems-without-support.md
│   │   └── lsl-and-interop.md
│   ├── 03-project/
│   │   ├── roadmap.md
│   │   ├── decisions-log.md
│   │   └── glossary.md
│   └── 99-sources/references.md
├── scripts/
│   ├── live_view.py               # ⭐ real-time viewer; records every run, replays one
│   ├── record.py                  # record N seconds of decoded uV to a datestamped CSV
│   ├── alpha_test.py              # the acceptance test: eyes-closed/open + verdict
│   ├── monitor.py                 # is data flowing? every 3 s
│   ├── recording_paths.py         # where recordings go (recordings/<name>_<datestamp>)
│   ├── decode_to_csv.py           # reference decoder (imported by the others)
│   ├── read_live.py               # low-level capture + key check
│   ├── probe_device.py            # identify the dongle / pick the crypto path
│   ├── test_ud2016_crypto.py      # test key derivations vs real ciphertext
│   ├── find_layout.py             # brute-force the field layout (how LE was found)
│   ├── verify_layout.py           # LE vs BE per field + spectral characterisation
│   ├── check_layout_live.py       # per-byte diagnostic against the live dongle
│   ├── analyze_capture.py         # entropy / packet-structure analysis
│   ├── decode_capture.py          # layout + autocorrelation scoring
│   └── final_validation.py        # cross-channel correlation test
├── recordings/                    # git-ignored — every recording lands here, datestamped
├── vendor/
│   ├── README.md                  # provenance + licence of the vendored clone
│   └── emokit/                    # pristine clone (public domain) — DO NOT EDIT
├── AGENTS.md                      # project state — read this first
├── PUBLISHING.md                  # the legal posture
└── README.md
```

## Quick start

Run everything **from the project root** — the scripts resolve `scripts/` and `vendor/emokit/`
relative to the working directory.

> **Which Python?** `python` is not on `PATH`, and the `py` launcher (3.12) has `numpy` but
> **not `hidapi`**, so every dongle script fails there. Use the project venv, which has
> everything already (Python 3.14.0, numpy 2.5.3, pycryptodome 3.23.0, hidapi):
> **`.venv\Scripts\python.exe`**. Recipe for rebuilding it: [`AGENTS.md`](AGENTS.md) §5.

### 1. Probe the hardware

```powershell
.venv\Scripts\python.exe scripts\probe_device.py --all
```

No hardware handy? See the decision table anyway:

```powershell
.venv\Scripts\python.exe scripts\probe_device.py --demo
```

The script prints the dongle's **USB serial number**, the single value that decides everything:
`UD` + manufacture date + counter. Ours is `UD20180927003B78` (2018-09-27) — stock emokit's
`startswith("UD2016")` test fails on it, which is why the vendored decoder parses the date.

Found something new? Record it in [`eeg-vault/01-device/identify-your-revision.md`](eeg-vault/01-device/identify-your-revision.md)
— the vault is this project's durable memory.

### 2. Look at the signal

```powershell
.venv\Scripts\python.exe scripts\live_view.py
```

Real-time, several times a second: per-channel µV, a bar with the **10–100 µV normal band**
marked, contact status in words (`ok` / `high` / `DEAD` / `DRY?`), mains contamination, and a
live 8–12 Hz alpha meter for `O1`/`O2`. It is the best tool for debugging a wet electrode —
and it records every run (see below), so nothing you notice on screen is lost.

### 3. Run the alpha test

**Do not skip this.** A wrong AES key does not raise an error — it silently
produces meaningless numbers. The only trustworthy proof that acquisition works
is the classic physiological signature:

- electrodes properly wetted with saline, all 14 contacts "Good"/"Excellent"
- subject relaxed, headset on
- **eyes closed** → clear spectral peak at **8–12 Hz** in `O1`/`O2`
- **eyes open** → that peak attenuates
- steady packet rate at 128 (or 256) Hz

```powershell
.venv\Scripts\python.exe scripts\alpha_test.py
```

It prompts the eyes-closed / eyes-open protocol and prints a verdict
(**ALPHA CONFIRMED** needs a closed/open ratio above 1.5 on the occipital channels).

If you have not seen the alpha peak, you do not have EEG yet.

## Recording and replay

Every recording lands in `recordings/` with a **datestamp in its name**, so consecutive runs
never overwrite each other. That folder is git-ignored, because these files are biometric data —
see the privacy note at the end.

| command | what it does |
| --- | --- |
| `.venv\Scripts\python.exe scripts\live_view.py` | viewer **and recorder**, no flags: writes `recordings/live_<datestamp>/eeg.csv` (the complete µV stream) and `screen.txt` (the numbers it displayed, once per refresh) |
| `.venv\Scripts\python.exe scripts\live_view.py --replay recordings\live_<datestamp>` | play a recorded session back at 128 Hz through the same screen — review what happened with the headset off. `--speed 4` plays 4× faster |
| `.venv\Scripts\python.exe scripts\alpha_test.py` | prompted protocol + verdict, and its own recording in `recordings/alpha_<datestamp>.csv` |
| `.venv\Scripts\python.exe scripts\alpha_test.py --file <csv>` | re-analyse any recorded CSV offline — a `live_view` session included |
| `.venv\Scripts\python.exe scripts\record.py 180` | record a flat 180 s to `recordings/eeg_<datestamp>.csv` |
| `.venv\Scripts\python.exe scripts\monitor.py` | every 3 s: is data still flowing? |

Every CSV uses the same layout — 14 columns, `F3_uV … F4_uV`, decoded microvolts after a
0.5 Hz highpass — so any of these tools can read any of the others' output. Bear in mind that
`eeg.csv` is ~130 bytes per sample row: about **55 MB per hour** of viewing.

## 🎯 Result: the protocol is cracked — offline first, then on hardware

emokit ships **real encrypted captures** from a dongle with serial `UD20160103001874`. Since the
serial *is* the key material, every candidate key is fully determined — so the whole protocol could
be reverse-engineered against genuine ciphertext **without the headset**.

```powershell
.venv\Scripts\python.exe scripts\find_layout.py       # brute-force the field layout
.venv\Scripts\python.exe scripts\verify_layout.py     # LE vs BE + spectral character
.venv\Scripts\python.exe scripts\decode_to_csv.py     # -> eeg_decoded.csv (14 ch, uV)
```

**The complete format:**

```
32-byte HID report, AES-128-ECB, key = new_crypto_key(dongle_serial)
byte 0     counter
byte 1     type: 0x10 = EEG sample, 0x20 = extra/status
bytes 2..31  15 x 16-bit LITTLE-ENDIAN fields:
             F3=2  FC5=4  AF3=6  F7=8  T7=10  P7=12  O1=14
             QUALITY=16
             O2=18 P8=20 T8=22 F8=24 AF4=26 FC6=28 F4=30
scale      1 LSB = 0.51 uV   (needs a 0.5 Hz highpass to remove ~16 mV DC offset)
```

| Finding | Status |
| --- | --- |
| `new_crypto_key(serial)` = `b'4778887141771174'` is the correct key | ✅ 132.6-bit entropy collapse vs control |
| Packets are **32 bytes**, not the 64 the "new format" code assumes | ✅ confirmed |
| Two packet types interleaved (byte 1: `0x10` EEG / `0x20` extra) | ✅ confirmed |
| Fields are 16-bit **little-endian** — emokit decoded them big-endian | ✅ **LE won 13/15 fields**; autocorrelation 0.555 (BE) → **0.797 (LE)** |
| The decode is real physiology | ✅ amplitudes 7–54 µV; neighbours correlate (F7/F8 **+0.53**); theta/beta spectrum, low delta; controls ≈ 0 |
| **Verification on this unit** (`UD20180927003B78`) | ✅ **verified on hardware 2026-02-14** — 159 reports/s sustained for 180 s; byte 1 collapses to 2 values (the key check); 14/14 channels in range |
| **Alpha rhythm — proof it is a brain** | ⬜ **open — the only substantive task left** (see *Run the alpha test* above) |

So the *"Unsupported: Epoc+(2016+)"* claim is beaten. emokit's byte **offsets** were right; its byte
**order** was wrong. Full write-up: `eeg-vault/02-software/ud2016-crypto-crack.md`.

## Research status

- ✅ EPOC+ specs, channels, connection options — documented
- ✅ emokit internals, support matrix, all three AES key derivations — documented
- ✅ Cortex API licence scopes, error codes, prices — documented
- ✅ BrainFlow/OpenBCI non-support — verified
- ✅ Serial-number format decoded (`UD` + manufacture date + counter)
- ✅ The `UD2016` literal-string bug identified (breaks 2017+ dongles)
- ⚠️ Part code `EMO-EPO-BT9X-03` traced to a single 2020 paper — an *inference* about the model
  era, and the unit's own serial (`2018-09-27`) disagrees with it
- ✅ **emokit is public domain** — freely vendorable (clone in `vendor/emokit/`)
- ✅ **Why the licence exists** — the dongle encrypts specifically to enforce it
- ✅ **AES key + packet layout + scaling — solved, with a working decoder**
- ✅ **Verified on this specific unit** — 159 reports/s for 180 s, 14/14 channels 10–85 µV
- ⬜ **Alpha rhythm confirmed** — the last piece of evidence; needs the headset on a head
- ⬜ Battery / gyro fields — not needed for EEG

## Scope, legality and privacy

### What this is

An independent, open-source driver and toolkit for an **EPOC+ headset the author owns**,
built to interoperate with open EEG tooling (MNE, LSL, SciPy) instead of vendor software
that gates raw data behind a paid licence. It contains **no Emotiv code, binaries,
firmware, SDK, or credentials** — only a description of the wire protocol, derived partly
from the public-domain [emokit](https://github.com/openyou/emokit) project and partly from
original work here (see [`NOTICE`](NOTICE)).

Not affiliated with, endorsed by, or sponsored by Emotiv. "Emotiv", "EPOC" and "Cortex"
are trademarks of their respective owners, used descriptively.

### The honest legal caveat

The dongle encrypts its output, and Emotiv's own protocol documentation states the purpose
plainly: *"to ensure that raw data is only read by those that have paid for the raw data
license."* So this project documents how to bypass a technological access control.

That engages anti-circumvention law in some jurisdictions (in the US, **DMCA §1201**), which
is legally separate from copyright fair use. Interoperability reverse-engineering has real
protection in case law (*Sega v. Accolade*, *Sony v. Connectix*), but that does not
automatically resolve a §1201 question. **This is not legal advice.** If you plan to use any
of this commercially, get proper counsel.

Context, not reassurance: emokit has been public since 2010 and has apparently attracted no
legal action. That is evidence about emokit, not about you.

### ⚠️ If you fork this: do not commit your own EEG recordings

**EEG is biometric data.** Brain signals are uniquely identifying and count as special-category
personal data under GDPR-style regimes. Recordings and anything derived from them — spectra,
per-channel amplitudes, contact-quality logs — must never be published.

This repo's `.gitignore` excludes `*.csv`, `*_report.txt` and the `recordings/` folder — every
recording tool writes there (`recordings/live_<datestamp>/`, `recordings/eeg_<datestamp>.csv`, …)
for that reason. Check before you push:

```bash
git status --short          # nothing personal?
git ls-files '*.csv'        # should list only vendor/emokit/**
```

## Licence

- **This project:** MIT — see [`LICENSE`](LICENSE).
- **`vendor/emokit/`:** public domain (BSD-style fallback) — Cody Brocious, Kyle Machulis,
  The OpenYou Organization. See [`NOTICE`](NOTICE) and `vendor/emokit/LICENSE`.

Attribution to emokit is not decorative. The reverse engineering that made this possible was
theirs.

## Sources

All external sources are collected in [`eeg-vault/99-sources/references.md`](eeg-vault/99-sources/references.md).
