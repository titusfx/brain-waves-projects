# vendor/emokit — provenance

**This directory is an unmodified clone of a third-party project. Do not edit it.**

| | |
| --- | --- |
| **Upstream** | <https://github.com/openyou/emokit> |
| **Cloned** | `git clone --depth 1 https://github.com/openyou/emokit.git` |
| **Commit** | **`7f25321a1c3a240f5b64a1572e5f106807b1beea`** — *"Merge pull request #255 from CerebralPower/master"*, 2017-04-16 |
| **Nested `.git`** | **deliberately removed.** It made git treat this as an embedded repository, so the files would have been published as a broken submodule link instead of real content. It is now plain vendored source, pinned to the commit above. |
| **Status upstream** | **ARCHIVED** — last functional commit 2017-04-17, last push 2019-07-05 |
| **Purpose here** | reference implementation + protocol documentation + **real captured ciphertext** |

## Licence — this is why we can use it

`vendor/emokit/LICENSE` is, verbatim:

> `Aes.py` copyright 2001 Bram Cohen and released into the public domain.
>
> Everything else:
> In countries where it's respected, everything is released into the **public domain**; otherwise it's released under the following terms:
> Copyright (c) 2010-2016, Cody Brocious, The OpenYou Organization — All rights reserved.
> Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met: [BSD-style attribution + no-endorsement clauses]

**Public domain (with a BSD-style fallback).** That is permissive enough to vendor, copy, and adapt the logic into our own code as long as attribution is retained. It resolves the licensing worry raised in [[decisions-log]] ADR-003 — the concern there was hypothetical; the answer is that we are free to reimplement from this source.

Attribution to carry forward if any code is copied:
`Cody Brocious / Kyle Machulis / The OpenYou Organization, emokit, 2010–2017`
plus the `Aes.py` public-domain notice from Bram Cohen.

## What is actually valuable in here

### 1. `doc/emotiv_protocol.asciidoc` — ⭐ the protocol spec

The only written description of the wire format. Contains the packet bit-layout, the battery lookup table, the counter/quality rotation, and the *reason the encryption exists*:

> "To ensure that raw data is only read by those that have paid for the **raw data license**, each USB dongle encrypts incoming wireless data via AES against a key composed of the Serial Number of the dongle before emitting it as an HID report."

It also documents the serial format `SNXXXXXXXXXXYYYY` and notes dates embedded in serials.

### 2. `python/emotiv_encrypted_data_UD20160103001874_*.csv` — ⭐⭐ real ciphertext

**Three captures of ~3200 real encrypted HID reports each, taken 2017-04-05 from a dongle whose serial is in the filename** (`UD20160103001874`). Because the serial is known, every candidate AES key is *fully determined* — no brute force needed, and the captures can be used to verify any decoder **entirely offline, without the headset**.

This is the single most useful artefact in the repo. See [[ud2016-crypto-crack]].

### 3. `python/key_solver.py`, `key_solver_bruteforce*.py`

Attempts at searching the key space. `key_solver.py` hardcodes `serial_number = 'UD20160103001874'` and builds a charset from the serial's last 4 characters plus the literal key bytes (`\x00`, `\x10`, `H`, `T`, `B`, `P`). Useful as a starting point for a real key search, though we did not need it.

### 4. `python/emokit/sensors.py` — the bit masks

`sensors_14_bits`, `sensors_16_bytes`, `quality_bits`, `sensor_quality_bit`, `sensors_mapping`. These encode emokit's *assumed* field layout, which our testing shows is wrong for the 2016+ format (see [[ud2016-crypto-crack]]).

### 5. `python/emokit/reader.py` — ⭐ a self-incriminating comment

```python
# Doesn't seem to matter how big we make the buffer 32 returned every time,
# 33 for other platforms
```

**The dongle returns 32-byte reports regardless of the requested size** — even though the "new format" code path assumes 64 bytes. This is direct evidence from the author that the new-format model was wrong.

### 6. `Find Key` — the IDA Pro reverse-engineering procedure

Step-by-step instructions for extracting the key from Emotiv's `Pure.EEG` binary with IDA. Of historical interest; not needed now that the derivation is known.

### 7. `linux/epoc.rules` — udev rules

For HID device permissions on Linux.

## How this directory is used

- **Read-only reference.** Our own implementation lives in `src/`, not here.
- `scripts/test_ud2016_crypto.py`, `scripts/analyze_capture.py`, `scripts/decode_capture.py` read the captures from here.

## Caveat

The captures were made in 2017 on a **2016** dongle. They tell us nothing directly about a 2019/2020 dongle — the key *pattern* may differ. They do give us a verified oracle and a method that can be pointed at a fresh capture from the target unit.
