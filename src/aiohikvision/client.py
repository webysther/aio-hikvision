"""The entry point of aiohikvision for ISAPI: connect to a device.

::

    import asyncio

    from aiohikvision import HikvisionClient


    async def main() -> None:
        async with HikvisionClient() as client:
            device = await client.connect("192.0.2.10", "admin", "password")
            print(device.identity.model, device.capabilities.domains)


    asyncio.run(main())
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from aiohikvision._extras import require

require("isapi")

import aiohttp  # noqa: E402

from aiohikvision.device import Device  # noqa: E402
from aiohikvision.isapi.wire.link import Endpoint, IsapiLink  # noqa: E402

if TYPE_CHECKING:
    import ssl
    from collections.abc import Iterable
    from types import TracebackType

    from aiohikvision.behaviours import BehaviourPatch
    from aiohikvision.behaviours.rules import Rule

HTTP_PORT = 80
HTTPS_PORT = 443


class HikvisionClient:
    """Connects to Hikvision devices over ISAPI, with an aiohttp session.

    Give it the session of your application (Home Assistant's, for one); without one, the
    client opens its own and closes it with :meth:`close` (or ``async with``). ``rules`` and
    ``overrides`` change the behaviours of the devices it connects to
    (:mod:`aiohikvision.behaviours.rules`).
    """

    def __init__(
        self,
        session: aiohttp.ClientSession | None = None,
        *,
        rules: Iterable[Rule] = (),
        overrides: BehaviourPatch | None = None,
    ) -> None:
        """Use a session, or open one when needed."""
        self._session = session
        self._own_session = session is None
        self.rules = tuple(rules)
        self.overrides = overrides

    @property
    def session(self) -> aiohttp.ClientSession:
        """Return the session of the client, opening one when it has none."""
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return self._session

    async def connect(
        self,
        host: str,
        username: str,
        password: str,
        *,
        port: int | None = None,
        https: bool = False,
        ssl_context: ssl.SSLContext | None = None,
        trusted: bool = False,
    ) -> Device:
        """Connect to a device and read who it is, what it can do and how it behaves.

        ``trusted``: the credentials are stored ones that already worked, not a new login (the
        link then tells a passing refusal from a wrong password). ``ssl_context`` replaces the
        session's TLS settings for an HTTPS device.
        """
        link = IsapiLink(
            self.session,
            Endpoint(host, port or (HTTPS_PORT if https else HTTP_PORT), "https" if https else "http"),
            username,
            password,
            trusted=trusted,
            ssl_context=ssl_context,
        )
        return await Device.from_link(link, rules=self.rules, overrides=self.overrides)

    async def close(self) -> None:
        """Close the session the client opened; a session it was given stays open."""
        if self._own_session and self._session is not None:
            await self._session.close()
            self._session = None

    async def __aenter__(self) -> Self:
        """Use the client in ``async with``."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the session the client opened."""
        await self.close()
