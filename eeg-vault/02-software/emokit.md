---
title: emokit — the community driver
type: software
repo: https://github.com/openyou/emokit
language: Python
last_code_commit: 2017-04-17
last_push: 2019-07-05
status: ARCHIVED
stars: 562
forks: 235
open_issues: 66
tags: [software, emokit, open-source, usb-hid, aes]
updated: 2026-02-14
---

# emokit

The one serious community attempt at freeing the EPOC from Emotiv's software. **Last functional commit 17 April 2017; the GitHub repo is now formally ARCHIVED** (last push 2019-07-05, 562 stars, 235 forks, 66 open issues). But it is the only documented map of the dongle protocol, so it is the foundation any future work stands on.

> 🎯 **See [[ud2016-crypto-crack]] — we tested this repo's own encrypted captures offline and CONFIRMED that `new_crypto_key` is correct for `UD2016` dongles.** The "2016+ unsupported" claim is beatable. The failure was never the crypto; it was the packet layout.
>
> Also note: `emokit` is **public domain** (BSD-style fallback), so its logic can be freely vendored and adapted with attribution. A local clone lives in `vendor/emokit/` — see `vendor/README.md`.

- **Repo:** <https://github.com/openyou/emokit> — **archived**
- **Last code commit:** `7f25321` — *"Merge pull request #255 from CerebralPower/master"*, **2017-04-17**
- **Language:** Python (`pip install emokit`)
- **Original authors:** Cody Brocious (`daeken`), Kyle Machulis (`qdot`); later Bill Schumacher fixed the Python library; Sharif Olorin added `hidapi` support
- **C port:** <https://github.com/openyou/emokit-c> (separate repo)
- **Go binding:** <https://github.com/fractalcat/emogo>

## What it does and does not give you

From `FAQ.md`, verbatim:

> **What data does emokit give me?** The raw channels of the headset … Battery power … Signal quality of each connection
> **What data does emokit not give me?** Processed data that can tell you moods or muscles or whatever.
> … We publish emokit as a low level access tool, nothing more.

So: raw ADC counts → µV, battery, per-electrode contact quality. No band powers, no mental commands, no artifact rejection, no filters. **You bring the DSP.** That is a feature, not a bug, for this project — it means emokit is a clean acquisition layer.

## Declared support matrix

> **Supported:** Epoc, Epoc+(Pre-2016, limited gyro sensors)
> **Unsupported:** Epoc+(2016+), other models.

But the *code* contradicts the README in an interesting way — see [[identify-your-revision]]. There is a working-looking `UD2016` branch:

```python
if self.serial_number.startswith("UD2016") and not self.force_epoc_mode:
    self.new_format = True          # → 64-byte packets, EmotivNewPacket
```

and in the crypto layer:

```python
if self.serial_number.startswith('UD2016') and not self.force_old_crypto:
    if self.force_epoc_mode:
        return AES.new(epoc_plus_crypto_key(self.serial_number), AES.MODE_ECB, iv)
    else:
        return AES.new(new_crypto_key(self.serial_number))
else:
    return AES.new(crypto_key(self.serial_number, self.is_research), AES.MODE_ECB, iv)
```

**Read the README as "we could not confirm this works" rather than "this was never attempted."**

### And then it has a bug that matters for this project ⚠️

`startswith("UD2016")` is a **literal string comparison, not a date test**. Combined with the finding that serials encode the manufacture date (`UD` + `YYYYMMDD` + counter → [[identify-your-revision]]), this means:

> **A dongle made in 2017, 2018, 2019 or 2020 has a serial like `UD2019…`, which matches neither `"UD2016"` nor a sane legacy assumption — and emokit silently falls through to the OLD crypto key.**

A GitHub search for `UD2017`/`UD2018`/`UD2019` in the repo returns **zero results**: nobody ever reported or fixed it. This is the single most consequential latent bug for our unit, which appears to be 2019–2020 vintage.

### How well the `UD2016` path worked in practice

