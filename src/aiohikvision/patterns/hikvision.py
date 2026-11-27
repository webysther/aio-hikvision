"""A Hikvision device as an integration sees it: who it is, what it supports, its cameras.

::

    async with aiohikvision.connect("192.0.2.10", "admin", "password") as hik:
        print(hik.name, hik.model, hik.firmware, hik.kind, hik.supports)
        jpeg = await hik.camera.snapshot()
        url = await hik.camera.stream_url()

What a device is and has is read once, when it connects, and answered by attributes; only
the verbs (``snapshot()``, ``stream_url()``, ``report()``, ``check()``) ask the device. Level 2
stays one step away: ``hik.device``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Self

from aiohikvision.client import HikvisionClient
from aiohikvision.models._coded import CodedEnum, coded
from aiohikvision.models.capabilities import Capabilities, Domain, Support
from aiohikvision.models.streaming import Stream, StreamId, StreamKind
from aiohikvision.patterns.events import EventMonitor

if TYPE_CHECKING:
    import ssl
    from collections.abc import Generator, Iterable
    from types import TracebackType

    import aiohttp

    from aiohikvision.behaviours import BehaviourPatch
    from aiohikvision.behaviours.rules import Rule
    from aiohikvision.device import Device
    from aiohikvision.report import CapabilityReport
    from aiohikvision.services.streaming import Streaming

_RECORDER_TYPES = ("nvr", "dvr", "hvr", "dvs", "recorder")
"""Words of the ``deviceType`` of recorders (NVR, DVR, HybirdNVR as some write it…)."""


@coded(CAMERA=1, RECORDER=2, DOOR_STATION=3, OTHER=4)
class Kind(CodedEnum):
    """What a device is."""

    CAMERA = "camera"
    RECORDER = "recorder"
    DOOR_STATION = "door_station"
    OTHER = "other"

    @classmethod
    def of(cls, device_type: str | None, capabilities: Capabilities) -> Kind:
        """Return what a device is, from its ``deviceType`` and, when it says little, its domains."""
        written = (device_type or "").lower()
        if written == "vis" or capabilities.support(Domain.VIDEO_INTERCOM) is Support.PRESENT:
            return cls.DOOR_STATION
        if any(word in written for word in _RECORDER_TYPES):
            return cls.RECORDER
        if (
            "camera" in written
            or "dome" in written
            or capabilities.support(Domain.STREAMING) is Support.PRESENT
        ):
            return cls.CAMERA
        return cls.OTHER


def _known(support: Support) -> bool | None:
    return None if support is Support.UNKNOWN else support is Support.PRESENT


@dataclass(frozen=True, slots=True)
class Supports:
    """What a device supports, in short; None where it does not say."""

    snapshot: bool | None
    streaming: bool | None
    events: bool | None
    smart: bool | None
    ptz: bool | None
    two_way_audio: bool | None
    intercom: bool | None
    doors: bool | None
    holidays: bool | None
    inputs: int | None
    """Alarm inputs."""
    outputs: int | None
    """Relay outputs."""

    @classmethod
    def of(cls, capabilities: Capabilities) -> Supports:
        """Return what the capabilities of a device show."""
        tree = capabilities.tree
        return cls(
            snapshot=_known(tree.flag("isSupportSnapshot")),
            streaming=_known(capabilities.support(Domain.STREAMING)),
            events=_known(capabilities.support(Domain.EVENTS)),
            smart=_known(capabilities.support(Domain.SMART)),
            ptz=_known(capabilities.support(Domain.PTZ)),
            two_way_audio=_known(capabilities.support(Domain.TWO_WAY_AUDIO)),
            intercom=_known(capabilities.support(Domain.VIDEO_INTERCOM)),
            doors=_known(capabilities.support(Domain.ACCESS_CONTROL)),
            holidays=_known(capabilities.support(Domain.HOLIDAYS)),
            inputs=tree.count("IOInputPortNums"),
            outputs=tree.count("IOOutputPortNums"),
        )


class Camera:
    """A camera of a device: a video channel and its streams.

    A camera or a door station has one; a recorder has one per channel.
    """

    def __init__(self, streaming: Streaming, channel: int, streams: tuple[Stream, ...]) -> None:
        """Make the camera of a channel, with the streams the device listed for it."""
        self.streaming = streaming
        self.channel = channel
        self.streams = streams
        self.name = next((stream.name for stream in streams if stream.name), None)
        """The name the device gives the channel, when it gives one."""

    @property
    def main(self) -> Stream | None:
        """Return the main stream, when the device listed it."""
        return self._of(StreamKind.MAIN)

    @property
    def sub(self) -> Stream | None:
        """Return the sub stream, lighter to play, when the device listed it."""
        return self._of(StreamKind.SUB)

    def _of(self, kind: StreamKind) -> Stream | None:
        return next((stream for stream in self.streams if stream.kind is kind), None)

    def _id(self, stream: StreamKind | StreamId) -> StreamId:
        if isinstance(stream, StreamId):
            return stream
        listed = self._of(stream)
        index = {StreamKind.MAIN: 1, StreamKind.SUB: 2, StreamKind.THIRD: 3}.get(stream, 1)
        return listed.id if listed else StreamId(self.channel, index)

    async def snapshot(self, stream: StreamKind | StreamId = StreamKind.MAIN) -> bytes:
        """Return a JPEG of the camera now, of its main stream unless told another."""
        return await self.streaming.snapshot(self._id(stream))

    async def stream_url(
        self, stream: StreamKind | StreamId = StreamKind.MAIN, *, credentials: bool = True
    ) -> str:
        """Return the RTSP address of the camera, its main stream unless told another.

        With ``credentials`` (the default) the account is in the address: keep it out of logs.
        """
        return await self.streaming.rtsp_url(self._id(stream), credentials=credentials)

    def __repr__(self) -> str:
        """Show the channel and its streams."""
        listed = ", ".join(stream.id.isapi for stream in self.streams) or "no streams listed"
        return f"<Camera {self.channel}: {listed}>"


class Hikvision:
    """A Hikvision device: who it is, what it supports, its cameras; ``device`` is level 2."""

    def __init__(
        self,
        device: Device,
        cameras: tuple[Camera, ...],
        events: EventMonitor | None = None,
        client: HikvisionClient | None = None,
    ) -> None:
        """Make the device of what was read from it; :func:`connect` reads it."""
        self.device = device
        self.cameras = cameras
        self.events = events
        """Its events; None when the device has none."""
        self._client = client
        identity = device.identity
        self.id = identity.stable_id
        self.name = identity.name
        self.model = identity.model
        self.serial = identity.serial
        self.firmware = identity.firmware
        self.kind = Kind.of(identity.device_type, device.capabilities)
        self.supports = Supports.of(device.capabilities)

    @classmethod
    async def from_device(cls, device: Device, client: HikvisionClient | None = None) -> Self:
        """Read the cameras (its streams, by channel) and the events of a device (level 2)."""
        events = None if device.events is None else EventMonitor(device.events, await device.events.sources())
        return cls(device, await _cameras(device.streaming), events, client)

    @property
    def camera(self) -> Camera | None:
        """Return the first camera: the camera of a camera or of a door station."""
        return self.cameras[0] if self.cameras else None

    async def report(self) -> CapabilityReport:
        """Return what the device is and answers, anonymized, to send to aiohikvision."""
        return await self.device.report()

    async def check(self) -> None:
        """Ask the device who it is: raises the fault of a device that is down or refuses us."""
        await self.device.check()

    async def close(self) -> None:
        """Close the session :func:`connect` opened; a session it was given stays open."""
        if self._client is not None:
            await self._client.close()

    async def __aenter__(self) -> Self:
        """Use the device in ``async with``."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the session :func:`connect` opened."""
        await self.close()

    def __repr__(self) -> str:
        """Show what the device is."""
        return f"<Hikvision {self.kind} {self.model} {self.firmware}>"


