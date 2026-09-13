"""Decoding: the two mistakes that were made once and must never be made again.

1. Reading the fields as *signed* manufactures 65535-count spikes.
2. Restarting the highpass every burst stamps a step into the signal.

Both are invisible in a summary statistic and obvious in the assertions below.
"""

from __future__ import annotations

import numpy as np
import pytest

from eeg_api.domain.models import CHANNEL_OFFSETS, CHANNELS, EEG_PACKET_TYPE, UV_PER_LSB
from eeg_api.eeg.crypto import (
    crypto_key,
    decrypt_ecb,
    key_candidates,
    new_crypto_key,
    serial_key,
)
from eeg_api.eeg.decoder import UVStream, decode_reports, raw_counts, u16le


REPORT_LEN = 32


def make_report(
    *, byte1: int = EEG_PACKET_TYPE, counter: int = 0, values: dict[int, int] | None = None
) -> np.ndarray:
    """A decrypted report with little-endian fields at the given offsets."""
    row = np.zeros(REPORT_LEN, dtype=np.uint8)
    row[0] = counter
    row[1] = byte1
    for offset, value in (values or {}).items():
        row[offset] = value & 0xFF
        row[offset + 1] = (value >> 8) & 0xFF
    return row


def test_fields_are_read_little_endian() -> None:
    row = make_report(values={2: 0x0201})  # F3
    counts = raw_counts(np.array([row], dtype=np.uint8))
    assert counts[0, 0] == 0x0201


def test_a_high_byte_crossing_is_not_a_spike() -> None:
    """The bug: 0x7FFF -> 0x8000 as *signed* is a -65535 jump. As unsigned it is +1."""
    low = make_report(values={2: 0x7FFF})
    high = make_report(values={2: 0x8000})
    counts = raw_counts(np.array([low, high], dtype=np.uint8))
    assert counts[0, 0] == 32767
    assert counts[1, 0] == 32768
    assert counts[1, 0] - counts[0, 0] == 1


def test_u16le_matches_manual_composition() -> None:
    row = make_report(values={14: 0x1234})  # O1
    assert u16le(np.array([row], dtype=np.uint8), 14)[0] == 0x1234


def test_only_eeg_packets_become_samples() -> None:
    eeg = make_report(byte1=EEG_PACKET_TYPE, values={2: 1000})
    status = make_report(byte1=0x20, values={2: 9999})
    uv, counters, _quality = decode_reports(np.array([eeg, status], dtype=np.uint8))
    assert uv.shape == (1, len(CHANNELS))
    assert counters.tolist() == [0]


def test_every_channel_has_a_field_and_they_are_distinct() -> None:
    values = {offset: 100 + index for index, (_, offset) in enumerate(CHANNEL_OFFSETS)}
    counts = raw_counts(np.array([make_report(values=values)], dtype=np.uint8))
    assert counts.shape == (1, len(CHANNELS))
    assert sorted(counts[0].tolist()) == sorted(values.values())


def test_the_highpass_removes_a_large_dc_offset() -> None:
    """The real signal sits on a ~16000-count electrode offset."""
    stream = UVStream()
    counts = np.full((600, len(CHANNELS)), 16000.0)
    uv = stream.push(counts)
    # A constant input decays to zero, so the tail is DC-free while the head is not.
    assert abs(float(uv[-1, 0])) < 1.0
    assert abs(float(uv[0, 0])) < abs(16000.0 * UV_PER_LSB)


def test_pushing_in_two_halves_equals_pushing_at_once() -> None:
    """The stream must be continuous: a per-burst filter restart would fail this."""
    rng = np.random.default_rng(11)
    counts = (rng.standard_normal((256, len(CHANNELS))) * 40 + 16000).astype(np.float64)

    whole = UVStream().push(counts)

    stream = UVStream()
    first = stream.push(counts[:100])
    second = stream.push(counts[100:])
    halves = np.vstack([first, second])

    assert np.allclose(whole, halves, atol=1e-9)


def test_a_signal_scales_by_0_51_microvolts_per_count() -> None:
    """A slow sine of 100 counts peak must come out as 51 uV peak."""
    stream = UVStream()
    t = np.arange(1280) / 128.0
    counts = np.zeros((1280, len(CHANNELS)))
    counts[:, 0] = 16000.0 + 100.0 * np.sin(2 * np.pi * 2.0 * t)
    uv = stream.push(counts)
    settled = uv[512:, 0]  # let the highpass transient die, then measure
    peak_uv = float(settled.max() - settled.min()) / 2.0
    assert peak_uv == pytest.approx(100 * UV_PER_LSB, rel=0.05)


# --------------------------------------------------------------------------- #
# Crypto
# --------------------------------------------------------------------------- #
def test_new_crypto_key_matches_emokit_for_the_documented_capture() -> None:
    """The derivation emokit's own captured ciphertext was decrypted with."""
    assert new_crypto_key("UD20160103001874") == b"4778887141771174"


def test_new_crypto_key_for_this_unit() -> None:
    # UD20180927003B78 -> the last four characters are 3B78.
    assert new_crypto_key("UD20180927003B78") == b"877BBB7383773378"


def test_the_serial_decides_the_crypto_path() -> None:
    # 2018 is the UD2016+ branch; a pre-2016 date falls back to the legacy key.
    assert serial_key("UD20180927003B78") == new_crypto_key("UD20180927003B78")
    assert serial_key("UD20150103001874") == crypto_key("UD20150103001874")


def test_there_are_four_candidate_keys_and_they_differ() -> None:
    keys = dict(key_candidates("UD20180927003B78"))
    assert len(keys) == 4
    assert len(set(keys.values())) == 4


def test_decrypt_is_the_inverse_of_encrypt_per_block() -> None:
    from Crypto.Cipher import AES

    key = new_crypto_key("UD20180927003B78")
    plaintext = bytes(range(32))
    ciphertext = b"".join(
        AES.new(key, AES.MODE_ECB).encrypt(plaintext[i : i + 16]) for i in (0, 16)
    )
    assert decrypt_ecb(key, ciphertext) == plaintext


def test_report_is_32_bytes_and_splits_into_two_blocks() -> None:
    assert REPORT_LEN == 32
    assert len(decrypt_ecb(new_crypto_key("UD20180927003B78"), bytes(32))) == 32
