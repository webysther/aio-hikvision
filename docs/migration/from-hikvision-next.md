# Migrating hikvision_next to aiohikvision

This guide maps the ISAPI client of
[hikvision_next](https://github.com/maciej-or/hikvision_next) (the `ISAPIClient` class of
`custom_components/hikvision_next/isapi/isapi.py`, which its `HikvisionDevice` extends) onto
aiohikvision 0.2. It says what exists today, under its exact name, and what is still to come,
with the slice of the plan that brings it. Nothing planned is presented as existing.

aiohikvision has [three levels](https://github.com/webysther/aio-hikvision/blob/main/README.md#three-levels).
Level 3, `aiohikvision.connect()` → `Hikvision`, answers what an integration asks: start there.
`hik.device` (level 2, `Device`) and `hik.device.link` (level 1) are for what level 3 does not
answer yet, and each snippet that goes down says why.

The hikvision_next repository has no license file. This guide therefore names its methods and
describes what they do, without quoting its code.

## Where aiohikvision 0.2 stands

0.2 is in development. Each part of the plan is published as a minor release (before 1.0 a
minor may change the API), which a consumer pins exactly. Today it has:

- `aiohikvision.connect(...)`, which returns a `Hikvision` (level 3): who the device is
  (`hik.name`, `hik.model`, `hik.serial`, `hik.firmware`), what it is (`hik.kind`) and
  supports (`hik.supports`), and its cameras (`hik.cameras`), all read once; a camera takes a
  picture and gives the RTSP address of each of its streams;
- `hik.device`, a `Device` (level 2): the whole identity (`device.identity`), every element of
  `/ISAPI/System/capabilities` (`device.capabilities`), how it behaves (`device.behaviours`,
  set from its model and firmware by rules), and `device.streaming` (`Streaming`): a picture
  at any size, and the open video sessions;
- `await hik.report()` and `python -m aiohikvision report <address>`: an anonymized report
  of a device, to attach to an issue;
- the wire layer, which stays as it is: `IsapiLink` (digest that respects the device's login
  lockout, TLS, XML and JSON documents), the faults, the alert stream (`AlarmFeed`) and the
  parsers of event notifications.

Next, by slice:

- **S4, events, cameras and recorders.** An `Events` service: the event capabilities and
  triggers, falling back to triggersCap where the device needs it; switching a detection on
  and off after a mutex pre-check; the alert feed; `EventStates`, active or inactive with a
  hold time, since many alerts never send their end. A `Recorder`: IP, analog and proxied
  channels, the picture through the StreamingProxy, and the RTSP address of recorders and
  single cameras. `isapi.model.discover` and `isapi.model.inventory` leave.
- **S5, the rest of the parity with hikvision_next and Hikvision Bridge.** Protocols, IOProxy
  and the IO status of every port at once, holidays, httpHosts (the alarm server), reboot,
  PIR and FaceDetect, image settings read from the capabilities, storage, and recordings.
  The modules of `isapi.model.features` leave.
- **S6.** Door stations on `Device`, and 0.2.0 final.

## Status

- **Available**: in 0.2 now, under the name given, and staying.
- **Partial**: in 0.2 now, but it does less than the hikvision_next method. The cell says
  what is missing, and which slice brings it.
- **Planned (Sx)**: not in the 0.2 API yet; Sx is the slice that brings it. Where the 0.1
  low-level layer (`aiohikvision.isapi.model`) has something, the cell names it. That layer
  leaves without a shim when its slice lands, so do not build new code on it.

## Method map

`hik` is the `Hikvision` that `aiohikvision.connect()` returns, `device` is `hik.device`, and
`camera` one of `hik.cameras`.

| `ISAPIClient` | aiohikvision 0.2 | Status |
|---|---|---|
| `ISAPIClient(host, username, password, verify_ssl, rtsp_port_forced, session)` | `await aiohikvision.connect(host, username, password, session=, port=, https=, ssl_context=, trusted=)` → `Hikvision`. The session is aiohttp (Home Assistant's `async_get_clientsession`), not httpx; the host and the port are given apart, not as a URL; `verify_ssl` becomes the session's or an `ssl_context`. There is no forced RTSP port: see `get_stream_source`. | Partial |
| `get_device_info()` | `hik.name`, `hik.model`, `hik.serial`, `hik.firmware` and `hik.id` (the serial, for identifiers), read by `connect()`; the rest of `deviceInfo` (`mac`, `device_type`, `hardware`, `device_id`) is in `device.identity` (`Identity`), read again with `await device.system.identity()`. `firmware` is a `Firmware` (`str()` gives what the device wrote, `.parts` and `.build` compare). The address is `device.link.endpoint.host`. There is no `manufacturer` field. | Available |
| `get_hardware_info()` | `connect()` reads the identity, the capabilities, the behaviours and the streams of each camera (`hik.cameras`). Cameras of a recorder, events, protocols and storage: see their rows. | Partial |
| `capabilities` (the `CapabilitiesInfo` flags) | `hik.supports.inputs`, `.outputs` and `.holidays` (None where the device does not say); the other flags in `device.capabilities.tree`: `.count("videoInputPortNums")`, `.count("inputProxyNums")`, `.flag("isSupportZeroChan")`, `.flag("isSupportGetmutexFuncErrMsg")`. `flag()` answers a `Support` (PRESENT, ABSENT, or UNKNOWN when the device sent no capabilities). `support_alarm_server` comes with httpHosts (S5). | Available |
| `device_info.is_nvr` (more than one video input) | `hik.kind is Kind.RECORDER`, from `deviceType` and the domains, not from a count of inputs. The `Recorder` (S4) decides from its channels. | Partial |
| `get_cameras()` | A camera, or a camera with several channels: `hik.cameras`, a `Camera` per channel (`channel`, `streams`, `main`, `sub`). The IP (InputProxy) and analog channels of a recorder, with each camera's model, serial and firmware: the `Recorder` (S4). | Partial |
| `get_camera_streams(channel_id)` | `camera.streams`: the enabled streams of a channel (`camera.main`, `camera.sub`), each a `Stream` with `id` (`StreamId`), `kind` (`StreamKind`: MAIN, SUB, THIRD, OTHER), `name`, `video` (`VideoFormat`: `codec`, `width`, `height`, `fps`, `gop_frames`, `bitrate_kbps`) and `audio` (`AudioCodec`, None without sound). One stream read again: `await device.streaming.stream(StreamId(channel, index))`, None when it is off. | Available |
| `get_camera_by_id()`, `get_camera_by_serial_no()` | Lookups over the channels of the `Recorder` (S4). | Planned (S4) |
| `get_protocols()` | `await device.streaming.rtsp_port()`: the RTSP port of `/ISAPI/Security/adminAccesses` (554 when the device names none), read once. That is all `get_protocols` keeps; the other protocols come in S5. | Available |
| `get_supported_events(system_capabilities)` | The `Events` service (S4); the triggersCap fallback is decided by `device.behaviours.triggers` (`TriggerSource`), which exists now. PIR: S5. 0.1 low-level: `isapi.model.features.linkage.parse_triggers`. | Planned (S4) |
| `get_event_url(...)` | None to call: the `Events` service (S4) owns the paths of its detections; IOProxy inputs and PIR come in S5. | Planned (S4) |
| `get_event_enabled_state(event)` | The `Events` service (S4). 0.1 low-level: `isapi.model.features.detection.read`. | Planned (S4) |
| `get_event_switch_mutex(event, channel_id)` | The mutex pre-check of `Events` (S4). Whether the device offers it, now: `device.capabilities.tree.flag("isSupportGetmutexFuncErrMsg")`. | Planned (S4) |
| `set_event_enabled_state(channel_id, event, is_enabled)` | The `Events` service (S4); PIR and FaceDetect in S5. 0.1 low-level: `isapi.model.features.detection.switch` (reads the value back, no mutex pre-check). | Planned (S4) |
| `get_io_port_status(port_type, port_no)` | An IO service with IOProxy ports and the bulk `/ISAPI/System/IO/status` (S5). 0.1 low-level: `isapi.model.features.io.read_state`. | Planned (S5) |
| `set_output_port_state(port_no, turn_on)` | The IO service (S5). 0.1 low-level: `isapi.model.features.io.set_output`. | Planned (S5) |
| `get_holiday_enabled_state()`, `set_holiday_enabled_state()` | Holidays (S5). Whether the device has them, now: `hik.supports.holidays`. | Planned (S5) |
| `get_alarm_server()`, `set_alarm_server(base_url, path)` | httpHosts (S5). Without an alarm server, now: the alert stream, `AlarmFeed` in `aiohikvision.isapi.wire.feed` (flow 4). | Planned (S5) |
| `reboot()` | Reboot (S5). | Planned (S5) |
| `get_storage_devices()`, `get_storage_device_by_id()` | Storage (S5). 0.1 low-level: `isapi.model.features.storage.read`. | Planned (S5) |
| `parse_event_notification(xml)` | `frame_from_xml(parse(xml))`, or `frame_from_part(part)` for a part of a multipart POST (`aiohikvision.isapi.wire.feed`, `aiohikvision.isapi.wire.xmlview`): a `FeedFrame` with `raw_type`, `state`, `channel_id` (or `dynChannelID`), `port_id`, `targets`, `region_id`, `mac`, `device_time` and the pictures; a `duration` alert is unwrapped to its `relationEvent`. Missing: an alert with a bare `&` is skipped, not repaired; the serial of `Extensions` is not read; the kind (0.1 `isapi.model.vocabulary.canonical`) does not know `VMDHumanVehicle` yet, and the kinds move to `Events` in S4. | Partial |
| `get_camera_image(stream, width, height)` | `await camera.snapshot(stream_id)`, at a size of the device's choosing; a size is level 2's, `await device.streaming.snapshot(stream_id, width=, height=)`. Both check that the answer is a JPEG and raise `DeviceRejected` otherwise. Missing: the picture through `ContentMgmt/StreamingProxy` for recorder channels and devices that answer statusCode 6 (the `Recorder`, S4), and the retry on statusCode 3 (planned as a `snapshot` behaviour, no slice fixed yet). | Partial |
| `get_stream_source(stream)` | `await camera.stream_url(stream_id)`: the account escaped in the address, on the device's RTSP port; `credentials=False` gives an address safe to log. A forced port: replace it with yarl (flow 2). | Available |
| `request(method, url, present, data)`, `request_bytes(...)` | `device.link` (`IsapiLink`, `aiohikvision.isapi.wire.link`): `read_xml`, `read_json`, `read_text`, `read_bytes`, `write_xml`, `call`. Paths are absolute (`/ISAPI/...`). `optional=True` answers None for a resource the device lacks, where hikvision_next silences errors while `pending_initialization`. | Available |
| `_detect_auth_method()` | Inside `IsapiLink`: digest from the device's challenge; Basic over plain HTTP refused (`InsecureAuth`); a link that proved digest never accepts a weaker scheme; a refused login stops the link before the device's lockout (`BadCredentials.retries_left`, `LockedOut.retry_after`). | Available |
| `ISAPIUnauthorizedError`, `ISAPIForbiddenError` | `BadCredentials`, `LockedOut`, `Forbidden` (`aiohikvision.isapi.wire.faults`), each a `HikvisionError` (`aiohikvision.errors`). | Available |
| `ISAPISetEventStateMutexError` | A typed error of `Events` naming the detections in the way (S4). | Planned (S4) |

## Before and after

The "before" of each flow describes what hikvision_next does; the "after" uses only names that
exist in aiohikvision today, and a `# planned (Sx)` comment where a slice is still to come.

### 1. Connecting, device information and cameras

**Before.** `HikvisionDevice` builds an `ISAPIClient` with the device's URL, the account,
`verify_ssl`, an optional forced RTSP port and Home Assistant's httpx client. The config flow
calls `get_device_info()` to check the login. Setup calls `get_hardware_info()`, which:

- reads `System/deviceInfo` and `System/capabilities` into the flags of `CapabilitiesInfo`;
- asks `Event/notification/httpHosts` whether an alarm server can be set;
- takes the device for an NVR when it counts more than one analog or IP input;
- lists the cameras (`get_cameras()`). On a camera, they are the channels named in
  `Streaming/channels`. On an NVR, they are the IP cameras of `ContentMgmt/InputProxy/channels`
  and the analog ones of `System/Video/inputs/channels`. Each camera asks for its streams one
  by one (`Streaming/channels/{channel}0{1..4}`);
- then reads the events, the protocols and the storage.

The first request goes out without credentials, to pick Basic or Digest from the
`WWW-Authenticate` header. While `pending_initialization` is set, HTTP errors are silenced.

**After.**

```python
"""Connect to a camera or a recorder, and list its streams by channel."""

import asyncio
import os

import aiohikvision


async def main() -> None:
    async with aiohikvision.connect(
        os.environ.get("DEVICE_HOST", "192.0.2.10"),
        os.environ["DEVICE_USERNAME"],
        os.environ["DEVICE_PASSWORD"],
        # In Home Assistant: session=async_get_clientsession(hass), the session of the app
    ) as hik:
        print(hik.model, hik.serial, hik.firmware)  # get_device_info(), read once by connect()
        print(hik.kind, hik.supports.inputs, hik.supports.holidays)  # get_hardware_info()'s flags

        # The MAC and the counts of video inputs have no level-3 answer yet: level 2 has them
        identity, tree = hik.device.identity, hik.device.capabilities.tree
        print(identity.mac, tree.count("videoInputPortNums"), tree.count("inputProxyNums"))

        for camera in hik.cameras:  # a Camera per channel, its streams read by connect()
            for stream in camera.streams:
                print(camera.channel, stream.id, stream.kind, stream.video)
        # planned (S4): the Recorder lists the IP (InputProxy) and analog channels of an NVR,
        # with each camera's model, serial and firmware, and decides what is a recorder


asyncio.run(main())
```

Errors are typed from the first request: `BadCredentials` (with the logins left before the
lockout), `LockedOut`, `Unreachable`, `NotIsapi`, `InsecureAuth`, all `HikvisionError`.

### 2. Streams and the snapshot

**Before.** `get_stream_source(stream)` builds `rtsp://user:password@host:port/Streaming/channels/{id}`,
with the account escaped and the port from `get_protocols()` or the forced one.
`get_camera_image(stream, width, height)`:

- reads `Streaming/channels/{id}/picture`, at the stream's own size unless the width asked is
  100 or less;
- when the answer is XML with statusCode 6, switches that stream to
  `ContentMgmt/StreamingProxy/channels/{id}/picture` for good;
- when the statusCode is 3, tries again, twice at most.

**After.**

```python
"""The picture and the RTSP address of a stream."""

from yarl import URL

from aiohikvision import Camera, StreamId
from aiohikvision.isapi.wire.faults import DeviceRejected


async def camera_image(
    camera: Camera, stream: StreamId, width: int | None = None, height: int | None = None
) -> bytes | None:
    """Return a JPEG of a stream of a camera (one of hik.cameras); None when it sends none."""
    try:
        if width and height:  # level 3 takes no size yet: its level-2 service does
            return await camera.streaming.snapshot(stream, width=width, height=height)
        return await camera.snapshot(stream)
    except DeviceRejected:
        # planned (S4): the Recorder's picture through ContentMgmt/StreamingProxy, for recorder
        # channels and for devices that answer statusCode 6 on Streaming/channels
        return None


async def stream_source(camera: Camera, stream: StreamId, forced_port: int | None = None) -> str:
    """Return the RTSP address of a stream, on the device's RTSP port or a forced one."""
    address = await camera.stream_url(stream)  # the account inside: keep it out of logs
    return str(URL(address).with_port(forced_port)) if forced_port else address


MAIN_STREAM = StreamId(1, 1)  # "101"; StreamId.parse("102") is the sub stream of channel 1
```

### 3. Detections and alarm outputs

**Before.** `set_event_enabled_state(channel_id, event, is_enabled)` first checks for conflicts,
when it is switching on, on a channel, and the device offers the check
(`isSupportGetmutexFuncErrMsg`). It POSTs the function to `System/mutexFunction?format=json`,
spelling motion as `VMDHumanVehicle` there, and raises `ISAPISetEventStateMutexError` when
another detection is in the way. Otherwise it reads the event's document, sets `enabled`,
rebuilds the whole document with xmltodict and PUTs it back. The event's path comes from
`get_event_url`: direct or InputProxy channels, `System/IO` or `ContentMgmt/IOProxy` inputs,
`WLAlarm/PIR`, `Smart/...`. `get_io_port_status` reads `ioState`; `set_output_port_state` PUTs
`outputState` high or low to the output's `trigger`.

**After.** The services are S4 and S5, and level 3 answers neither yet, so this goes down to
the link (`hik.device.link`). The wire layer stays, and edits a document in place: unknown
elements, their order and the namespaces survive, which an xmltodict round trip does not
guarantee.

```python
"""Switch a detection and an alarm output on the link, until Events (S4) and IO (S5) land."""

from aiohikvision import Hikvision
from aiohikvision.isapi.wire.xmlview import RawDocument

OUTPUT_TRIGGER = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<IOPortData version="2.0" xmlns="http://www.isapi.org/ver20/XMLSchema">'
    "<outputState>{state}</outputState></IOPortData>"
)


async def set_detection(hik: Hikvision, path: str, enabled: bool) -> None:
    """Set `enabled` of a detection's document (path: "/ISAPI/Smart/LineDetection/1")."""
    # planned (S4): Events pre-checks System/mutexFunction when the device offers it
    # (device.capabilities.tree.flag("isSupportGetmutexFuncErrMsg")) and raises a typed error
    text = await hik.device.link.read_text(path)
    if text is None:
        return
    document = RawDocument(text)
    value = "true" if enabled else "false"
    if document.get("enabled") != value and document.set("enabled", value):
        await hik.device.link.write_xml(path, document.text)
    # planned (S4): Events switches a detection by its kind and channel, and reads it back;
    # planned (S5): PIR and FaceDetect


async def set_output(hik: Hikvision, port: int, on: bool) -> None:
    """Set an alarm output high or low."""
    if hik.supports.outputs is not None and port > hik.supports.outputs:
        return  # the device has fewer outputs; None: it did not say
    document = OUTPUT_TRIGGER.format(state="high" if on else "low")
    await hik.device.link.write_xml(f"/ISAPI/System/IO/outputs/{port}/trigger", document)
    # planned (S5): an IO service, with IOProxy ports and the status of every port at once
```

### 4. Alarm server and notifications

**Before.** At setup, `set_alarm_server(base_url, path)` writes the first slot of
`Event/notification/httpHosts`, so that the device POSTs its alerts to Home Assistant at
`/api/hikvision`: the protocol, an IP address or a host name, the port, and no
authentication. At unload it points the slot at `0.0.0.0`. A Home Assistant view without
authentication receives each POST. It splits a multipart body with requests-toolbelt, parses
the alert with `parse_event_notification` (bare `&` escaped first, alternate event names
mapped, the serial read from `Extensions`), and finds the entry by the sender's address or
MAC.

**After, without an alarm server.** The device keeps an authenticated alert stream open
(`/ISAPI/Event/notification/alertStream`). No view without authentication is needed, and
nothing is written on the device. `AlarmFeed` reconnects with a backoff, judges a stream that
never works, and learns the device's clock from its heartbeats. Level 3 has no events yet
(S4), so the feed goes down to `hik.device`.

```python
"""Receive the events of a device over its alert stream."""

import asyncio

from aiohikvision import AlertStream, Hikvision
from aiohikvision.errors import HikvisionError
from aiohikvision.isapi.model.vocabulary import canonical  # 0.1 low-level, until Events (S4)
from aiohikvision.isapi.wire.feed import AlarmFeed, FeedFrame


def on_frame(frame: FeedFrame) -> None:
    if frame.heartbeat:  # an inactive video loss: the device's keepalive
        return
    print(canonical(frame.raw_type), frame.state, frame.channel_id, frame.port_id, frame.targets)


def on_state(connected: bool, fault: HikvisionError | None) -> None:
    print("connected" if connected else f"down: {fault}")


def start_feed(hik: Hikvision) -> AlarmFeed | None:
    """Start the feed; None for a device a rule knows to have no alert stream (poll it)."""
    if hik.device.behaviours.alert_stream is AlertStream.NONE:
        return None
    feed = AlarmFeed(hik.device.link, on_frame, on_state)
    loop = asyncio.get_running_loop()
    # In Home Assistant: entry.async_create_background_task(hass, coro, name)
    feed.start(lambda coro, name: loop.create_task(coro, name=name))
    # planned (S4): Events offers the feed on the Device, with EventStates (hold times)
    return feed  # await feed.stop() at unload
```

**After, keeping the alarm server.** The parsers of the wire layer read the POSTed body:
multipart or a single XML or JSON document, with its pictures.

```python
"""Parse the events a device POSTs to an alarm server."""

from aiohttp import web

from aiohikvision.isapi.wire.feed import (
    FeedFrame,
    MultipartSplitter,
    Part,
    boundary_of,
    frame_from_part,
)


def frames_of(content_type: str, body: bytes) -> list[FeedFrame]:
    """Return the events of one POST: a multipart body, or one XML or JSON document."""
    boundary = boundary_of(content_type)
    if boundary:
        # The trailing delimiter lets the splitter close the last part
        parts = list(MultipartSplitter(boundary).push(body + b"\r\n--"))
    else:
        parts = [Part({"content-type": content_type}, body)]
    return [frame for part in parts if isinstance(frame := frame_from_part(part), FeedFrame)]


async def post(request: web.Request) -> web.Response:
    for frame in frames_of(request.headers.get("Content-Type", ""), await request.read()):
        print(frame.raw_type, frame.state, frame.channel_id, frame.mac)
    # planned (S5): writing the device's httpHosts (the alarm server) through the library
    return web.Response()
```

## What hikvision_next would gain

hikvision_next can keep its entities and its users' unique IDs, and hand the device side to
one maintained client. That client is already used by Hikvision Bridge, whose ISAPI code it
grew from, and by Hikvision Virtual Indoor Station, and it is meant for Home Assistant's own
`hikvision` integration too. A device fixed once is fixed for all of them.

What the device says it can do is read once, and each domain is PRESENT, ABSENT or UNKNOWN.
A service is None when the capabilities rule it out, and asks the device when they are silent.
Today such decisions are spread over flags and probes.

Where models or firmware differ, the difference is a named behaviour, set by rules that say on
which model and firmware it was seen. The DS-KV8113 whose alert stream sends a few bytes and
closes is one (`AlertStream.NONE`); hikvision_next's alternate picture path would be another.
Users can add their own rules, or override a behaviour, without waiting for a release.

Its users get a tool to report a device they own: `python -m aiohikvision report <address>`
reads it with GET only and writes an anonymized report (no account, address, serial, MAC or
given names). Attached to an issue, the report becomes a fixture and a rule.

It would also get:

- authentication that never sends Basic over plain HTTP and stops before the device's
  lockout;
- credentials scrubbed from its logs, and a short debug log;
- documents edited in place rather than rebuilt, parsed with defusedxml;
- Home Assistant's aiohttp session injected, frozen models, and strict typing;
- two fewer requirements: xmltodict and requests-toolbelt.

## Getting started

- Require `aiohikvision[isapi]` at an exact version (`"aiohikvision[isapi]==0.2.0"`).
  Home Assistant compares only the name and the version of a requirement, not its extras,
  but it ships aiohttp and yarl, all the `isapi` part needs: defusedxml comes with the
  extra, and without it a guarded parser reads the XML.
- Turn on the debug log of `aiohikvision`. It says, in one record, how each device was
  recognised: its domains, how the library covers each, and the behaviours a rule set.
- Ask users whose device misbehaves for its report, and
  [open a device report](https://github.com/webysther/aio-hikvision/issues/new?template=device_report.yml)
  with it.
