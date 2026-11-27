"""Talkback: 20 ms frames in, 40 ms packets out, on time, in bursts."""

from __future__ import annotations

import asyncio
import struct
from itertools import pairwise
from typing import TYPE_CHECKING

import pytest

from aiohikvision import Packetizer, Talkback

if TYPE_CHECKING:
    from .conftest import Collector

FRAME = 160


def frame(value: int) -> bytes:
    """Build a 20 ms frame whose bytes all hold one value, to follow it into the packets."""
    return bytes([value]) * FRAME


def header(packet: bytes) -> tuple[int, bool, int, int, int, int]:
    """Version, marker, payload type, sequence, timestamp and SSRC of an RTP packet."""
    first, second, sequence, timestamp, ssrc = struct.unpack("!BBHII", packet[:12])
    return first >> 6, bool(second & 0x80), second & 0x7F, sequence, timestamp, ssrc


def test_packetizer() -> None:
    """RTP version 2, marker as asked, sequence and timestamp moving with the payload."""
    packetizer = Packetizer(0, ssrc=0x01020304, sequence=0xFFFF, timestamp=0xFFFFFF00)
    first = packetizer.packet(b"\xff" * 320, marker=True)
    second = packetizer.packet(b"\xff" * 320)
    assert header(first) == (2, True, 0, 0xFFFF, 0xFFFFFF00, 0x01020304)
    assert header(second) == (2, False, 0, 0, 0x40, 0x01020304)
    packetizer.skip(8000)
    assert header(packetizer.packet(b"\xd5" * 320))[4] == 0x40 + 320 + 8000
    assert len(first) == 12 + 320


def test_random_start() -> None:
    """Without a start, SSRC, sequence and timestamp are random (RFC 3550)."""
    starts = {(p.ssrc, p.sequence, p.timestamp) for p in (Packetizer(0) for _ in range(5))}
    assert len(starts) == 5


def test_only_g711() -> None:
    """Talk-back is G.711: the door station is set to offer nothing else."""
    with pytest.raises(ValueError, match=r"G\.711"):
        Talkback(("127.0.0.1", 9), payload_type=96)


async def test_a_burst_at_the_pace_of_speech(collector: tuple[Collector, tuple[str, int]]) -> None:
    """Frames every 20 ms go out two per packet, every 40 ms, in order, marker on the first."""
    protocol, address = collector
    talkback = Talkback(address, local=("127.0.0.1", 0))
    await talkback.start()
    try:
        for value in range(20):
            talkback.push(frame(value))
            await asyncio.sleep(0.02)
        await asyncio.sleep(0.3)
    finally:
        await talkback.close()
    packets = [data for _, data in protocol.received]
    assert len(packets) == 10
    assert [header(p)[1] for p in packets] == [True] + [False] * 9
    assert [p[12:] for p in packets] == [frame(2 * i) + frame(2 * i + 1) for i in range(10)]
    sequences = [header(p)[3] for p in packets]
    assert all((b - a) & 0xFFFF == 1 for a, b in pairwise(sequences))
    timestamps = [header(p)[4] for p in packets]
    assert all((b - a) & 0xFFFFFFFF == 320 for a, b in pairwise(timestamps))
    times = [t for t, _ in protocol.received]
    gaps = [b - a for a, b in pairwise(times)]
    assert 0.03 < sum(gaps) / len(gaps) < 0.05
    assert talkback.stats.packets == 10
    assert talkback.stats.bursts == 1
    assert talkback.stats.frames_dropped == 0


async def test_silence_between_bursts(collector: tuple[Collector, tuple[str, int]]) -> None:
    """Nothing is sent between bursts; the next one has the marker and a timestamp that counted the gap."""
    protocol, address = collector
    talkback = Talkback(address, local=("127.0.0.1", 0))
    await talkback.start()
    try:
        for _ in range(2):
            for value in range(6):
                talkback.push(frame(value))
                await asyncio.sleep(0.02)
            await asyncio.sleep(0.4)
    finally:
        await talkback.close()
    packets = [data for _, data in protocol.received]
    assert len(packets) == 6
    assert [header(p)[1] for p in packets] == [True, False, False, True, False, False]
    jump = (header(packets[3])[4] - header(packets[2])[4]) & 0xFFFFFFFF
    # About 0.4 s of silence plus the burst's own length: far more than one packet
    assert 3200 < jump < 8000
    assert talkback.stats.bursts == 2