async def _cameras(streaming: Streaming | None) -> tuple[Camera, ...]:
    if streaming is None:
        return ()
    streams = await streaming.streams()
    channels = sorted({stream.id.channel for stream in streams}) or [1]
    return tuple(
        Camera(streaming, channel, tuple(stream for stream in streams if stream.id.channel == channel))
        for channel in channels
    )


class Connecting:
    """The connection :func:`connect` makes: awaited, or used in ``async with``."""

    def __init__(
        self, client: HikvisionClient, host: str, username: str, password: str, options: dict[str, Any]
    ) -> None:
        """Hold what to connect to."""
        self._client = client
        self._args = (host, username, password)
        self._options = options

    async def _connect(self) -> Hikvision:
        try:
            device = await self._client.connect(*self._args, **self._options)
            return await Hikvision.from_device(device, self._client)
        except BaseException:
            await self._client.close()
            raise

    def __await__(self) -> Generator[Any, None, Hikvision]:
        """Connect: ``hik = await aiohikvision.connect(...)`` (then ``await hik.close()``)."""
        return self._connect().__await__()

    async def __aenter__(self) -> Hikvision:
        """Connect for an ``async with`` block."""
        return await self._connect()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the session the connection opened (a session it was given stays open)."""
        await self._client.close()


def connect(
    host: str,
    username: str,
    password: str,
    *,
    session: aiohttp.ClientSession | None = None,
    port: int | None = None,
    https: bool = False,
    ssl_context: ssl.SSLContext | None = None,
    trusted: bool = False,
    rules: Iterable[Rule] = (),
    overrides: BehaviourPatch | None = None,
) -> Connecting:
    """Connect to a Hikvision device; use it with ``async with``, or await it.

    It reads, once and with GET only, who the device is, what it supports and its cameras.
    Give it your application's ``session``; without one it opens its own, closed with the
    device. ``rules`` and ``overrides`` change how devices behave (``aiohikvision.behaviours``).
    """
    client = HikvisionClient(session, rules=rules, overrides=overrides)
    options = {"port": port, "https": https, "ssl_context": ssl_context, "trusted": trusted}
    return Connecting(client, host, username, password, options)
