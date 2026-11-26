"""A Hikvision video door station over ISAPI: who it is, its doors, its picture and its speaker.

The calls of a door station are SIP (``aiohikvision.sip``); everything else a door station does
for its indoor station is here, on one authenticated link:

- what it is (model, serial, firmware), and which doors, inputs and speaker it has;
- opening a door (its lock relay);
- how loaded it is (CPU, open video sessions);
- its settings: image, volumes, how long each door stays open, its voice prompt;
- its picture: a snapshot, and the RTSP address of its stream (sound included);
- talking through its speaker outside a call (two-way audio). One talk at a time: a new one
  takes the speaker over, and the previous one ends as ``TalkEnd.REPLACED``.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from yarl import URL

from aiohikvision.isapi.model.discover import read_identity_only, read_stream
from aiohikvision.isapi.model.features import adjust, health, inputs, intercom, outputs
from aiohikvision.isapi.model.features import talk as two_way
from aiohikvision.isapi.model.features.image import ImageCapability, ImageSetting, ImageValue
from aiohikvision.isapi.model.features.inputs import Input
from aiohikvision.isapi.model.features.outputs import Output, OutputUse
from aiohikvision.isapi.model.features.talk import TalkChannel, TalkEnd, TalkError, TwoWayAudio
from aiohikvision.isapi.model.ids import seg
from aiohikvision.isapi.wire.faults import BridgeFault
from aiohikvision.isapi.wire.link import Endpoint, IsapiLink
from aiohikvision.isapi.wire.xmlview import XmlNode

if TYPE_CHECKING:
    import ssl

    import aiohttp

    from aiohikvision.isapi.model.inventory import Identity, StreamSpec

ADMIN_ACCESSES = "/ISAPI/Security/adminAccesses"
RTSP_PORT = 554
# The main stream of the camera of a door station; its sub stream is 102.
MAIN_STREAM = "101"
# The camera and the audio of a door station are its channel 1.
CAMERA_CHANNEL = "1"
# The setting sources of a door station: the image of its camera (one of ``adjust.SOURCES``,
# whose others belong to cameras and recorders: strobe, siren, park action, two-way audio
# volumes), and ``adjust.DOOR_STATION_SOURCES``.
SETTING_SOURCES = ("image", "audio", "door", "access")


class NotADoorStation(BridgeFault):
    """The device answers ISAPI, but it is no video door station."""

    translation_key = "not_door_station"


class NotALock(BridgeFault):
    """The output of the door drives no lock (a doorbell, or nothing): it cannot open."""

    translation_key = "not_a_lock"

    def __init__(self, door: int, use: OutputUse) -> None:
        super().__init__(f"the output of door {door} drives no lock: {use}")
        self.door = door
        self.use = use


@dataclass(frozen=True, slots=True)
class DoorStationInfo:
    """What a door station is and what it has."""

    identity: Identity
    # The doors its relays open (1 and 2 on a DS-KD8003), from its remote control capabilities.
    doors: tuple[int, ...]
    # Whether it answers /ISAPI/VideoIntercom/callStatus.
    call_status: bool
    # Its speaker, if it plays G.711 (the sound a browser sends).
    talk: TalkChannel | None
    rtsp_port: int = RTSP_PORT
    # What its outputs drive (the output of door N is output N); empty when it does not say.
    outputs: tuple[Output, ...] = ()
    # Its main stream (codec and size), when it says. Its pictures do not always have the
    # shape of this stream: a DS-KD8003 (V3.7.3) takes them 11:9 while it streams 16:9.
    stream: StreamSpec | None = None
    # What its inputs read (door contact, exit button); empty when it does not say.
    inputs: tuple[Input, ...] = ()

    def output_of(self, door: int) -> Output | None:
        """The output that drives a door, if the door station lists it."""
        return next((output for output in self.outputs if output.number == door), None)

    @property
    def locks(self) -> tuple[int, ...]:
        """The doors that open: those whose output drives a lock, or all when unknown."""
        return tuple(
            door
            for door in self.doors
            if (output := self.output_of(door)) is None or output.use is OutputUse.ELECTRIC_LOCK
        )


@dataclass(frozen=True, slots=True)
class DoorStationHealth:
    """How loaded a door station is; None where it does not say."""

    cpu_percent: int | None = None
    # Clients streaming its video (RTSP or HTTP); each one costs the door station CPU.
    video_sessions: int | None = None


@dataclass(frozen=True, slots=True)
class Setting:
    """A setting a door station offers: which one (``key``, of ``adjust.BY_KEY``), on which
    channel (the camera, or the number of a door), and its choices or range.
    """

    key: str
    channel: str
    capability: ImageCapability

    @property
    def spec(self) -> ImageSetting:
        """How the setting is read and written: its platform, its source, its unit."""
        return adjust.BY_KEY[self.key]

    @property
    def ref(self) -> tuple[str, str]:
        """The setting and its channel, as its value is found among the values."""
        return (self.key, self.channel)


def rtsp_port(accesses: XmlNode | None) -> int:
    """The RTSP port among the access protocols (enabled unless said otherwise)."""
    if accesses is None:
        return RTSP_PORT
    for node in accesses.children("AdminAccessProtocol"):
        if (node.text("protocol") or "").upper() == "RTSP" and node.flag("enabled", True):
            return node.numeric("portNo") or RTSP_PORT
    return RTSP_PORT


class DoorStation:
    """One door station, reached over ISAPI."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        username: str,
        password: str,
        *,
        port: int = 80,
        https: bool = False,
        trusted: bool = False,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        """``trusted``: the credentials are stored ones that already worked (not a new login)."""
        self.link = IsapiLink(
            session,
            Endpoint(host, port, "https" if https else "http"),
            username,
            password,
            trusted=trusted,
            ssl_context=ssl_context,
        )
        self._username = username
        self._password = password
        self.info: DoorStationInfo | None = None
        self._talk: TwoWayAudio | None = None
        self._talk_lock = asyncio.Lock()

    @property
    def host(self) -> str:
        return self.link.endpoint.host

    async def read_info(self) -> DoorStationInfo:
        """Ask the device what it is; refuse a device that is no door station."""
        identity = await read_identity_only(self.link)
        capabilities = await intercom.read_capabilities(self.link)
        if capabilities is None and (identity.device_type or "").upper() != "VIS":
            raise NotADoorStation(f"{identity.model} is no video intercom")
        accesses = await self.link.read_xml(ADMIN_ACCESSES, optional=True)
        self.info = DoorStationInfo(
            identity=identity,
            doors=capabilities.doors if capabilities else (),
            call_status=bool(capabilities and capabilities.has_call_status),
            talk=await two_way.read(self.link),
            rtsp_port=rtsp_port(accesses),
            outputs=await outputs.read_outputs(self.link),
            stream=await read_stream(self.link, MAIN_STREAM),
            inputs=await inputs.read_inputs(self.link),
        )
        return self.info

    async def read_outputs(self) -> tuple[Output, ...]:
        """Read again what the outputs drive: its web page can change it at any time.

        Also proves the device answers, as ``check`` does (it raises the same faults).
        """
        read = await outputs.read_outputs(self.link)
        if self.info is not None:
            self.info = replace(self.info, outputs=read)
        return read

    async def read_inputs(self) -> tuple[Input, ...]:
        """Read again what the inputs read: its web page can change it at any time."""
        read = await inputs.read_inputs(self.link)
        if self.info is not None:
            self.info = replace(self.info, inputs=read)
        return read

    async def read_health(self) -> DoorStationHealth:
        """How loaded the door station is now: its CPU, and how many clients stream from it.

        Its memory is left out: cameras report it on a scale nobody documents.
        """
        status = await health.read_status(self.link, memory_in_mb=False)
        return DoorStationHealth(
            cpu_percent=status.cpu_percent if status is not None else None,
            video_sessions=await health.read_session_count(self.link),
        )

    def _setting_channels(self, source: str) -> tuple[str, ...]:
        """The channels a source has here: each door for the doors, the camera otherwise."""
        if source == "door":
            doors = self.info.doors if self.info is not None and self.info.doors else (1,)
            return tuple(str(door) for door in doors)
        return (CAMERA_CHANNEL,)

    async def read_settings(self) -> tuple[Setting, ...]:
        """The settings the door station offers, from its capabilities (read once: they do not
        change while it runs).
        """
        found: list[Setting] = []
        for source in SETTING_SOURCES:
            for channel in self._setting_channels(source):
                offered = await adjust.source_of(source).read_capabilities(self.link, channel)
                found.extend(Setting(key, channel, capability) for key, capability in offered.items())
        return tuple(found)

    async def read_setting_values(self, settings: tuple[Setting, ...]) -> dict[tuple[str, str], ImageValue]:
        """The values of these settings now, by ``Setting.ref``; one the device did not
        answer is left out.
        """
        wanted: dict[tuple[str, str], set[str]] = {}
        for setting in settings:
            wanted.setdefault((setting.spec.source, setting.channel), set()).add(setting.key)
        values: dict[tuple[str, str], ImageValue] = {}
        for (source, channel), keys in wanted.items():
            read = await adjust.source_of(source).read_values(self.link, channel, keys)
            for key, value in (read or {}).items():
                values[(key, channel)] = value
        return values

    async def write_setting(self, setting: Setting, field: str, value: str) -> None:
        """Change a setting (``field`` is the element its value was read from) and read it
        back: a value the device does not keep raises ``VerifyMismatch``.
        """
        await adjust.write(self.link, setting.channel, setting.key, field, value)

    async def check(self) -> None:
        """Ask the device who it is, the lightest request: it raises when the device does not
        answer (``Unreachable``) or refuses the account (``BadCredentials``, ``LockedOut``).
        """
        await read_identity_only(self.link)

    async def open_door(self, door: int = 1) -> None:
        """Pulse the lock relay of a door; a door whose output drives no lock raises NotALock."""
        output = self.info.output_of(door) if self.info else None
        if output is not None and output.use is not OutputUse.ELECTRIC_LOCK:
            raise NotALock(door, output.use)
        await intercom.remote_open_door(self.link, door)

    async def call_status(self) -> str | None:
        """idle, ringing or on_call; None if the device does not say."""
        return await intercom.read_call_status(self.link)

    async def snapshot(self, stream: str = MAIN_STREAM) -> bytes:
        """A JPEG of the camera now."""
        reply = await self.link.read_bytes(f"/ISAPI/Streaming/channels/{seg(stream)}/picture")
        return reply.body

    def rtsp_url(self, stream: str = MAIN_STREAM) -> str:
        """The RTSP address of a stream, with the credentials in it (keep it out of logs)."""
        port = self.info.rtsp_port if self.info is not None else RTSP_PORT
        return str(
            URL.build(
                scheme="rtsp",
                user=self._username,
                password=self._password,
                host=self.host,
                port=port,
                path=f"/Streaming/Channels/{seg(stream)}",
            )
        )

    @property
    def talking(self) -> TwoWayAudio | None:
        """The open talk, if any."""
        return self._talk

    async def talk(self, on_end: Callable[[TalkEnd], None]) -> TwoWayAudio:
        """Open the speaker, ending the talk already there; ``on_end`` hears why it ended."""
        channel = self.info.talk if self.info is not None else None
        if channel is None:
            raise TalkError("no_talk")
        async with self._talk_lock:
            if self._talk is not None:
                await self._talk.close(TalkEnd.REPLACED)

            def ended(reason: TalkEnd) -> None:
                if self._talk is session:
                    self._talk = None
                on_end(reason)

            session = TwoWayAudio(self.link, channel, ended)
            await session.open()
            self._talk = session
            return session

    async def close(self) -> None:
        """End the talk, if one is open: its owner went away."""
        if self._talk is not None:
            with contextlib.suppress(BridgeFault):
                await self._talk.close(TalkEnd.UNLOADED)
