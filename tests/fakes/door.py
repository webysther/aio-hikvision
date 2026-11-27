"""A door station that behaves as the measured DS-KD8003-IME1(B) (V3.7.3), for tests.

What it sends was captured on 2026-11-24 (docs/DEVICE_FINDINGS.md), with documentation addresses:
its REGISTER with the line's number as the user, the ``jaK`` keepalive, an INVITE with
``Subject: This is a call for conversation`` and its SDP, and the out-of-dialog ``<locknumXML>``
MESSAGE after the ACK. It records the RTP it receives.
"""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from aiosipua import OutgoingCall, SipMessage, SipRequest, SipUAC, SipUAS, UdpSipTransport
from aiosipua.sdp import parse_sdp

if TYPE_CHECKING:
    from aiosipua import SdpMessage

SUBJECT = "This is a call for conversation"
USER_AGENT = "HKVS/2.0"

G711_OFFER = """v=0
o=FX0000000 0 0 IN IP4 {host}
s=Talk session
c=IN IP4 {host}
t=0 0
m=audio {audio} RTP/AVP 0 8 101
a=rtpmap:0 PCMU/8000
a=rtpmap:8 PCMA/8000
a=rtpmap:101 telephone-event/8000
a=fmtp:101 0-16
a=sendrecv
m=video {video} RTP/AVP 96
a=rtpmap:96 H264/90000
a=fmtp:96 profile-level-id=42801F;packetization-mode=1
a=sendrecv
"""
"""Its offer with only G.711 enabled in its SIP audio settings (as it should be set)."""

FULL_OFFER = """v=0
o=FX0000000 0 0 IN IP4 {host}
s=Talk session
c=IN IP4 {host}
t=0 0
m=audio {audio} RTP/AVP 98 115 0 8 103 104 100 18 101
a=rtpmap:98 G7221/16000
a=rtpmap:115 OPUS/16000
a=rtpmap:0 PCMU/8000
a=rtpmap:8 PCMA/8000
a=rtpmap:103 G726-32/8000
a=rtpmap:104 MP4A-LATM/16000
a=rtpmap:100 MP4A-LATM/16000
a=rtpmap:18 G729/8000
a=rtpmap:101 telephone-event/8000
a=fmtp:101 0-16
a=sendrecv
m=video {video} RTP/AVP 96
a=rtpmap:96 H264/90000
a=fmtp:96 profile-level-id=42801F;packetization-mode=1
a=sendrecv
"""
"""Its factory offer, every codec enabled (Opus and G.722.1 are non-standard here)."""


class _Rtp(asyncio.DatagramProtocol):
    def __init__(self) -> None:
        self.packets: list[bytes] = []
        self.arrived = asyncio.Event()

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:  # noqa: ARG002
        self.packets.append(data)
        self.arrived.set()


@dataclass(eq=False)
class FakeCall:
    """A call the fake door placed."""

    door: FakeDoorStation
    call: OutgoingCall
    ringing: asyncio.Event = field(default_factory=asyncio.Event)
    ended: asyncio.Event = field(default_factory=asyncio.Event)

    @property
    def id(self) -> str:
        """The Call-ID."""
        return self.call.call_id

    @property
    def answer(self) -> SdpMessage | None:
        """The SDP the callee answered with."""
        return self.call.sdp_answer

    @property
    def rtp(self) -> list[bytes]:
        """The RTP packets the door received so far."""
        return self.door.rtp.packets

    async def answered(self, timeout: float = 2.0) -> None:  # noqa: ASYNC109 (aiosipua's API)
        """Wait for the 200 OK; RuntimeError if the call was refused."""
        await self.call.wait_answered(timeout=timeout)

    def send_audio(self, *packets: bytes) -> None:
        """Send RTP from the door's audio port to the address of the answer, as the door does."""
        answer = self.call.sdp_answer
        transport = self.door._rtp_transport
        assert answer is not None
        assert answer.rtp_address is not None
        assert transport is not None
        for packet in packets:
            transport.sendto(packet, answer.rtp_address)

    def cancel(self) -> None:
        """Give up while it rings (the visitor walked away, or the ring time ran out)."""
        self.call.cancel(self.door.uac)

    def hangup(self) -> None:
        """Hang up (the visitor did, or the talk time ran out)."""
        self.call.hangup(self.door.uac)
        self.ended.set()


