---
title: Roadmap
type: plan
tags: [project, roadmap, plan]
updated: 2026-02-14
---

# Roadmap

Principle: **solve acquisition once, then never let it constrain anything else.**
Everything downstream is ordinary EEG work; only Phase 1 is genuinely uncertain.

Status legend: ✅ done · 🔄 in progress · ⬜ not started · ⛔ blocked

---

## Phase 0 — Foundations ✅

- [x] Create this vault (`eeg-vault/`) as the project's durable memory
- [x] Document the device → [[common-info-eeg-device]]
- [x] Survey the software landscape → [[opensource-landscape]], [[emokit]], [[cortex-api]]
- [x] Write `scripts/probe_device.py` (serial → date → crypto path) — verified with `--demo`
- [x] `README.md`, `.gitignore`
- [ ] Add the rest of the repo skeleton (`pyproject.toml`, `src/`, `data/`)

**Exit criteria:** anyone (including future-me) can read the vault and understand what the hardware is and what the options are.

---

## Phase 1 — Acquisition ✅ *done*

Goal: **one command that prints live, correct-looking EEG from this specific headset.**

- [x] **1.0 Offline crypto verification** ✅ — using emokit's own captured ciphertext, confirmed that `new_crypto_key()` is the **correct** AES-128-ECB key for `UD2016` dongles (132-bit entropy collapse; byte 1 matches emokit's `is_extra_data()` test; autocorrelation +0.53 after splitting packet types). Also established: the dongle emits **32-byte** reports, not the 64 the "new format" code assumes. → [[ud2016-crypto-crack]]
- [x] **1.1 Probe the device** ✅ — serial **`UD20180927003B78`**, VID `0x1234` / PID `0xED02`. → [[device-identifiers]]
- [x] **1.2 Classify the unit** ✅ — `UD2018` ⇒ **post-2016 "new format"**. (The printed "Model 1.1" label was a red herring — only the serial dates it.)
- [x] **1.2b 🚨 Do NOT update the firmware** — ongoing policy. No Emotiv software on this machine. → [[identify-your-revision]] §0.1
- [x] **1.3 Crypto path determined** ✅ — **`new_crypto_key()`**, confirmed live: 2 distinct `byte1` values vs 256 for the legacy keys.
- [x] **1.3b `UD2016` literal-string bug** ✅ — **this unit is a confirmed victim of it**; bypassed by calling `new_crypto_key()` directly. No emokit flag covers it.
- [x] **1.3d Live acquisition working** ✅ — interface **1** (`EEG Signals`) streams ~160 reports/s; **1532–1909 EEG samples** decoded per run; amplitudes **7–16 µV** (sane). → `scripts/read_live.py`
- [x] **1.3c Field layout reverse-engineered** ✅ — little-endian 16-bit fields; **LE wins 12/14 on this dongle too**. → [[ud2016-crypto-crack]]
- [x] **1.4 ⭐ VALIDATE WITH THE ALPHA TEST** ✅ — **PASSED 2026-09-13.** All 16 pads wetted, seven eyes-closed/eyes-open pairs off the real dongle. The 8–12 Hz occipital peak rose with the eyes closed — consistently, in **every** pair, on O1 and on O2 — clearing the pass criterion of a closed/open ratio above 1.5. The decoded signal is a real brain. The measured values are withheld (biometric data) and live in `private/`. → [[2026-09-13-alpha-confirmed]]
  - The earlier failure was contact, exactly as predicted: mains contamination on the occipital channels collapsed once all 16 pads were wetted. **Never trust a stream you have not alpha-tested.**
  - ⚠️ Use `scripts/alpha_by_segment.py` on a **labelled dataset** — `alpha_test.py --file` is not label-aware and reports a false negative on one.
- [x] **1.5 Check contact quality** ✅ — 14/14 channels usable in the successful session, occipital channels in the normal range with negligible mains, and the weakest channel still acceptable. Frontotemporal channels read well above the physiological range, consistent with EMG rather than brain — do not use them quantitatively yet.
- [x] **1.6 Fallback decision** ✅ — not needed: the hardware route works end to end. [[cortex-api]] stays on file only for the free band-power / mental-command streams.

**Exit criteria:** 60 seconds of recorded, alpha-verified raw EEG, saved to disk, reproducible. **Met — well over it.**

---

## Phase 2 — Source abstraction ⬜

Goal: make the rest of the project independent of how we got the data.

