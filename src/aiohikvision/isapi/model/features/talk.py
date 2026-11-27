"""Two-way audio: the channel a device plays sound from Home Assistant on, and how to open it.

The device lists its channels at /ISAPI/System/TwoWayAudio/channels, each with the codec it
expects. Talking is close (a previous session may still hold the channel), open, then one
PUT of audioData whose body is the sound itself, raw G.711 for as long as the talk lasts.

The sound is passed on as it comes, already encoded in the channel's G.711 variant (a
browser sends it 20 ms at a time): no decoding, no transcoding.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum

from aiohikvision.errors import HikvisionError
from aiohikvision.isapi.model.ids import seg
from aiohikvision.isapi.wire.link import IsapiLink, Upload
from aiohikvision.isapi.wire.scrub import scrubbed_logger
from aiohikvision.isapi.wire.xmlview import XmlError, XmlNode

_LOGGER = scrubbed_logger(__name__)

PATH = "/ISAPI/System/TwoWayAudio/channels"
# The codecs the browser encodes; devices offering only others (G.726, AAC) get no microphone.
CODECS = ("G.711ulaw", "G.711alaw")


@dataclass(frozen=True, slots=True)
class TalkChannel:
    """A two-way audio channel and the G.711 variant it expects."""

    channel_id: str
    codec: str

    @property
    def path(self) -> str:
        return f"{PATH}/{seg(self.channel_id)}"


def parse_channels(document: XmlNode | None) -> TalkChannel | None:
    """The first channel with a G.711 codec.

    Its ``enabled`` is not looked at: devices report it false while nobody talks.
    """
    if document is None:
        return None
    for node in document.children("TwoWayAudioChannel"):
        channel_id = node.text("id")
        codec = node.text("audioCompressionType")
        if channel_id and codec in CODECS:
            return TalkChannel(channel_id, codec)
    return None


async def read(link: IsapiLink) -> TalkChannel | None:
    document = await link.read_xml(PATH, optional=True)
    channel = parse_channels(document)
    if channel is None:
        # Why a device gets no microphone: no answer, or channels with other codecs
        _LOGGER.debug(
            "%s has no G.711 two-way audio channel: %s",
            link.endpoint.host,
            "no answer"
            if document is None
            else [
                (node.text("id"), node.text("audioCompressionType"))
                for node in document.children("TwoWayAudioChannel")
            ],
        )
    return channel


def session_id(document: XmlNode | None) -> str | None:
    """The session some firmwares hand out on open; audioData then names it."""
    return document.text("sessionId") if document is not None else None


class TalkEnd(StrEnum):
    """Why a talk ended."""

    STOPPED = "stopped"  # the person stopped it, or left the page
    REPLACED = "replaced"  # someone else started talking to the device
    DEVICE = "device"  # the device closed the connection
    UNLOADED = "unloaded"  # the owner of the talk went away


class TalkError(Exception):
    """The talk could not start; ``reason`` names why, for the person."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class TwoWayAudio:
    """One open two-way audio session on a device: its speaker plays what is sent."""

    def __init__(self, link: IsapiLink, channel: TalkChannel, on_end: Callable[[TalkEnd], None]) -> None:
        self.link = link
        self.channel = channel
        self._on_end = on_end
        self._upload: Upload | None = None
        self._watch: asyncio.Task[None] | None = None
        self._ended = False
        self.sent = 0
        self.dropped = 0

    @property
    def codec(self) -> str:
        return self.channel.codec

    @property
    def ended(self) -> bool:
        return self._ended

    async def open(self) -> None:
        """Close what a previous session may have left open, open the channel, then the body."""
        path = self.channel.path
        with suppress(HikvisionError):
            await self.link.call("PUT", f"{path}/close")
        try:
            reply = await self.link.call("PUT", f"{path}/open")
            session = None
            if reply.body:
                with suppress(XmlError):
                    session = session_id(reply.xml())
            data_path = f"{path}/audioData" + (f"?sessionId={session}" if session else "")
            self._upload = await self.link.open_upload(data_path)
        except HikvisionError as err:
            _LOGGER.debug("Two-way audio did not open on %s: %r", self.link.endpoint.host, err)
            with suppress(HikvisionError):
                await self.link.call("PUT", f"{path}/close")
            raise TalkError("talk_failed") from err
        self._watch = asyncio.get_running_loop().create_task(self._watch_device())

    async def _watch_device(self) -> None:
        upload = self._upload
        if upload is None:
            return
        await upload.wait_closed_by_device()
        if not self._ended:
            _LOGGER.debug("%s ended the two-way audio", self.link.endpoint.host)
            await self.close(TalkEnd.DEVICE)

    def send(self, frame: bytes) -> None:
        """Pass a frame of sound on; frames the device cannot take yet are dropped."""
        if self._upload is None or self._ended:
            return
        if self._upload.write(frame):
            self.sent += len(frame)
        else:
            self.dropped += len(frame)

    async def close(self, reason: TalkEnd) -> None:
        """End the talk once: the socket, then the channel on the device."""
        if self._ended:
            return
        self._ended = True
        if self._upload is not None:
            self._upload.close()
        if self._watch is not None and self._watch is not asyncio.current_task():
            self._watch.cancel()
        with suppress(HikvisionError):
            await self.link.call("PUT", f"{self.channel.path}/close")
        _LOGGER.debug(
            "Two-way audio on %s ended (%s): %d bytes sent, %d dropped",
            self.link.endpoint.host,
            reason,
            self.sent,
            self.dropped,
        )
        self._on_end(reason)
