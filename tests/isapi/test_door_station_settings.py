"""The inputs, load and settings of a door station, against the answers of a DS-KD8003."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import aiohttp
import pytest

from aiohikvision.isapi.door_station import DoorStation, DoorStationHealth, Setting
from aiohikvision.isapi.model.features import access, adjust, audio, doors, health
from aiohikvision.isapi.model.features.image import ImageCapability, ImageValue
from aiohikvision.isapi.model.features.inputs import Input, InputUse, input_use, parse_inputs
from aiohikvision.isapi.wire.xmlview import parse
from tests.fakes import FakeIsapiDevice

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from aiohttp.test_utils import TestServer

IMAGE_CHANNEL = """<ImageChannel><id>1</id><IrcutFilter><IrcutFilterType>auto</IrcutFilterType>
<nightToDayFilterLevel>4</nightToDayFilterLevel></IrcutFilter>
<powerLineFrequency><powerLineFrequencyMode>60hz</powerLineFrequencyMode></powerLineFrequency>
<Color><brightnessLevel>50</brightnessLevel></Color></ImageChannel>"""


@pytest.fixture
async def session() -> AsyncIterator[aiohttp.ClientSession]:
    async with aiohttp.ClientSession() as client:
        yield client


async def opened(
    serve: Callable[[FakeIsapiDevice], Awaitable[TestServer]],
    session: aiohttp.ClientSession,
    device: FakeIsapiDevice,
) -> DoorStation:
    server = await serve(device)
    door = DoorStation(session, "127.0.0.1", device.username, device.password, port=server.port)
    await door.read_info()
    return door


async def test_the_inputs_and_what_they_read(serve, session) -> None:
    door = await opened(serve, session, FakeIsapiDevice("door_station"))
    assert door.info is not None
    assert door.info.inputs == (
        Input(1, "AI1", InputUse.DOOR_CONTACT, (InputUse.DOOR_CONTACT,)),
        Input(2, "AI2", InputUse.DISABLED, (InputUse.DISABLED, InputUse.DOOR_CONTACT)),
        Input(3, "AI3", InputUse.EXIT_BUTTON, (InputUse.EXIT_BUTTON,)),
        Input(4, "AI4", InputUse.DISABLED, (InputUse.DISABLED, InputUse.EXIT_BUTTON)),
    )
    # Its web page can change them: they are read again, and kept
    device = FakeIsapiDevice("door_station")
    door = await opened(serve, session, device)
    device.overrides["/ISAPI/System/IO/inputs"] = (
        200,
        "<IOInputPortList><IOInputPort><id>2</id><IOUseType>doorStatus</IOUseType></IOInputPort>"
        "<IOInputPort><IOUseType>openDoor</IOUseType></IOInputPort></IOInputPortList>",
    )
    assert [item.use for item in await door.read_inputs()] == [InputUse.DOOR_CONTACT]
    assert door.info is not None
    assert door.info.inputs[0].number == 2


def test_inputs_a_device_does_not_list() -> None:
    assert parse_inputs(None) == ()
    assert input_use("something") is InputUse.OTHER
    assert input_use(None) is InputUse.OTHER
    listed = parse(
        "<IOInputPortList><IOInputPort><id>1</id><IOUseType>disable</IOUseType></IOInputPort></IOInputPortList>"
    )
    capabilities = parse(
        "<IOInputPortList><IOInputPort><IOUseType opt='doorStatus'/></IOInputPort>"
        "<IOInputPort><id>1</id><IOUseType/></IOInputPort></IOInputPortList>"
    )
    assert parse_inputs(listed, capabilities) == (Input(1, None, InputUse.DISABLED),)


async def test_inputs_of_a_device_without_them(serve, session) -> None:
    device = FakeIsapiDevice("door_station")
    device.overrides["/ISAPI/System/IO/inputs"] = (404, "")
    door = await opened(serve, session, device)
    assert door.info is not None
    assert door.info.inputs == ()
    assert await door.read_inputs() == ()


async def test_how_loaded_it_is(serve, session) -> None:
    door = await opened(serve, session, FakeIsapiDevice("door_station"))
    # The DS-KD8003 of the capture: five clients streaming, the CPU at 88%
    assert await door.read_health() == DoorStationHealth(cpu_percent=88, video_sessions=5)


async def test_load_a_device_does_not_say(serve, session) -> None:
    device = FakeIsapiDevice("door_station")
    door = await opened(serve, session, device)
    device.overrides["/ISAPI/System/status"] = (404, "")
    device.overrides["/ISAPI/Streaming/status"] = (404, "")
    assert await door.read_health() == DoorStationHealth()
    assert health.parse_session_count(parse("<StreamingStatus/>")) is None
    negative = parse("<StreamingStatus><totalStreamingSessions>-1</totalStreamingSessions></StreamingStatus>")
    assert health.parse_session_count(negative) is None


async def test_the_settings_it_offers(serve, session) -> None:
    door = await opened(serve, session, FakeIsapiDevice("door_station"))
    offered = {setting.ref: setting.capability for setting in await door.read_settings()}
    # The image settings of its camera, as its capabilities list them; its BLC is left out:
    # it offers "ture,false"
    assert offered[("day_night", "1")].options == ("day", "night", "auto", "schedule")
    assert offered[("day_night_sensitivity", "1")] == ImageCapability(
        "day_night_sensitivity", minimum=0, maximum=7
    )
    assert offered[("power_line_frequency", "1")].options == ("50hz", "60hz")
    assert offered[("wdr", "1")].options == ("close", "open")
    assert ("blc", "1") not in offered
    # Its volumes, 0 to 10
    for key in ("input_volume", "output_volume", "talk_volume"):
        assert offered[(key, "1")] == ImageCapability(key, minimum=0, maximum=10)
    # How long each door stays open: its doors have no capabilities, so the guide's range
    assert offered[("open_time", "1")] == ImageCapability("open_time", minimum=1, maximum=255)
    assert ("open_time", "2") in offered
    # What it says when a door opens
    assert offered[("door_voice_prompt", "1")] == ImageCapability("door_voice_prompt")
    assert offered[("door_voice_prompt_type", "1")].options == ("long", "short", "doorIsOpen")


async def test_the_values_of_its_settings(serve, session) -> None:
    device = FakeIsapiDevice("door_station")
    device.overrides["/ISAPI/Image/channels/1"] = (200, IMAGE_CHANNEL)
    door = await opened(serve, session, device)
    settings = await door.read_settings()
    values = await door.read_setting_values(settings)
    assert values[("day_night", "1")] == ImageValue("IrcutFilterType", "auto")
    assert values[("power_line_frequency", "1")].value == "60hz"
    assert values[("output_volume", "1")] == ImageValue("AudioOutVolumelist/AudioOutVlome/volume", "7")
    assert values[("talk_volume", "1")].value == "7"
    assert values[("input_volume", "1")].value == "7"
    assert values[("open_time", "1")] == ImageValue("openDuration", "1")
    assert values[("open_time", "2")].value == "7"
    assert values[("door_voice_prompt", "1")] == ImageValue("openDoorVoicePromptEnabled", "true")
    assert values[("door_voice_prompt_type", "1")].value == "doorIsOpen"
    # A setting whose document does not answer is left out
    assert ("sharpness", "1") not in values


async def test_changing_its_settings(serve, session) -> None:
    device = FakeIsapiDevice("door_station")
    door = await opened(serve, session, device)
    settings = {setting.ref: setting for setting in await door.read_settings()}
    await door.write_setting(
        settings[("talk_volume", "1")], "AudioOutVolumelist/AudioOutVlome/talkVolume", "5"
    )
    method, path, body = device.writes[-1]
    assert (method, path) == ("PUT", "/ISAPI/System/Audio/AudioOut/channels/1")
    assert "<talkVolume>5</talkVolume>" in body
    assert "<volume>7</volume>" in body
    await door.write_setting(settings[("open_time", "2")], "openDuration", "10")
    assert device.writes[-1][1] == "/ISAPI/AccessControl/Door/param/2"
    assert "<openDuration>10</openDuration>" in device.writes[-1][2]
    await door.write_setting(settings[("door_voice_prompt", "1")], "openDoorVoicePromptEnabled", "false")
    method, path, body = device.writes[-1]
    assert path == "/ISAPI/AccessControl/AcsCfg?format=json"
    assert json.loads(body)["AcsCfg"] == {
        "openDoorVoicePromptEnabled": False,
        "openDoorVoicePromptType": "doorIsOpen",
        "uploadVerificationPic": True,
    }
    await door.write_setting(settings[("door_voice_prompt_type", "1")], "openDoorVoicePromptType", "short")
    assert json.loads(device.writes[-1][2])["AcsCfg"]["openDoorVoicePromptType"] == "short"


def test_a_setting_knows_how_it_is_read() -> None:
    setting = Setting("open_time", "2", ImageCapability("open_time", minimum=1, maximum=255))
    assert setting.ref == ("open_time", "2")
    assert setting.spec.source == "door"
    assert setting.spec.seconds


def test_volumes_and_doors_a_device_does_not_describe() -> None:
    assert audio.parse_capabilities("AudioOut", None) == {}
    assert audio.parse_values("AudioOut", None) == {}
    no_range = parse(
        "<AudioOutCap><AudioOutVolumelist><AudioOutVlome><volume/></AudioOutVlome></AudioOutVolumelist></AudioOutCap>"
    )
    assert audio.parse_capabilities("AudioOut", no_range) == {}
    flat = parse(
        "<AudioOutCap><AudioOutVolumelist><AudioOutVlome><volume min='5' max='5'/>"
        "</AudioOutVlome></AudioOutVolumelist></AudioOutCap>"
    )
    assert audio.parse_capabilities("AudioOut", flat) == {}
    current = parse(
        "<AudioOut><AudioOutVolumelist><AudioOutVlome><volume>3</volume></AudioOutVlome></AudioOutVolumelist></AudioOut>"
    )
    assert audio.parse_values("AudioOut", current, {"talk_volume"}) == {}

    assert doors.parse_capabilities(None, None) == {}
    param = parse("<DoorParam><openDuration>3</openDuration></DoorParam>")
    ranged = parse("<DoorParam><openDuration min='1' max='60'/></DoorParam>")
    assert doors.parse_capabilities(param, ranged)["open_time"].maximum == 60
    broken = parse("<DoorParam><openDuration min='x'/></DoorParam>")
    assert doors.parse_capabilities(param, broken)["open_time"].maximum == 255
    upside_down = parse("<DoorParam><openDuration min='9' max='2'/></DoorParam>")
    assert doors.parse_capabilities(param, upside_down)["open_time"].minimum == 1
    assert doors.parse_values(param, {"name"}) == {}
    assert doors.parse_values(parse("<DoorParam/>")) == {}

    assert access.parse_capabilities(None) == {}
    assert access.parse_capabilities({"AcsCfg": {"openDoorVoicePromptType": {"@opt": ["long"]}}}) == {}
    assert access.parse_values({"AcsCfg": []}) == {}


async def test_volumes_of_a_device_without_audio(serve, session) -> None:
    device = FakeIsapiDevice("door_station")
    door = await opened(serve, session, device)
    for resource in ("AudioIn", "AudioOut"):
        device.overrides[f"/ISAPI/System/Audio/{resource}/channels/1"] = (404, "")
    assert await audio.read_values(door.link, "1") is None
    # Only the documents of the wanted volumes are read
    assert await audio.read_values(door.link, "1", {"input_volume"}) is None


async def test_doors_of_a_device_without_door_parameters(serve, session) -> None:
    device = FakeIsapiDevice("door_station")
    door = await opened(serve, session, device)
    device.overrides["/ISAPI/AccessControl/Door/param/1"] = (404, "")
    assert await doors.read_capabilities(door.link, "1") == {}
    assert await doors.read_values(door.link, "1") is None


def test_the_channel_sources_stay_those_of_cameras() -> None:
    # hikvision_bridge walks adjust.SOURCES for every channel of every device: the sources
    # of door stations stay apart, so that it asks its cameras nothing new.
    assert set(adjust.SOURCES) == {"image", "strobe", "siren", "speaker", "park"}
    assert set(adjust.DOOR_STATION_SOURCES) == {"audio", "door", "access"}
    assert adjust.BY_KEY["open_time"].source == "door"
    assert adjust.source_of("door") is adjust.DOOR_STATION_SOURCES["door"]
