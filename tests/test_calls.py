"""CallServer against the fake door station, on loopback: ring, answer, talk, hang up."""

from __future__ import annotations

import asyncio
import struct
from typing import TYPE_CHECKING

import pytest

from aiohikvision import (
    CallError,
    CallServer,
    CallState,
    DoorCall,
    DoorRegistrar,
    DoorTransport,
    EndReason,
    Talkback,
)
from tests.fakes import FULL_OFFER, FakeDoorStation

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable


HOST = "127.0.0.1"
FRAME = bytes([0x55]) * 160


async def until(condition: Callable[[], object], timeout: float = 2.0) -> None:  # noqa: ASYNC109
    """Wait for a condition to hold."""
    async with asyncio.timeout(timeout):
        while not condition():  # noqa: ASYNC110 (polls state that no event announces)
            await asyncio.sleep(0.01)


class Server:
    """A call server on loopback, with what it reported."""

    def __init__(self) -> None:
        """Build it; start() opens it."""
        self.changes: list[tuple[str, CallState, EndReason | None]] = []
        self.registrar = DoorRegistrar()
        self.transport = DoorTransport(local_addr=(HOST, 0), allowed_hosts={HOST})
        self.calls = CallServer(
            self.transport, advertise=HOST, rtp_host=HOST, on_change=self._changed, registrar=self.registrar
        )

    def _changed(self, call: DoorCall) -> None:
        self.changes.append((call.id, call.state, call.end_reason))

    @property
    def address(self) -> tuple[str, int]:
        """Where the doors send."""
        udp = self.transport._udp_transport
        assert udp is not None
        return HOST, int(udp.get_extra_info("sockname")[1])

    def call(self) -> DoorCall:
        """Return the door's current call."""
        call = self.calls.current(HOST)
        assert call is not None
        return call


@pytest.fixture
async def server() -> AsyncIterator[Server]:
    """Give a started call server."""
    server = Server()
    await server.calls.start()
    yield server
    await server.calls.stop()


@pytest.fixture
async def door(server: Server) -> AsyncIterator[FakeDoorStation]:
    """Give a fake door station pointed at the server."""
    door = FakeDoorStation(HOST)
    await door.start(server.address)
    yield door
    await door.stop()


async def test_ring_answer_talk_hang_up(server: Server, door: FakeDoorStation) -> None:
    """The whole call: 180, an answer that only sends, 40 ms packets, and our BYE."""
    fake = door.call("REDACTED")
    await until(lambda: server.calls.current(HOST) is not None)
    call = server.call()
    assert call.state is CallState.RINGING
    assert call.callee == "REDACTED"
    assert call.caller == "100"
    await asyncio.wait_for(fake.ringing.wait(), 2)

    await server.calls.answer(call.id)
    await fake.answered()
    answer = fake.answer
    assert answer is not None
    assert answer.audio is not None
    assert "sendonly" in answer.audio.attributes
    assert answer.audio.attributes.get("ptime") == ["40"]
    assert [c.payload_type for c in answer.audio.codecs if c.encoding_name.upper() == "PCMU"] == [0]
    assert answer.video is None or answer.video.port == 0
    assert server.calls.calls[call.id].state is CallState.ANSWERED

    for _ in range(6):
        call.push(FRAME)
        await asyncio.sleep(0.02)
    await until(lambda: len(fake.rtp) >= 3)
    assert {len(p) for p in fake.rtp} == {12 + 320}
    assert {struct.unpack("!B", p[1:2])[0] & 0x7F for p in fake.rtp} == {0}

    ended = await server.calls.hangup(call.id)
    await asyncio.wait_for(fake.ended.wait(), 2)
    assert ended.state is CallState.ENDED
    assert call.end_reason is EndReason.HUNG_UP
    assert call.talkback is None
    assert [state for _, state, _ in server.changes] == [
        CallState.RINGING,
        CallState.ANSWERED,
        CallState.ENDED,
    ]


async def test_the_door_hangs_up(server: Server, door: FakeDoorStation) -> None:
    """The visitor, or the door's talk time, ends the call."""
    fake = door.call("REDACTED")
    await until(lambda: server.calls.current(HOST) is not None)
    call = server.call()
    await server.calls.answer(call.id)
    await fake.answered()
    fake.hangup()
    await until(lambda: call.state is CallState.ENDED)
    assert call.end_reason is EndReason.DOOR_HUNG_UP
    await until(lambda: call.talkback is None)


