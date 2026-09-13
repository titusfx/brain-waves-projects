# Publishing this project

Audit performed **2026-02-14** before any `git init`. Verdict: **publishable, with three fixes.**

⚠️ This is a technical audit, not legal advice. See §4.

---

## 1. Must be excluded — biometric data

**EEG recordings are personal data of a special category.** Brain signals are uniquely identifying and, under GDPR-style regimes, count as sensitive data. They must never be committed.

| file | status |
| --- | --- |
| `alpha_test.csv` (2.5 MB, your 3-min recording) | ✅ excluded — `*.csv` |
| `live_capture.csv`, `eeg_decoded.csv` | ✅ excluded — `*.csv` |
| **`alpha_report.txt`** (analysis of your recording) | ❌ **was NOT excluded — now fixed** |

`alpha_report.txt` contains per-channel amplitudes and spectra derived from a real person's brain. It is not raw EEG, but it is still derived biometric data. `.gitignore` now excludes `*_report.txt` and `alpha_report.txt`.

> **This was the only genuine leak.** Everything else was already covered.

## 2. Device identifiers — DECISION: keep the real serial

> **Decision (2026-02-14):** the owner chose to **publish the real serial
> `UD20180927003B78` as-is.** Rationale: it is readable from the dongle by anyone with
> physical access, so it is not a secret in the strong sense, and keeping it makes the
> reverse-engineering record exactly reproducible.
>
> **Accepted consequence:** the repository is permanently tied to this specific physical
> device. If that ever becomes undesirable, change it in the 9 files listed below and the
> derivations still hold — nothing technical depends on the value.

### The serial is the key material 🔑

```
serial : UD20180927003B78
key    : new_crypto_key(serial) -> b'4778887141771174'
```

The AES key is *derived from* the serial. It appears in **9 files** (16 occurrences):

```
eeg-vault/01-device/device-identifiers.md        (5)
eeg-vault/01-device/identify-your-revision.md    (3)
eeg-vault/02-software/ud2016-crypto-crack.md     (3)
eeg-vault/01-device/common-info-eeg-device.md    (1)
eeg-vault/03-project/roadmap.md                  (1)
eeg-vault/04-sessions/2026-02-14-first-live-session.md (1)
eeg-vault/Home.md                                (1)
scripts/probe_device.py                          (1)
README.md                                        (1)
```

### Machine-specific identifiers — low risk, optional cleanup

`eeg-vault/01-device/device-identifiers.md` also contains Windows identifiers:

- `USB\VID_1234&PID_ED02&MI_01\6&8417E44&0&0001` — `6&8417E44` is **bus/hub-relative to this machine**
- `HID\...\7&21A47CEE&0&0000`, `HID\...\7&E7460B0&0&0000`

These reveal nothing about the device, only about the host PC's USB topology. Left as-is for
now; stripping them would lose no information.

## 3. No secrets found

No `.env`, no API tokens, no Emotiv client secret, no credentials. ✅

## 4. The judgement call — circumvention material

**This is the part only you can decide.**

The protocol documentation in `vendor/emokit/doc/emotiv_protocol.asciidoc` states the encryption exists for a specific purpose:

> *"To ensure that raw data is only read by those that have paid for the raw data license, each USB dongle encrypts incoming wireless data via AES…"*

So this repository documents how to bypass a technological access control. In the United States that engages the **DMCA §1201 anti-circumvention** provision, which is legally *separate* from copyright fair use. Interoperability reverse-engineering has real protection in case law (*Sega v. Accolade*, *Sony v. Connectix*), but that line of authority does not automatically resolve a §1201 claim. Other jurisdictions differ.

Practical context, again not legal advice:

- **emokit itself has been public on GitHub since 2010** and has apparently attracted no legal action. That is meaningful evidence that the practical risk is low — but it is evidence about *them*, not about you.
- You would be **republishing** circumvention material, not just consuming it. Some people draw a line there; some don't.
- The work here is genuinely original: nobody had documented the little-endian layout or the `UD2016` literal-string bug before.

### Reducing the profile, if you want to

`vendor/emokit/` is public-domain, so redistributing it is **legally fine**. But two files are more "how to crack it" than "how to read it":

- `vendor/emokit/Find Key` — step-by-step IDA Pro instructions for extracting the key from Emotiv's `Pure.EEG` binary
- `vendor/emokit/python/key_solver*.py` — brute-force key search

You could vendor only the decoder + protocol doc and omit those. Note the trade-off: the 2.6 MB of encrypted captures **should stay** — our analysis scripts depend on them, and they make the whole thing reproducible.

## 5. Attribution and licensing

| component | licence | obligation |
| --- | --- | --- |
| `vendor/emokit/` | **public domain** (BSD-style fallback) | keep the copyright notice + `LICENSE` file; do not imply endorsement |
| Your own code + vault | none yet | **add a LICENSE** — MIT or Apache-2.0 are the usual picks |

Required attribution to carry forward:
> Cody Brocious, Kyle Machulis, The OpenYou Organization — *emokit*, 2010–2017
> plus the public-domain `Aes.py` notice from Bram Cohen.

## Checklist before `git push`

- [x] `.gitignore` excludes `*_report.txt` — **(fixed)**
- [ ] Verify nothing personal sneaks in: `git status --short` after `git add -A`
- [ ] Confirm no `.csv` staged: `git ls-files '*.csv'` should show only `vendor/emokit/**`
- [ ] Decide on the serial: redact, or accept
- [ ] Strip username + machine instance IDs
- [ ] Decide whether to include `Find Key` / `key_solver*.py`
- [ ] Add your own `LICENSE`
- [ ] Add a `NOTICE`/README paragraph explaining what this is and its legal posture
- [ ] Consider a `SECURITY.md`-style note: *"do not publish your own EEG recordings"*

## A note worth adding to the README

Something like:

> This project reverse-engineers the USB HID protocol of a device the author owns, for
> interoperability with open-source EEG tooling. It contains no Emotiv software or
> binaries. The protocol documentation is public domain, derived from the emokit project.
> **If you use this, do not commit your own EEG recordings — they are biometric data.**

## Related
[[device-identifiers]] · [[why-the-licence]] · [[references]] · `vendor/README.md`
