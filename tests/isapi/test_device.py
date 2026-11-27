"""A device over ISAPI: who it is, what it can do and how it behaves, read once."""

from __future__ import annotations

from typing import TYPE_CHECKING

import aiohttp
import pytest

from aiohikvision import (
    BehaviourPatch,
    Device,
    Domain,
    HikvisionClient,
    Match,
    PacketTime,
    Rule,
    Support,
)
from aiohikvision.behaviours.rules import Source
from aiohikvision.isapi.wire.faults import BadCredentials, NotIsapi
from aiohikvision.isapi.wire.link import Endpoint, IsapiLink
from tests.fakes import FakeIsapiDevice

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from aiohttp.test_utils import TestServer

type Serve = Callable[[FakeIsapiDevice], Awaitable[TestServer]]


async def test_a_door_station(serve: Serve) -> None:
    """The client reads who the door station is, its domains, and its 40 ms packets."""
    fake = FakeIsapiDevice("door_station")
    server = await serve(fake)
    async with HikvisionClient() as client:
        device = await client.connect("127.0.0.1", fake.username, fake.password, port=server.port)
        assert device.identity.model == "DS-KD8003-IME1(B)"
        assert str(device.identity.firmware) == "V3.7.3 build 260915"
        assert device.identity.device_id == "00000000-0000-4000-8000-000000000001"
        assert device.capabilities.support(Domain.VIDEO_INTERCOM) is Support.PRESENT
        assert device.capabilities.support(Domain.PTZ) is Support.ABSENT
        assert device.behaviours.talk_packet is PacketTime.MS_40
        assert device.resolved.decisions["talk_packet"].source is Source.RULE
        await device.check()
        session = client.session
    # The session the client opened is closed with it
    assert session.closed


async def test_the_callers_rules_and_overrides(serve: Serve) -> None:
    """A consumer's rules and overrides change how the devices it connects to behave."""
    fake = FakeIsapiDevice("door_station")
    server = await serve(fake)
    async with aiohttp.ClientSession() as session:
        mine = Rule(Match(model="DS-KD8003*"), BehaviourPatch(talk_packet=PacketTime.MS_20))
        client = HikvisionClient(session, rules=[mine])
        device = await client.connect("127.0.0.1", fake.username, fake.password, port=server.port)
        assert device.behaviours.talk_packet is PacketTime.MS_20
        assert device.resolved.decisions["talk_packet"].rule is mine
        client = HikvisionClient(session, overrides=BehaviourPatch(talk_packet=PacketTime.MS_20))
        device = await client.connect("127.0.0.1", fake.username, fake.password, port=server.port)
        assert device.resolved.decisions["talk_packet"].source is Source.OVERRIDE
        # A session the client was given stays open
        await client.close()
        assert not session.closed


async def test_a_device_without_capabilities(serve: Serve) -> None:
    """A device that does not say what it can do leaves every domain to be asked."""
    fake = FakeIsapiDevice("camera_g3", overrides={"/ISAPI/System/capabilities": (404, "")})
    server = await serve(fake)
    async with aiohttp.ClientSession() as session:
        link = IsapiLink(session, Endpoint("127.0.0.1", server.port), fake.username, fake.password)
        device = await Device.from_link(link)
        assert device.identity.device_type == "IPCamera"
        assert device.capabilities.support(Domain.STREAMING) is Support.UNKNOWN
        assert device.behaviours.talk_packet is PacketTime.MS_20


async def test_what_is_no_device(serve: Serve) -> None:
    """An answer without device information is no ISAPI device; a wrong password is said so."""
    fake = FakeIsapiDevice("door_station", overrides={"/ISAPI/System/deviceInfo": (200, "")})
    server = await serve(fake)
    async with HikvisionClient() as client:
        with pytest.raises(NotIsapi):
            await client.connect("127.0.0.1", fake.username, fake.password, port=server.port)
        with pytest.raises(BadCredentials):
            await client.connect("127.0.0.1", fake.username, "wrong", port=server.port)
