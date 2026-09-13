---
title: Decisions Log
type: log
tags: [project, adr, decisions]
updated: 2026-09-13
---

# Decisions Log

ADR-style. Append-only. Each entry: **context → decision → consequences.**

---

## ADR-001 — Keep the EPOC+, do not replace it yet

**Date:** 2026-02-14 · **Status:** accepted

**Context.** The device was previously unusable because Emotiv's software gates raw EEG behind a paid licence. The obvious alternative is to buy open hardware (OpenBCI Cyton, ~8 flexible channels).

**Decision.** Keep and work with the EPOC+ for now.

**Consequences.**
- We accept an uncertain Phase 1 (see [[roadmap]]).
- We get 14 channels at 128/256 Hz, at zero additional cost.
- We lose montage flexibility permanently — no C3/C4/Cz, so motor imagery is off the table.
- Revisit if Phase 1 fails *and* the free Cortex streams prove insufficient.

---

## ADR-002 — Put a `Source` abstraction in front of acquisition

**Date:** 2026-02-14 · **Status:** accepted

**Context.** We do not yet know whether the USB-HID/emokit route, the Cortex API route, or neither will work on this unit. Building directly against one of them risks a rewrite.

**Decision.** All downstream code depends on a `Source` interface, never on emokit or Cortex directly.

**Consequences.**
- `SyntheticSource` and `ReplaySource` let Phases 2–5 proceed while Phase 1 is blocked. **This is the main point.**
- One extra indirection layer to maintain.
- A conformance test suite is required so every source is genuinely interchangeable.

**Alternatives rejected.** (a) Build on emokit directly — brittle, abandoned dependency. (b) Wait for Phase 1 to resolve — needless serialisation of the whole project.

---

## ADR-003 — Vendor emokit's protocol logic instead of depending on the package

**Date:** 2026-02-14 · **Status:** accepted

**Context.** `openyou/emokit` has had no commits since **2017-04-17** and is now **archived**. It depends on `pycrypto` (unmaintained, CVEs), mixes Python 2/3 code paths, and its motion decoding is a stub that returns the constant `42`. But it is the only public map of the dongle protocol.

**UPDATE (resolved):** emokit's `LICENSE` is **public domain** (with a BSD-style fallback for jurisdictions that don't recognise public-domain dedication): *"In countries where it's respected, everything is released into the public domain."* The licensing concern below is therefore **moot** — we are free to copy and adapt the logic, retaining attribution to Cody Brocious / The OpenYou Organization and the public-domain `Aes.py` notice. A pristine clone is kept in `vendor/emokit/` (see `vendor/README.md`).

**Decision.** Re-implement the *specific* pieces we need — AES key derivation, packet decoding, field masks, µV scaling — in our own small, tested module. Credit and cite `emokit` for the reverse-engineering.

**Consequences.**
- We control the dependency and can swap `pycrypto` → `pycryptodome`.
- We can unit-test against recorded packet captures, including the replay round-trip.
- We forfeit upstream fixes — but there have been none for nine years.
- Licence/attribution must be handled carefully: check emokit's licence terms before copying code verbatim.

---

## ADR-004 — Treat the alpha response as the acceptance test for acquisition

**Date:** 2026-02-14 · **Status:** accepted

**Context.** A wrong AES key does **not** raise an error — `emokit` happily "decrypts" to meaningless bytes and emits plausible-looking numbers. It is entirely possible to build an elaborate pipeline on noise.

**Decision.** Phase 1 is not considered complete until a recorded session shows an **eyes-closed 8–12 Hz peak in O1/O2 that attenuates on eyes-open**, with good contact quality.

**Consequences.**
- Adds a human-in-the-loop step with a real protocol (electrode wetting, dark room, relaxed subject).
- We will likely attempt to run the alpha test *with the headphones on and the dongle paired*, so the protocol must be reproducible.
- Protects against the single most dangerous failure mode in this project.

---

## ADR-005 — Do not attempt motor imagery

**Date:** 2026-02-14 · **Status:** accepted

**Context.** Motor imagery classification depends on sensorimotor rhythms over the central strip (C3, Cz, C4). The EPOC+ montage is `AF3 F7 F3 FC5 T7 P7 O1 O2 P8 T8 FC6 F4 F8 AF4` — **no central or parietal electrodes.**

**Decision.** Rule out motor-imagery work. Focus on frontal/occipital paradigms instead.

**Consequences.** Alpha/neurofeedback, SSVEP, attention metrics, and facial-expression work are in scope; MI is not. Documented so it is not re-litigated.

---

## ADR-006 — Patch the crypto selection to test the serial's *date*, not the literal `"UD2016"`

**Date:** 2026-02-14 · **Status:** accepted

**Context.** `emokit` selects its AES key and packet format with a literal string test:

