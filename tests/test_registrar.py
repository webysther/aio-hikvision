"""DoorRegistrar: the door's VoIP line registers with us, refreshes, and expires."""

from __future__ import annotations

import asyncio

import pytest
from aiosipua import SipMessage, SipRequest, SipResponse, SipUAS

from aiohikvision import DoorRegistrar, DoorTransport, Registration

from .conftest import DOOR, Collector, register


class Clock:
    """A clock the test moves by hand."""

    def __init__(self) -> None:
        """Start at 1000 s."""
        self.now = 1000.0

    def __call__(self) -> float:
        """Return the time now."""
        return self.now


def request(data: bytes) -> SipRequest:
    """Parse a request, as the transport would."""
    message = SipMessage.parse(data)
    assert isinstance(message, SipRequest)
    return message


@pytest.fixture
def clock() -> Clock:
    """Give a hand-moved clock."""
    return Clock()


@pytest.fixture
def changes() -> list[tuple[Registration, bool]]:
    """Collect the registrations that came and went."""
    return []


@pytest.fixture
def registrar(clock: Clock, changes: list[tuple[Registration, bool]]) -> DoorRegistrar:
    """Build a registrar granting at most 10 minutes."""
    return DoorRegistrar(
        max_expires=600, clock=clock, on_change=lambda r, registered: changes.append((r, registered))
    )


def test_the_door_registers(registrar: DoorRegistrar, changes: list[tuple[Registration, bool]]) -> None:
    """The door gets a 200 with our tag and the time granted, and is remembered."""
    response = registrar.answer(request(register()), (DOOR, 5060))
    assert isinstance(response, SipResponse)
    assert response.status_code == 200
    assert response.get_header("to") is not None
    assert ";tag=" in (response.get_header("to") or "")
    assert response.get_header("contact") == f"<sip:100@{DOOR}:5060;line=REDACTED>;expires=600"
    assert response.get_header("expires") == "600"
    assert response.get_header("call-id") == f"1554248840@{DOOR}"
    assert response.get_header("cseq") == "1 REGISTER"
    assert (response.get_header("via") or "").startswith(f"SIP/2.0/UDP {DOOR}:5060")
    registration = registrar.registration(DOOR)
    assert registration is not None
    assert registration.user == "100"
    assert registration.contact == f"sip:100@{DOOR}:5060;line=REDACTED"
    assert registration.user_agent == "HKVS/2.0"
    assert changes == [(registration, True)]


def test_a_shorter_time_is_kept(registrar: DoorRegistrar) -> None:
    """When the door asks for less than the most we grant, it gets what it asked."""
    response = registrar.answer(request(register(expires=120)), (DOOR, 5060))
    assert response.get_header("expires") == "120"


def test_refresh_is_quiet_and_extends(
    registrar: DoorRegistrar, clock: Clock, changes: list[tuple[Registration, bool]]
) -> None:
    """Registering again moves the end, without telling anyone."""
    registrar.answer(request(register()), (DOOR, 5060))
    clock.now += 500
    registrar.answer(request(register()), (DOOR, 5060))
    clock.now += 500
    assert registrar.registration(DOOR) is not None
    assert len(changes) == 1


def test_expiry(registrar: DoorRegistrar, clock: Clock, changes: list[tuple[Registration, bool]]) -> None:
    """A door that stops registering is gone once its time runs out."""
    registrar.answer(request(register()), (DOOR, 5060))
    clock.now += 599
    assert registrar.prune() == []
    clock.now += 1
    assert registrar.registration(DOOR) is None
    expired = registrar.prune()
    assert [r.user for r in expired] == ["100"]
    assert changes[-1] == (expired[0], False)
    assert registrar.prune() == []


def test_unregister(registrar: DoorRegistrar, changes: list[tuple[Registration, bool]]) -> None:
    """Expires 0 removes the line."""
    registrar.answer(request(register()), (DOOR, 5060))
    response = registrar.answer(request(register(expires=0)), (DOOR, 5060))
    assert response.status_code == 200
    assert response.get_header("expires") == "0"
    assert response.get_header("contact") is None
    assert registrar.registration(DOOR) is None
    assert [registered for _, registered in changes] == [True, False]


def test_unregister_unknown_line_is_quiet(
    registrar: DoorRegistrar, changes: list[tuple[Registration, bool]]
) -> None:
    """Removing a line we never had still gets a 200."""
    response = registrar.answer(request(register(expires=0)), (DOOR, 5060))
    assert response.status_code == 200
    assert changes == []


def test_contact_expires_wins(registrar: DoorRegistrar) -> None:
    """The Contact's expires parameter comes before the Expires header (RFC 3261 203.0.113.1)."""
    data = register().replace(b";line=REDACTED>", b";line=REDACTED>;expires=60")
    response = registrar.answer(request(data), (DOOR, 5060))
    assert response.get_header("expires") == "60"


def test_without_expires_the_most_is_granted(registrar: DoorRegistrar) -> None:
    """A REGISTER that asks for no time gets the most we grant."""
    data = register().replace(b"Expires: 3600\r\n", b"")
    response = registrar.answer(request(data), (DOOR, 5060))
    assert response.get_header("expires") == "600"


def test_a_register_without_user_is_refused(registrar: DoorRegistrar) -> None:
    """There is no line to register without a user in To."""
    data = register().replace(b"To: REDACTED <sip:100@", b"To: REDACTED <sip:")
    response = registrar.answer(request(data), (DOOR, 5060))
    assert response.status_code == 400
    assert registrar.registration(DOOR) is None


def test_lines_of_a_door(registrar: DoorRegistrar) -> None:
    """A door's two lines are kept apart."""
    registrar.answer(request(register()), (DOOR, 5060))
    second = register().replace(b"sip:100@", b"sip:101@")
    registrar.answer(request(second), (DOOR, 5060))
    first = registrar.registration(DOOR, "100")
    other = registrar.registration(DOOR, "101")
    assert first is not None
    assert other is not None
    assert first.user == "100"
    assert other.user == "101"
    assert registrar.registration(DOOR, "102") is None
    assert registrar.registration("192.0.2.99") is None


async def test_over_udp() -> None:
    """A real UAS on loopback answers the door's REGISTER and ignores its keepalive."""
    loop = asyncio.get_running_loop()
    transport = DoorTransport(local_addr=("127.0.0.1", 0), allowed_hosts={"127.0.0.1"})
    uas = SipUAS(transport)
    registrar = DoorRegistrar()
    registrar.attach(uas)
    await uas.start()
    door, protocol = await loop.create_datagram_endpoint(Collector, local_addr=("127.0.0.1", 0))
    try:
        assert transport._udp_transport is not None
        server = transport._udp_transport.get_extra_info("sockname")[:2]
        port = door.get_extra_info("sockname")[1]
        door.sendto(b"jaK\x00", server)
        door.sendto(register(door="127.0.0.1", port=port), server)
        await asyncio.wait_for(protocol.arrived.wait(), 2)
        response = SipMessage.parse(protocol.received[0][1])
        assert isinstance(response, SipResponse)
        assert response.status_code == 200
        assert transport.keepalives == 1
        assert registrar.registration("127.0.0.1") is not None
    finally:
        door.close()
        await uas.stop()
