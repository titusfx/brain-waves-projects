# AGENTS.md — project state

**Read this first.** It is the onboarding document for an AI agent (or a human) picking up
this repository. Everything here was verified on real hardware on **2026-02-14**.

> Naming note: this file is `AGENTS.md`, the conventional auto-discovered name; on Windows it
> also resolves as `agents.md`. It used to be called `agent.md` — any reference to that name
> means this file.

---

## 1. What this project is

An independent, open-source driver and toolkit for an **Emotiv EPOC+** 14-channel EEG headset.
Emotiv's own API gates raw EEG behind a paid licence; this project reads raw EEG directly from
the USB dongle instead, with no Emotiv software, no account, and no licence.

The vendor's dongle encrypts its output specifically to enforce that licence. This project
reverse-engineered the encryption and the packet layout. → `PUBLISHING.md` for the legal posture.

On top of the driver there is now an application: a **FastAPI service (`api/`)** that owns the
dongle and records labelled datasets, and an **Angular client (`web/`)** that shows the signal
live, documents every electrode, and builds guided protocols. → §11, and
`eeg-vault/03-project/web-workbench.md`.

---

## 2. Current state

| | status |
| --- | --- |
| AES key derivation | ✅ **solved, verified on hardware** |
| Packet layout | ✅ **solved** (16-bit little-endian) |
| Live acquisition | ✅ **working** — 159 reports/s sustained for 180 s |
| Decode to µV | ✅ **working** — amplitudes in physiological range |
| Electrode contact | ✅ **good** — 14/14 channels `ok`, 10–85 µV |
| Web workbench (`api/` + `web/`) | ✅ **working** — live monitor, channel reference, protocol builder, labelled datasets, a **discovery** screen (below) and deleting with confirmation. Verified end to end by `tools/verify-web.mjs` (17/17), and the dongle path exercised against the real, silent device. |
| **Alpha rhythm confirmed** | ⬜ **NOT YET — this is the only substantive task left** |
| Battery level | ⬜ unidentified |
| Gyro / motion | ⬜ unidentified (`emokit`'s is a stub returning `42`) |

**The acquisition chain is proven. What is not yet proven is that the decoded signal is a
real brain.** That is the alpha test (§7).

---

## 3. Hard facts — do not re-derive these

```
serial          UD20180927003B78        (= UD + 2018-09-27 + 003B78)
manufacture     2018-09-27
VID / PID       0x1234 / 0xED02
data interface  HID interface 1, product string "EEG Signals"
                (interface 0, "Brain Computer Interface USB Receiver/Dongle", is SILENT)
report size     32 bytes
cipher          AES-128-ECB, two independent 16-byte blocks
key             new_crypto_key(serial), i.e. the UD2016+ branch — for this serial
                that is b'877BBB7383773378'
sample rate     128 Hz  (159 reports/s total = ~128 EEG + ~31 status)
```

> **Correction (2026-02-14 facts, checked 2026-09-13).** This block used to read
> `key -> b'4778887141771174'` under *this* serial. That byte string is the key for
> **`UD20160103001874`** — the serial of emokit's own captured ciphertext — and it is
> quoted in the crypto write-up for that reason. Two different serials, two different
> keys; the derivation is the same. `tools/verify-*` does not depend on the value, but a
> human reading the old line would have derived the wrong key by hand. Both values are
> pinned by `api/tests/test_decoder.py`.

### Packet format

```
byte 0      counter
byte 1      packet type: 0x10 = EEG sample, 0x20 = status packet
bytes 2..31 15 x 16-bit LITTLE-ENDIAN fields:

    offset  2  F3      offset 18  O2
    offset  4  FC5     offset 20  P8
    offset  6  AF3     offset 22  T8
    offset  8  F7      offset 24  F8
    offset 10  T7      offset 26  AF4
    offset 12  P7      offset 28  FC6
    offset 14  O1      offset 30  F4
    offset 16  QUALITY (not EEG)

scaling        1 LSB = 0.51 uV
DC             each channel carries a large DC offset (~16 000 uV);
               remove with a 0.5 Hz highpass. This is normal, not a bug.
```

---

## 4. Hard rules — each of these was learned by getting it wrong

1. **NEVER trust a stream you have not validated.** A wrong AES key does not raise an error; it
   produces confident-looking numbers. Two mandatory checks:
   - **byte 1 must collapse to ~2 distinct values** (0x10, 0x20). A wrong key gives ~256.
   - **autocorrelation / alpha**: correct EEG is band-limited and temporally correlated.
2. **Do NOT update the dongle firmware. Do NOT install or run Emotiv Launcher** on the machine
   with the dongle attached. Firmware updates are what introduced the crypto that broke the
   community driver, and dongle firmware is not downgradable by us. This route needs no Emotiv
   software at all.
3. **Read the fields as UNSIGNED.** They are raw ADC counts with a per-channel DC offset.
   Interpreting them as signed int16 manufactures 65535-count spikes whenever the high byte
   crosses 0x7F/0x80 — we measured a fake 5317 µV from 26 such flips.
4. **Only HID interface 1 streams.** Interface 0 opens fine and returns zero reports forever.
5. **`emokit`'s `startswith("UD2016")` is a literal string test** and this unit is `UD2018`, so
   stock emokit silently picks the **wrong** key. Call `new_crypto_key()` directly. No emokit
   flag fixes this.
6. **EEG is biometric data.** Never commit recordings or anything derived from them
   (spectra, amplitudes, contact logs). `.gitignore` covers `*.csv`, `*_report.txt` and the
   whole `recordings/` folder.
7. **`python` is not on PATH, and the `py` launcher does not have the dependencies.** `py`
   resolves to Python 3.12, which has `numpy` but **not `hidapi`** — every dongle script fails
   there. Use the project venv: `.venv\Scripts\python.exe`.
8. **Run scripts from the project root** — they resolve `vendor/emokit/...` and `scripts/`
   relative to the working directory.

---

## 5. Environment

```powershell
# the venv already exists — Python 3.14.0 with numpy 2.5.3, pycryptodome 3.23.0, hidapi
.venv\Scripts\python.exe scripts\live_view.py

# if you must recreate it, keep the uv cache inside the workspace:
$env:UV_CACHE_DIR = "$PWD\.uv-cache"
uv venv .venv
uv pip install --python .venv\Scripts\python.exe numpy pycryptodome hidapi
```

`uv`'s default cache (`%LOCALAPPDATA%\uv\cache`) may be unwritable under the file sandbox —
setting `UV_CACHE_DIR` inside the workspace avoids the problem entirely.

---

## 6. Scripts

| script | purpose |
| --- | --- |
| `probe_device.py` | enumerate HID, print VID/PID/serial, classify crypto path. `--demo` needs no hardware. |
| `live_view.py` | **real-time viewer**: per-channel amplitude, the 10–100 µV "normal range" marker, contact status, and a live 8–12 Hz alpha meter for O1/O2. Best tool for physical debugging. **Records every run** to `recordings/live_<YYYY-MM-DD_HH-MM-SS>/` (`eeg.csv` + `screen.txt`), no flags needed. `--replay <csv\|dir> [--speed N]` plays a recording back through the same screen. |
| `record.py N [out.csv]` | record N seconds to CSV (decoded µV). **Omit the filename** and it writes `recordings/eeg_<YYYY-MM-DD_HH-MM-SS>.csv`, so runs never overwrite. |
| `alpha_test.py` | prompted eyes-closed/eyes-open protocol + verdict; saves `recordings/alpha_<YYYY-MM-DD_HH-MM-SS>.csv`. `--file x.csv` analyses an existing recording (writes nothing). |
| `monitor.py` | watch the stream and report every 3 s whether data is flowing. |
| `recording_paths.py` | where recordings go (`recordings/<prefix>_<stamp>[...]`); imported by the three tools above so names stay uniform. |
| `test_ud2016_crypto.py` | test all 4 key derivations against emokit's real captured ciphertext. |
| `find_layout.py` | brute-force the field layout (this is how little-endian was found). |
| `verify_layout.py` | LE vs BE per field + spectral characterisation. |
| `check_layout_live.py` | per-byte diagnostic against the **live** dongle. |
| `analyze_capture.py` | entropy / structure analysis of a capture. |
| `decode_capture.py` | autocorrelation-based decode validation. |
| `decode_to_csv.py` | reference decoder (imported by others). |
| `final_validation.py` | cross-channel correlation test. |

These are the **terminal** tools. The web application is separate — `api/` and `web/`, run
with `npm run api` and `npm run web` from the root. Both decode with the same rules; if you
change the packet handling, change it in `scripts/decode_to_csv.py` **and**
`api/src/eeg_api/eeg/decoder.py`.

---

## 7. ⭐ The next task: the alpha test

**Goal:** prove the decoded signal is real brain, not artefact.

**Protocol** — put the headset on, wet **all 16 pads** (14 EEG + **2 references**), then
alternate eyes closed / eyes open ~20 s each, about 4 cycles.

**Pass criteria:**
- `alpha_test.py` alpha peak ratio **> 1.5** on O1/O2, or
- `live_view.py` shows the O1/O2 `peak` column rising above 1.5 and the `share` rising with
  eyes closed.

Either way the session is on disk: `live_view.py` records every run to
`recordings/live_<stamp>/`, so a failed attempt can be replayed
(`live_view.py --replay recordings\live_<stamp>`) and analysed
(`alpha_test.py --file recordings\live_<stamp>\eeg.csv`) without the headset — do that
before asking the subject to sit through another run.

**If it fails, in order of likelihood:**
1. **The 2 reference pads (CMS/DRL) are dry.** If they are, common-mode rejection fails and
   *every* channel shows a large common artefact. This was the cause of the first failed
   session — 10 of 14 channels sat at 200–280 µV.
2. Electrodes not on scalp (hair in the way, headset loose, pads not soaked).
3. Subject not relaxed, moving, or talking.

A **negative result is not evidence of a decoding problem.** The decoder is verified. It is a
contact problem. The diagnostic that separates the two: *if the decode were broken, all 14
channels would be wrong together — a per-channel difference means physics, not software.*

---

## 8. Open questions

| question | how to settle it |
| --- | --- |
| **Battery level** | Long recording on battery power; find the field that decreases monotonically. Best current candidate: byte 13 of the `0x20` status packets (values 242/243/244 → 82–89 % on the old-format table). Needs a `record.py --raw` mode. → `eeg-vault/02-software/status-packets-and-battery.md` |
| **The 27–28 Hz spectral peak** | Appears in O2 with power comparable to the 1–2 Hz drift. Not mains (50/60 Hz). Likely EMG — but could be a packet-reassembly artefact. Check whether it survives good contact. |
| **`emokit`'s whole/precision scaling** | `vendor/emokit/python/emokit/packet.py` decodes new-format fields as `high/0.031 + low/3.1` (~4000 µV nonsense). Our unsigned 16-bit read is empirically physiological. Worth reconciling one day. |
| **Gyro / motion** | Undecoded. Not needed for EEG. |
| **Battery field vs. `0x20` payload layout** | The status packet uses only bytes 0–19; bytes 20–31 are always zero. Nine 16-bit fields — presumably the rotating contact-quality scheme. |

---

## 9. Where the knowledge lives

`eeg-vault/` is an Obsidian vault and the project's durable memory. Open it as a vault.

| note | contents |
| --- | --- |
| `Home.md` | map of content |
| `01-device/device-identifiers.md` | **all IDs**: serial, VID/PID, interfaces, AES key, Windows instance paths |
| `01-device/common-info-eeg-device.md` | specs, capabilities, limits |
| `01-device/identify-your-revision.md` | the probe procedure + **§0.1 the firmware warning** |
| `02-software/ud2016-crypto-crack.md` | **the protocol, fully solved, with all evidence** |
| `02-software/why-the-licence.md` | why the dongle encrypts at all |
| `02-software/emokit.md` | the archived community driver, and exactly how it fails |
| `02-software/cortex-api.md` | the official paid alternative, with real prices |
| `02-software/status-packets-and-battery.md` | open question on battery |
| `03-project/roadmap.md` | phase plan and risk register |
| `03-project/web-workbench.md` | **the app**: architecture, the protocol model, the dataset format, what was verified |
| `03-project/decisions-log.md` | ADRs — read before changing architecture |
| `04-sessions/2026-02-14-first-live-session.md` | the first real session, including the failed one |
| `99-sources/references.md` | **every source + a verified/unverified ledger** |

That is the key subset — the vault holds **19 notes** in total. The others are
`01-device/connection-and-dongle.md`, `02-software/opensource-landscape.md`,
`02-software/ecosystems-without-support.md`, `02-software/lsl-and-interop.md`, and
`03-project/glossary.md`. Start from `Home.md` for the full map.

The `references.md` ledger is load-bearing: it distinguishes what has been **verified** from
what is **inferred**. Do not promote an inference to a fact without checking it.

---

## 10. Rules for working in this repo

- **Update the vault, not just the code.** Findings belong in `eeg-vault/`, with sources.
- **Mark inferences as inferences.** The ledger exists because several early conclusions
  (notably "this is a pre-2016 dongle" from the printed label) were wrong.
- **Keep `vendor/emokit/` pristine.** It is an unmodified public-domain snapshot pinned to
  commit `7f25321a…`. Put adaptations in `scripts/`, not there.
- **Never commit** recordings, derived EEG data, or Emotiv credentials.
- **Verify before claiming.** Use the byte-1 test and the alpha test. Numbers that look
  plausible are not evidence.

---

## 11. The web workbench (`api/` + `web/`)

Added 2026-09-13. Full write-up: `eeg-vault/03-project/web-workbench.md`.

```powershell
npm run api        # FastAPI on http://127.0.0.1:8020   (uv --directory api run uvicorn …)
npm run web        # Angular dev server on :4301, proxying /api and /ws
npm run build:web; npm run api:prod   # one process, one origin — no proxy needed
npm test           # api pytest + web vitest
npm run verify     # lint + mypy + arch + tests + web build
npm run verify:web # headless-Chrome end-to-end (needs the API running)
```

**The ports are 8020 and 4301, not the conventional 8000 and 4200.** Both conventional
ports are already bound on this machine by the author's other projects, and one of them
answers `GET /health` plausibly — so an accidental clash looks like a working deployment
rather than a conflict. 4300 is taken too. 8020 is the API's port and the proxy target in
`web/proxy.conf.json`; 4301 is the dev server's own port, set in the root `package.json`.

### Layout

```
api/src/eeg_api/
├── domain/    signal model, the channel-doc catalog, the analysis, the FLOW STATE MACHINE
│              (pure: no FastAPI, no I/O, no clock — enforced by import-linter + ruff)
├── eeg/       the only code that opens the dongle or reads a recording
├── services/  acquisition hub, dataset recorder, flow runner, library
└── main/      settings, app factory, HTTP routers, the WebSocket
web/src/app/   core/ (api, eeg, speech, format) + features/ (one folder per screen)
tools/verify-web.mjs   drives the BUILT app in headless Chrome over CDP
```

### Things that will bite you

1. **There are now two decoders.** `scripts/decode_to_csv.py` and
   `api/src/eeg_api/eeg/decoder.py` implement the same rules. Change both or neither.
2. **Response models declare no defaults, on purpose.** A default makes a field optional in
   the generated TypeScript, so every consumer has to be defensive about a field that is
   always sent. Requests keep their defaults; responses do not. `npm run api:types`
   regenerates `web/src/app/core/api/schema.d.ts` from `web/openapi.json`.
3. **Router input binding writes `undefined` over an input's default** when a route or query
   parameter is absent. Inputs bound from the router are therefore typed `| undefined` and
   handled; a default value there is a lie that only fails at runtime.
4. **An `output()` must not be named after a DOM event.** `close` is one; `dismiss` is not.
5. **Vitest runs with `pool: 'threads'`** (`web/vitest-base.config.ts`) because the default
   `forks` pool cannot start a worker here.
6. **The countdown is never recorded, and a stopped loop drops its tail.** Both are
   asserted in `api/tests/` and in `tools/verify-web.mjs` — do not "simplify" either away
   without reading §"Two decisions" of the vault note.
7. **The demo source must always be labelled `demo`.** It is a synthetic head, not a
   headset, and a UI that blurs the two is a hazard.
8. **Not yet exercised against a streaming headset.** Every web check runs on the synthetic
   source. The *dongle* path was exercised on 2026-09-13: with the headset off, interface 1
   opens and returns zero reports, and the monitor shows the power/charge/LED/pairing
   checklist rather than blaming the cable. That is as far as it has been, and the harness
   asserts it (`a connected-but-silent dongle is explained as an RF problem`).
9. **The Discovery screen measures; it does not classify.** Its numbers are per-frequency
   effect sizes and a leave-one-out nearest-centroid, and every readout carries the count it
   was computed from. Do not present any of it as a validated model.
10. **Discovery's p-value has a ceiling, and the API reports it.** The labels can only be
    split C(n_a+n_b, n_a) ways, so with three instances a side *nothing* can come out below
    0.048 — `min_attainable_p`. That is usually the real answer to "why is my obvious
    difference not significant?", and the screen says so rather than leaving a hopeful number
    standing.
11. **Deleting is the only irreversible operation.** A modal that names what will go gates it
    (Cancel focused; Escape and outside-click cancel), and the server refuses any id resolving
    outside `recordings/` as well as anything the current source or recording is using.
    `api/tests/test_delete.py` is mostly about those refusals — keep it that way.
