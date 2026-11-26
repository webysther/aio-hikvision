"""A SIP registrar for door stations: Home Assistant as the SIP server of a door's VoIP line."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from aiosipua.header_codec import parse_address

from aiohikvision.sip.messages import response

if TYPE_CHECKING:
    from collections.abc import Callable

    from aiosipua import SipRequest, SipResponse, SipTransport, SipUAS

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Registration:
    """A door station's line, registered with us."""

    user: str
    """The line's own SIP number, which the door's web page calls "Number"."""
    host: str
    port: int
    contact: str
    """The door's Contact URI, where calls to the line go."""
    expires_at: float
    """When the registration ends, on the registrar's clock."""
    user_agent: str | None


class DoorRegistrar:
    """Accepts the REGISTER of door stations and remembers them.

    A Hikvision door asks for an hour (Expires 3600) and sends no credentials, because it is
    never challenged. Only the transport's known hosts get here (see DoorTransport), so there is
    no challenge.

    The granted time can be shorter than the door asks (``max_expires``), so that a door which
    lost its registration, for example while Home Assistant restarted, registers again sooner.
    """

    def __init__(
        self,
        *,
        max_expires: int = 3600,
        on_change: Callable[[Registration, bool], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Grant at most ``max_expires`` seconds, and call ``on_change(registration, registered)``."""
        self.max_expires = max_expires
        self._on_change = on_change
        self._clock = clock
        self._registrations: dict[tuple[str, str], Registration] = {}

    def attach(self, uas: SipUAS) -> None:
        """Have the UAS hand REGISTER requests to the registrar."""
        transport = uas.transport

        def handle(request: SipRequest, addr: tuple[str, int]) -> None:
            self.handle(transport, request, addr)

        # aiosipua 0.7 answers 405 to REGISTER and has no public way to add a method: its
        # table of methods is private (hence the pinned version)
        uas._handlers["REGISTER"] = handle  # noqa: SLF001

    def handle(self, transport: SipTransport, request: SipRequest, addr: tuple[str, int]) -> None:
        """Answer a REGISTER and update the registrations."""
        transport.send_reply(self.answer(request, addr))

    def answer(self, request: SipRequest, addr: tuple[str, int]) -> SipResponse:
        """Build the response to a REGISTER, recording or removing the registration."""
        user = parse_address(request.get_header("to") or "").uri.user or ""
        contact = (request.get_header("contact") or "").strip()
        asked = _asked_expires(request, contact)
        key = (addr[0], user)
        if not user or not contact:
            return _response(request, 400, "Bad Request")
        if contact == "*" or asked == 0:
            removed = self._registrations.pop(key, None)
            if removed is not None:
                _LOGGER.info("Door station %s unregistered line %s", addr[0], user)
                self._notify(removed, registered=False)
            return _response(request, 200, "OK", expires=0)
        granted = min(asked if asked is not None else self.max_expires, self.max_expires)
        uri = _contact_uri(contact)
        registration = Registration(
            user=user,
            host=addr[0],
            port=addr[1],
            contact=uri,
            expires_at=self._clock() + granted,
            user_agent=request.get_header("user-agent"),
        )
        previous = self._registrations.get(key)
        self._registrations[key] = registration
        if previous is None or previous.contact != registration.contact:
            _LOGGER.info("Door station %s registered line %s for %d s", addr[0], user, granted)
            self._notify(registration, registered=True)
        return _response(request, 200, "OK", expires=granted, contact=f"<{uri}>")

    def registration(self, host: str, user: str | None = None) -> Registration | None:
        """Return the live registration of a door station (of one of its lines, given the user)."""
        now = self._clock()
        for (registered_host, registered_user), registration in self._registrations.items():
            if registered_host != host or (user is not None and registered_user != user):
                continue
            if registration.expires_at > now:
                return registration
        return None

    def prune(self) -> list[Registration]:
        """Forget the registrations that ran out, and return them."""
        now = self._clock()
        expired = [r for r in self._registrations.values() if r.expires_at <= now]
        for registration in expired:
            del self._registrations[(registration.host, registration.user)]
            _LOGGER.info("Door station %s let line %s expire", registration.host, registration.user)
            self._notify(registration, registered=False)
        return expired

    def _notify(self, registration: Registration, *, registered: bool) -> None:
        if self._on_change is not None:
            self._on_change(registration, registered)


def _contact_uri(contact: str) -> str:
    """Return the URI of a Contact header, without its parameters or angle brackets."""
    if "<" in contact:
        return contact.split("<", 1)[1].split(">", 1)[0].strip()
    return contact.split(";", 1)[0].strip()


def _asked_expires(request: SipRequest, contact: str) -> int | None:
    """Return the time the door asks for: the Contact's expires parameter, else the Expires header."""
    if contact and contact != "*":
        value = parse_address(contact).params.get("expires")
        if value is not None and value.strip().isdigit():
            return int(value.strip())
    header = request.get_header("expires")
    if header is not None and header.strip().isdigit():
        return int(header.strip())
    return None


def _response(
    request: SipRequest, status: int, reason: str, *, expires: int | None = None, contact: str | None = None
) -> SipResponse:
    """Build a response to a REGISTER, with the time granted and the Contact it applies to."""
    reply = response(request, status, reason)
    if contact is not None and expires:
        reply.headers.set_single("Contact", f"{contact};expires={expires}")
    if expires is not None:
        reply.headers.set_single("Expires", str(expires))
    return reply
