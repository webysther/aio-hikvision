"""The SIP transport of a door station: UDP, with the datagrams that are not SIP left out."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from aiosipua import UdpSipTransport

_LOGGER = logging.getLogger(__name__)

EXOSIP_KEEPALIVE = b"jaK"
"""What a Hikvision door station (eXosip2) sends to its SIP server every 20 s, NUL-terminated."""


def is_keepalive(data: bytes) -> bool:
    """Whether a datagram only keeps a NAT binding open: eXosip2's ``jaK``, or blank lines (RFC 5626)."""
    return data.rstrip(b"\0") == EXOSIP_KEEPALIVE or not data.strip(b"\r\n")


@dataclass
class DoorTransport(UdpSipTransport):
    """A UDP SIP transport that only hears the door stations it knows.

    - Keepalives are counted and dropped. aiosipua would otherwise log a parse error, with a
      traceback, three times a minute.
    - Datagrams from other hosts are dropped without an answer. A SIP server on a LAN must not
      ring, or answer at all, for anyone who can send it UDP.
    """

    allowed_hosts: set[str] = field(default_factory=set)
    """The addresses of the door stations; change it as they come and go."""

    on_keepalive: Callable[[tuple[str, int]], None] | None = None
    """Called with the address of a door station on each keepalive: it is alive."""

    keepalives: int = field(default=0, init=False)
    dropped: int = field(default=0, init=False)

    def _dispatch(self, data: bytes, addr: tuple[str, int]) -> None:
        # aiosipua 0.7 has no hook before parsing: this private method is the one every
        # datagram goes through (hence the pinned version)
        if addr[0] not in self.allowed_hosts:
            self.dropped += 1
            _LOGGER.debug("Dropped %d bytes from %s, not a door station", len(data), addr[0])
            return
        if is_keepalive(data):
            self.keepalives += 1
            if self.on_keepalive is not None:
                self.on_keepalive(addr)
            return
        super()._dispatch(data, addr)
