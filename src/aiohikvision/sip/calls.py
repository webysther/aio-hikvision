"""Calls from a door station: it rings, someone answers and talks, someone hangs up.

The call and our microphone go over SIP, and no video (``m=video 0``): the door's picture is
read over RTSP (docs/ADR-0001-hybrid-call.md). Its sound is too, unless the server is given
``on_audio``: then the answer asks for the door's own RTP (``a=sendrecv``) and hands its G.711
payloads on, for browsers that cannot play the sound of the RTSP stream
(docs/ADR-0002-door-sound-over-sip.md). Otherwise the door is asked to send none
(``a=sendonly``).
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from aiosipua import IncomingCall, SipUAS
from aiosipua.header_codec import parse_address, parse_uri
from aiosipua.sdp_negotiate import negotiate_sdp

from aiohikvision.rtp.door_sound import DoorSound
from aiohikvision.rtp.talkback import Talkback
from aiohikvision.sip.messages import SERVER, response

if TYPE_CHECKING:
    from collections.abc import Callable

    from aiosipua import SdpMessage, SipRequest

    from aiohikvision.sip.registrar import DoorRegistrar
    from aiohikvision.sip.transport import DoorTransport

_LOGGER = logging.getLogger(__name__)
# Ended calls kept in CallServer.calls, newest last, for whoever looks back at them; the
# older ones are forgotten.
KEPT_ENDED_CALLS = 20

PTIME = 40
"""The packet time the door station sends, and must be sent (see aiohikvision.rtp.talkback)."""
G711 = (0, 8)
_LOCK_NUM = re.compile(rb"<lockNum>\s*(\d+)\s*</lockNum>")
_DIRECTIONS = ("sendrecv", "sendonly", "recvonly", "inactive")


class CallState(StrEnum):
    """Where a call is."""

    RINGING = "ringing"
    ANSWERED = "answered"
    ENDED = "ended"


class EndReason(StrEnum):
    """Why a call ended."""

    CANCELLED = "cancelled"
    """The door stopped ringing: the visitor gave up, or its ring time ran out."""
    DOOR_HUNG_UP = "door_hung_up"
    """The door hung up: the visitor did, or its talk time (``talkTime``) ran out."""
    HUNG_UP = "hung_up"
    """We hung up."""
    REJECTED = "rejected"
    """We refused the call; the door shows "busy"."""
    LOST = "lost"
    """The door never confirmed our answer (no ACK)."""
    STOPPED = "stopped"
    """The call server stopped."""


class CallError(Exception):
    """A command for a call that is not there, or not in the right state for it."""


@dataclass(eq=False)
class DoorCall:
    """A call from a door station."""

    id: str
    """The SIP Call-ID: every command names the call, so a late click cannot touch the next one."""
    door: str
    """The address of the door station."""
    callee: str
    """The number it called, e.g. the name its screen shows."""
    caller: str
    """The door's display name, or its own number."""
    state: CallState = CallState.RINGING
    end_reason: EndReason | None = None
    lock_count: int | None = None
    """How many locks the door says it can open (its ``<locknumXML>`` MESSAGE)."""
    started_at: float = field(default_factory=time.monotonic)
    answered_at: float | None = None
    ended_at: float | None = None
    talkback: Talkback | None = field(default=None, repr=False)
    """Our microphone to the door, while the call is answered."""
    sound: DoorSound | None = field(default=None, repr=False)
    """The door's sound, while the call is answered, when the server hands it on."""
    _incoming: IncomingCall | None = field(default=None, repr=False)

    def push(self, frame: bytes) -> None:
        """Send a 20 ms G.711 frame of the microphone to the door, if the call is answered."""
        if self.talkback is not None and self.state is CallState.ANSWERED:
            self.talkback.push(frame)


