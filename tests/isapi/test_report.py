"""The capability report: what a device is and answers, anonymized, and what is missing."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

import aiohttp
import pytest

from aiohikvision import Device, Domain
from aiohikvision.isapi.wire.faults import BadCredentials
from aiohikvision.isapi.wire.link import Endpoint, IsapiLink
from aiohikvision.report import NEVER_READ, REPORT_PATHS, Coverage, Outcome, readable
from tests.fakes import FakeIsapiDevice

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from aiohttp.test_utils import TestServer

type Serve = Callable[[FakeIsapiDevice], Awaitable[TestServer]]
ADDRESS = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
DOCUMENTATION = ("192.0.2.", "198.51.100.", "203.0.113.", "127.", "0.0.0.0", "255.")  # noqa: S104  # kept


@pytest.fixture
async def session() -> AsyncIterator[aiohttp.ClientSession]:
    """Yield a session for the links of a test."""
    async with aiohttp.ClientSession() as client:
        yield client


async def connect(serve: Serve, session: aiohttp.ClientSession, fake: FakeIsapiDevice) -> Device:
    """Return the device of a fake."""
    server = await serve(fake)
    return await Device.from_link(
        IsapiLink(session, Endpoint("127.0.0.1", server.port), fake.username, fake.password)
    )


@pytest.mark.parametrize("profile", ["door_station", "camera_g3", "camera_noio", "nvr"])
async def test_a_report_shares_nothing_of_a_home(
    serve: Serve, session: aiohttp.ClientSession, profile: str
) -> None:
    """No account, serial, MAC, real address or name of a home leaves in a report; GET only."""
    fake = FakeIsapiDevice(profile)
    device = await connect(serve, session, fake)
    report = await device.report(secrets=["Door Station"])
    text = report.to_json()
    assert json.loads(text) == json.loads(json.dumps(report.as_dict()))
    for secret in (fake.password, fake.username, device.identity.serial, "Door Station"):
        assert secret not in text
    assert not re.search(r"\b[0-9a-f]{2}(:[0-9a-f]{2}){5}\b", text, re.IGNORECASE)
    for address in ADDRESS.findall(text):
        assert address.startswith(DOCUMENTATION), address
    assert {method for method, _ in fake.requests} == {"GET"}
    assert all(readable(path) for _, path in fake.requests)
    assert report.library == "0.2.0"


async def test_what_a_door_station_report_says(serve: Serve, session: aiohttp.ClientSession) -> None:
    """The report of a DS-KD8003: its domains, how each is covered, its behaviours, its documents."""
    device = await connect(serve, session, FakeIsapiDevice("door_station"))
    report = await device.report()
    assert report.device["model"] == "DS-KD8003-IME1(B)"
    assert report.domains[Domain.VIDEO_INTERCOM] == "present"
    assert report.coverage == {
        Domain.STREAMING: Coverage.SERVICE,
        Domain.EVENTS: Coverage.DOOR_STATION,
        Domain.IO: Coverage.DOOR_STATION,
        Domain.VIDEO_INTERCOM: Coverage.DOOR_STATION,
        Domain.ACCESS_CONTROL: Coverage.DOOR_STATION,
        Domain.TWO_WAY_AUDIO: Coverage.DOOR_STATION,
    }
    assert report.behaviours["talk_packet"] == {"value": "40ms", "decided_by": "rule", "rule": "DS-KD8003*"}
    assert report.unknown == ()
    paths = {entry.path: entry for entry in report.entries}
    assert paths["/ISAPI/Streaming/channels/102/capabilities"].outcome is Outcome.ANSWERED
    assert "/ISAPI/Smart/capabilities" not in paths  # the device has no smart detections
    assert paths["/ISAPI/System/IO/status"].outcome is Outcome.UNSUPPORTED
    body = paths["/ISAPI/Streaming/status"].body or ""
    assert "<totalStreamingSessions>5</totalStreamingSessions>" in body


async def test_what_is_missing_and_what_failed(serve: Serve, session: aiohttp.ClientSession) -> None:
    """A model no rule knows, codecs not recognised, refusals and failures are all said."""
    listing = (
        '<StreamingChannelList xmlns="http://www.isapi.org/ver20/XMLSchema"><StreamingChannel><id>101</id>'
        "<Video><videoCodecType>SVAC</videoCodecType></Video>"
        "<Audio><enabled>true</enabled><audioCompressionType>G.729</audioCompressionType></Audio>"
        "</StreamingChannel></StreamingChannelList>"
    )
    fake = FakeIsapiDevice(
        "camera_g3",
        overrides={
            "/ISAPI/Streaming/channels": (200, listing),
            "/ISAPI/System/status": (
                500,
                "<ResponseStatus><subStatusCode>deviceError</subStatusCode></ResponseStatus>",
            ),
            "/ISAPI/Security/illegalLoginLock": (
                403,
                "<ResponseStatus><statusCode>4</statusCode><subStatusCode>lowPrivilege</subStatusCode></ResponseStatus>",
            ),
        },
    )
    report = await (await connect(serve, session, fake)).report()
    assert report.unknown == (
        "stream 101: video codec not recognised",
        "stream 101: sound codec not recognised",
        "no rule knows this model and firmware: its behaviours are the defaults",
    )
    assert [entry.path for entry in report.failed] == ["/ISAPI/System/status"]
    assert report.failed[0].error is not None
    assert report.as_dict()["failed"] == ["/ISAPI/System/status"]
    outcomes = {entry.path: entry.outcome for entry in report.entries}
    assert outcomes["/ISAPI/Security/illegalLoginLock"] is Outcome.FORBIDDEN
    assert Coverage.NONE in report.coverage.values()


async def test_a_refused_login_stops_the_report(serve: Serve, session: aiohttp.ClientSession) -> None:
    """The report stops at a refused login: the device's lockout is never approached."""
    fake = FakeIsapiDevice("door_station")
    device = await connect(serve, session, fake)
    device.link.replace_credentials(fake.username, "wrong")
    with pytest.raises(BadCredentials):
        await device.report()
    # Refused on a document too, not only on the list of streams
    device = await connect(serve, session, fake)
    device.streaming = None
    device.link.replace_credentials(fake.username, "wrong")
    with pytest.raises(BadCredentials):
        await device.report()


def test_the_report_reads_nothing_it_must_not() -> None:
    """No listed path acts or hands out secrets; the words of NEVER_READ are refused."""
    assert all(readable(path) for path, _ in REPORT_PATHS)
    for path in ("/ISAPI/System/reboot", "/ISAPI/Streaming/channels/101/picture", "/ISAPI/Security/users"):
        assert not readable(path)
    assert all(word == word.lower() for word in NEVER_READ)