async def test_the_visitor_gives_up(server: Server, door: FakeDoorStation) -> None:
    """A CANCEL while it rings ends the call; the door gets its 487."""
    fake = door.call("REDACTED")
    await until(lambda: server.calls.current(HOST) is not None)
    call = server.call()
    await asyncio.wait_for(fake.ringing.wait(), 2)
    fake.cancel()
    await until(lambda: call.state is CallState.ENDED)
    assert call.end_reason is EndReason.CANCELLED
    assert fake.answer is None


async def test_reject(server: Server, door: FakeDoorStation) -> None:
    """We refuse: the door gets 486 and shows "busy"."""
    fake = door.call("REDACTED")
    await until(lambda: server.calls.current(HOST) is not None)
    call = await server.calls.reject(server.call().id)
    with pytest.raises(RuntimeError, match="486"):
        await fake.answered()
    assert call.end_reason is EndReason.REJECTED


async def test_one_call_per_door(server: Server, door: FakeDoorStation) -> None:
    """Pressing again during a call gets "busy"; the first call goes on."""
    door.call("REDACTED")
    await until(lambda: server.calls.current(HOST) is not None)
    first = server.call()
    second = door.call("REDACTED")
    with pytest.raises(RuntimeError, match="486"):
        await second.answered()
    assert server.call() is first
    assert first.state is CallState.RINGING


async def test_the_lock_message(server: Server, door: FakeDoorStation) -> None:
    """The out-of-dialog <locknumXML> after the ACK lands on the door's call."""
    fake = door.call("REDACTED")
    await until(lambda: server.calls.current(HOST) is not None)
    call = server.call()
    await server.calls.answer(call.id)
    await fake.answered()
    door.lock_message(2)
    await until(lambda: call.lock_count == 2)


async def test_commands_name_their_call(server: Server, door: FakeDoorStation) -> None:
    """A command for a call that ended, or is in another state, or never was, fails."""
    fake = door.call("REDACTED")
    await until(lambda: server.calls.current(HOST) is not None)
    call = server.call()
    with pytest.raises(CallError, match="answered"):
        await server.calls.hangup(call.id)
    with pytest.raises(CallError, match="ringing"):
        await server.calls.answer("not-a-call")
    await server.calls.answer(call.id)
    await fake.answered()
    with pytest.raises(CallError, match="ringing"):
        await server.calls.answer(call.id)
    await server.calls.hangup(call.id)
    with pytest.raises(CallError):
        await server.calls.hangup(call.id)
    call.push(FRAME)  # after the end: ignored


async def test_the_factory_offer(server: Server) -> None:
    """With every codec enabled, the answer still picks PCMU, never the door's Opus or G.722.1."""
    door = FakeDoorStation(HOST, offer=FULL_OFFER)
    await door.start(server.address)
    try:
        fake = door.call("REDACTED")
        await until(lambda: server.calls.current(HOST) is not None)
        await server.calls.answer(server.call().id)
        await fake.answered()
        assert fake.answer is not None
        assert fake.answer.audio is not None
        assert [
            c.payload_type for c in fake.answer.audio.codecs if c.encoding_name.upper() != "TELEPHONE-EVENT"
        ] == [0]
    finally:
        await door.stop()


async def test_no_g711(server: Server) -> None:
    """A door with only Opus enabled is refused with 488 and a hint."""
    only_opus = FULL_OFFER.replace("RTP/AVP 98 115 0 8 103 104 100 18 101", "RTP/AVP 115 101")
    door = FakeDoorStation(HOST, offer=only_opus)
    await door.start(server.address)
    try:
        fake = door.call("REDACTED")
        await until(lambda: server.calls.current(HOST) is not None)
        call = server.call()
        with pytest.raises(CallError, match=r"G\.711"):
            await server.calls.answer(call.id)
        with pytest.raises(RuntimeError, match="488"):
            await fake.answered()
        assert call.end_reason is EndReason.REJECTED
    finally:
        await door.stop()


async def test_registration_and_keepalive(server: Server, door: FakeDoorStation) -> None:
    """The fake door registers its line and keeps alive, as the real one."""
    door.register()
    door.keepalive()
    await until(lambda: server.registrar.registration(HOST) is not None)
    await until(lambda: server.transport.keepalives == 1)
    registration = server.registrar.registration(HOST)
    assert registration is not None
    assert registration.user == "100"