class CallServer:
    """The callee of door stations: it rings, and answers, rejects and hangs up on command.

    One call per door at a time: a second INVITE from a door that is in a call gets 486.
    """

    def __init__(
        self,
        transport: DoorTransport,
        *,
        advertise: str,
        rtp_host: str = "0.0.0.0",  # noqa: S104 (the door station is on the LAN)
        on_change: Callable[[DoorCall], None] | None = None,
        on_audio: Callable[[DoorCall, bytes], None] | None = None,
        registrar: DoorRegistrar | None = None,
        user_agent: str = SERVER,
    ) -> None:
        """Serve calls on a transport; ``advertise`` is our address as the doors reach it.

        ``on_audio`` takes the door's sound of each answered call: 40 ms G.711 payloads in
        the law of ``call.talkback.codec``, in order.
        """
        self.transport = transport
        self.advertise = advertise
        self.rtp_host = rtp_host
        self._on_change = on_change
        self._on_audio = on_audio
        self._uas = SipUAS(
            transport, user_agent=user_agent, advertised_addr=(advertise, transport.local_addr[1])
        )
        self._uas.on_invite = self._on_invite
        self._uas.on_cancel = self._on_cancel
        self._uas.on_bye = self._on_bye
        self._uas.on_ack_timeout = self._on_ack_timeout
        # aiosipua 0.7 answers 405 to MESSAGE and has no public way to add a method
        self._uas._handlers["MESSAGE"] = self._on_message  # noqa: SLF001
        if registrar is not None:
            registrar.attach(self._uas)
        self.calls: dict[str, DoorCall] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        # Calls whose answer is under way: a second answer (another phone) is refused.
        self._answering: set[str] = set()

    async def start(self) -> None:
        """Bind the transport and listen."""
        await self._uas.start()
        port = self.transport.local_addr[1]
        udp = self.transport._udp_transport  # noqa: SLF001
        if port == 0 and udp is not None:
            port = udp.get_extra_info("sockname")[1]
        self._uas.advertised_addr = (self.advertise, port)

    async def stop(self) -> None:
        """Hang up what is answered, refuse what rings, and stop listening."""
        for call in list(self.calls.values()):
            if call.state is CallState.ENDED:
                continue
            if call.state is CallState.ANSWERED and call._incoming is not None:  # noqa: SLF001
                call._incoming.hangup()  # noqa: SLF001
            elif call.state is CallState.RINGING and call._incoming is not None:  # noqa: SLF001
                call._incoming.reject(480, "Temporarily Unavailable")  # noqa: SLF001
            await self._end(call, EndReason.STOPPED)
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        await self._uas.stop()

    def current(self, door: str) -> DoorCall | None:
        """Return the call of a door station that has not ended, if any."""
        for call in self.calls.values():
            if call.door == door and call.state is not CallState.ENDED:
                return call
        return None

    async def answer(self, call_id: str) -> DoorCall:
        """Answer a ringing call: 200 OK, and the microphone ready to talk."""
        call = self._live(call_id, CallState.RINGING)
        incoming = call._incoming  # noqa: SLF001
        offer = incoming.sdp_offer if incoming is not None else None
        if incoming is None or offer is None or offer.rtp_address is None:
            msg = f"Call {call_id} has no audio to answer"
            raise CallError(msg)
        payload_type = _first_g711(offer)
        if payload_type is None:
            incoming.reject(488, "Not Acceptable Here")
            await self._end(call, EndReason.REJECTED)
            msg = "The door station offers no G.711: enable only G.711 in its SIP audio settings"
            raise CallError(msg)
        if call_id in self._answering:
            msg = f"Call {call_id} is already being answered"
            raise CallError(msg)
        self._answering.add(call_id)
        sound = self._sound_of(call, offer.rtp_address[0], payload_type)
        try:
            talkback = Talkback(
                offer.rtp_address,
                payload_type,
                local=(self.rtp_host, 0),
                received=sound.received if sound is not None else None,
            )
            await talkback.start()
        finally:
            self._answering.discard(call_id)
        if call.state is not CallState.RINGING:
            # The visitor walked away (CANCEL) while the microphone was being readied
            await talkback.close()
            msg = f"Call {call_id} ended before it was answered"
            raise CallError(msg)
        answer = _answer(offer, self.advertise, talkback.local_port, payload_type, receive=sound is not None)
        incoming.accept(answer)
        call.talkback = talkback
        call.sound = sound
        call.state = CallState.ANSWERED
        call.answered_at = time.monotonic()
        _LOGGER.info("Answered call %s of door station %s", call.id, call.door)
        self._notify(call)
        return call

    async def reject(self, call_id: str, code: int = 486) -> DoorCall:
        """Refuse a ringing call; with 486 the door shows "busy"."""
        call = self._live(call_id, CallState.RINGING)
        if call._incoming is not None:  # noqa: SLF001
            call._incoming.reject(code)  # noqa: SLF001
        await self._end(call, EndReason.REJECTED)
        return call

    async def hangup(self, call_id: str) -> DoorCall:
        """Hang up an answered call (BYE)."""
        call = self._live(call_id, CallState.ANSWERED)
        if call._incoming is not None:  # noqa: SLF001
            call._incoming.hangup()  # noqa: SLF001
        await self._end(call, EndReason.HUNG_UP)
        return call

    def _sound_of(self, call: DoorCall, media_host: str, payload_type: int) -> DoorSound | None:
        """Return the door's sound of a call, handed to ``on_audio``; None without it.

        It comes from the address of the door's SDP, which is the one it calls from.
        """
        on_audio = self._on_audio
        if on_audio is None:
            return None
        return DoorSound({call.door, media_host}, payload_type, lambda payload: on_audio(call, payload))

    def _live(self, call_id: str, state: CallState) -> DoorCall:
        call = self.calls.get(call_id)
        if call is None or call.state is not state:
            msg = f"Call {call_id} is not {state.value}"
            raise CallError(msg)
        return call

    def _on_invite(self, incoming: IncomingCall) -> None:
        door = incoming.source_addr[0]
        if self.current(door) is not None:
            _LOGGER.info("Door station %s called again during a call: busy", door)
            incoming.reject(486)
            return
        caller = parse_address(incoming.invite.get_header("from") or "")
        call = DoorCall(
            id=incoming.call_id,
            door=door,
            callee=parse_uri(incoming.invite.uri).user or "",
            caller=caller.display_name or caller.uri.user or door,
            _incoming=incoming,
        )
        self.calls[call.id] = call
        incoming.ringing()
        _LOGGER.info("Door station %s calls %s", door, call.callee)
        self._notify(call)

    def _on_cancel(self, request: SipRequest, _addr: tuple[str, int]) -> None:
        call = self.calls.get(request.call_id or "")
        if call is not None and call.state is CallState.RINGING:
            self._end_now(call, EndReason.CANCELLED)

    def _on_bye(self, incoming: IncomingCall, _request: SipRequest) -> None:
        call = self.calls.get(incoming.call_id)
        if call is not None and call.state is not CallState.ENDED:
            self._end_now(call, EndReason.DOOR_HUNG_UP)

    def _on_ack_timeout(self, incoming: IncomingCall) -> None:
        call = self.calls.get(incoming.call_id)
        if call is not None and call.state is CallState.ANSWERED:
            self._end_now(call, EndReason.LOST)

    def _on_message(self, request: SipRequest, addr: tuple[str, int]) -> None:
        """Take the door's ``<locknumXML>`` MESSAGE: in its own dialog or not, it is about its call."""
        self.transport.send_reply(response(request, 200, "OK"))
        found = _LOCK_NUM.search(request.body)
        call = self.calls.get(request.call_id or "") or self.current(addr[0])
        if found is not None and call is not None:
            call.lock_count = int(found.group(1))
            self._notify(call)

    def _end_now(self, call: DoorCall, reason: EndReason) -> None:
        """End a call from a callback of the SIP stack, which cannot wait."""
        call.state = CallState.ENDED
        call.end_reason = reason
        call.ended_at = time.monotonic()
        call.sound = None
        if call.talkback is not None:
            talkback, call.talkback = call.talkback, None
            task = asyncio.get_running_loop().create_task(talkback.close())
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        _LOGGER.info("Call %s of door station %s ended: %s", call.id, call.door, reason.value)
        self._notify(call)

    async def _end(self, call: DoorCall, reason: EndReason) -> None:
        call.sound = None
        if call.talkback is not None:
            talkback, call.talkback = call.talkback, None
            await talkback.close()
        call.state = CallState.ENDED
        call.end_reason = reason
        call.ended_at = time.monotonic()
        _LOGGER.info("Call %s of door station %s ended: %s", call.id, call.door, reason.value)
        self._notify(call)

    def _notify(self, call: DoorCall) -> None:
        if call.state is CallState.ENDED:
            self._forget_old_calls()
        if self._on_change is not None:
            self._on_change(call)

    def _forget_old_calls(self) -> None:
        """Keep the latest ended calls only (KEPT_ENDED_CALLS): a door rings for years."""
        ended = [key for key, call in self.calls.items() if call.state is CallState.ENDED]
        for key in ended[: max(0, len(ended) - KEPT_ENDED_CALLS)]:
            del self.calls[key]


def _first_g711(offer: SdpMessage) -> int | None:
    """Return the first G.711 payload type the door offers, in its order of preference."""
    audio = offer.audio
    if audio is None:
        return None
    for codec in audio.codecs:
        if codec.payload_type in G711:
            return int(codec.payload_type)
    return None


def _answer(offer: SdpMessage, address: str, port: int, payload_type: int, *, receive: bool) -> SdpMessage:
    """Our answer: G.711 in 40 ms packets, sent only by us unless we ``receive`` too, no video."""
    events = [
        c for c in (offer.audio.codecs if offer.audio else []) if c.encoding_name.lower() == "telephone-event"
    ]
    telephone_event = int(events[0].payload_type) if events else 101
    answer, _ = negotiate_sdp(
        offer, address, port, supported_codecs=[payload_type], dtmf_payload_type=telephone_event, ptime=PTIME
    )
    if answer.audio is not None:
        for direction in _DIRECTIONS:
            answer.audio.attributes.pop(direction, None)
        answer.audio.attributes["sendrecv" if receive else "sendonly"] = []
        answer.audio.attributes["ptime"] = [str(PTIME)]
    return answer
