---
title: "UD2016 Protocol — Cracked Offline"
type: results
status: SOLVED (crypto + packet layout)
tags: [reverse-engineering, emokit, aes, results, breakthrough]
updated: 2026-02-14
---

# UD2016 Protocol — Cracked Offline

**We beat the "Unsupported: Epoc+(2016+)" claim — and we did it without the headset.**

Both unknowns are now solved: **the encryption key** and **the packet layout**. There is a working decoder that turns a captured file — or the live dongle — into 14 channels of microvolts.

## ✅ CONFIRMED ON THE REAL DEVICE (2026-02-14)

Everything below was derived from emokit's 2016 captures. It has since been **verified end-to-end on the actual 2018 dongle** (serial `UD20180927003B78`, → [[device-identifiers]]):

```
interface 1 ('EEG Signals'): 1914 reports in 12 s  (~160/s)

new_crypto_key (correct)   byte1 distinct values =   2   {0x10: 1532, 0x20: 382}
crypto_key(is_research=F)  byte1 distinct values = 256   <- noise
crypto_key(is_research=T)  byte1 distinct values = 255   <- noise
```

- **Live key confirmed** — 2 distinct `byte1` values vs 256 for the wrong keys.
- **Layout confirmed** — little-endian won **12/14 fields** on this dongle too (`scripts/check_layout_live.py`).
- **Amplitudes sane** — 7–16 µV with dry electrodes on a desk. That is noise floor, not brain; it needs the alpha test. → [[roadmap]]
- **This unit is a confirmed victim of emokit's `startswith("UD2016")` bug** — the exact trap predicted in [[identify-your-revision]].

Live read: `scripts/read_live.py`. Layout check: `scripts/check_layout_live.py`.

## ⚠️ Decoder gotcha: do NOT treat the fields as signed int16

Found the hard way on live data. The high byte legitimately flips across the `0x7F`/`0x80` boundary as the signal drifts — e.g. byte 3 is `0x7F` for 996 packets and `0x80` for 26. Interpreting the pair as **signed** int16 turns each flip into a **65535-count jump**, manufacturing enormous fake spikes. We measured a bogus **5317 µV** on F8 from 26 flip events.

**Correct model:** an **unsigned** raw ADC reading with a large per-channel DC offset (the electrode offset), removed with a 0.5 Hz highpass — exactly as in any real EEG pipeline. After the fix, the same live data gave 7–16 µV across all 14 channels. See `to_counts()` in `scripts/decode_to_csv.py`.

Reproduce:

```powershell
.venv\Scripts\python.exe scripts\test_ud2016_crypto.py    # key search
.venv\Scripts\python.exe scripts\analyze_capture.py       # entropy / structure
.venv\Scripts\python.exe scripts\find_layout.py           # brute-force the field layout
.venv\Scripts\python.exe scripts\verify_layout.py         # LE vs BE, spectral character
.venv\Scripts\python.exe scripts\decode_to_csv.py         # -> eeg_decoded.csv
```

## The answer up front — the format, complete

```
HID report : 32 bytes, AES-128-ECB encrypted
key        : new_crypto_key(dongle_serial)        e.g. UD20160103001874 -> b'4778887141771174'

byte 0     : packet counter (0..255)
byte 1     : packet type   0x10 = EEG sample,  0x20 = extra/status
bytes 2..31: 15 x 16-bit LITTLE-ENDIAN fields
```

| offset | field | offset | field |
| --- | --- | --- | --- |
| 2 | F3 | 18 | O2 |
| 4 | FC5 | 20 | P8 |
| 6 | AF3 | 22 | T8 |
| 8 | F7 | 24 | F8 |
| 10 | T7 | 26 | AF4 |
| 12 | P7 | 28 | FC6 |
| 14 | O1 | 30 | F4 |
| 16 | **QUALITY** (not EEG) | | |

**Scaling: 1 LSB = 0.51 µV.** Values carry a large per-channel DC offset (~16 000 µV) which must be removed with a 0.5 Hz highpass — standard EEG practice, not a decoding error.


## Result 1 — the key is confirmed ✅

```
serial : UD20160103001874
key    : new_crypto_key(serial) -> b'4778887141771174'
cipher : AES-128-ECB (emokit's decrypt_data(): two independent 16-byte blocks)
```

Not a guess. Three independent lines of evidence:

### Evidence A — 132 bits of entropy collapse

Per-byte-position Shannon entropy, correct key vs a deliberately wrong key (control). A wrong AES key yields white noise, so every position sits at 8.00 bits.

