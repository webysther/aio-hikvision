"""A lean, rich debug log: how a device was recognised, its streams, what failed, once each."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import aiohttp
import pytest

from aiohikvision import BehaviourPatch, Device, PacketTime
from aiohikvision.isapi.wire.faults import Unsupported
from aiohikvision.isapi.wire.link import Endpoint, IsapiLink
from tests.fakes import FakeIsapiDevice

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from aiohttp.test_utils import TestServer

type Serve = Callable[[FakeIsapiDevice], Awaitable[TestServer]]


@pytest.fixture
async def session() -> AsyncIterator[aiohttp.ClientSession]:
    """Yield a session for the links of a test."""
    async with aiohttp.ClientSession() as client:
        yield client


@pytest.fixture(autouse=True)
def debug(caplog: pytest.LogCaptureFixture) -> None:
    """Capture the debug log of the library."""
    caplog.set_level(logging.DEBUG, logger="aiohikvision")


async def link_of(serve: Serve, session: aiohttp.ClientSession, fake: FakeIsapiDevice) -> IsapiLink:
    """Return a link to a fake device."""
    server = await serve(fake)
    return IsapiLink(session, Endpoint("127.0.0.1", server.port), fake.username, fake.password)


async def test_how_a_door_station_was_recognised(
    serve: Serve, session: aiohttp.ClientSession, caplog: pytest.LogCaptureFixture
) -> None:
    """One record says who it is, its domains and how they are covered, and its rules."""
    device = await Device.from_link(await link_of(serve, session, FakeIsapiDevice("door_station")))
    summary = device.summary()
    assert (
        summary[0]
        == "Recognised DS-KD8003-IME1(B) V3.7.3 build 260915 on 127.0.0.1 (type VIS, hardware 1-1-0)"
    )
    assert summary[1] == (
        "Domains: streaming (service), events (door_station), io (door_station), video_intercom (door_station), "
        "access_control (door_station), two_way_audio (door_station); absent: smart, ptz, holidays"
    )
    assert summary[2].startswith(
        "Behaviour talk_packet=40ms: rule DS-KD8003*, seen on DS-KD8003-IME1(B) V3.7.3"
    )
    records = [record.getMessage() for record in caplog.records if record.name == "aiohikvision.device"]
    assert records == ["\n  ".join(summary)]


async def test_a_device_no_rule_knows(serve: Serve, session: aiohttp.ClientSession) -> None:
    """A device without capabilities or rules says so; an override says whose it is."""
    fake = FakeIsapiDevice("camera_g3", overrides={"/ISAPI/System/capabilities": (404, "")})
    device = await Device.from_link(await link_of(serve, session, fake))
    assert device.summary()[1:] == [
        "Domains: unknown, the device sent no capabilities: each service asks it",
        "Behaviours: the defaults, no rule knows this model and firmware",
    ]
    overridden = await Device.from_link(device.link, overrides=BehaviourPatch(talk_packet=PacketTime.MS_40))
    assert overridden.summary()[2] == "Behaviour talk_packet=40ms: the caller's override"
    none = FakeIsapiDevice(
        "camera_g3", overrides={"/ISAPI/System/capabilities": (200, "<DeviceCap><x>1</x></DeviceCap>")}
    )
    bare = await Device.from_link(await link_of(serve, session, none))
    assert bare.summary()[1] == (
        "Domains: none; absent: streaming, events, io, video_intercom, access_control, two_way_audio, "
        "smart, ptz, holidays"
    )


async def test_a_failing_request_is_said_once(
    serve: Serve, session: aiohttp.ClientSession, caplog: pytest.LogCaptureFixture
) -> None:
    """A request that fails is logged once, then once more when it answers again."""
    fake = FakeIsapiDevice("door_station")
    link = await link_of(serve, session, fake)
    for _ in range(3):
        with pytest.raises(Unsupported):
            await link.read_xml("/ISAPI/System/IO/status?format=x")
    fake.overrides["/ISAPI/System/IO/status"] = (200, "<IOPortStatusList/>")
    await link.read_xml("/ISAPI/System/IO/status")
    await link.read_xml("/ISAPI/System/IO/status")
    said = [record.getMessage() for record in caplog.records if record.name == "aiohikvision.isapi.wire.link"]
    assert said == [
        "GET /ISAPI/System/IO/status on 127.0.0.1: Unsupported (notSupport) (said once, until it answers again)",
        "GET /ISAPI/System/IO/status on 127.0.0.1 answers again",
    ]


async def test_the_streams_are_said_when_they_change(
    serve: Serve, session: aiohttp.ClientSession, caplog: pytest.LogCaptureFixture
) -> None:
    """The streams are logged in a few words the first time, and again only after a change."""
    fake = FakeIsapiDevice("door_station")
    streaming = (await Device.from_link(await link_of(serve, session, fake))).streaming
    assert streaming is not None
    await streaming.streams()
    await streaming.streams()
    fake.overrides["/ISAPI/Streaming/channels"] = (200, "<StreamingChannelList/>")
    await streaming.streams()
    said = [
        record.getMessage() for record in caplog.records if record.name == "aiohikvision.services.streaming"
    ]
    assert said == [
        "Streams of 127.0.0.1: 101 h264 1920x1080 30fps key 2s 4096kbps g711_ulaw; "
        "102 h264 1280x720 30fps key 2s 2048kbps g711_ulaw",
        "Streams of 127.0.0.1: none",
    ]
