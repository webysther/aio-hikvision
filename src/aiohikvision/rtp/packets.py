"""RTP packets as they arrive (RFC 3550): the header a receiver reads, and the payload."""

from __future__ import annotations

import struct
from dataclasses import dataclass

HEADER_BYTES = 12
"""The fixed header: version, flags, payload type, sequence, timestamp, SSRC."""
VERSION = 2


@dataclass(frozen=True, slots=True)
class RtpPacket:
    """An RTP packet: what a receiver needs to put its payload in order."""

    payload_type: int
    sequence: int
    timestamp: int
    ssrc: int
    marker: bool
    payload: bytes

    @classmethod
    def parse(cls, data: bytes) -> RtpPacket | None:
        """Read a datagram; None when it is no RTP packet of version 2.

        The contributing sources, the header extension and the padding are skipped.
        """
        if len(data) < HEADER_BYTES or data[0] >> 6 != VERSION:
            return None
        first, second, sequence, timestamp, ssrc = struct.unpack_from("!BBHII", data)
        start = HEADER_BYTES + 4 * (first & 0x0F)
        if first & 0x10:
            if len(data) < start + 4:
                return None
            (words,) = struct.unpack_from("!H", data, start + 2)
            start += 4 + 4 * words
        end = len(data) - (data[-1] if first & 0x20 else 0)
        if end < start:
            return None
        return cls(second & 0x7F, sequence, timestamp, ssrc, bool(second & 0x80), data[start:end])