| | control (legacy key) | `new_crypto_key` |
| --- | --- | --- |
| byte 1 | 7.949 | **0.918** |
| byte 3 | 7.941 | **0.989** |
| byte 7 | 7.943 | **0.945** |
| byte 11 | 7.936 | **0.925** |
| byte 29 | 7.919 | **0.918** |
| … | ~7.9 everywhere | 0.9–1.7 at 16 of 32 positions |

**Total: 132.60 bits of structure recovered** across the 32 byte positions. A wrong key gives ~0.00. ECB is a bijection, so repeated-ciphertext effects appear under *any* key — this collapse is key-specific and therefore real.

### Evidence B — byte 1 matches emokit's own expectation ⭐

| key | byte[1] value distribution |
| --- | --- |
| **correct** | `0x10` (1067×) and `0x20` (2134×) — **exactly two values** |
| wrong | 190, 211, 50, 249, 134… spread uniformly |

And emokit's own new-format code contains:

```python
def is_extra_data(data):
    if ord(data[1]) == 32:      # 32 == 0x20
        return True
    return False
```

The decrypted stream produces **precisely the marker emokit's new-format code was written to detect**. That is not a coincidence a wrong key can produce.

### Evidence C — the counter becomes perfect once the packet types are separated

Full-stream packet counter (`byte0 & 0x7F`) shows only **33.81%** consecutive increments — but that is an artifact of interleaving. Split by byte 1:

| subset | n | byte 0 sequence | counter |
| --- | --- | --- | --- |
| `byte1 == 0x20` | 1067 | `74, 75, 76, 77, 78, 79, 80, …` | **perfect +1, range 0–127** |
| `byte1 == 0x10` | 2134 | `144, 149, 150, 151, 152, …` | +1, range 0–255 |

### Evidence D — real temporal structure appears

Lag-1 autocorrelation. Real band-limited EEG is strongly autocorrelated in time; noise is not.

