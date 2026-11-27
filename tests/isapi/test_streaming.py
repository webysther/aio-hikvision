"""The streams of a device: what each carries, its picture and its RTSP address."""

from __future__ import annotations

from typing import TYPE_CHECKING

import aiohttp
import pytest

from aiohikvision import Device
from aiohikvision.isapi.wire.faults import DeviceRejected
from aiohikvision.isapi.wire.link import Endpoint, IsapiLink
from aiohikvision.isapi.wire.xmlview import parse
from aiohikvision.models.streaming import (
    AudioCodec,
    Stream,
    StreamId,
    StreamKind,
    VideoCodec,
    VideoFormat,
)
from aiohikvision.parsers.streaming import parse_rtsp_port, parse_streams
from tests.fakes import FakeIsapiDevice

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from aiohttp.test_utils import TestServer

    from aiohikvision.services.streaming import Streaming

type Serve = Callable[[FakeIsapiDevice], Awaitable[TestServer]]
NS = 'xmlns="http://www.isapi.org/ver20/XMLSchema"'


@pytest.fixture
async def session() -> AsyncIterator[aiohttp.ClientSession]:
    """Yield a session for the links of a test."""
    async with aiohttp.ClientSession() as client:
        yield client


async def device_of(serve: Serve, session: aiohttp.ClientSession, fake: FakeIsapiDevice) -> Device:
    """Return the device of a fake, read through its link."""
    server = await serve(fake)
    return await Device.from_link(
        IsapiLink(session, Endpoint("127.0.0.1", server.port), fake.username, fake.password)
    )


async def streaming_of(serve: Serve, session: aiohttp.ClientSession, fake: FakeIsapiDevice) -> Streaming:
    """Return the streams of a fake device."""
    streaming = (await device_of(serve, session, fake)).streaming
    assert streaming is not None
    return streaming


