"""Our microphone to a door station during a call: G.711 in 40 ms RTP packets, sent on time.

A Hikvision door station sends 40 ms packets, and the size of the packets it receives matters.
While it receives 20 ms ones, its own audio slows to about 0.7 of real time, and the delay keeps
growing. With 40 ms packets, or with none, it stays at 1.0. It is also half duplex: it plays what
it receives and leaves it out of its microphone. So the browser's 20 ms G.711 frames go two per
packet, in bursts while someone presses to talk, and nothing is sent in between.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
import struct
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

_LOGGER = logging.getLogger(__name__)

RATE = 8000
"""G.711 samples a second: one byte each."""
FRAME_BYTES = 160
"""A browser frame: 20 ms."""
PACKET_BYTES = 320
"""A packet to the door station: 40 ms, the size it sends itself."""
PACKET_SECONDS = PACKET_BYTES / RATE
CODECS = {0: "G.711ulaw", 8: "G.711alaw"}
SILENCE = {0: b"\xff", 8: b"\xd5"}
"""Digital silence of PCMU (payload type 0) and PCMA (8)."""


class Packetizer:
    """RTP packets of one stream: the header, the sequence, and the timestamp in samples."""

    def __init__(
        self,
        payload_type: int,
        *,
        ssrc: int | None = None,
        sequence: int | None = None,
        timestamp: int | None = None,
    ) -> None:
        """Start a stream; random SSRC, sequence and timestamp unless given (RFC 3550)."""
        self.payload_type = payload_type
        self.ssrc = secrets.randbits(32) if ssrc is None else ssrc
        self.sequence = secrets.randbits(16) if sequence is None else sequence
        self.timestamp = secrets.randbits(32) if timestamp is None else timestamp

    def packet(self, payload: bytes, *, marker: bool = False) -> bytes:
        """Build a packet of G.711 payload; the sequence and the timestamp then move on."""
        header = struct.pack(
            "!BBHII",
            0x80,
            (0x80 if marker else 0) | self.payload_type,
            self.sequence,
            self.timestamp,
            self.ssrc,
        )
        self.sequence = (self.sequence + 1) & 0xFFFF
        self.timestamp = (self.timestamp + len(payload)) & 0xFFFFFFFF
        return header + payload

    def skip(self, samples: int) -> None:
        """Let the timestamp run through a silence, as if the samples had been sent."""
        self.timestamp = (self.timestamp + samples) & 0xFFFFFFFF


@dataclass(slots=True)
class TalkbackStats:
    """What a talk-back sent and threw away."""

    packets: int = 0
    bursts: int = 0
    frames_dropped: int = 0
    """Frames thrown away to keep the delay short, or because they were not 20 ms."""


class _Endpoint(asyncio.DatagramProtocol):
    """The UDP socket of the stream: it sends our packets, and hands on what arrives."""

    def __init__(self, received: Callable[[bytes, tuple[str, int]], None] | None) -> None:
        self._received = received

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if self._received is not None:
            self._received(data, addr)


class Talkback:
    """Sends a microphone's 20 ms G.711 frames to a door station, 40 ms per RTP packet.

    Frames go in with push() as they arrive from the browser.

    - **Starting a burst:** a burst starts once three frames are waiting (60 ms), which leaves
      room for the jitter of the trip from the browser.
    - **During a burst:** one packet goes every 40 ms on an absolute clock. If frames pile up past
      ``max_delay`` seconds, the oldest ones are thrown away, so the delay stays short.
    - **Ending a burst:** the burst ends when the frames stop. A lone last frame is padded with
      silence.
    - **Silence:** nothing is sent, and the RTP timestamp keeps counting the elapsed time. The
      next burst starts with the marker bit (RFC 3551).
    """

    def __init__(
        self,
        remote: tuple[str, int],
        payload_type: int = 0,
        *,
        local: tuple[str, int] = ("0.0.0.0", 0),  # noqa: S104 (the door station is on the LAN)
        max_delay: float = 0.12,
        received: Callable[[bytes, tuple[str, int]], None] | None = None,
    ) -> None:
        """Talk to ``remote`` from ``local``, the address our SDP gave the door.

        ``received`` takes what arrives on that socket: the door's own RTP, when the
        answer asked for it (aiohikvision.rtp.door_sound).
        """
        if payload_type not in SILENCE:
            msg = f"G.711 payload type expected (0 or 8), not {payload_type}"
            raise ValueError(msg)
        self.remote = remote
        self.local = local
        self.stats = TalkbackStats()
        self._packetizer = Packetizer(payload_type)
        self._silence = SILENCE[payload_type] * FRAME_BYTES
        self._max_frames = max(2, round(max_delay * RATE / FRAME_BYTES))
        self._frames: deque[bytes] = deque()
        self._arrived = asyncio.Event()
        self._transport: asyncio.DatagramTransport | None = None
        self._task: asyncio.Task[None] | None = None
        self._last_packet_at: float | None = None
        self._last_frame_at = 0.0
        self._received = received

    @property
    def payload_type(self) -> int:
        """The G.711 payload type sent: 0 (µ-law, PCMU) or 8 (A-law, PCMA)."""
        return self._packetizer.payload_type

    @property
    def codec(self) -> str:
        """The G.711 variant, named as ISAPI names it (``G.711ulaw``, ``G.711alaw``)."""
        return CODECS[self._packetizer.payload_type]

    @property
    def local_port(self) -> int:
        """The port packets leave from, once started."""
        if self._transport is None:
            return self.local[1]
        return int(self._transport.get_extra_info("sockname")[1])

    async def start(self) -> None:
        """Open the socket and start the sender."""
        loop = asyncio.get_running_loop()
        self._transport, _ = await loop.create_datagram_endpoint(
            lambda: _Endpoint(self._received), local_addr=self.local
        )
        self._task = loop.create_task(self._run(), name="aiohikvision talkback")

    def push(self, frame: bytes) -> None:
        """Queue a 20 ms frame of the microphone, in the stream's G.711 law."""
        if len(frame) != FRAME_BYTES:
            self.stats.frames_dropped += 1
            return
        self._frames.append(frame)
        while len(self._frames) > self._max_frames:
            self._frames.popleft()
            self.stats.frames_dropped += 1
        self._last_frame_at = asyncio.get_running_loop().time()
        self._arrived.set()

    async def close(self) -> None:
        """Stop sending and close the socket."""
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        if self._transport is not None:
            self._transport.close()
            self._transport = None

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            await self._arrived.wait()
            self._arrived.clear()
            if not self._frames:
                continue
            # Let up to three frames gather, unless the speech is shorter than that
            await self._gather(3, PACKET_SECONDS)
            self._resume_timestamp(loop.time())
            await self._burst()

    async def _gather(self, frames: int, within: float) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + within
        while len(self._frames) < frames and loop.time() < deadline:
            self._arrived.clear()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._arrived.wait(), deadline - loop.time())

    def _resume_timestamp(self, now: float) -> None:
        """Count the silence since the last packet into the RTP timestamp."""
        if self._last_packet_at is not None:
            silent = now - self._last_packet_at - PACKET_SECONDS
            if silent > 0:
                self._packetizer.skip(round(silent * RATE))

    async def _burst(self) -> None:
        loop = asyncio.get_running_loop()
        self.stats.bursts += 1
        marker = True
        deadline = loop.time()
        while self._frames:
            if len(self._frames) == 1 and loop.time() - self._last_frame_at < PACKET_SECONDS:
                # The next frame is probably on its way: give it a little time
                await self._gather(2, PACKET_SECONDS / 2)
            first = self._frames.popleft()
            second = self._frames.popleft() if self._frames else self._silence
            self._send(self._packetizer.packet(first + second, marker=marker))
            marker = False
            deadline += PACKET_SECONDS
            await asyncio.sleep(max(0.0, deadline - loop.time()))
            if not self._frames:
                # A last chance for frames that are only late, before the burst ends
                await self._gather(1, PACKET_SECONDS / 2)
        self._arrived.clear()

    def _send(self, packet: bytes) -> None:
        if self._transport is None:
            return
        self._transport.sendto(packet, self.remote)
        self.stats.packets += 1
        self._last_packet_at = asyncio.get_running_loop().time()