async def test_a_lone_last_frame_is_padded(collector: tuple[Collector, tuple[str, int]]) -> None:
    """Three frames make two packets; the second ends in silence."""
    protocol, address = collector
    talkback = Talkback(address, local=("127.0.0.1", 0))
    await talkback.start()
    try:
        for value in (1, 2, 3):
            talkback.push(frame(value))
        await asyncio.sleep(0.3)
    finally:
        await talkback.close()
    payloads = [data[12:] for _, data in protocol.received]
    assert payloads == [frame(1) + frame(2), frame(3) + b"\xff" * FRAME]


async def test_a_law_silence(collector: tuple[Collector, tuple[str, int]]) -> None:
    """PCMA pads with its own silence."""
    protocol, address = collector
    talkback = Talkback(address, payload_type=8, local=("127.0.0.1", 0))
    await talkback.start()
    try:
        talkback.push(frame(7))
        await asyncio.sleep(0.2)
    finally:
        await talkback.close()
    assert [data[12:] for _, data in protocol.received] == [frame(7) + b"\xd5" * FRAME]
    assert header(protocol.received[0][1])[2] == 8


async def test_the_delay_stays_short(collector: tuple[Collector, tuple[str, int]]) -> None:
    """A pile of late frames loses its oldest, so the door hears the newest."""
    protocol, address = collector
    talkback = Talkback(address, local=("127.0.0.1", 0), max_delay=0.12)
    await talkback.start()
    try:
        for value in range(10):
            talkback.push(frame(value))
        await asyncio.sleep(0.3)
    finally:
        await talkback.close()
    payloads = [data[12:] for _, data in protocol.received]
    assert payloads == [frame(4) + frame(5), frame(6) + frame(7), frame(8) + frame(9)]
    assert talkback.stats.frames_dropped == 4


async def test_wrong_frames_are_dropped() -> None:
    """Only 20 ms frames go in."""
    talkback = Talkback(("127.0.0.1", 9), local=("127.0.0.1", 0))
    await talkback.start()
    try:
        talkback.push(b"\xff" * 80)
        assert talkback.stats.frames_dropped == 1
        assert talkback.local_port > 0
    finally:
        await talkback.close()
        await talkback.close()
    assert talkback.local_port == 0


async def test_what_arrives_on_the_socket() -> None:
    """What arrives goes to ``received``; without it, it is left alone."""
    arrived: list[tuple[bytes, tuple[str, int]]] = []
    listening = Talkback(
        ("127.0.0.1", 9), local=("127.0.0.1", 0), received=lambda data, addr: arrived.append((data, addr))
    )
    deaf = Talkback(("127.0.0.1", 9), local=("127.0.0.1", 0))
    await listening.start()
    await deaf.start()
    loop = asyncio.get_running_loop()
    sender, _ = await loop.create_datagram_endpoint(asyncio.DatagramProtocol, local_addr=("127.0.0.1", 0))
    try:
        sender.sendto(b"door", ("127.0.0.1", deaf.local_port))
        sender.sendto(b"door", ("127.0.0.1", listening.local_port))
        async with asyncio.timeout(2):
            while not arrived:  # noqa: ASYNC110 (the datagram has no event of its own)
                await asyncio.sleep(0.01)
        assert arrived[0][0] == b"door"
    finally:
        sender.close()
        await listening.close()
        await deaf.close()


def test_the_codec_is_named_as_isapi_names_it() -> None:
    """The browser encodes in the variant the talk names, during a call or not."""
    assert Talkback(("127.0.0.1", 9)).codec == "G.711ulaw"
    alaw = Talkback(("127.0.0.1", 9), 8)
    assert alaw.codec == "G.711alaw"
    assert alaw.payload_type == 8
