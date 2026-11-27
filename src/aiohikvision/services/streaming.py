"""The streams of a device: what each one carries, its picture, and its RTSP address."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from yarl import URL

from aiohikvision.isapi.model.features.health import read_session_count
from aiohikvision.isapi.wire.faults import DeviceRejected
from aiohikvision.models.streaming import Stream, StreamId
from aiohikvision.parsers.streaming import STREAMING_CHANNELS, parse_rtsp_port, parse_streams

if TYPE_CHECKING:
    from aiohikvision.isapi.wire.link import IsapiLink

MAIN: Final = StreamId(1, 1)
"""The main stream of the first channel: the camera of a door station, or of a camera."""

JPEG_START: Final = b"\xff\xd8"
"""How a JPEG picture begins (its SOI marker): a device that fails may answer 200 with XML."""

ADMIN_ACCESSES: Final = "/ISAPI/Security/adminAccesses"
"""The protocols a device is reached by, with their ports (RTSP among them)."""


class Streaming:
    """The streams of a device."""

    def __init__(self, link: IsapiLink) -> None:
        """Talk to the device through its link."""
        self.link = link
        self._rtsp_port: int | None = None

    async def streams(self) -> tuple[Stream, ...]:
        """Return the enabled streams of every channel, in order of id."""
        return parse_streams(await self.link.read_xml(STREAMING_CHANNELS, optional=True))

    async def stream(self, stream: StreamId | str) -> Stream | None:
        """Return one stream; None when it is off or the device does not describe it."""
        path = f"{STREAMING_CHANNELS}/{_id(stream).isapi}"
        return next(iter(parse_streams(await self.link.read_xml(path, optional=True))), None)

    async def snapshot(
        self, stream: StreamId | str = MAIN, *, width: int | None = None, height: int | None = None
    ) -> bytes:
        """Return a JPEG of a stream now, at a size of its own unless asked for one."""
        path = f"{STREAMING_CHANNELS}/{_id(stream).isapi}/picture"
        if width and height:
            path += f"?videoResolutionWidth={width}&videoResolutionHeight={height}"
        reply = await self.link.read_bytes(path)
        if not reply.body.startswith(JPEG_START):
            msg = "the device sent no picture"
            raise DeviceRejected(msg, reply.status)
        return reply.body

    async def rtsp_port(self) -> int:
        """Return the RTSP port of the device (554 unless it says another), read once."""
        if self._rtsp_port is None:
            self._rtsp_port = parse_rtsp_port(await self.link.read_xml(ADMIN_ACCESSES, optional=True))
        return self._rtsp_port

    async def rtsp_url(self, stream: StreamId | str = MAIN, *, credentials: bool = True) -> str:
        """Return the RTSP address of a stream, its sound with it.

        With ``credentials`` (the default) the account is in the address, as players need it:
        keep that address out of logs.
        """
        username, password = self.link.credentials if credentials else (None, None)
        return str(
            URL.build(
                scheme="rtsp",
                user=username,
                password=password,
                host=self.link.endpoint.host,
                port=await self.rtsp_port(),
                path=f"/Streaming/Channels/{_id(stream).isapi}",
            )
        )

    async def sessions(self) -> int | None:
        """Return how many clients stream from the device now; None when it does not say.

        A door station serves a few RTSP sessions at a time: each player of each stream is one.
        """
        return await read_session_count(self.link)


def _id(stream: StreamId | str) -> StreamId:
    return stream if isinstance(stream, StreamId) else StreamId.parse(stream)