| decoding | mean lag-1 autocorr |
| --- | --- |
| correct key, `byte1 == 0x10` packets | **+0.53** |
| correct key, `byte1 == 0x20` packets | −0.007 |
| correct key, all packets together (emokit's way) | **−0.50** |
| wrong key | +0.01 |

## Result 2 — the dongle still emits **32-byte** reports ⚠️

emokit's `new_format` path assumes `UD2016` dongles send **64-byte** reports:

```python
def validate_data(data, new_format=False):
    if new_format:
        if len(data) == 64:
            data.insert(0, 0)
        if len(data) != 65:
            return None
```

The captures are **32 bytes each**. And emokit's own reader admits it:

> `# Doesn't seem to matter how big we make the buffer 32 returned every time, 33 for other platforms`

So the "new format" is **not** a longer packet — emokit's core structural assumption was wrong. This alone would break every downstream offset.

## Result 3 — two interleaved packet types, decoded identically by emokit

The stream alternates between two packet types on a 2:1 ratio, tagged in byte 1:

| | `byte1 == 0x20` ("extra") | `byte1 == 0x10` ("normal") |
| --- | --- | --- |
| count | 1067 | 2134 |
| byte 0 | clean 0–127 counter | counter 0–255 |
| EEG content | none (median \|v\| = 0.0) | **present** (median \|v\| ≈ 4092) |
| autocorr | −0.007 | **+0.53** |

emokit's `EmotivNewPacket` runs **the same bit masks over both**, which produces:

- the **−0.50 autocorrelation** artifact (values alternating between two levels),
- **absurd amplitudes**: median ≈ **4092 µV**, max ≈ **8308 µV**. Scalp EEG is 10–100 µV. 4082 µV ≈ 0x1000 in raw counts — a strong hint the masks are reading a marker byte as signal.

## This explains emokit issue #229 exactly

Issue #229 reported, on a real 2016+ dongle:

| #229 symptom | Cause identified here |
| --- | --- |
| *"decryption is working it seems"* | ✅ correct — `new_crypto_key` **is** the right key |
| "implausible sensor values" | ❌ masks applied to both packet types; ~4092 µV nonsense |
| "sampling capped at ~192 Hz instead of 256" | ❌ 1/3 of reports are non-EEG "extra" packets being counted as samples |
| "battery needed hardcoding to 0" | ❌ battery is not in the same place as the legacy layout |
| "X and Y were still moving while stationary" | ❌ `get_gyro()` is literally `return 42` |

Every symptom is accounted for. The crypto was never the hard part — **the packet layout was.**

## How the layout was found

Autocorrelation is a **scoring function**: real band-limited EEG is strongly autocorrelated in time, so a correctly decoded channel scores high while a misaligned one scores ~0.

1. Isolated the `byte1 == 0x10` EEG packets (2134 of 3201).
2. Brute-forced every byte-aligned 16-bit window, in both byte orders (`find_layout.py`).
3. **Little-endian won 13 of 15 fields**, and the offsets matched emokit's `sensors_16_bytes` map exactly.
4. A per-byte diagnostic showed the odd bytes are slowly-varying *high* bytes (`byte 19: 0x73/0x74/0x72`, AC 0.64) while even bytes carry the fast signal — the signature of 16-bit LE fields.
5. Dumping raw packets made it visually obvious: `94 7D | 7F 7D | 92 7D | D0 80 | …` — low byte, then high byte.

**Mean lag-1 autocorrelation: BE = 0.555 → LE = 0.797** (best channel 0.922). emokit's byte *offsets* were right; its byte *order* was wrong.

## Evidence the decode is real physiology

The controls are what make this convincing. Decoded with the wrong key, or applied to the non-EEG `0x20` packets, everything collapses to zero:

| measure | **LE, EEG packets** | BE, EEG | LE, extra pkts | LE, wrong key |
| --- | --- | --- | --- | --- |
| mean lag-1 autocorrelation | **+0.797** | +0.480 | −0.032 | +0.007 |
| mean \|cross-channel correlation\| | **0.266** | 0.061 | — | 0.016 |

And the decoded signal behaves like EEG should:

- **Amplitudes 7–54 µV** — textbook scalp EEG range (T8 6.9 µV, AF4 53.5 µV).
- **Neighbouring electrodes correlate**: F7/F8 **+0.53**, F3/F4 **+0.35**, FC5/FC6 +0.34, AF3/AF4 +0.34. Physically sensible — and impossible to get from noise.
- **Band-limited spectrum**: theta 20–61 %, beta 19–50 %, alpha 6–16 %, delta 2–22 %, sub-0.5 Hz under 3 %. Brownian drift would be dominated by sub-1 Hz; this is not.
- **2134 EEG samples** from 3201 reports — the 2:1 split explains issue #229's *"capped at ~192 Hz"*.

## Status

| Component | State |
| --- | --- |
| AES key derivation (`new_crypto_key`) | ✅ **solved and verified** |
| Cipher mode (AES-128-ECB, two 16-byte blocks) | ✅ solved |
| Packet length (32 bytes, not 64) | ✅ solved |
| Packet type separation (byte 1) | ✅ solved |
| Field offsets (bytes 2…30, even) | ✅ solved |
| **Byte order — LITTLE-endian** | ✅ **solved** |
| µV scaling (0.51 µV/LSB) | ✅ solved — yields plausible amplitudes |
| Working decoder | ✅ `scripts/decode_to_csv.py` |
| Battery field | ⚠️ open (not needed for EEG) |
| Gyro / motion | ⚠️ open (`get_gyro()` is a stub) |
| **Verification on the owner's 2019/2020 unit** | ⚠️ **open — needs the hardware** |

## Applying this to the target unit

The captures come from a **2016** dongle; the unit at hand looks **2019–2020**, so the key pattern may differ. The method transfers directly:

1. `scripts/probe_device.py` → read the real serial and its encoded date.
2. Capture ~30 s of encrypted traffic from the target dongle.
3. Run the same tests: entropy collapse vs a control key; byte 1 collapsing to a small set; **autocorrelation > 0.7 after separating packet types**.
4. If the standard derivations fail, brute-force. `new_crypto_key` builds its key from only **4 serial characters**, so even an unknown pattern leaves a tiny search space — and these tests are an excellent oracle.

The decoder is written to be portable: point `decode_to_csv.py` at any capture and it will tell you whether the amplitudes are sane.

> ⚠️ **Never trust a stream you have not autocorrelation-tested.** A wrong key does not raise an error — it produces confident-looking numbers.

## Caveats

- Verified on **emokit's shipped 2016 captures**, not on the owner's hardware.
- The 32-byte finding contradicts emokit's documented model; that is our reading of these files.
- We recover only ~8 bits of useful dynamic range, because each channel's high byte sits at a near-constant DC offset. That is ample for EEG (10–100 µV at 0.51 µV/LSB) but worth knowing.
- The recording is **theta/beta dominant with little alpha** — consistent with a drowsy subject or a headset not properly fitted, not with relaxed eyes-closed. So this capture cannot serve as the alpha test; that still has to be done on a real head.
- Battery and gyro remain undecoded — neither blocks EEG work.


## Related
[[emokit]] · [[identify-your-revision]] · [[opensource-landscape]] · [[decisions-log]] · [[roadmap]] · [[references]]
