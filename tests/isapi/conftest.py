"""What the ISAPI tests share: a fake device served on localhost."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from aiohttp.test_utils import TestServer

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from tests.fakes.isapi import FakeIsapiDevice


@pytest.fixture
async def serve() -> AsyncIterator[Callable[[FakeIsapiDevice], Awaitable[TestServer]]]:
    """Start fake devices on localhost, and stop them after the test."""
    servers: list[TestServer] = []

    async def start(device: FakeIsapiDevice) -> TestServer:
        server = TestServer(device.app())
        await server.start_server()
        servers.append(server)
        return server

    yield start
    for server in servers:
        await server.close()