- [ ] `Source` protocol: `start() / stop() / read() -> Sample` + `channel_names`, `sample_rate`
- [ ] `SyntheticSource` — pink-noise + injected 10 Hz alpha + optional artifact bursts. **Lets all later work proceed even while Phase 1 is blocked.** (Borrowed from BrainFlow's `SYNTHETIC_BOARD`.)
- [ ] `ReplaySource` — read a recorded CSV.
- [ ] `EmokitSource` — wraps the vendored HID decoder.
- [ ] `CortexSource` — WebSocket JSON-RPC to Emotiv Launcher (if/when needed).
- [ ] Unit tests + a conformance test suite that every `Source` must pass.

**Exit criteria:** switching source is a one-line change; tests pass against `SyntheticSource` in CI with no hardware.

---

## Phase 3 — Recording & offline analysis ⬜

- [ ] Session recorder: timestamped CSV/Parquet + metadata sidecar (device, serial, sample rate, montage, crypto path, operator, notes)
- [ ] Load into **MNE-Python**; verify channel names/locations render in a standard montage
- [ ] Standard chain: 50/60 Hz notch → 0.5–45 Hz bandpass → bad-channel handling
- [ ] PSD / spectrogram; alpha-band power over time
- [ ] Artefact notes: eye blinks (frontal), jaw clench/EMG (temporal), and the EPOC+'s known drift

**Exit criteria:** a recorded session that produces a sensible PSD plot and a standard topomap.

---

## Phase 4 — Real-time ⬜

- [ ] Publish to **LSL** so OpenViBE / Timeflux / Brainstorm / anything can consume it → [[lsl-and-interop]]
- [ ] Live scrolling plot (matplotlib or pyqtgraph; pyqtgraph for headroom)
- [ ] Real-time band power with a sliding window
- [ ] Ring buffer + backpressure handling; measure and report end-to-end latency

**Exit criteria:** stream visible simultaneously in our own UI and in a third-party LSL consumer.

---

## Phase 5 — Applications ⬜

Pick one to start; they are listed easiest → hardest given the EPOC+ montage.

1. **Alpha neurofeedback** — eyes-closed alpha training. Easiest, most robust, uses occipital channels that exist. Also the best demo that the rig works.
2. **Attention / engagement index** — beta/(alpha+theta) ratios; well-trodden but noisy.
3. **Sleepiness / drowsiness detection** — theta/alpha ratio over time.
4. **SSVEP** — flickering stimuli; occipital channels again, decent fit for this montage.
5. **Facial-expression / EMG-based control** — the EPOC+ is actually good at this, and it is honest about being muscle, not brain.
6. **Motor imagery** — ⚠️ **not a good fit.** Needs C3/C4/Cz; the EPOC+ montage has none. Mentioned here so nobody wastes a month on it.

---

## Risks

| Risk | Likelihood | Mitigation |
| --- | --- | --- |
| 🚨 **Bricking a working setup by updating the dongle firmware** | **medium, and irreversible** | Never install/run Emotiv Launcher, EmotivPRO or Testbench on the machine with the dongle attached. Our route needs none of them. → [[identify-your-revision]] §0.1 |
| The unit turns out to be 2016+ after all (`UD…` serial) | medium | Already solved — `new_crypto_key` + the LE layout, see [[ud2016-crypto-crack]] |
| emokit's `UD2016` literal-string bug silently picks the wrong key | low **if** the serial is `SN…`; high otherwise | Patch step 1.3b; the alpha test catches it either way |
| Garbage data mistaken for real EEG | **very high** | The alpha test in 1.4 is mandatory, not optional. Autocorrelation is the objective check. |
| emokit Python 2/3 rot, `pycrypto` CVEs | certain | Vendor the logic (public domain), port to `pycryptodome`, own the tests |
| Saline electrodes dry out mid-session | certain | Standardise wetting protocol; log contact quality per session |
| Paying for a licence that doesn't grant the `eeg` scope | medium | ⚠️ unresolved — **ask Emotiv support in writing before paying** |
| Cloud-synced recordings lock after a licence lapses | medium | If ever using EmotivPRO records, **export/back them up** |
| Scope creep into a UI before acquisition works | medium | Phase 2's synthetic source removes the excuse |

## Related
[[common-info-eeg-device]] · [[identify-your-revision]] · [[opensource-landscape]] · [[decisions-log]]
