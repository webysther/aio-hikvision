"""Regression tests: lockout expiry, bounded multipart parts, bounded channel state."""

from unittest.mock import MagicMock, patch

import aiohttp
import pytest

from aiohikvision.isapi.wire import (
    faults,
)
from aiohikvision.isapi.wire import (
    feed as feed_module,
)
from aiohikvision.isapi.wire import (
    link as link_module,
)
from aiohikvision.isapi.wire.feed import (
    MultipartSplitter,
)
from aiohikvision.isapi.wire.link import Endpoint, IsapiLink


def _link() -> IsapiLink:
    return IsapiLink(MagicMock(spec=aiohttp.ClientSession), Endpoint("h", 80, "http"), "u", "p")


def test_lockout_expires_and_clears_state() -> None:
    link = _link()
    link._signer = object()  # type: ignore[assignment]
    link._auth_checked = True
    now = [1000.0]
    with patch.object(link_module.time, "monotonic", lambda: now[0]):
        link._lock(faults.LockedOut("lock", 60))
        with pytest.raises(faults.LockedOut):
            link._check_open()
        now[0] += 61
        link._check_open()
    assert link.blocked is None
    assert link._signer is None
    assert link._auth_checked is False


def test_lockout_without_time_falls_back_to_half_an_hour() -> None:
    link = _link()
    now = [0.0]
    with patch.object(link_module.time, "monotonic", lambda: now[0]):
        link._lock(faults.LockedOut("lock"))
        now[0] = 1799
        with pytest.raises(faults.LockedOut):
            link._raise_if_blocked()
        now[0] = 1801
        link._raise_if_blocked()
    assert link.blocked is None


def test_bad_credentials_block_stays() -> None:
    link = _link()
    link._blocked = faults.BadCredentials("no")
    with (
        patch.object(link_module.time, "monotonic", lambda: 10**9),
        pytest.raises(faults.BadCredentials),
    ):
        link._raise_if_blocked()


def _part(name: bytes, body: bytes) -> bytes:
    return (
        b"--boundary\r\nContent-Type: application/xml\r\nContent-Length: "
        + str(len(body)).encode()
        + b"\r\n\r\n"
        + body
        + b"\r\n"
    )


def test_unterminated_header_block_is_bounded() -> None:
    splitter = MultipartSplitter("boundary")
    big = b"x" * (feed_module.MAX_PART_BYTES + 10)
    assert list(splitter.push(b"--boundary\r\nContent-Type: a\r\n" + big)) == []
    assert len(splitter._buffer) < 10


def test_missing_closing_boundary_is_bounded_and_resyncs() -> None:
    splitter = MultipartSplitter("boundary")
    head = b"--boundary\r\nContent-Type: text/plain\r\n\r\n"
    assert list(splitter.push(head + b"y" * (feed_module.MAX_PART_BYTES + 10))) == []
    parts = list(splitter.push(_part(b"", b"<ok/>")))
    assert len(splitter._buffer) < 100
    assert [p.body for p in parts] == [b"<ok/>"]


def test_no_boundary_no_length_is_bounded() -> None:
    splitter = MultipartSplitter(None)
    head = b"--x\r\nContent-Type: text/plain\r\n\r\n"
    assert list(splitter.push(head + b"y" * (feed_module.MAX_PART_BYTES + 10))) == []
    assert len(splitter._buffer) == 0
