"""DoorTransport: only the door stations get through, and their keepalives stay quiet."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest

from aiohikvision import DoorTransport, is_keepalive

if TYPE_CHECKING:
    from aiosipua import SipMessage

from .conftest import DOOR, register


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (b"jaK\x00", True),
        (b"jaK", True),
        (b"\r\n\r\n", True),
        (b"\r\n", True),
        (b"", True),
        (b"jaKe\x00", False),
        (b"OPTIONS sip:100@192.0.2.20 SIP/2.0\r\n\r\n", False),
    ],
)
def test_keepalives(*, data: bytes, expected: bool) -> None:
    """eXosip2's keepalive and RFC 5626 blank lines are keepalives; SIP is not."""
    assert is_keepalive(data) is expected


def test_a_door_station_reaches_the_sip_stack() -> None:
    """A REGISTER from a known door is parsed and handed on."""
    messages: list[tuple[SipMessage, tuple[str, int]]] = []
    transport = DoorTransport(allowed_hosts={DOOR}, on_message=lambda m, a: messages.append((m, a)))
    transport._dispatch(register(), (DOOR, 5060))
    assert len(messages) == 1
    assert messages[0][1] == (DOOR, 5060)
    assert transport.dropped == 0


def test_other_hosts_are_dropped_without_an_answer() -> None:
    """Nobody else on the LAN can ring or register."""
    messages: list[object] = []
    transport = DoorTransport(allowed_hosts={DOOR}, on_message=lambda m, a: messages.append((m, a)))
    transport._dispatch(register(door="192.0.2.99"), ("192.0.2.99", 5060))
    assert messages == []
    assert transport.dropped == 1


def test_keepalives_are_counted_not_parsed(caplog: pytest.LogCaptureFixture) -> None:
    """A keepalive tells the door is alive, and logs nothing."""
    alive: list[tuple[str, int]] = []
    messages: list[object] = []
    transport = DoorTransport(
        allowed_hosts={DOOR}, on_message=lambda m, a: messages.append((m, a)), on_keepalive=alive.append
    )
    with caplog.at_level(logging.DEBUG):
        transport._dispatch(b"jaK\x00", (DOOR, 5060))
    assert alive == [(DOOR, 5060)]
    assert transport.keepalives == 1
    assert messages == []
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_hosts_can_change() -> None:
    """A door added later is heard from then on."""
    messages: list[object] = []
    transport = DoorTransport(on_message=lambda m, a: messages.append((m, a)))
    transport._dispatch(register(), (DOOR, 5060))
    transport.allowed_hosts.add(DOOR)
    transport._dispatch(register(), (DOOR, 5060))
    assert len(messages) == 1
    assert transport.dropped == 1
