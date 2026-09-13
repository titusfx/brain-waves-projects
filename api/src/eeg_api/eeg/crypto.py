"""The dongle's cryptography — byte-for-byte ports of emokit's derivations.

Four derivations exist in emokit and only one is correct for a given dongle. The
oracle is decisive and cheap: after decrypting with the right key, **byte 1 of
every report collapses to about two values** (0x10 EEG, 0x20 status). With the
wrong key it is uniformly random across 0..255.

emokit itself picks the branch with ``serial.startswith("UD2016")`` — a literal
string test that fails on this unit (``UD20180927003B78``), silently selecting the
wrong key. That is why nothing here delegates to emokit's dispatch: the caller
decides, and :func:`key_candidates` returns all four so the check can be made
rather than assumed.
"""

from __future__ import annotations

from collections.abc import Iterator

from Crypto.Cipher import AES


BLOCK = 16


def new_crypto_key(serial: str) -> bytes:
    """emokit's key for UD2016+ dongles. Correct for this unit."""
    k = ["\0"] * 16
    (k[0], k[1], k[2], k[3]) = (serial[-1], serial[-2], serial[-2], serial[-3])
    (k[4], k[5], k[6], k[7]) = (serial[-3], serial[-3], serial[-2], serial[-4])
    (k[8], k[9], k[10], k[11]) = (serial[-1], serial[-4], serial[-2], serial[-2])
    (k[12], k[13], k[14], k[15]) = (serial[-4], serial[-4], serial[-2], serial[-1])
    return "".join(k).encode("latin-1")


def epoc_plus_crypto_key(serial: str) -> bytes:
    """emokit's key for ``force_epoc_mode`` on a UD2016 dongle."""
    k = ["\0"] * 16
    (k[0], k[1], k[2], k[3]) = (serial[-1], "\x00", serial[-2], "\x15")
    (k[4], k[5], k[6], k[7]) = (serial[-3], "\x00", serial[-4], "\x0c")
    (k[8], k[9], k[10], k[11]) = (serial[-3], "\x00", serial[-2], "D")
    (k[12], k[13], k[14], k[15]) = (serial[-1], "\x00", serial[-2], "X")
    return "".join(k).encode("latin-1")


def crypto_key(serial: str, is_research: bool = False) -> bytes:
    """emokit's legacy key, used on pre-UD2016 dongles."""
    k = ["\0"] * 16
    k[0], k[1], k[2] = serial[-1], "\0", serial[-2]
    if is_research:
        k[3], k[4], k[5], k[6], k[7] = "H", serial[-1], "\0", serial[-2], "T"
        k[8], k[9], k[10], k[11] = serial[-3], "\x10", serial[-4], "B"
    else:
        k[3], k[4], k[5], k[6], k[7] = "T", serial[-3], "\x10", serial[-4], "B"
        k[8], k[9], k[10], k[11] = serial[-1], "\0", serial[-2], "H"
    k[12], k[13], k[14], k[15] = serial[-3], "\0", serial[-4], "P"
    return "".join(k).encode("latin-1")


def key_candidates(serial: str) -> Iterator[tuple[str, bytes]]:
    """Every derivation emokit knows, best first."""
    yield "new_crypto_key (UD2016+ branch)", new_crypto_key(serial)
    yield "epoc_plus_crypto_key (force_epoc_mode)", epoc_plus_crypto_key(serial)
    yield "crypto_key(is_research=False) [legacy]", crypto_key(serial, False)
    yield "crypto_key(is_research=True) [legacy]", crypto_key(serial, True)


def decrypt_ecb(key: bytes, data: bytes) -> bytes:
    """AES-128-ECB, block by block — emokit's ``decrypt_data()``.

    The report is 32 bytes, i.e. two independent 16-byte blocks, so ECB's usual
    weakness is irrelevant here: there is no repeated plaintext structure to leak.
    """
    cipher = AES.new(key, AES.MODE_ECB)
    return b"".join(
        cipher.decrypt(data[i : i + BLOCK]) for i in range(0, len(data) - (BLOCK - 1), BLOCK)
    )


def serial_key(serial: str) -> bytes:
    """The key this project uses, chosen by the *parsed date* rather than a prefix test.

    Serials encode ``UD`` + ``YYYYMMDD`` + counter, so the crypto path is a function
    of the date. Pre-2016 units use the legacy derivation; everything from 2016 on
    uses :func:`new_crypto_key`.
    """
    digits = serial[2:10] if serial.upper().startswith("UD") else ""
    if len(digits) == 8 and digits.isdigit() and int(digits[:4]) < 2016:
        return crypto_key(serial, False)
    return new_crypto_key(serial)