Decryption succeeded; the data did not. From [issue #229](https://github.com/openyou/emokit/issues/229), a real 2016 dongle:

- ✅ *"The good news, decryption is working it seems."*
- ❌ implausible sensor values
- ❌ sample rate capped at **~192 Hz** instead of 256
- ❌ battery had to be hardcoded to 0
- ❌ X/Y gyro *"were still moving"* while stationary

Closed 2017-04-14. The final commit messages are self-aware: *"Fixed epoc+ sensor data**?**"*, *"…set old epoc get_level to something reasonable, maybe."*

## The three AES key derivations

All are **AES-ECB** over 16-byte keys derived from the **last 4 characters of the serial number**. `decrypt_data()` decrypts the 32-byte packet as two independent 16-byte ECB blocks.

| Function | Applies to | Key structure (indices into a 16-byte key) |
| --- | --- | --- |
| `crypto_key(serial, is_research)` | pre-2016 EPOC / EPOC+ | interleaves `s[-1], s[-2], s[-3], s[-4]` with literals `'T'`, `'\x10'`, `'B'`, `'H'`, `'P'`; `is_research=True` swaps in `'H'`, `'T'`, `'\x10'`, `'B'` at different slots |
| `new_crypto_key(serial)` | `UD2016…` dongles | `s[-1], s[-2], s[-2], s[-3], s[-3], s[-3], s[-2], s[-4], s[-1], s[-4], s[-2], s[-2], s[-4], s[-4], s[-2], s[-1]` — no literals at all |
| `epoc_plus_crypto_key(serial)` | `UD2016…` + `force_epoc_mode` | interleaves serial chars with literals `'\x15'`, `'\x0C'`, `'D'`, `'X'` |

The `is_research` flag is documented by its own author as unreliable:

> `:param is_research - Is EPOC headset research edition? Doesn't seem to work even if it is.`

and again in `decrypter.py`:

> `# EPOC+ and research edition may need to have this set to True`
> `# TODO: Add functions that check variance in data received. If extreme toggle is_research and check again.`

That TODO is exactly the heuristic [[identify-your-revision]] recommends doing by hand: **try the key, look at the variance, if it is garbage try the other key.**

## Marks of abandonment (worth knowing before trusting output)

- **`get_gyro()` is a stub that returns the constant `42`:**
  ```python
  def get_gyro(data, bits, verbose=False):
      level = 42
      return level
  ```
  The README's "limited gyro sensors" is doing a lot of work. **Motion data from emokit is not real.**
- Python 2/3 straddling throughout (`sys.version_info >= (3,0)` branches, `latin-1` round-trips, `unicode = str` shims).
- Depends on **`pycrypto`**, which is unmaintained/has known CVEs — must be swapped for `pycryptodome` (`Crypto.Cipher.AES` import path is compatible).
- Windows path uses `pywinusb`, *not* `hidapi` — a different API surface from the POSIX path (`find_all_hid_devices()` vs `hid_enumerate()`), so bug reports are platform-specific.
- Packet-validation logic (`validate_data`) prepends a byte to reach 33/65 because the sensor bit-masks are 1-indexed. Fragile but stable.

## Interface (what a wrapper must adapt)

```python
from emokit.emotiv import Emotiv

with Emotiv(display_output=True, verbose=True) as headset:
    while True:
        packet = headset.dequeue()
        if packet is not None:
            ...   # packet.sensors['AF3']['value'], ['quality'], packet.battery
```

Key constructor knobs for our purposes:

| Param | Why it matters |
| --- | --- |
| `serial_number` | Needed when serial can't be auto-detected; **and it is the dongle's serial that seeds the key** |
| `is_research` | Toggles the alternate legacy key; author admits it's unreliable |
| `force_epoc_mode` | Treat a `UD2016` dongle with EPOC semantics / `epoc_plus_crypto_key` |
| `force_old_crypto` | Force the legacy `crypto_key()` path on a `UD2016` serial |
| `input_source` | Can replay a recorded CSV instead of a headset — **useful for developing without hardware** |
| `write`, `write_values`, `write_decrypted` | Built-in CSV sinks |

`input_source` accepting a file is a small gift: it means the replay/testing harness in [[roadmap]] can reuse emokit's own reader.

## Verdict for this project

| Use it as | Don't use it as |
| --- | --- |
| The protocol reference / crypto oracle | A dependency you trust long-term |
| A first-attempt acquisition backend | A source of trustworthy motion data |
| A CSV replay source | Anything needing maintenance or security guarantees |

**Strategy:** vendor the crypto + packet-decoding logic into our own small, tested, dependency-light module rather than depending on `pip install emokit`. Keep it behind the `Source` interface so it can be replaced.

## Known-issue trail

| Issue | Title | What it establishes |
| --- | --- | --- |
| [#138](https://github.com/openyou/emokit/issues/138) | *Is the Epoc+ supported?* | pre-2016 EPOC+ dongle is `VID 1234 / PID ED02` |
| [#145](https://github.com/openyou/emokit/issues/145) | *EPOC+ limited licence issue* | ⭐ **emokit is READ-ONLY.** Maintainer: *"Emokit will not change the dongle settings in any way (that I've been able to detect or find remotely plausible)."* Non-destructive — safe to try. |
| [#146](https://github.com/openyou/emokit/issues/146) | *is the emotiv insight supported?* | ⚠️ **Not about the EPOC+ at all.** Opened and closed 2015-07-14. Don't cite it as EPOC+ evidence. |
| [#229](https://github.com/openyou/emokit/issues/229) | 2016+ EPOC+ testing | serial `UD20160103001874` → manufacture date 2016-01-03; decryption worked, data did not (see above) |
| `#249`–`#255` | final burst, April 2017 | *"Added force old crypto option"*, *"Fixed epoc+ sensor data?"*, *"troubleshooting, scratch files, fixed gyro values in epoc mode"*, *"Re-enable old packet, remove debugging prints"* |

The README's `Headset Support` block was itself added on **2017-04-05** (commit `b9009886`) — in the same April-2017 burst as the new-crypto work whose commit messages are hedged. The disclaimer and the code were written together, by someone unsure the code worked.

## It is read-only — try it without fear

Because the key derives from the dongle, a natural worry is that poking at it might alter pairing or trip a licence. It does not (issue #145, above). **Running emokit does not modify the dongle and cannot consume a licence.** The only cost of trying is your time.

## Forks and reimplementations — the discouraging summary

| Repo | Lang | Approach | Last push | Works on 2016+? |
| --- | --- | --- | --- | --- |
| `openyou/emokit` | Python | USB HID + AES, experimental `UD2016` path | archived 2019 | ❌ per its own README |
| `a455bcd9/emokit` | Python | fork "for the EPOC+ only" — VID/PID + gyro-centre hacks | 2015-10 | ❌ pre-2016 only |
| `fabriciotorquato/emokit`, + ~230 other forks | Python/C | mirrors of upstream | 2011–2019 | ❌ no distinct 2016+ implementation |
| `eugenehp/emotiv-rs` | Rust | **Cortex API client** — *not* a dongle reader | active | n/a — its `raw` feature is **mock-only** |

`emotiv-rs`'s own `RAW_FEATURE.md` states: *"No real BLE/USB driver integration (btleplug/hidapi not fully integrated) · Uses mock device data for testing"*, and its planned-enhancements list still has `[ ] HIDAPI USB integration` unchecked. Its examples print `MOCK-SN-000001`.

**Conclusion: there is no verified, working, maintained open-source reader for a 2016+ EPOC+ over the USB dongle.** This is strong evidence, though not exhaustive proof.


## Sources
- <https://github.com/openyou/emokit>
- <https://raw.githubusercontent.com/openyou/emokit/master/README.md>
- <https://raw.githubusercontent.com/openyou/emokit/master/FAQ.md>
- <https://raw.githubusercontent.com/openyou/emokit/master/python/emokit/emotiv.py>
- <https://raw.githubusercontent.com/openyou/emokit/master/python/emokit/decrypter.py>
- <https://raw.githubusercontent.com/openyou/emokit/master/python/emokit/util.py>

## Related
[[common-info-eeg-device]] · [[identify-your-revision]] · [[opensource-landscape]] · [[cortex-api]] · [[roadmap]]
