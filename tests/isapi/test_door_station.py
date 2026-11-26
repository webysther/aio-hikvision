"""DoorStation against the fake device with the answers of a DS-KD8003 (anonymized)."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import aiohttp
import pytest

from aiohikvision.isapi.door_station import DoorStation, DoorStationInfo, NotADoorStation, NotALock, rtsp_port
from aiohikvision.isapi.model.features.outputs import Output, OutputUse, parse_outputs
from aiohikvision.isapi.model.features.talk import TalkChannel, TalkEnd, TalkError
from aiohikvision.isapi.model.inventory import Identity
from aiohikvision.isapi.wire.faults import BadCredentials
from aiohikvision.isapi.wire.xmlview import parse
from tests.fakes import FakeIsapiDevice, FakeTalkDevice

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from aiohttp.test_utils import TestServer

FRAME = bytes(range(160))


@pytest.fixture
async def session() -> AsyncIterator[aiohttp.ClientSession]:
    async with aiohttp.ClientSession() as client:
        yield client


async def station(
    serve: Callable[[FakeIsapiDevice], Awaitable[TestServer]],
    session: aiohttp.ClientSession,
    device: FakeIsapiDevice,
    password: str | None = None,
) -> DoorStation:
    server = await serve(device)
    return DoorStation(session, "127.0.0.1", device.username, password or device.password, port=server.port)


async def test_what_a_door_station_is(serve, session) -> None:
    door = await station(serve, session, FakeIsapiDevice("door_station"))
    info = await door.read_info()
    assert info.identity.model == "DS-KD8003-IME1(B)"
    assert info.identity.name == "Door Station"
    assert info.identity.firmware == "V3.7.3"
    assert info.identity.stable_id == "dskd8003ime1b0120250101enfx0000001"
    assert info.doors == (1, 2)
    assert info.call_status
    assert info.talk == TalkChannel("1", "G.711ulaw")
    assert info.rtsp_port == 554
    # COM2 drives a mechanical doorbell: door 2 is listed, but it does not open.
    # Its capabilities (as a DS-KD8003 V3.7.3 answers) say what else it could drive.
    assert info.outputs == (
        Output(1, "COM1", OutputUse.ELECTRIC_LOCK, (OutputUse.ELECTRIC_LOCK,)),
        Output(
            2, "COM2", OutputUse.DOORBELL, (OutputUse.DISABLED, OutputUse.ELECTRIC_LOCK, OutputUse.DOORBELL)
        ),
    )
    assert info.locks == (1,)
    assert door.info is info
    assert await door.call_status() == "idle"


async def test_opening_a_door(serve, session) -> None:
    device = FakeIsapiDevice("door_station")
    door = await station(serve, session, device)
    await door.open_door(2)  # what its outputs drive is not known yet: it is tried
    method, path, body = device.writes[-1]
    assert (method, path) == ("PUT", "/ISAPI/AccessControl/RemoteControl/door/2")
    assert "<cmd>open</cmd>" in body


async def test_a_door_without_a_lock_does_not_open(serve, session) -> None:
    device = FakeIsapiDevice("door_station")
    door = await station(serve, session, device)
    await door.read_info()
    with pytest.raises(NotALock) as raised:
        await door.open_door(2)
    assert (raised.value.door, raised.value.use) == (2, OutputUse.DOORBELL)
    assert raised.value.translation_key == "not_a_lock"
    assert not device.writes
    await door.open_door(1)
    assert device.writes[-1][1] == "/ISAPI/AccessControl/RemoteControl/door/1"


async def test_the_outputs_are_read_again(serve, session) -> None:
    device = FakeIsapiDevice("door_station")
    door = await station(serve, session, device)
    await door.read_info()
    # Its web page sets COM2 to drive a lock
    device.overrides["/ISAPI/System/IO/outputs"] = (200, OUTPUTS.format(second="electricLock"))
    assert [output.use for output in await door.read_outputs()] == [OutputUse.ELECTRIC_LOCK] * 2
    assert door.info is not None
    assert door.info.locks == (1, 2)
    await door.open_door(2)


async def test_a_door_station_that_lists_no_outputs(serve, session) -> None:
    device = FakeIsapiDevice("door_station", overrides={"/ISAPI/System/IO/outputs": (404, "")})
    door = await station(serve, session, device)
    info = await door.read_info()
    # Every door it can open remotely is tried
    assert info.outputs == ()
    assert info.locks == (1, 2)
    assert await door.read_outputs() == ()


OUTPUTS = (
    '<IOOutputPortList xmlns="http://www.isapi.org/ver20/XMLSchema">'
    "<IOOutputPort><id>1</id><name>COM1</name><IOUseType>electricLock</IOUseType></IOOutputPort>"
    "<IOOutputPort><id>2</id><name>COM2</name><IOUseType>{second}</IOUseType></IOOutputPort>"
    "</IOOutputPortList>"
)


def test_what_the_outputs_drive_and_could() -> None:
    ns = 'xmlns="http://www.isapi.org/ver20/XMLSchema"'
    capabilities = parse(
        f"<IOOutputPortList {ns}>"
        '<IOOutputPort><id>1</id><IOUseType opt="electricLock">electricLock</IOUseType></IOOutputPort>'
        '<IOOutputPort><id>2</id><IOUseType opt="disable,electricLock,mechanicalDoorbell">'
        "disable</IOUseType></IOOutputPort></IOOutputPortList>"
    )
    read = parse_outputs(parse(OUTPUTS.format(second="disable")), capabilities)
    assert read == (
        Output(1, "COM1", OutputUse.ELECTRIC_LOCK, (OutputUse.ELECTRIC_LOCK,)),
        Output(
            2, "COM2", OutputUse.DISABLED, (OutputUse.DISABLED, OutputUse.ELECTRIC_LOCK, OutputUse.DOORBELL)
        ),
    )
    # A use this library does not know, and no capabilities
    assert parse_outputs(parse(OUTPUTS.format(second="siren")))[1].use is OutputUse.OTHER
    assert parse_outputs(None) == ()
    info = DoorStationInfo(
        identity=Identity(serial="S", model="M", name="N", firmware="F"),
        doors=(1, 2),
        call_status=True,
        talk=None,
        outputs=read,
    )
    assert info.locks == (1,)
    assert info.output_of(3) is None


async def test_picture_and_stream(serve, session) -> None:
    door = await station(serve, session, FakeIsapiDevice("door_station"))
    assert door.rtsp_url() == "rtsp://operator:s3cret-pass@127.0.0.1:554/Streaming/Channels/101"
    await door.read_info()
    assert (await door.snapshot()).startswith(b"\xff\xd8")
    assert door.rtsp_url("102").endswith("/Streaming/Channels/102")


def test_credentials_in_the_rtsp_address_are_encoded() -> None:
    door = DoorStation(None, "192.0.2.10", "admin", "p@ss:w/rd")
    assert door.rtsp_url() == "rtsp://admin:p%40ss%3Aw%2Frd@192.0.2.10:554/Streaming/Channels/101"


def test_the_rtsp_port() -> None:
    ns = 'xmlns="http://www.isapi.org/ver20/XMLSchema"'
    moved = parse(
        f"<AdminAccessProtocolList {ns}><AdminAccessProtocol><protocol>RTSP</protocol>"
        "<portNo>8554</portNo></AdminAccessProtocol></AdminAccessProtocolList>"
    )
    assert rtsp_port(moved) == 8554
    assert rtsp_port(None) == 554
    off = parse(
        f"<AdminAccessProtocolList {ns}><AdminAccessProtocol><protocol>RTSP</protocol>"
        "<enabled>false</enabled><portNo>8554</portNo></AdminAccessProtocol></AdminAccessProtocolList>"
    )
    assert rtsp_port(off) == 554


async def test_a_camera_is_no_door_station(serve, session) -> None:
    door = await station(serve, session, FakeIsapiDevice("camera_g3"))
    with pytest.raises(NotADoorStation):
        await door.read_info()


async def test_wrong_credentials(serve, session) -> None:
    door = await station(serve, session, FakeIsapiDevice("door_station"), password="wrong")
    with pytest.raises(BadCredentials):
        await door.read_info()


@pytest.fixture
async def speaker() -> AsyncIterator[FakeTalkDevice]:
    device = FakeTalkDevice()
    yield device
    await device.close()


async def talking_station(session: aiohttp.ClientSession, speaker: FakeTalkDevice) -> DoorStation:
    host, port = await speaker.start()
    door = DoorStation(session, host, speaker.username, speaker.password, port=port)
    with pytest.raises(TalkError, match="no_talk"):
        await door.talk(lambda _: None)
    door.info = DoorStationInfo(
        identity=Identity(serial="S", model="M", name="N", firmware="F"),
        doors=(1,),
        call_status=True,
        talk=TalkChannel("1", "G.711ulaw"),
    )
    return door


async def test_talking_through_the_speaker(session, speaker) -> None:
    door = await talking_station(session, speaker)
    ends: list[TalkEnd] = []
    first = await door.talk(ends.append)
    assert door.talking is first
    assert first.codec == "G.711ulaw"
    first.send(FRAME)
    second = await door.talk(ends.append)
    assert ends == [TalkEnd.REPLACED]
    assert first.ended
    assert door.talking is second
    second.send(FRAME)
    await asyncio.sleep(0.05)
    await door.close()
    assert ends == [TalkEnd.REPLACED, TalkEnd.UNLOADED]
    assert door.talking is None
    await door.close()


async def test_checking_the_door_station(serve, session) -> None:
    door = await station(serve, session, FakeIsapiDevice("door_station"))
    await door.check()
    bad = await station(serve, session, FakeIsapiDevice("door_station"), password="wrong")
    with pytest.raises(BadCredentials):
        await bad.check()
