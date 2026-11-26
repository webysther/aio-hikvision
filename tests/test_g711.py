"""G.711: the reference encoders, as audioop and the browser microphone have them."""

from __future__ import annotations

import hashlib
import struct

import pytest

from aiohikvision.media.g711 import PCMA, PCMU, a_law, encode, frames, mu_law, table, tone


def test_every_sample_as_the_reference() -> None:
    """The tables match audioop's lin2ulaw and lin2alaw (hashes pinned by the card's tests too)."""
    assert hashlib.sha256(table(PCMU)).hexdigest() == (
        "81d633c9e6972a18c74a58720b96cb8ca0bdd096d4060b646dd708c3b846019a"
    )
    assert hashlib.sha256(table(PCMA)).hexdigest() == (
        "38488f6fd710f4686360edc4d38639f96c491595ef93f8eb8d62d5e07ca6ce7b"
    )


def test_silence() -> None:
    """Zero is each law's silence."""
    assert mu_law(0) == 0xFF
    assert a_law(0) == 0xD5


def test_encode() -> None:
    """PCM in, one code per sample out; an odd last byte is left out."""
    pcm = struct.pack("<3h", 0, 32767, -32768) + b"\x01"
    assert encode(pcm) == bytes([0xFF, mu_law(32767), mu_law(-32768)])
    assert encode(pcm, PCMA) == bytes([0xD5, a_law(32767), a_law(-32768)])


def test_tone() -> None:
    """A second of tone is 8000 samples, within the amplitude."""
    pcm = tone(1000, 1.0, 6000)
    samples = struct.unpack(f"<{len(pcm) // 2}h", pcm)
    assert len(samples) == 8000
    assert max(samples) <= 6000
    assert min(samples) >= -6000


@pytest.mark.parametrize(("payload_type", "silence"), [(PCMU, 0xFF), (PCMA, 0xD5)])
def test_frames(payload_type: int, silence: int) -> None:
    """20 ms frames, the last one padded with the law's silence."""
    chunks = frames(bytes(330), payload_type)
    assert [len(c) for c in chunks] == [160, 160, 160]
    assert chunks[2] == bytes(10) + bytes([silence]) * 150
    assert frames(b"") == []