```python
if self.serial_number.startswith("UD2016") and not self.force_epoc_mode:
    self.new_format = True
```

Emotiv dongle serials encode the manufacture date as `UD` + `YYYYMMDD` + counter (confirmed by issue #229: stated date 2016-01-03 ↔ serial `UD20160103001874`). This unit appears to be **2019–2020** vintage, so its serial is likely `UD2019…`/`UD2020…`, which **fails** that test and silently falls through to the legacy 32-byte key path. There is no flag for this. A search for `UD2017`/`UD2018`/`UD2019` in the emokit repo returns zero results — nobody ever hit or fixed it.

**Decision.** In our vendored decoder, decide the crypto path from the **parsed date** in the serial (`year >= 2016`), never from a literal prefix. Log the parsed date and the chosen path on every session.

**Consequences.**
- Removes the single most likely silent failure mode before we waste time debugging "wrong-looking EEG".
- Slightly diverges from upstream emokit behaviour — document it prominently, because it is a real bug fix, not a preference.
- Because the failure is silent, we also gain a mandatory diagnostic: log which key was used alongside every recording.

**Alternatives rejected.** (a) Rely on `force_epoc_mode`/`force_old_crypto` — those flags don't cover this case and the introducing commit says *"not functional yet"*. (b) Assume the unit is pre-2016 — contradicted by the part-code research.

---

## ADR-007 — Record every viewer session, and let the viewer replay a recording

**Date:** 2026-09-13 · **Status:** accepted

**Context.** `live_view.py` was display-only: it decrypted, drew the screen, and kept every sample in memory. A session was therefore unrecoverable — the only way to keep anything was to redirect the screen to a text file, which PowerShell truncated on the next run and which could never be re-analysed, because it held rendered bars rather than samples. Separately, `record.py` and `alpha_test.py` both wrote a *fixed* filename, so each run silently overwrote the previous capture. And the alpha test (§7 of `AGENTS.md`) is exactly the case where a session has to be re-examined *after* the headset is off and the subject has gone home.

**Decision.**
- `live_view.py` records **every** live run, no flags: `recordings/live_<YYYY-MM-DD_HH-MM-SS>/{eeg.csv,screen.txt}`. `eeg.csv` uses the same 14-column `{channel}_uV` layout as `record.py`, so `alpha_test.py --file <that file>` analyses it directly; `screen.txt` is one numeric block per refresh (amplitude, current value, mains %, status per channel, plus the O1/O2 alpha share and peak).
- Samples are written from a **continuous** stream, not from the sliding display window, so a slow refresh cannot leave gaps in the file. This required a stateful 0.5 Hz highpass (`UVStream`) carried across HID bursts; it is verified **bit-identical** to a single-pass `decode_to_csv.decode()` over the same reports.
- `live_view.py --replay <csv|folder> [--speed N]` plays a recording back at 128 Hz through the same rendering path — this is the `ReplaySource` of ADR-002, finally cashed in.
- All recording tools take their output paths from one place (`scripts/recording_paths.py`), so every run is datestamped and nothing overwrites.

**Consequences.**
- Any session can be reviewed and analysed afterwards, without hardware or subject; a bad alpha session can be diagnosed rather than repeated blind.
- The viewer is no longer read-only, and viewing now costs disk: `eeg.csv` is ~130 bytes per sample row, about **55 MB per hour**. `recordings/` is git-ignored, but the files must be pruned by hand.
- Amplitudes shown are now the true continuous values: the old code re-decoded the 2 s window five times a second, restarting the highpass on every refresh, and its O1/O2 traces re-appended the whole window each time. Both are fixed. Numbers stay in the documented physiological range.
- Because a wrong key cannot raise an error, `screen.txt` records the byte-1 verdict alongside the numbers — every recording carries its own key diagnostic.

**Alternatives rejected.** (a) Record only behind a flag — the session that matters is the one you forget to flag, and the request was explicitly "no flags". (b) Dump the ANSI frames to a log — huge, brittle, and full of box-drawing noise; a numeric block is smaller and greppable. (c) Decode each HID burst independently for the recording — simplest, but it restarts the highpass every ~0.2 s and stamps a step into every channel. (d) Leave the viewer read-only and use `record.py` when data is wanted — the two tools drift, and session review is impossible in the moment it is needed.

---

## Template for new entries

```markdown
## ADR-NNN — <short title>
**Date:** YYYY-MM-DD · **Status:** proposed | accepted | superseded by ADR-NNN

**Context.** What is the situation and the forces at play?
**Decision.** What we are doing.
**Consequences.** What becomes easier, what becomes harder, what we accept.
**Alternatives rejected.** What else was considered and why not.
```

## Related
[[roadmap]] · [[common-info-eeg-device]] · [[opensource-landscape]]
