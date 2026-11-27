"""The streams of a device, from ``/ISAPI/Streaming/channels``."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from aiohikvision.models.streaming import AudioCodec, Stream, StreamId, VideoCodec, VideoFormat

if TYPE_CHECKING:
    from aiohikvision.isapi.wire.xmlview import XmlNode

STREAMING_CHANNELS = "/ISAPI/Streaming/channels"

RTSP_PORT: Final = 554
"""The RTSP port of a device that does not say another (RFC 2326)."""

FRAME_RATE_SCALE: Final = 100
"""ISAPI writes frame rates in hundredths: ``maxFrameRate`` 3000 is 30 frames a second."""


def parse_streams(document: XmlNode | None) -> tuple[Stream, ...]:
    """Return the enabled streams of a list (or of one ``StreamingChannel``), in order of id.

    A stream turned off, or without a stream id ISAPI uses, is left out.
    """
    if document is None:
        return ()
    nodes = [document] if document.name == "StreamingChannel" else document.all("StreamingChannel")
    streams = [stream for node in nodes if (stream := _stream(node)) is not None]
    return tuple(sorted(streams, key=lambda stream: stream.id))


def _stream(node: XmlNode) -> Stream | None:
    try:
        stream_id = StreamId.parse(node.text("id") or "")
    except ValueError:
        return None
    if node.flag("enabled") is False:
        return None
    video = node.first("Video")
    audio = node.first("Audio")
    return Stream(
        id=stream_id,
        name=node.text("channelName"),
        video=_video(video) if video is not None and video.flag("enabled") is not False else None,
        audio=AudioCodec.of(audio.text("audioCompressionType"))
        if audio is not None and audio.flag("enabled")
        else None,
    )


def _video(video: XmlNode) -> VideoFormat:
    rate = video.numeric("maxFrameRate")
    variable = (video.text("videoQualityControlType") or "").upper() == "VBR"
    return VideoFormat(
        codec=VideoCodec.of(video.text("videoCodecType")),
        width=video.numeric("videoResolutionWidth"),
        height=video.numeric("videoResolutionHeight"),
        fps=rate / FRAME_RATE_SCALE if rate else None,
        gop_frames=video.numeric("GovLength"),
        bitrate_kbps=video.numeric("vbrUpperCap" if variable else "constantBitRate"),
    )


def parse_rtsp_port(accesses: XmlNode | None) -> int:
    """Return the RTSP port among the protocols of ``/ISAPI/Security/adminAccesses``.

    A protocol is enabled unless the device says otherwise; without RTSP among them, 554.
    """
    if accesses is None:
        return RTSP_PORT
    for node in accesses.children("AdminAccessProtocol"):
        if (node.text("protocol") or "").upper() == "RTSP" and node.flag("enabled", default=True):
            return node.numeric("portNo") or RTSP_PORT
    return RTSP_PORT