async def test_the_streams_of_a_door_station(serve: Serve, session: aiohttp.ClientSession) -> None:
    """A DS-KD8003 streams 1080p and 720p H.264 at 30 frames, a key frame every 2 s, with G.711."""
    streaming = await streaming_of(serve, session, FakeIsapiDevice("door_station"))
    main, sub = await streaming.streams()
    assert main.id == StreamId(1, 1)
    assert main.kind is StreamKind.MAIN
    assert main.video == VideoFormat(VideoCodec.H264, 1920, 1080, 30.0, 60, 4096)
    assert main.video.gop_seconds == 2.0
    assert main.video.aspect == 16 / 9
    assert main.audio is AudioCodec.G711_ULAW
    assert main.name == "REDACTED"
    assert (sub.kind, sub.video.width if sub.video else None) == (StreamKind.SUB, 720 * 16 // 9)
    assert await streaming.stream("102") == sub
    assert await streaming.sessions() == 5


async def test_a_stream_the_device_does_not_describe(serve: Serve, session: aiohttp.ClientSession) -> None:
    """A stream the device does not describe is None; without a list, there are no streams."""
    fake = FakeIsapiDevice(
        "door_station",
        overrides={"/ISAPI/Streaming/channels/101": (404, ""), "/ISAPI/Streaming/channels": (404, "")},
    )
    streaming = await streaming_of(serve, session, fake)
    assert await streaming.stream(StreamId(1, 1)) is None
    assert await streaming.streams() == ()


async def test_a_picture_of_a_stream(serve: Serve, session: aiohttp.ClientSession) -> None:
    """A picture is a JPEG, at the size asked for; an answer that is no picture is refused."""
    fake = FakeIsapiDevice("door_station")
    streaming = await streaming_of(serve, session, fake)
    assert (await streaming.snapshot()).startswith(b"\xff\xd8")
    await streaming.snapshot("102", width=640, height=360)
    assert fake.requests[-1] == (
        "GET",
        "/ISAPI/Streaming/channels/102/picture?videoResolutionWidth=640&videoResolutionHeight=360",
    )
    fake.overrides["/ISAPI/Streaming/channels/101/picture"] = (
        200,
        "<ResponseStatus><statusCode>3</statusCode></ResponseStatus>",
    )
    with pytest.raises(DeviceRejected, match="no picture"):
        await streaming.snapshot()


async def test_the_rtsp_address(serve: Serve, session: aiohttp.ClientSession) -> None:
    """The RTSP address carries the account, encoded, on the port the device says."""
    fake = FakeIsapiDevice("door_station", password="p@ss:w/rd")
    streaming = await streaming_of(serve, session, fake)
    assert (
        await streaming.rtsp_url() == "rtsp://operator:p%40ss%3Aw%2Frd@127.0.0.1:554/Streaming/Channels/101"
    )
    assert await streaming.rtsp_url("102", credentials=False) == "rtsp://127.0.0.1:554/Streaming/Channels/102"


async def test_a_device_without_streams(serve: Serve, session: aiohttp.ClientSession) -> None:
    """A device whose capabilities show no video has no streaming service."""
    fake = FakeIsapiDevice(
        "door_station",
        overrides={"/ISAPI/System/capabilities": (200, f"<DeviceCap {NS}><EventCap/></DeviceCap>")},
    )
    assert (await device_of(serve, session, fake)).streaming is None


def test_the_rtsp_port() -> None:
    """The RTSP port is the one the device enables, 554 otherwise."""
    moved = parse(
        f"<AdminAccessProtocolList {NS}><AdminAccessProtocol><protocol>RTSP</protocol>"
        "<portNo>8554</portNo></AdminAccessProtocol></AdminAccessProtocolList>"
    )
    assert parse_rtsp_port(moved) == 8554
    assert parse_rtsp_port(None) == 554
    off = parse(
        f"<AdminAccessProtocolList {NS}><AdminAccessProtocol><protocol>RTSP</protocol>"
        "<enabled>false</enabled><portNo>8554</portNo></AdminAccessProtocol></AdminAccessProtocolList>"
    )
    assert parse_rtsp_port(off) == 554


def test_the_streams_of_a_recorder() -> None:
    """A recorder lists the streams of its channels: H.265 and H.264, without sound."""
    from pathlib import Path  # noqa: PLC0415  # only this test reads a fixture

    listing = (Path(__file__).parents[1] / "fakes/fixtures/nvr/ISAPI_Streaming_channels.xml").read_text()
    streams = parse_streams(parse(listing))
    assert [stream.id.isapi for stream in streams][:3] == ["101", "102", "104"]
    assert streams[0].video is not None
    assert streams[0].video.codec is VideoCodec.H265
    assert streams[0].audio is None
    assert streams[2].kind is StreamKind.OTHER


def test_what_a_stream_list_may_hold() -> None:
    """Streams turned off, or with ids ISAPI does not use, are left out; one stream alone is read."""
    listing = parse(
        f"<StreamingChannelList {NS}>"
        "<StreamingChannel><id>201</id><Video><videoCodecType>MJPEG</videoCodecType>"
        "<videoQualityControlType>CBR</videoQualityControlType><constantBitRate>512</constantBitRate>"
        "</Video><Audio><enabled>true</enabled><audioCompressionType>G.722.1</audioCompressionType></Audio>"
        "</StreamingChannel>"
        "<StreamingChannel><id>103</id><Video><enabled>false</enabled></Video></StreamingChannel>"
        "<StreamingChannel><id>101</id><enabled>false</enabled></StreamingChannel>"
        "<StreamingChannel><id>1</id></StreamingChannel>"
        "</StreamingChannelList>"
    )
    third, second = parse_streams(listing)
    assert third == Stream(StreamId(1, 3))
    assert third.kind is StreamKind.THIRD
    assert second.video == VideoFormat(VideoCodec.MJPEG, bitrate_kbps=512)
    assert second.video.gop_seconds is None
    assert second.video.aspect is None
    assert second.audio is AudioCodec.G722
    assert parse_streams(None) == ()
    one = parse_streams(parse(f"<StreamingChannel {NS}><id>102</id></StreamingChannel>"))
    assert one == (Stream(StreamId(1, 2)),)


@pytest.mark.parametrize(
    ("text", "codec"),
    [
        ("H.264", VideoCodec.H264),
        ("h265", VideoCodec.H265),
        ("MJPEG", VideoCodec.MJPEG),
        ("SVAC", VideoCodec.OTHER),
    ],
)
def test_video_codecs(text: str, codec: VideoCodec) -> None:
    """The codec of a stream's video, as devices write it."""
    assert VideoCodec.of(text) is codec


@pytest.mark.parametrize(
    ("text", "codec"),
    [
        ("G.711ulaw", AudioCodec.G711_ULAW),
        ("G.711alaw", AudioCodec.G711_ALAW),
        ("AAC", AudioCodec.AAC),
        ("MP2L2", AudioCodec.MP2L2),
        ("G.726", AudioCodec.G726),
        ("MP3", AudioCodec.MP3),
        ("PCM", AudioCodec.PCM),
        ("OPUS", AudioCodec.OPUS),
        (None, AudioCodec.OTHER),
    ],
)
def test_audio_codecs(text: str | None, codec: AudioCodec) -> None:
    """The codec of a stream's sound, as devices write it."""
    assert AudioCodec.of(text) is codec


def test_stream_ids() -> None:
    """A stream id is its channel times 100 plus its place; other texts are no stream id."""
    assert StreamId.parse("101") == StreamId(1, 1)
    assert StreamId.parse(1602) == StreamId(16, 2)
    assert str(StreamId(2, 1)) == "201"
    for text in ("1", "1a1", ""):
        with pytest.raises(ValueError, match="stream id"):
            StreamId.parse(text)
