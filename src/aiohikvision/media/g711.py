"""G.711 (ITU-T G.191 reference): the µ-law and A-law the door stations speak.

The same encoders as the integration's browser microphone, and as Python's audioop had: the
tables match audioop's lin2ulaw and lin2alaw on every 16-bit sample.
"""

from __future__ import annotations

import math
import struct
from functools import cache

RATE = 8000
FRAME_SAMPLES = 160
"""20 ms, the frames the browser sends and Talkback takes."""
PCMU = 0
PCMA = 8
_MU_LAW_SEGMENTS = (0x3F, 0x7F, 0xFF, 0x1FF, 0x3FF, 0x7FF, 0xFFF, 0x1FFF)
_A_LAW_SEGMENTS = (0x1F, 0x3F, 0x7F, 0xFF, 0x1FF, 0x3FF, 0x7FF, 0xFFF)
_A_LAW_LINEAR = 2
"""A-law's first two segments share one step size."""


def mu_law(sample: int) -> int:
    """Encode a 16-bit sample in µ-law (PCMU)."""
    value = sample >> 2
    mask = 0xFF
    if value < 0:
        mask = 0x7F
        value = -value
    value = min(value, 8159) + 0x21
    for segment, end in enumerate(_MU_LAW_SEGMENTS):
        if value <= end:
            return ((segment << 4) | ((value >> (segment + 1)) & 0x0F)) ^ mask
    return 0x7F ^ mask


def a_law(sample: int) -> int:
    """Encode a 16-bit sample in A-law (PCMA)."""
    value = sample >> 3
    mask = 0xD5
    if value < 0:
        mask = 0x55
        value = -value - 1
    for segment, end in enumerate(_A_LAW_SEGMENTS):
        if value <= end:
            step = 1 if segment < _A_LAW_LINEAR else segment
            return ((segment << 4) | ((value >> step) & 0x0F)) ^ mask
    return 0x7F ^ mask  # pragma: no cover (every 13-bit value has a segment, see the table test)


@cache
def table(payload_type: int) -> bytes:
    """Return the code of every 16-bit sample, from -32768 up, in PCMU (0) or PCMA (8)."""
    encode = {PCMU: mu_law, PCMA: a_law}[payload_type]
    return bytes(encode(sample) for sample in range(-32768, 32768))


def encode(pcm: bytes, payload_type: int = PCMU) -> bytes:
    """Encode 16-bit little-endian mono PCM in G.711."""
    codes = table(payload_type)
    samples = struct.unpack(f"<{len(pcm) // 2}h", pcm[: len(pcm) // 2 * 2])
    return bytes(codes[sample + 32768] for sample in samples)


def tone(frequency: float, seconds: float, amplitude: int = 6000) -> bytes:
    """Build a sine tone as 16-bit little-endian mono PCM at 8 kHz."""
    count = round(seconds * RATE)
    return struct.pack(
        f"<{count}h", *(round(amplitude * math.sin(2 * math.pi * frequency * n / RATE)) for n in range(count))
    )


SILENCE = {PCMU: 0xFF, PCMA: 0xD5}
"""The code of digital silence in each law."""


def frames(codes: bytes, payload_type: int = PCMU) -> list[bytes]:
    """Cut G.711 into 20 ms frames, the last one padded with the law's silence."""
    silence = bytes([SILENCE[payload_type]])
    chunks = [codes[i : i + FRAME_SAMPLES] for i in range(0, len(codes), FRAME_SAMPLES)]
    if chunks and len(chunks[-1]) < FRAME_SAMPLES:
        chunks[-1] += silence * (FRAME_SAMPLES - len(chunks[-1]))
    return chunks