class FakeDoorStation:
    """A door station on loopback that registers, keeps alive and calls like the real one."""

    def __init__(self, host: str = "127.0.0.1", *, number: str = "100", offer: str = G711_OFFER) -> None:
        """Make a door at ``host`` whose line's own number is ``number``."""
        self.host = host
        self.number = number
        self.offer = offer
        self.server: tuple[str, int] = ("127.0.0.1", 5060)
        self.transport = UdpSipTransport(local_addr=(host, 0))
        self.uac = SipUAC(self.transport)
        self.uas = SipUAS(self.transport, uac=self.uac, user_agent=USER_AGENT)
        self.uas.on_bye = self._on_bye
        self.rtp = _Rtp()
        self._rtp_transport: asyncio.DatagramTransport | None = None
        self.calls: dict[str, FakeCall] = {}

    @property
    def port(self) -> int:
        """The door's SIP port."""
        udp = self.transport._udp_transport
        return int(udp.get_extra_info("sockname")[1]) if udp is not None else 0

    @property
    def rtp_port(self) -> int:
        """The door's audio port."""
        if self._rtp_transport is None:
            return 0
        return int(self._rtp_transport.get_extra_info("sockname")[1])

    async def start(self, server: tuple[str, int]) -> None:
        """Open its SIP and audio ports, toward a server."""
        self.server = server
        await self.uas.start()
        self.uac.advertised_addr = (self.host, self.port)
        self.uas.advertised_addr = (self.host, self.port)
        loop = asyncio.get_running_loop()
        self._rtp_transport, _ = await loop.create_datagram_endpoint(
            lambda: self.rtp, local_addr=(self.host, 0)
        )

    async def stop(self) -> None:
        """Close its ports."""
        if self._rtp_transport is not None:
            self._rtp_transport.close()
        await self.uas.stop()

    def register(self, expires: int = 3600) -> None:
        """Send the REGISTER of its line, as it does when its VoIP line is enabled."""
        server = f"{self.server[0]}"
        branch = f"z9hG4bK{secrets.randbelow(10**9)}"
        self._send(
            f"REGISTER sip:{self.number}@{server}:{self.server[1]} SIP/2.0\r\n"
            f"Via: SIP/2.0/UDP {self.host}:{self.port};rport;branch={branch}\r\n"
            f"From: REDACTED <sip:{self.number}@{server}>;tag={secrets.randbelow(10**9)}\r\n"
            f"To: REDACTED <sip:{self.number}@{server}>\r\n"
            f"Call-ID: {secrets.randbelow(10**9)}@{self.host}\r\n"
            "CSeq: 1 REGISTER\r\n"
            f"Contact: <sip:{self.number}@{self.host}:{self.port};line=REDACTED>\r\n"
            "Max-Forwards: 70\r\n"
            f"User-Agent: {USER_AGENT}\r\n"
            f"Expires: {expires}\r\n"
            "Content-Length: 0\r\n\r\n"
        )

    def keepalive(self) -> None:
        """Send eXosip2's keepalive, as it does every 20 s."""
        udp = self.transport._udp_transport
        if udp is not None:
            udp.sendto(b"jaK\x00", self.server)

    def call(self, callee: str) -> FakeCall:
        """Call a number through the server, as its button does."""
        offer = parse_sdp(self.offer.format(host=self.host, audio=self.rtp_port, video=self.rtp_port + 2))
        outgoing = self.uac.send_invite(
            f"sip:{self.number}@{self.server[0]}",
            f"sip:{callee}@{self.server[0]}:{self.server[1]}",
            self.server,
            sdp_offer=offer,
            extra_headers={"Subject": SUBJECT},
            user_agent=USER_AGENT,
        )
        fake = FakeCall(self, outgoing)
        outgoing.on_ringing = lambda _call: fake.ringing.set()
        self.calls[fake.id] = fake
        return fake

    def lock_message(self, locks: int = 1) -> None:
        """Send the out-of-dialog MESSAGE that follows its ACK, to its own number."""
        body = f"<locknumXML>\n<lockNum>{locks}</lockNum>\n</locknumXML>\n"
        server = self.server[0]
        self._send(
            f"MESSAGE sip:{self.number}@{server}:{self.server[1]} SIP/2.0\r\n"
            f"Via: SIP/2.0/UDP {self.host}:{self.port};rport;branch=z9hG4bK{secrets.randbelow(10**9)}\r\n"
            f"From: <sip:{self.number}@{self.host}>;tag={secrets.randbelow(10**9)}\r\n"
            f"To: <sip:{self.number}@{server}:{self.server[1]}>\r\n"
            f"Call-ID: {secrets.randbelow(10**9)}\r\n"
            "CSeq: 20 MESSAGE\r\n"
            f"Contact: <sip:{self.number}@{self.host}:{self.port}>\r\n"
            "Content-Type: text/plain\r\n"
            "Max-Forwards: 70\r\n"
            f"User-Agent: {USER_AGENT}\r\n"
            f"Content-Length: {len(body)}\r\n\r\n{body}"
        )

    def _send(self, text: str) -> None:
        message = SipMessage.parse(text.encode())
        assert isinstance(message, SipRequest)
        self.transport.send(message, self.server)

    def _on_bye(self, call: Any, _request: SipRequest) -> None:  # noqa: ANN401 (aiosipua passes either call type)
        fake = self.calls.get(call.call_id)
        if fake is not None:
            fake.ended.set()
