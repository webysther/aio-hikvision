"""The streams of a device: each video channel has a main stream, a sub stream, and maybe more.

ISAPI numbers a stream by its channel and its place: stream ``101`` is the main stream of
channel 1, ``102`` its sub stream, ``201`` the main stream of channel 2.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from aiohikvision.models._coded import CodedEnum, coded

STREAMS_PER_CHANNEL: Final = 100
"""How ISAPI numbers streams: the channel times 100, plus the stream's place (101, 102, 201)."""

_STREAM_ID: Final = re.compile(r"^\d{3,}$")


@coded(MAIN=1, SUB=2, THIRD=3, OTHER=4)
class StreamKind(CodedEnum):
    """The place of a stream in its channel."""

    MAIN = "main"
    """The first stream: the full picture."""
    SUB = "sub"
    """The second stream: a smaller picture, lighter to play."""
    THIRD = "third"
    """The third stream, on devices that have one."""
    OTHER = "other"


@coded(H264=1, H265=2, MJPEG=3, OTHER=4)
class VideoCodec(CodedEnum):
    """How a stream's video is encoded (``videoCodecType``)."""

    H264 = "h264"
    H265 = "h265"
    MJPEG = "mjpeg"
    OTHER = "other"

    @classmethod
    def of(cls, text: str | None) -> VideoCodec:
        """Return the codec of ``videoCodecType`` ("H.264", "H.265", "MJPEG")."""
        key = re.sub(r"[^a-z0-9]", "", (text or "").lower())
        return {"h264": cls.H264, "h265": cls.H265, "mjpeg": cls.MJPEG}.get(key, cls.OTHER)


@coded(G711_ULAW=1, G711_ALAW=2, G722=3, G726=4, AAC=5, MP2L2=6, MP3=7, PCM=8, OPUS=9, OTHER=10)
class AudioCodec(CodedEnum):
    """How a stream's sound is encoded (``audioCompressionType``)."""

    G711_ULAW = "g711_ulaw"
    G711_ALAW = "g711_alaw"
    G722 = "g722"
    G726 = "g726"
    AAC = "aac"
    MP2L2 = "mp2l2"
    MP3 = "mp3"
    PCM = "pcm"
    OPUS = "opus"
    OTHER = "other"

    @classmethod
    def of(cls, text: str | None) -> AudioCodec:
        """Return the codec of ``audioCompressionType`` ("G.711ulaw", "G.722.1", "AAC")."""
        key = re.sub(r"[^a-z0-9]", "", (text or "").lower())
        codecs = {
            "g711ulaw": cls.G711_ULAW,
            "g711alaw": cls.G711_ALAW,
            "g7221": cls.G722,
            "g722": cls.G722,
            "g726": cls.G726,
            "aac": cls.AAC,
            "mp2l2": cls.MP2L2,
            "mp3": cls.MP3,
            "pcm": cls.PCM,
            "opus": cls.OPUS,
        }
        return codecs.get(key, cls.OTHER)


@dataclass(frozen=True, slots=True, order=True)
class StreamId:
    """A stream, by its channel and its place in the channel: ``StreamId(1, 2)`` is ``102``."""

    channel: int
    index: int

    @classmethod
    def parse(cls, text: str | int) -> StreamId:
        """Return the stream of an ISAPI id ("101"); raise ValueError for another text."""
        text = str(text).strip()
        if not _STREAM_ID.match(text):
            msg = f"not an ISAPI stream id: {text!r}"
            raise ValueError(msg)
        channel, index = divmod(int(text), STREAMS_PER_CHANNEL)
        return cls(channel, index)

    @property
    def isapi(self) -> str:
        """Return the id ISAPI writes: "101"."""
        return str(self.channel * STREAMS_PER_CHANNEL + self.index)

    @property
    def kind(self) -> StreamKind:
        """Return the place of the stream in its channel."""
        return {1: StreamKind.MAIN, 2: StreamKind.SUB, 3: StreamKind.THIRD}.get(self.index, StreamKind.OTHER)

    def __str__(self) -> str:
        """Return the id ISAPI writes."""
        return self.isapi


@dataclass(frozen=True, slots=True)
class VideoFormat:
    """The video of a stream; None where the device does not say."""

    codec: VideoCodec
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    gop_frames: int | None = None
    """Frames from one key frame to the next (``GovLength``): a player starts at a key frame."""
    bitrate_kbps: int | None = None
    """The most the stream sends: the cap of a variable rate, or the constant rate."""

    @property
    def gop_seconds(self) -> float | None:
        """Return the seconds between key frames: how long a player may wait for its first picture."""
        if not self.gop_frames or not self.fps:
            return None
        return self.gop_frames / self.fps

    @property
    def aspect(self) -> float | None:
        """Return the shape of the picture, width over height."""
        return self.width / self.height if self.width and self.height else None


@dataclass(frozen=True, slots=True)
class Stream:
    """A stream of a device: its video and, when it has sound, the codec of its sound."""

    id: StreamId
    name: str | None = None
    video: VideoFormat | None = None
    audio: AudioCodec | None = None
    """None when the stream carries no sound."""

    @property
    def kind(self) -> StreamKind:
        """Return the place of the stream in its channel."""
        return self.id.kind
