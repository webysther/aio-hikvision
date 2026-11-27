"""Level 3: a device as an integration sees it, built only on level 2."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import TYPE_CHECKING

import aiohttp
import pytest

import aiohikvision
from aiohikvision import Camera, Hikvision, Kind, StreamId, StreamKind, Supports
from aiohikvision.isapi.wire.faults import BadCredentials
from aiohikvision.models.capabilities import Capabilities
from aiohikvision.parsers.capabilities import parse_capabilities
from tests.fakes import FakeIsapiDevice

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from aiohttp.test_utils import TestServer

type Serve = Callable[[FakeIsapiDevice], Awaitable[TestServer]]
PATTERNS = Path(__file__).parents[2] / "src/aiohikvision/patterns"


async def test_a_door_station_in_a_few_lines(serve: Serve) -> None:
    """Who it is, what it supports and its camera, answered by attributes; verbs ask the device."""
    fake = FakeIsapiDevice("door_station")
    server = await serve(fake)
    async with aiohikvision.connect("127.0.0.1", fake.username, fake.password, port=server.port) as hik:
        assert (hik.name, hik.model, str(hik.firmware)) == (
            "Door Station",
            "DS-KD8003-IME1(B)",
            "V3.7.3 build 260915",
        )
        assert hik.id == "dskd8003ime1b0120250101enfx0000001"
        assert hik.serial.startswith("DS-KD8003")
        assert hik.kind is Kind.DOOR_STATION
        assert hik.supports == Supports(
            snapshot=True,
            streaming=True,
            events=True,
            smart=False,
            ptz=False,
            two_way_audio=True,
            intercom=True,
            doors=True,
            holidays=False,
            inputs=4,
            outputs=2,
        )
        camera = hik.camera
        assert camera is not None
        assert [stream.id.isapi for stream in camera.streams] == ["101", "102"]
        assert camera.main is not None
        assert camera.sub is not None
        assert camera.sub.video is not None
        assert camera.sub.video.width == 1280
        assert (await camera.snapshot()).startswith(b"\xff\xd8")
        await camera.snapshot(StreamKind.SUB)
        assert fake.requests[-1] == ("GET", "/ISAPI/Streaming/channels/102/picture")
        assert (
            await camera.stream_url()
            == f"rtsp://operator:{fake.password}@127.0.0.1:554/Streaming/Channels/101"
        )
        assert (await camera.stream_url(StreamId(1, 2), credentials=False)).endswith("/Channels/102")
        assert (await hik.report()).device["model"] == "DS-KD8003-IME1(B)"
        await hik.check()
        # Level 2 is one step away, and level 1 one more
        assert hik.device.streaming is camera.streaming
        assert hik.device.link.endpoint.port == server.port
        assert repr(hik) == "<Hikvision door_station DS-KD8003-IME1(B) V3.7.3 build 260915>"
        assert repr(camera) == "<Camera 1: 101, 102>"
        session = hik.device.link._session
    # The session it opened is closed with it
    assert session.closed


async def test_a_recorder_has_a_camera_per_channel(serve: Serve) -> None:
    """A recorder's streams are grouped by channel: a camera each."""
    fake = FakeIsapiDevice("nvr")
    server = await serve(fake)
    async with aiohttp.ClientSession() as session:
        hik = await aiohikvision.connect(
            "127.0.0.1", fake.username, fake.password, port=server.port, session=session
        )
        assert hik.kind is Kind.RECORDER
        assert [camera.channel for camera in hik.cameras] == [1, 2, 3, 4, 5, 6]
        assert [stream.id.isapi for stream in hik.cameras[1].streams] == ["201", "202", "204"]
        await hik.cameras[2].snapshot()
        assert fake.requests[-1] == ("GET", "/ISAPI/Streaming/channels/301/picture")
        await hik.close()
        # A session it was given stays open
        assert not session.closed


