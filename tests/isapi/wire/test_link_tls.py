"""The TLS argument of the requests: a given context for HTTPS, else the session's own."""

from __future__ import annotations

import ssl
from typing import Any, Self
from unittest.mock import MagicMock

import aiohttp
from multidict import CIMultiDict

from aiohikvision.isapi.wire.link import Endpoint, IsapiLink


class _Response:
    status = 200
    headers = CIMultiDict({"Content-Type": "application/xml"})

    async def read(self) -> bytes:
        return b"<ok/>"

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


async def _sent_kwargs(scheme: str, context: ssl.SSLContext | None) -> dict[str, Any]:
    session = MagicMock(spec=aiohttp.ClientSession)
    session.request.return_value = _Response()
    link = IsapiLink(
        session, Endpoint("192.0.2.10", 443, scheme), "u", "p", trusted=True, ssl_context=context
    )
    link._auth_checked = True  # no challenge round trip needed to see the request
    await link.call("GET", "/ISAPI/System/deviceInfo")
    kwargs: dict[str, Any] = session.request.call_args.kwargs
    return kwargs


async def test_https_requests_use_the_given_context() -> None:
    context = ssl.create_default_context()
    assert (await _sent_kwargs("https", context))["ssl"] is context


async def test_plain_http_and_no_context_leave_the_session_alone() -> None:
    """A session made not to verify (self-signed devices) keeps doing so."""
    assert "ssl" not in await _sent_kwargs("http", ssl.create_default_context())
    assert "ssl" not in await _sent_kwargs("https", None)
