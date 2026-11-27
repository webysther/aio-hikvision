"""Reader for the device event stream (multipart alert stream)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import time
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any

from aiohikvision.errors import HikvisionError
from aiohikvision.isapi.wire.faults import BadCredentials, LockedOut, Unsupported, detail
from aiohikvision.isapi.wire.link import IsapiLink
from aiohikvision.isapi.wire.scrub import scrubbed_logger
from aiohikvision.isapi.wire.xmlview import XmlError, XmlNode, decode, parse

_LOGGER = scrubbed_logger(__name__)

STREAM_PATH = "/ISAPI/Event/notification/alertStream"
MAX_PART_BYTES = 2 * 1024 * 1024
SILENCE_LIMIT = 60.0
BACKOFF_FIRST = 5.0
BACKOFF_MAX = 300.0
# A connection that ends sooner than this (seconds) without delivering anything is no sign of
# a working stream, so it does not reset the backoff (hikvision_bridge #84).
QUICK_CLOSE = 5.0
# Connections in a row that answer 200 without a multipart body and deliver nothing: some door
# stations answer so (a bare XML declaration, then a closed connection) instead of a 404.
# After this many the stream counts as unsupported.
BARE_LIMIT = 3
# How often (seconds) a stream that counts as unsupported is tried again, in case its firmware
# changes; the device is polled meanwhile.
UNSUPPORTED_RETRY = 3600.0
# ``FeedStats.last_error`` of those two cases.
NO_STREAM = "no event stream: 200 without a multipart body"
QUICK_CLOSE_ERROR = "stream closed right after connecting"
BACKLOG_TOLERANCE = timedelta(seconds=5)
# Devices replay their backlog right after connecting. Without heartbeats the device clock is
# unknown, so a frame arriving later than this into a connection is taken as live.
REPLAY_WINDOW = 3.0
# How long a frame waits for the pictures it announces (ANPR sends plate and scene pictures).
PICTURE_WAIT = 2.0
# Values plate cameras report when they saw a vehicle but could not read its plate.
_NO_PLATE = {"", "unknown", "noplate", "none", "无车牌"}  # last: "no plate" (zh)


@dataclass(slots=True)
class Part:
    headers: dict[str, str]
    body: bytes

    @property
    def content_type(self) -> str:
        return self.headers.get("content-type", "").split(";")[0].strip().lower()

    @property
    def name(self) -> str | None:
        """File name of a picture part (``licensePlatePicture.jpg``), if the device sends one."""
        disposition = self.headers.get("content-disposition", "")
        for key in ("filename", "name"):
            match = re.search(rf'(?:^|;)\s*{key}="?([^";]+)"?', disposition, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip()
        content_id = self.headers.get("content-id", "").strip("<> ")
        return content_id or None


class MultipartSplitter:
    """Incrementally cuts a multipart byte stream into parts.

    Uses ``Content-Length`` when present and the boundary otherwise. Oversized parts are
    skipped without ending the stream.
    """

    def __init__(self, boundary: str | None) -> None:
        self._boundary = ("--" + boundary.strip('"')).encode() if boundary else None
        self._buffer = bytearray()
        self._skip = 0

    def push(self, chunk: bytes) -> Iterator[Part]:
        self._buffer.extend(chunk)
        while True:
            if self._skip:
                dropped = min(self._skip, len(self._buffer))
                del self._buffer[:dropped]
                self._skip -= dropped
                if self._skip:
                    return
            part = self._next()
            if part is None:
                return
            yield part

    def _boundary_at_start(self) -> int | None:
        """Strip leading blank lines and a boundary line; return header start or None."""
        buf = self._buffer
        while buf[:2] == b"\r\n" or buf[:1] == b"\n":
            del buf[: 2 if buf[:2] == b"\r\n" else 1]
        if not buf.startswith(b"--"):
            # Some firmwares omit the boundary before the first headers.
            return 0 if re.match(rb"[A-Za-z-]+:", bytes(buf[:40])) else None
        line_end = buf.find(b"\n")
        if line_end == -1:
            return None
        return line_end + 1

    def _drop_if_oversized(self, start: int) -> None:
        """Give up on an unfinished part that outgrew the cap and resync to the next boundary."""
        if len(self._buffer) - start <= MAX_PART_BYTES:
            return
        nxt = self._buffer.find(self._boundary, 1) if self._boundary else -1
        del self._buffer[: nxt if nxt != -1 else len(self._buffer)]
        return

    def _next(self) -> Part | None:
        start = self._boundary_at_start()
        if start is None:
            if len(self._buffer) > MAX_PART_BYTES:
                self._buffer.clear()
            return None
        header_end = self._buffer.find(b"\r\n\r\n", start)
        sep = 4
        if header_end == -1:
            header_end = self._buffer.find(b"\n\n", start)
            sep = 2
        if header_end == -1:
            self._drop_if_oversized(start)
            return None
        headers: dict[str, str] = {}
        for line in decode(bytes(self._buffer[start:header_end])).splitlines():
            key, _, value = line.partition(":")
            if value:
                headers[key.strip().lower()] = value.strip()
        body_start = header_end + sep
        length = headers.get("content-length")
        if length and length.isdigit():
            size = int(length)
            if size > MAX_PART_BYTES:
                available = len(self._buffer) - body_start
                del self._buffer[:body_start]
                self._skip = size - min(size, available)
                del self._buffer[: min(size, available)]
                return Part(headers, b"")
            if len(self._buffer) - body_start < size:
                return None
            body = bytes(self._buffer[body_start : body_start + size])
            del self._buffer[: body_start + size]
            return Part(headers, body)
        if self._boundary is None:
            self._drop_if_oversized(body_start)
            return None
        end = self._buffer.find(self._boundary, body_start)
        if end == -1:
            self._drop_if_oversized(body_start)
            return None
        body = bytes(self._buffer[body_start:end]).rstrip(b"\r\n")
        del self._buffer[:end]
        return Part(headers, body)


@dataclass(frozen=True, slots=True)
class PlateRead:
    """What a licence plate (ANPR) camera read for one vehicle."""

    number: str | None
    country: str | None = None
    direction: str | None = None
    confidence: int | None = None
    plate_type: str | None = None
    plate_color: str | None = None
    vehicle_type: str | None = None
    vehicle_color: str | None = None
    list_name: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "plate": self.number,
            "country": self.country,
            "direction": self.direction,
            "confidence": self.confidence,
            "plate_type": self.plate_type,
            "plate_color": self.plate_color,
            "vehicle_type": self.vehicle_type,
            "vehicle_color": self.vehicle_color,
            "list": self.list_name,
        }


def _plate_number(raw: Any) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    return None if text.lower() in _NO_PLATE else text


def _list_name(raw: Any) -> str | None:
    """AllowList / blockList / otherList (older firmware: whiteList / blackList)."""
    if raw in (None, ""):
        return None
    text = str(raw).strip().lower().removesuffix("list")
    return {"white": "allow", "black": "block"}.get(text, text) or None


def _to_int(raw: Any) -> int | None:
    try:
        return int(float(str(raw)))
    except (TypeError, ValueError):
        return None


def picture_slot(name: str | None) -> str:
    """Which picture a part is: the plate crop or the full scene."""
    return "plate" if name and "plate" in name.lower() else "scene"


@dataclass(slots=True)
class FeedFrame:
    """One normalised notification from a device."""

    raw_type: str
    state: str
    channel_id: str | None = None
    port_id: str | None = None
    device_time: datetime | None = None
    received: datetime = field(default_factory=lambda: datetime.now(UTC))
    targets: tuple[str, ...] = ()
    region_id: str | None = None
    description: str | None = None
    channel_name: str | None = None
    mac: str | None = None
    picture: bytes | None = None
    pictures: dict[str, bytes] = field(default_factory=dict)  # by picture_slot
    pictures_expected: int = 0
    pictures_received: int = 0
    plate: PlateRead | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def add_picture(self, data: bytes, name: str | None) -> None:
        if self.picture is None:
            self.picture = data
        self.pictures.setdefault(picture_slot(name), data)
        self.pictures_received += 1

    @property
    def pictures_complete(self) -> bool:
        """True once every announced picture arrived (at least one when none are announced)."""
        return self.pictures_received >= max(self.pictures_expected, 1)

    @property
    def is_active(self) -> bool:
        return self.state == "active"

    @property
    def heartbeat(self) -> bool:
        """Devices send inactive video-loss notices as keep-alive."""
        return self.raw_type.lower() == "videoloss" and not self.is_active


def _device_clock(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _non_empty(value: str | None) -> str | None:
    return value if value not in (None, "") else None


def _is_duration(raw_type: str) -> bool:
    """Duration alerts name the actual event in DurationList/Duration/relationEvent."""
    return raw_type.strip().lower() == "duration"


def _plate_from_xml(node: XmlNode) -> PlateRead | None:
    """Read the ``ANPR`` block of a plate notification (``vehicleInfo`` holds the vehicle)."""
    anpr = next(node.walk("ANPR"), None)
    if anpr is None:
        return None
    vehicle = anpr.first("vehicleInfo")
    return PlateRead(
        number=_plate_number(anpr.text("licensePlate") or anpr.text("originalLicensePlate")),
        country=anpr.text("country"),
        direction=anpr.text("direction"),
        confidence=anpr.numeric("confidenceLevel"),
        plate_type=anpr.text("plateType"),
        plate_color=anpr.text("plateColor"),
        vehicle_type=anpr.text("vehicleType") or (vehicle.text("vehicleType") if vehicle else None),
        vehicle_color=vehicle.text("color") if vehicle else None,
        list_name=_list_name(anpr.text("vehicleListName")),
    )


def frame_from_xml(node: XmlNode) -> FeedFrame | None:
    raw_type = node.text("eventType")
    if not raw_type:
        major = node.numeric("majorEventType")
        sub = node.numeric("subEventType")
        if major == 5 and sub in (37, 38):
            raw_type = "doorbell"
    if not raw_type:
        return None
    extra: dict[str, Any] = {"active_count": node.numeric("activePostCount")}
    if _is_duration(raw_type):
        related = next((n.value for n in node.walk("relationEvent") if n.value), None)
        if related:
            raw_type, extra["via"] = related, raw_type
    targets: list[str] = []
    for name in ("detectionTarget", "targetType", "TargetType"):
        for found in node.walk(name):
            if found.value:
                targets.extend(t.strip().lower() for t in found.value.split(",") if t.strip())
    region = next((n.value for n in node.walk("regionID") if n.value), None)
    port = (
        node.text("inputIOPortID")
        or node.text("dynInputIOPortID")
        or node.text("IOPortID")
        or next((n.value for n in node.walk("inputIOPortID") if n.value), None)
    )
    channel = _non_empty(node.text("channelID")) or _non_empty(node.text("dynChannelID"))
    announced = sum(1 for _ in node.walk("pictureInfo")) or node.numeric("picNum") or 0
    return FeedFrame(
        raw_type=raw_type,
        state=(node.text("eventState") or "active").lower(),
        channel_id=channel,
        port_id=_non_empty(port),
        device_time=_device_clock(node.text("dateTime")),
        targets=tuple(dict.fromkeys(targets)),
        region_id=region,
        description=node.text("eventDescription"),
        channel_name=node.text("channelName"),
        mac=node.text("macAddress"),
        pictures_expected=announced,
        plate=_plate_from_xml(node),
        extra=extra,
    )


def _json_find(data: Any, key: str) -> Any:
    wanted = key.lower()
    if isinstance(data, dict):
        for k, v in data.items():
            if k.lower() == wanted:
                return v
        for v in data.values():
            found = _json_find(v, key)
            if found is not None:
                return found
    elif isinstance(data, list):
        for item in data:
            found = _json_find(item, key)
            if found is not None:
                return found
    return None


def _json_text(data: Any, key: str) -> str | None:
    value = _json_find(data, key)
    return None if value in (None, "") or isinstance(value, dict | list) else str(value)


def _plate_from_json(data: Any) -> PlateRead | None:
    anpr = _json_find(data, "ANPR")
    if not isinstance(anpr, dict):
        return None
    vehicle = _json_find(anpr, "vehicleInfo")
    vehicle = vehicle if isinstance(vehicle, dict) else {}
    return PlateRead(
        number=_plate_number(_json_find(anpr, "licensePlate") or _json_find(anpr, "originalLicensePlate")),
        country=_json_text(anpr, "country"),
        direction=_json_text(anpr, "direction"),
        confidence=_to_int(_json_find(anpr, "confidenceLevel")),
        plate_type=_json_text(anpr, "plateType"),
        plate_color=_json_text(anpr, "plateColor"),
        vehicle_type=_json_text(anpr, "vehicleType") or _json_text(vehicle, "vehicleType"),
        vehicle_color=_json_text(vehicle, "color"),
        list_name=_list_name(_json_find(anpr, "vehicleListName")),
    )


def frame_from_json(data: Any) -> FeedFrame | None:
    if not isinstance(data, dict):
        return None
    raw_type = _json_find(data, "eventType")
    if not raw_type:
        major = _json_find(data, "majorEventType")
        sub = _json_find(data, "subEventType")
        if major in (5, "5") and sub in (37, "37", 38, "38"):
            raw_type = "doorbell"
    if not raw_type:
        return None
    extra: dict[str, Any] = {}
    if _is_duration(str(raw_type)) and (related := _json_find(data, "relationEvent")):
        raw_type, extra["via"] = related, str(raw_type)
    channel = _json_find(data, "channelID") or _json_find(data, "dynChannelID")
    target = _json_find(data, "targetType") or _json_find(data, "detectionTarget")
    targets = tuple(t.strip().lower() for t in str(target).split(",")) if target else ()
    port = _json_find(data, "inputIOPortID") or _json_find(data, "ioPortID")
    region = _json_find(data, "regionID")
    return FeedFrame(
        raw_type=str(raw_type),
        state=str(_json_find(data, "eventState") or "active").lower(),
        channel_id=str(channel) if channel not in (None, "") else None,
        port_id=str(port) if port not in (None, "") else None,
        device_time=_device_clock(_json_find(data, "dateTime")),
        targets=targets,
        region_id=str(region) if region not in (None, "") else None,
        description=_json_find(data, "eventDescription"),
        channel_name=_json_find(data, "channelName"),
        mac=_json_find(data, "macAddress"),
        pictures_expected=_to_int(_json_find(data, "picNum")) or 0,
        plate=_plate_from_json(data),
        extra=extra,
    )


def frame_from_part(part: Part) -> FeedFrame | bytes | None:
    """Turn a part into a frame, a picture (bytes) or nothing."""
    ctype = part.content_type
    if ctype.startswith("image/"):
        return part.body or None
    text = decode(part.body).strip()
    if not text:
        return None
    if "json" in ctype or text.startswith("{"):
        try:
            return frame_from_json(json.loads(text))
        except ValueError:
            return None
    try:
        return frame_from_xml(parse(text))
    except XmlError:
        _LOGGER.debug("Skipping unparsable event part (%d bytes)", len(part.body))
        return None


def boundary_of(content_type: str) -> str | None:
    match = re.search(r'boundary="?([^";]+)"?', content_type, flags=re.IGNORECASE)
    return match.group(1) if match else None


FrameHandler = Callable[[FeedFrame], None]
StateHandler = Callable[[bool, HikvisionError | None], Awaitable[None] | None]


@dataclass(slots=True)
class FeedStats:
    connects: int = 0
    frames: int = 0
    heartbeats: int = 0
    backlog_dropped: int = 0
    pictures: int = 0
    last_frame: float | None = None
    connected_since: datetime | None = None
    last_error: str | None = None


PROBE_TIMEOUT = 15.0


async def stream_missing(link: IsapiLink, path: str = STREAM_PATH) -> bool:
    """True only when the firmware has no event stream at all (it answers 404).

    Busy, refused or silent streams count as present: the feed keeps retrying those.
    The wait is bounded, since the stream request has no read timeout and setup awaits it.
    """
    try:
        async with asyncio.timeout(PROBE_TIMEOUT), link.open_stream(path):
            return False
    except (BadCredentials, LockedOut):
        raise
    except Unsupported as err:
        return str(err).startswith("HTTP 404")
    except (HikvisionError, TimeoutError):
        return False


class SessionEnd(Enum):
    """Why a connection to the event stream ended without an error."""

    CLOSED = "closed"  # the device closed it
    QUIET = "quiet"  # nothing came for SILENCE_LIMIT


@dataclass(frozen=True, slots=True)
class Session:
    """What one connection to the event stream did: what the reconnect decision reads."""

    end: SessionEnd
    multipart: bool  # the answer named a multipart boundary
    frames: int  # frames delivered (backlog replays dropped are not)
    seconds: float  # from the answer to the end

    @property
    def bare(self) -> bool:
        """A 200 without a multipart body that delivered nothing: no event stream behind it."""
        return not self.multipart and not self.frames

    @property
    def worked(self) -> bool:
        """It showed a working stream: frames, a quiet device, or a connection that lasted."""
        return bool(self.frames) or self.end is SessionEnd.QUIET or self.seconds >= QUICK_CLOSE


class StreamBehaviour(Enum):
    """How the event stream of a device behaves, judged from its connections.

    Each is a behaviour measured on some devices or firmware, decided in one place
    (:class:`Reconnects`) instead of in the loop of the feed.
    """

    # Frames, or a connection that lasted: connect again after the first delay.
    LIVE = "live"
    # Nothing for SILENCE_LIMIT: door stations send no heartbeats. Reopened at once, and the
    # feed stays connected (a failing reconnect still reports the drop).
    QUIET = "quiet"
    # Closed at once with nothing in it: no sign of a working stream, the backoff keeps growing.
    QUICK_CLOSE = "quick_close"
    # 200 without a multipart body, then closed: door stations on some firmware answer so (a
    # bare XML declaration) instead of a 404 (hikvision_bridge #84). Backs off like QUICK_CLOSE.
    BARE = "bare"
    # BARE_LIMIT bare answers in a row: the device has no event stream. Reported as
    # Unsupported, tried again every UNSUPPORTED_RETRY.
    NO_STREAM = "no_stream"

    @property
    def error(self) -> str | None:
        """What it records in ``FeedStats.last_error``; None when it is no error."""
        return _BEHAVIOUR_ERRORS.get(self)


_BEHAVIOUR_ERRORS = {
    StreamBehaviour.QUICK_CLOSE: QUICK_CLOSE_ERROR,
    StreamBehaviour.BARE: NO_STREAM,
    StreamBehaviour.NO_STREAM: NO_STREAM,
}


@dataclass(frozen=True, slots=True)
class Retry:
    """The decision after a connection: how the stream behaves, and when to connect again."""

    behaviour: StreamBehaviour
    delay: float


class Reconnects:
    """When to connect again to an event stream, from what its connections did.

    Pure, without I/O: the feed tells it each session or failure and follows the answer. The
    delay starts at BACKOFF_FIRST and doubles up to BACKOFF_MAX until a connection works.
    """

    def __init__(self) -> None:
        self._delay = BACKOFF_FIRST
        self._bare_streak = 0

    def after(self, session: Session) -> Retry:
        """Judge a connection that ended without an error."""
        self._bare_streak = self._bare_streak + 1 if session.bare else 0
        if self._bare_streak >= BARE_LIMIT:
            return Retry(StreamBehaviour.NO_STREAM, UNSUPPORTED_RETRY)
        if session.worked:
            self._delay = BACKOFF_FIRST
        if session.end is SessionEnd.QUIET:
            return Retry(StreamBehaviour.QUIET, 0.0)
        if self._bare_streak:
            behaviour = StreamBehaviour.BARE
        elif session.worked:
            behaviour = StreamBehaviour.LIVE
        else:
            behaviour = StreamBehaviour.QUICK_CLOSE
        return Retry(behaviour, self._next_delay())

    def after_failure(self) -> float:
        """The delay after a connection that failed (refused, timed out, broken)."""
        return self._next_delay()

    def _next_delay(self) -> float:
        delay = self._delay
        self._delay = min(delay * 2, BACKOFF_MAX)
        return delay


class AlarmFeed:
    """Keeps the event stream of one device open and delivers frames."""

    def __init__(
        self,
        link: IsapiLink,
        on_frame: FrameHandler,
        on_state: StateHandler,
        path: str = STREAM_PATH,
    ) -> None:
        self._link = link
        self._on_frame = on_frame
        self._on_state = on_state
        self._path = path
        self._task: asyncio.Task[None] | None = None
        self._connected = False
        self._clock_offset = timedelta(0)
        # Where the offset came from: None (unknown), "heartbeat" or "event".
        self._offset_source: str | None = None
        self.stats = FeedStats()
        self._behaviour: StreamBehaviour | None = None

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def behaviour(self) -> StreamBehaviour | None:
        """How the stream behaved at its last connection; None before the first one ends."""
        return self._behaviour

    @property
    def clock_offset(self) -> timedelta:
        """Device clock minus local clock, learnt from heartbeats (or live events without)."""
        return self._clock_offset

    @property
    def clock_offset_source(self) -> str | None:
        return self._offset_source

    def start(self, create_task: Callable[..., asyncio.Task[None]]) -> None:
        if self._task is None:
            self._task = create_task(self.run(), f"aiohikvision feed {self._link.endpoint.host}")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await self._set_state(False, None)

    async def _set_state(self, connected: bool, fault: HikvisionError | None) -> None:
        if connected == self._connected and fault is None:
            return
        self._connected = connected
        result = self._on_state(connected, fault)
        if asyncio.iscoroutine(result):
            await result

    async def run(self) -> None:
        """Keep the stream open, reconnecting, until cancelled or the account is refused."""
        reconnects = Reconnects()
        while True:
            try:
                retry = reconnects.after(await self._session())
                await self._report(retry)
                delay = retry.delay
            except (BadCredentials, LockedOut) as err:
                self.stats.last_error = type(err).__name__
                await self._set_state(False, err)
                return
            except HikvisionError as err:
                delay = reconnects.after_failure()
                self.stats.last_error = type(err).__name__
                _LOGGER.debug(
                    "Event stream of %s failed: %s; retrying in %d s",
                    self._link.endpoint.host,
                    detail(err),
                    delay,
                )
                await self._set_state(False, err)
            except asyncio.CancelledError:
                raise
            except Exception as err:
                delay = reconnects.after_failure()
                self.stats.last_error = type(err).__name__
                _LOGGER.exception("Event stream of %s failed unexpectedly", self._link.endpoint.host)
                await self._set_state(False, None)
            await asyncio.sleep(delay)

    async def _report(self, retry: Retry) -> None:
        """Make known how the stream behaved: the state, the last error, a warning."""
        behaviour, previous = retry.behaviour, self._behaviour
        self._behaviour = behaviour
        if behaviour.error is not None:
            self.stats.last_error = behaviour.error
        if behaviour is StreamBehaviour.QUIET:
            return
        if behaviour is not StreamBehaviour.NO_STREAM:
            await self._set_state(False, None)
            return
        if previous is not StreamBehaviour.NO_STREAM:
            _LOGGER.warning(
                "%s answers the event stream request without events (%d times in a row); "
                "relying on polling, retrying every %g s",
                self._link.endpoint.host,
                BARE_LIMIT,
                UNSUPPORTED_RETRY,
            )
        await self._set_state(False, Unsupported(NO_STREAM))

    async def _session(self) -> Session:
        """Run one connection, and say what it did."""
        host = self._link.endpoint.host
        async with self._link.open_stream(self._path) as response:
            connected_at = datetime.now(UTC)
            self.stats.connects += 1
            self.stats.connected_since = connected_at
            content_type = response.headers.get("Content-Type", "")
            boundary = boundary_of(content_type)
            splitter = MultipartSplitter(boundary)
            frames_before = self.stats.frames
            _LOGGER.debug(
                "Event stream of %s connected (%s, %s)",
                host,
                content_type or "no content type",
                "multipart boundary" if boundary else "no multipart boundary",
            )
            await self._set_state(True, None)
            answered = time.monotonic()

            def ended(end: SessionEnd) -> Session:
                frames = self.stats.frames - frames_before
                return Session(end, boundary is not None, frames, time.monotonic() - answered)

            pending: FeedFrame | None = None
            pending_until = 0.0
            last_chunk = time.monotonic()
            while True:
                wait = SILENCE_LIMIT - (time.monotonic() - last_chunk)
                if pending is not None:
                    wait = min(wait, pending_until - time.monotonic())
                try:
                    async with asyncio.timeout(max(wait, 0.0)):
                        chunk = await response.content.readany()
                except TimeoutError:
                    if pending is not None:
                        # The announced pictures did not all arrive: deliver what came.
                        self._deliver(pending, connected_at)
                        pending = None
                        continue
                    _LOGGER.debug(
                        "Event stream of %s went silent after %d frame(s); reconnecting",
                        host,
                        self.stats.frames - frames_before,
                    )
                    return ended(SessionEnd.QUIET)
                if not chunk:
                    if pending is not None:
                        self._deliver(pending, connected_at)
                    _LOGGER.debug(
                        "Event stream of %s closed by the device after %d frame(s); reconnecting",
                        host,
                        self.stats.frames - frames_before,
                    )
                    return ended(SessionEnd.CLOSED)
                last_chunk = time.monotonic()
                for part in splitter.push(chunk):
                    item = frame_from_part(part)
                    if isinstance(item, bytes):
                        self.stats.pictures += 1
                        if pending is not None:
                            pending.add_picture(item, part.name)
                            if pending.pictures_complete:
                                self._deliver(pending, connected_at)
                                pending = None
                        continue
                    if pending is not None:
                        self._deliver(pending, connected_at)
                        pending = None
                    if item is None:
                        continue
                    self.stats.last_frame = time.monotonic()
                    if item.heartbeat:
                        self.stats.heartbeats += 1
                        if item.device_time is not None:
                            # Heartbeats are "now" on the device clock: track the offset.
                            self._clock_offset = item.device_time - item.received
                            self._offset_source = "heartbeat"
                        continue
                    # Hold the frame briefly: a picture part may follow it.
                    pending = item
                    pending_until = time.monotonic() + PICTURE_WAIT
                if (
                    pending is not None
                    and pending.pictures_received >= pending.pictures_expected
                    and splitter_idle(splitter)
                ):
                    self._deliver(pending, connected_at)
                    pending = None

    def _deliver(self, frame: FeedFrame, connected_at: datetime) -> None:
        host = self._link.endpoint.host
        if frame.device_time is not None:
            live = (
                self._offset_source != "heartbeat"
                and (frame.received - connected_at).total_seconds() > REPLAY_WINDOW
            )
            if live:
                # No heartbeats (door stations): the replay is over, so this frame is live and
                # shows the device clock. A clock behind Home Assistant no longer drops events.
                self._clock_offset = frame.device_time - frame.received
                self._offset_source = "event"
            # Events stamped before the connection existed are replays of a device backlog.
            local_time = frame.device_time - self._clock_offset
            if not live and local_time < connected_at - BACKLOG_TOLERANCE:
                self.stats.backlog_dropped += 1
                # Without heartbeats the clock offset stays unknown: a device clock behind
                # Home Assistant shows up here as every event being dropped.
                _LOGGER.debug(
                    "Event stream of %s dropped %s stamped %s before the connection (clock offset %.0f s)",
                    host,
                    frame.raw_type,
                    frame.device_time.isoformat(),
                    self._clock_offset.total_seconds(),
                )
                return
        self.stats.frames += 1
        _LOGGER.debug(
            "Event stream of %s delivered %s (%s, channel %s, port %s)",
            host,
            frame.raw_type,
            frame.state,
            frame.channel_id,
            frame.port_id,
        )
        try:
            self._on_frame(frame)
        except Exception:
            _LOGGER.exception("Event handler failed")


def splitter_idle(splitter: MultipartSplitter) -> bool:
    """True when no partial part is buffered (the next chunk starts a new part)."""
    return not splitter._buffer.strip(b"\r\n")
