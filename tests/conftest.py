"""What the tests share: a door station's messages, as captured, with documentation addresses."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

DOOR = "192.0.2.10"
"""The door station (RFC 5737 documentation address; the captures had the LAN's)."""
SERVER = "192.0.2.20"
"""Home Assistant, the door's SIP server."""

# A DS-KD8003-IME1(B) on V3.7.3 registering its VoIP1 line ("Number" 100, display name
# "REDACTED"), as captured on 2026-11-24 with only the addresses changed
REGISTER = (
    "REGISTER sip:100@{server}:5060 SIP/2.0\r\n"
    "Via: SIP/2.0/UDP {door}:{port};rport;branch=z9hG4bK632402247\r\n"
    "From: REDACTED <sip:100@{server}>;tag=1507866664\r\n"
    "To: REDACTED <sip:100@{server}>\r\n"
    "Call-ID: 1554248840@{door}\r\n"
    "CSeq: 1 REGISTER\r\n"
    "Contact: <sip:100@{door}:{port};line=REDACTED>\r\n"
    "Max-Forwards: 70\r\n"
    "User-Agent: HKVS/2.0\r\n"
    "Expires: {expires}\r\n"
    "Content-Length: 0\r\n"
    "\r\n"
)


def register(door: str = DOOR, port: int = 5060, expires: int = 3600, server: str = SERVER) -> bytes:
    """Build a REGISTER of the door's line, as the door sends it."""
    return REGISTER.format(door=door, port=port, expires=expires, server=server).encode()


class Collector(asyncio.DatagramProtocol):
    """A UDP socket that keeps what it receives, with the time it arrived."""

    def __init__(self) -> None:
        """Start empty."""
        self.received: list[tuple[float, bytes]] = []
        self.arrived = asyncio.Event()

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:  # noqa: ARG002
        """Keep the datagram."""
        self.received.append((asyncio.get_running_loop().time(), data))
        self.arrived.set()


@pytest.fixture
async def collector() -> AsyncIterator[tuple[Collector, tuple[str, int]]]:
    """Yield a loopback UDP socket that collects datagrams, and its address."""
    loop = asyncio.get_running_loop()
    transport, protocol = await loop.create_datagram_endpoint(Collector, local_addr=("127.0.0.1", 0))
    address = transport.get_extra_info("sockname")
    yield protocol, (address[0], address[1])
    transport.close()