async def test_stop_ends_the_calls() -> None:
    """Stopping hangs up the answered call and refuses the ringing one."""
    server = Server()
    await server.calls.start()
    door = FakeDoorStation(HOST)
    await door.start(server.address)
    other = FakeDoorStation("127.0.0.2")
    server.transport.allowed_hosts.add("127.0.0.2")
    await other.start(server.address)
    try:
        answered = door.call("REDACTED")
        await until(lambda: server.calls.current(HOST) is not None)
        await server.calls.answer(server.call().id)
        await answered.answered()
        ringing = other.call("REDACTED")
        await until(lambda: server.calls.current("127.0.0.2") is not None)
        await server.calls.stop()
        await asyncio.wait_for(answered.ended.wait(), 2)
        with pytest.raises(RuntimeError, match="480"):
            await ringing.answered()
        assert {call.end_reason for call in server.calls.calls.values()} == {EndReason.STOPPED}
    finally:
        await other.stop()
        await door.stop()


async def test_a_lost_answer(server: Server, door: FakeDoorStation) -> None:
    """A 200 OK the door never acknowledges ends the call, and the microphone with it."""
    fake = door.call("REDACTED")
    await until(lambda: server.calls.current(HOST) is not None)
    call = await server.calls.answer(server.call().id)
    await fake.answered()
    assert call._incoming is not None
    server.calls._on_ack_timeout(call._incoming)
    assert call.end_reason is EndReason.LOST
    await until(lambda: call.talkback is None)


async def test_an_offer_without_audio(server: Server) -> None:
    """There is nothing to answer without an audio line."""
    video_only = FULL_OFFER.split("m=audio")[0] + "m=video" + FULL_OFFER.split("m=video")[1]
    door = FakeDoorStation(HOST, offer=video_only)
    await door.start(server.address)
    try:
        door.call("REDACTED")
        await until(lambda: server.calls.current(HOST) is not None)
        with pytest.raises(CallError, match="no audio"):
            await server.calls.answer(server.call().id)
    finally:
        await door.stop()


async def test_two_answers_at_once(server: Server, door: FakeDoorStation) -> None:
    """Two phones answer together: the first wins, the other is told the call is taken."""
    fake = door.call("REDACTED")
    await until(lambda: server.calls.current(HOST) is not None)
    call = server.call()
    results = await asyncio.gather(
        server.calls.answer(call.id), server.calls.answer(call.id), return_exceptions=True
    )
    assert results[0] is call
    assert isinstance(results[1], CallError)
    await fake.answered()
    assert call.state is CallState.ANSWERED
    assert [state for _, state, _ in server.changes].count(CallState.ANSWERED) == 1


async def test_the_visitor_leaves_during_the_answer(
    server: Server, door: FakeDoorStation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A CANCEL while the microphone is being readied: no 200 OK, and the microphone closes."""
    fake = door.call("REDACTED")
    await until(lambda: server.calls.current(HOST) is not None)
    call = server.call()
    await asyncio.wait_for(fake.ringing.wait(), 2)
    started = asyncio.Event()
    closed: list[bool] = []
    real_start = Talkback.start
    real_close = Talkback.close

    async def slow_start(self: Talkback) -> None:
        await real_start(self)
        started.set()
        await asyncio.sleep(0.2)

    async def close(self: Talkback) -> None:
        closed.append(True)
        await real_close(self)

    monkeypatch.setattr(Talkback, "start", slow_start)
    monkeypatch.setattr(Talkback, "close", close)
    answering = asyncio.create_task(server.calls.answer(call.id))
    await started.wait()
    fake.cancel()
    with pytest.raises(CallError, match="before it was answered"):
        await answering
    assert call.end_reason is EndReason.CANCELLED
    assert closed == [True]
    assert fake.answer is None


async def test_stop_leaves_the_ended_calls_alone(server: Server, door: FakeDoorStation) -> None:
    """A call refused before is not ended again, nor told again, when the server stops."""
    door.call("REDACTED")
    await until(lambda: server.calls.current(HOST) is not None)
    call = await server.calls.reject(server.call().id)
    told = len(server.changes)
    await server.calls.stop()
    assert call.end_reason is EndReason.REJECTED
    assert len(server.changes) == told
    await server.calls.start()  # the fixture stops it again


async def test_only_the_latest_ended_calls_are_kept(server: Server, monkeypatch: pytest.MonkeyPatch) -> None:
    """A door rings for years: the calls that ended long ago are forgotten."""
    monkeypatch.setattr("aiohikvision.sip.calls.KEPT_ENDED_CALLS", 2)
    for number in range(4):
        call = DoorCall(id=f"call-{number}", door=HOST, callee="REDACTED", caller="100")
        server.calls.calls[call.id] = call
        await server.calls._end(call, EndReason.CANCELLED)
    assert list(server.calls.calls) == ["call-2", "call-3"]