async def test_a_device_awaited_then_used_in_async_with(serve: Serve) -> None:
    """An awaited connection is used in ``async with`` too; one made from a Device closes nothing."""
    fake = FakeIsapiDevice("door_station")
    server = await serve(fake)
    async with await aiohikvision.connect("127.0.0.1", fake.username, fake.password, port=server.port) as hik:
        session = hik.device.link._session
        from_device = await Hikvision.from_device(hik.device)
        await from_device.close()
        assert not session.closed
    assert session.closed


async def test_a_camera_that_does_not_list_its_streams(serve: Serve) -> None:
    """Without a list of streams the camera of channel 1 is still there, on its main stream."""
    fake = FakeIsapiDevice("camera_g3")
    server = await serve(fake)
    async with aiohikvision.connect("127.0.0.1", fake.username, fake.password, port=server.port) as hik:
        assert hik.kind is Kind.CAMERA
        camera = hik.camera
        assert camera is not None
        assert (camera.channel, camera.streams, camera.main, camera.sub) == (1, (), None, None)
        await camera.snapshot(StreamKind.THIRD)
        assert fake.requests[-1] == ("GET", "/ISAPI/Streaming/channels/103/picture")
        assert repr(camera) == "<Camera 1: no streams listed>"


async def test_a_device_without_video(serve: Serve) -> None:
    """A device whose capabilities show no video has no camera."""
    ns = 'xmlns="http://www.isapi.org/ver20/XMLSchema"'
    fake = FakeIsapiDevice(
        "camera_g3",
        overrides={"/ISAPI/System/capabilities": (200, f"<DeviceCap {ns}><EventCap/></DeviceCap>")},
    )
    server = await serve(fake)
    async with aiohikvision.connect("127.0.0.1", fake.username, fake.password, port=server.port) as hik:
        assert hik.cameras == ()
        assert hik.camera is None
        assert hik.supports.streaming is False


async def test_a_refused_account_closes_what_it_opened(serve: Serve) -> None:
    """A device that refuses the account raises, and the session opened for it is closed."""
    fake = FakeIsapiDevice("door_station")
    server = await serve(fake)
    connecting = aiohikvision.connect("127.0.0.1", fake.username, "wrong", port=server.port)
    with pytest.raises(BadCredentials):
        async with connecting:
            pass  # never reached
    assert connecting._client._session is None


@pytest.mark.parametrize(
    ("device_type", "document", "kind"),
    [
        ("VIS", None, Kind.DOOR_STATION),
        ("IPCamera", None, Kind.CAMERA),
        ("IPDome", None, Kind.CAMERA),
        ("HybirdNVR", None, Kind.RECORDER),
        ("DVR", None, Kind.RECORDER),
        (None, "<DeviceCap><VideoIntercomCap/></DeviceCap>", Kind.DOOR_STATION),
        (None, "<DeviceCap><isSupportSnapshot>true</isSupportSnapshot></DeviceCap>", Kind.CAMERA),
        ("AccessControl", None, Kind.OTHER),
    ],
)
def test_what_a_device_is(device_type: str | None, document: str | None, kind: Kind) -> None:
    """The kind of a device comes from its deviceType, and from its domains when that says little."""
    from aiohikvision.isapi.wire.xmlview import parse  # noqa: PLC0415  # only this test

    capabilities = parse_capabilities(parse(document)) if document else Capabilities()
    assert Kind.of(device_type, capabilities) is kind


def test_a_device_that_says_nothing_supports_nothing_known() -> None:
    """Without capabilities every answer is None: unknown, not absent."""
    supports = Supports.of(Capabilities())
    assert supports == Supports(None, None, None, None, None, None, None, None, None, None, None)


def test_level_3_is_built_on_level_2_only() -> None:
    """The patterns never reach the wire: they go through Device and its services."""
    for source in PATTERNS.glob("*.py"):
        for node in ast.walk(ast.parse(source.read_text())):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith(("aiohikvision.isapi", "aiohikvision.parsers")), source


def test_the_names_of_level_3() -> None:
    """Level 3 is what the package offers first."""
    for name in ("connect", "Hikvision", "Camera", "Kind", "Supports"):
        assert name in aiohikvision.__all__
    assert Hikvision.__module__ == Camera.__module__ == "aiohikvision.patterns.hikvision"
