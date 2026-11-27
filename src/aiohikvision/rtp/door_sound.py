"""The door's sound during a call: its G.711 RTP packets, in order, for a listener.

A door station sends 40 ms PCMU or PCMA packets through the whole call. They come in a
burst of about 200 ms at the start, then a packet every 33 ms (median) and up to 106 ms
late (docs/DEVICE_FINDINGS.md). DoorSound keeps the packets of the door and of the codec
of the call, and drops one that comes again or behind one already handed on. It has no
jitter buffer: the player of the sound has one. It is pure: the socket of the call feeds
it.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from aiohikvision.rtp.packets import RtpPacket

if TYPE_CHECKING:
    from collections.abc import Callable, Collection

HALF_SEQUENCE = 0x8000
"""A sequence this far ahead or more is behind instead: the 16-bit counter wraps (RFC 3550)."""


class Dropped(StrEnum):
    """Why a datagram on the socket of the call is not the door's sound."""

    NOT_RTP = "not_rtp"
    FOREIGN = "foreign"
    """From another address than the door's."""
    OTHER_PAYLOAD = "other_payload"
    """Another payload type: a key press (telephone-event), comfort noise."""
    LATE = "late"
    """Again, or behind a packet already handed on."""


@dataclass(slots=True)
class DoorSoundStats:
    """What the door sent: the packets handed on, and those dropped, by why."""

    packets: int = 0
    dropped: Counter[Dropped] = field(default_factory=Counter)


class DoorSound:
    """The door's G.711 payloads of one call, in order, handed to a listener.

    Each payload is 40 ms of the door's microphone in the law of the call (µ-law for
    payload type 0, A-law for 8), as the door sent it.
    """

    def __init__(self, doors: Collection[str], payload_type: int, listener: Callable[[bytes], None]) -> None:
        """Hand on the packets of a payload type from the addresses of a door."""
        self.payload_type = payload_type
        self.stats = DoorSoundStats()
        self._doors = frozenset(doors)
        self._listener = listener
        self._ssrc: int | None = None
        self._sequence = 0

    def received(self, data: bytes, addr: tuple[str, int]) -> None:
        """Take a datagram of the socket of the call."""
        packet = RtpPacket.parse(data)
        if packet is None:
            self.stats.dropped[Dropped.NOT_RTP] += 1
            return
        if (dropped := self.judge(packet, addr[0])) is not None:
            self.stats.dropped[dropped] += 1
            return
        self._ssrc, self._sequence = packet.ssrc, packet.sequence
        self.stats.packets += 1
        self._listener(packet.payload)

    def judge(self, packet: RtpPacket, host: str) -> Dropped | None:
        """Return why a packet from a host is not the door's sound, or None when it is."""
        if host not in self._doors:
            return Dropped.FOREIGN
        if packet.payload_type != self.payload_type:
            return Dropped.OTHER_PAYLOAD
        if packet.ssrc == self._ssrc:
            ahead = (packet.sequence - self._sequence) & 0xFFFF
            if ahead == 0 or ahead >= HALF_SEQUENCE:
                return Dropped.LATE
        return None
