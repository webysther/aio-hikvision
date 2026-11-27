"""The door's sound: RTP packets read, and those of the door handed on in order."""

from __future__ import annotations

import struct

import pytest

from aiohikvision import DoorSound, Dropped, RtpPacket

DOOR = "192.0.2.10"
PAYLOAD = bytes([0xFF]) * 320  # 40 ms of PCMU silence


def rtp(
    sequence: int,
    payload: bytes = PAYLOAD,
    *,
    payload_type: int = 0,
    ssrc: int = 7,
    marker: bool = False,
    first: int = 0x80,
    extra: bytes = b"",
) -> bytes:
    """Build an RTP packet: ``first`` holds the version and flags, ``extra`` what follows the header."""
    second = (0x80 if marker else 0) | payload_type
    return struct.pack("!BBHII", first, second, sequence, sequence * 320, ssrc) + extra + payload


def test_a_packet_is_read() -> None:
    """The header gives the payload type, sequence, timestamp, source and marker."""
    packet = RtpPacket.parse(rtp(5, marker=True))
    assert packet == RtpPacket(0, 5, 1600, 7, marker=True, payload=PAYLOAD)


@pytest.mark.parametrize(
    ("data", "payload"),
    [
        # Two contributing sources
        (rtp(1, b"abc", first=0x82, extra=bytes(8)), b"abc"),
        # A header extension of one word
        (rtp(1, b"abc", first=0x90, extra=b"\xbe\xde\x00\x01" + bytes(4)), b"abc"),
        # Two bytes of padding
        (rtp(1, b"abc\x00\x02", first=0xA0), b"abc"),
    ],
)
def test_what_follows_the_header_is_skipped(data: bytes, payload: bytes) -> None:
    """Contributing sources, an extension and the padding are not the payload."""
    packet = RtpPacket.parse(data)
    assert packet is not None
    assert packet.payload == payload


@pytest.mark.parametrize(
    "data",
    [
        b"\x80\x00",  # shorter than a header
        rtp(1, first=0x40),  # version 1
        rtp(1, b"", first=0x90),  # an extension that is not there
        rtp(1, b"\x09", first=0xA0),  # more padding than payload
    ],
)
def test_what_is_no_rtp(data: bytes) -> None:
    """A datagram that is not RTP version 2, or is cut short, reads as nothing."""
    assert RtpPacket.parse(data) is None


def listen() -> tuple[DoorSound, list[bytes]]:
    """Return the sound of a PCMU call of the door, and what it handed on."""
    heard: list[bytes] = []
    return DoorSound({DOOR}, 0, heard.append), heard


def test_the_door_is_heard_in_order() -> None:
    """The payloads go on as they come; a lost packet leaves a gap."""
    sound, heard = listen()
    for sequence in (1, 2, 4):  # 3 was lost: the player fills the gap
        sound.received(rtp(sequence, bytes([sequence]) * 320), (DOOR, 5004))
    assert heard == [bytes([1]) * 320, bytes([2]) * 320, bytes([4]) * 320]
    assert sound.stats.packets == 3
    assert not sound.stats.dropped


@pytest.mark.parametrize(
    ("data", "host", "dropped"),
    [
        (b"not rtp", DOOR, Dropped.NOT_RTP),
        (rtp(11), "192.0.2.99", Dropped.FOREIGN),
        (rtp(11, payload_type=101), DOOR, Dropped.OTHER_PAYLOAD),  # a key pressed (telephone-event)
        (rtp(10), DOOR, Dropped.LATE),  # again
        (rtp(9), DOOR, Dropped.LATE),  # behind
    ],
)
def test_what_is_not_the_door_sound(data: bytes, host: str, dropped: Dropped) -> None:
    """What is not the door's sound is dropped, and counted by why."""
    sound, heard = listen()
    sound.received(rtp(10), (DOOR, 5004))
    sound.received(data, (host, 5004))
    assert len(heard) == 1
    assert sound.stats.dropped == {dropped: 1}


def test_the_sequence_wraps() -> None:
    """After 65535 comes 0: it is ahead, not behind."""
    sound, heard = listen()
    for sequence in (0xFFFE, 0xFFFF, 0, 1):
        sound.received(rtp(sequence), (DOOR, 5004))
    assert len(heard) == 4


def test_a_new_stream_starts_over() -> None:
    """A door that restarts its stream (a new SSRC) is heard from its new sequence."""
    sound, heard = listen()
    sound.received(rtp(500), (DOOR, 5004))
    sound.received(rtp(3, ssrc=8), (DOOR, 5004))
    assert len(heard) == 2
