# Migrating from pyHik to aiohikvision

For the maintainers of Home Assistant core's `hikvision` integration, and for anyone
else on [pyHik](https://github.com/mezz64/pyHik). It maps what core uses of pyHik to
aiohikvision, shows the main pieces of core's code before and after, and says what
is still missing.

aiohikvision has [three levels](https://github.com/webysther/aio-hikvision/blob/main/README.md#three-levels).
Level 3, `aiohikvision.connect()` → `Hikvision`, answers what an integration asks, and a
migration starts there. `hik.device` (level 2, `Device`) and `hik.device.link` (level 1)
are for what level 3 does not answer yet: each snippet that goes down says why.

Read on 2026-11-27: pyHik 0.5.0 (`e0ebc24`), core `dev` (`8fe6ad2`, which pins
`pyHik==0.5.0`), and the source of aiohikvision 0.2.0. **aiohikvision 0.2.0 is not
released yet**: every name below marked Available is in its source, not yet on PyPI.

Code quoted from core is Home Assistant core, Apache-2.0. Code quoted from pyHik is
pyHik, MIT, Copyright (c) John Mihalic 2016. Quotes keep the original code, with
the indentation of the enclosing class or function removed.

## Why

Core runs pyHik in the executor. `HikCamera(...)`, `get_video_channels`,
`get_event_triggers`, every snapshot and `disconnect` run there. pyHik's alert stream
is a non-daemonic thread that core has to join before the event loop closes
(`homeassistant/components/hikvision/__init__.py`, lines 146–162).

aiohikvision is built differently:

- **Async on Home Assistant's session.** It is asyncio on aiohttp, and
  `aiohikvision.connect(..., session=session)` takes Home Assistant's own session.
- **Typed.** It ships `py.typed` and is checked with mypy `--strict`. The models of
  its new API are frozen dataclasses and enums.
- **Capabilities read once.** On connect it reads who the device is (`hik.name`), what
  it can do (`hik.supports`, from `/ISAPI/System/capabilities`) and its cameras
  (`hik.cameras`). A service is `None` when the device has no such domain.
- **Named behaviours.** Each quirk of a model or firmware is a named behaviour
  (`device.behaviours`). Rules set them and say where each was measured
  (`KNOWN_RULES`), and a caller can add rules or overrides without waiting for a
  release.
- **Safe authentication.** Digest authentication never sends the password readable
  over HTTP and never falls back to a weaker scheme. It stops before the device locks
  the account. pyHik starts with Basic, then retries with digest without a timeout.
- **Reports and a lean log.** A device the library does not know yet produces an
  anonymized report (`await hik.report()`, or `python -m aiohikvision report` from
  a terminal). The debug log is short: it says once how the device was recognised,
  then logs each failing request once.

Core's `quality_scale.yaml` for `hikvision` lists three Platinum rules as `todo` that
this makes reachable: `async-dependency`, `inject-websession` and `strict-typing`.
`hikvision` is not in core's `.strict-typing` yet, so a migration PR would add it.

The library also gives material for rules the same file lists as `todo`:

- `reauthentication-flow`: a refused password is `BadCredentials`;
- `exception-translations`: every error has a `translation_key`;
- `diagnostics`: `hik.report()`;
- `entity-unavailable` and `log-when-unavailable`: the feed's state callback.

## pyHik → aiohikvision

**Available**: exists now under that exact name. **Partial**: exists, but does less
than what core uses. **Planned**: not in the library. The slice of the plan is named:

- S4: events, cameras and recorders, which add an `Events` service with `EventStates`
  and a `Recorder`;
- S5: the rest of the parity.

Every name is under `aiohikvision`. `hik` is the `Hikvision` that `aiohikvision.connect()`
returns, `device` is `hik.device`, and `camera` one of `hik.cameras`. `faults` is
`aiohikvision.isapi.wire.faults`, `feed` is `aiohikvision.isapi.wire.feed`, and `model` is
`aiohikvision.isapi.model`.

| pyHik (as core uses it) | aiohikvision | Status |
|---|---|---|
| `HikCamera(url, port, usr, pwd, verify_ssl)`, in the executor | `await aiohikvision.connect(host, username, password, session=, port=, https=, ssl_context=, trusted=)` → `Hikvision`. `verify_ssl` comes from the session (`async_get_clientsession(hass, verify_ssl=...)`) | **Available** |
| Authentication: Basic first, digest after a 401 | The device's `IsapiLink` (`device.link`). Digest; Basic only over HTTPS (`faults.InsecureAuth` over HTTP); never weaker after digest worked; one request at a time. It stops before the lockout: `BadCredentials.retries_left`, `LockedOut.retry_after` | **Available** |
| `requests` exceptions, `None` returns, `auth_failed` | `HikvisionError`, and in `faults`: `Unreachable`, `BadCredentials`, `LockedOut`, `Forbidden`, `Unsupported`, `DeviceRejected`, `InsecureAuth`, `NotIsapi`. Each has a `translation_key`. statusCode 7 ("reboot required") counts as success | **Available** |
| `get_id` | `device.identity.device_id`: the raw `deviceID`, as reported (`hik.id` is the serial, another id). There is no length rule and no uuid4 (see [Keeping the unique IDs](#keeping-the-unique-ids)) | **Available** |
| `get_name` | `hik.name`, which is the model when `deviceName` is empty | **Available** |
| `get_type` (`"NVR"`, `"CAM"` or `None`) | `hik.kind` (`Kind`: `camera`, `recorder`, `door_station`, `other`), from `deviceType` and the domains; the raw `deviceType` is `device.identity.device_type`. The rule differs from pyHik's | **Partial**. The `Recorder` is Planned (S4) |
| `get_video_channels()` → `VideoChannel(id, name, enabled)` | `hik.cameras`: a `Camera` per channel with enabled streams (`channel`, `streams`, `main`, `sub`). The channel's name: `await model.discover.discover(device.link)` → `ChannelProfile.name` | **Partial**. `discover` and `inventory` leave in S4 for `Recorder` (IP, analog and proxy channels). A channel's `<enabled>` is not read |
| `get_event_triggers(methods)` | `model.features.linkage.parse_triggers(await device.link.read_xml(linkage.LIST_PATH, optional=True))` → `TriggerLink(trigger_id, kind, raw_type, channel_id, methods)`, also in `DeviceProfile.triggers` | **Partial**. The method filter, channel 0 → 1 and de-duplication are the caller's. The triggersCap fallback on a 5xx is Planned (S4): `TriggerSource.TRIGGERS_CAP` and its rule (DS-2CD3366WDV3-I V5.8.22) exist, but nothing reads them yet |
| `SENSOR_MAP` labels | `model.vocabulary.Kind` and `canonical(raw)`. The raw type is kept on `TriggerLink.raw_type` and `FeedFrame.raw_type` | **Partial**, by design. `Kind` groups types differently and leaves 5 of them as `OTHER`. The labels stay in the integration |
| `current_event_states`, `fetch_attributes` (`[state, channel, count, last change, target]`), `inject_events` | Nothing in the library | **Planned (S4)**: `EventStates` in an `Events` service. Until then the integration keeps the state, from `FeedFrame` |
| `start_stream()` (a thread), `disconnect()` | `feed.AlarmFeed(device.link, on_frame, on_state)`, `feed.start(create_task)`, `await feed.stop()`. It is an asyncio task, so it can be a background task of the entry | **Available**. It lives in `isapi.wire.feed`, and S4 puts it behind `Events` |
| `add_update_callback(cb, "<id>.<label>.<ch>")`, `remove_update_callback` | A single `on_frame(FeedFrame)`, called in the event loop. The integration routes each frame, for instance with the dispatcher | **Available** |
| `stream_connected`, and its broadcast to every callback | `on_state(connected, fault)` and `feed.connected`. A `BadCredentials` or `LockedOut` fault stops the feed | **Available** |
| `process_stream` | `feed.frame_from_xml` and `frame_from_json` → `FeedFrame` (`raw_type`, `state`, `channel_id`, `port_id`, `device_time`, `targets`, `region_id`, `extra["active_count"]`, pictures, plate) | **Available**, and a superset: JSON, `duration` unwrapped to its `relationEvent`, pictures, backlog replays dropped |
| Watchdog (300 s without a video-loss heartbeat) and backoff | `feed.SILENCE_LIMIT` (60 s), a backoff from 5 to 300 s (`feed.Reconnects`), and detection of a stream that answers 200 without events (`feed.StreamBehaviour.NO_STREAM`) | **Available** |
| `_BROKEN_ALERT_STREAM_DEVICES` (DS-KV8113-WME1(B) V2.2.53) | `device.behaviours.alert_stream` is `AlertStream.NONE` there, set by a `KNOWN_RULES` entry | **Partial**. `AlarmFeed` does not read the behaviour yet. It finds such a stream by itself after `feed.BARE_LIMIT` (3) bare answers |
| `update_stale()`: off 5 s after the last update | Nothing in the library | **Planned (S4)**: `EventStates` that turn off after a while |
| `get_snapshot(channel)` | `await camera.snapshot()`, the main stream of the channel's `Camera`. It raises (`DeviceRejected` when the answer is no JPEG) instead of returning `None` | **Partial**. Recorders' fallback to `/ISAPI/ContentMgmt/StreamingProxy/channels/<id>/picture` is Planned (S4) |
| `get_stream_url(channel, stream_type=)` | `await camera.stream_url(StreamKind.SUB)` (the main stream by default; a `StreamId` too). The RTSP port comes from `/ISAPI/Security/adminAccesses` (pyHik: always 554). A camera's path becomes `/Streaming/Channels/101` (pyHik: `/1`) | **Available** |
| Reauthentication through `ISAPIClient` (draft core PRs) | `aiohikvision.connect(..., trusted=False)` for the new password, and `IsapiLink.replace_credentials()` | **Available** |
| Diagnostics (draft core PRs) | `await hik.report()` → an anonymized `CapabilityReport` (`as_dict()`); more secrets to mask: `device.report(secrets=...)` | **Available** |
| Image settings (draft core PRs) | `model.features.image` (`read_capabilities`, `read_values`, `write`, `ImageCapability`, `ImageValue`) | **Partial**. No recorder ImageProxy, and no WDR/HLC/BLC/Dehaze conflict handling (a parity proposal). Generic image settings are Planned (S5) |
| Detection switches (draft core PRs) | `model.features.detection` (`read`, `switch`) | **Partial**. PIR and face detection are Planned (S5) |
| Alarm I/O (draft core PRs) | `model.features.io` (`parse_ports`, `read_state`, `set_output`, `read_armed`, `set_armed`) | **Partial**. IOProxy and the bulk `/System/IO/status` are Planned (S5) |
| Holidays (draft core PRs) | Only whether the device has them (`hik.supports.holidays`) | **Planned (S5)** |

The table has 13 Available rows, 9 Partial and 3 Planned.

## Before and after

### Connecting and setting up

Before: `homeassistant/components/hikvision/__init__.py`, lines 60–75 (Home Assistant
core, Apache-2.0).

```python
protocol = "https" if ssl else "http"
url = f"{protocol}://{host}"

try:
    camera = await hass.async_add_executor_job(
        HikCamera, url, port, username, password, verify_ssl
    )
except requests.exceptions.RequestException as err:
    raise ConfigEntryNotReady(f"Unable to connect to {host}") from err

device_id = camera.get_id
if device_id is None:
    raise ConfigEntryNotReady(f"Unable to get device ID from {host}")

device_name = camera.get_name or host
device_type = camera.get_type or "Camera"
```

After:

```python
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SSL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

import aiohikvision
from aiohikvision import Hikvision, HikvisionError
from aiohikvision.isapi.wire.faults import BadCredentials


async def async_connect(hass: HomeAssistant, entry: ConfigEntry) -> Hikvision:
    """Connect to the device of an entry, on Home Assistant's session."""
    # Entries created before the option existed always verified the certificate
    verify_ssl = entry.data.get(CONF_VERIFY_SSL, True)
    try:
        return await aiohikvision.connect(
            entry.data[CONF_HOST],
            entry.data[CONF_USERNAME],
            entry.data[CONF_PASSWORD],
            session=async_get_clientsession(hass, verify_ssl=verify_ssl),
            port=entry.data[CONF_PORT],
            https=entry.data[CONF_SSL],
            # Stored credentials that worked: one refusal is a hiccup, not a new password
            trusted=True,
        )
    except BadCredentials as err:
        raise ConfigEntryAuthFailed from err
    except HikvisionError as err:
        raise ConfigEntryNotReady(f"Unable to connect to {entry.data[CONF_HOST]}") from err
```

`hik.name` replaces `camera.get_name`, and `hik.kind` is the library's own type: existing
entries keep pyHik's (see [Device id and type](#device-id-and-type)). Several things go away:

- **The executor jobs and `requests`.**
- **The stop handling.** The `EVENT_HOMEASSISTANT_STOP` listener and the
  `hass.is_stopping` check (lines 146–162) are no longer needed. The feed is a
  background task of the entry, so it is cancelled on unload and at shutdown (see
  below).
- **`disconnect` in `async_unload_entry`.** It no longer runs in the executor.

The config flow calls the same `connect(...)` with `trusted=False`, since it is a new
login. `BadCredentials` becomes `invalid_auth` and `HikvisionError` becomes
`cannot_connect`.

`ConfigEntryAuthFailed` needs a reauth step, which is `reauthentication-flow`, still
`todo` in core.

Some devices offer only Basic authentication over HTTP. pyHik sent their password
readable. aiohikvision refuses with `InsecureAuth`, so those users need a translated
error or a repair issue that asks them to switch the device to digest or use HTTPS.

The manifest changes too:

- `"requirements"` becomes `aiohikvision[isapi]==<version>`, and `"loggers"`
  becomes `["aiohikvision"]`.
- Home Assistant checks only the name and version of a requirement, not its extras.
  aiohttp and yarl come with Home Assistant, all the `isapi` part needs: defusedxml
  comes with the extra, and without it a guarded parser reads the XML.

### Device id and type

Before: `pyhik/hikvision.py`, lines 509–520 (pyHik, MIT).

```python
info_type = (device_info.get('deviceType') or '').lower()
if 'nvr' in info_type or 'dvr' in info_type:
    self.device_type = NVR_DEVICE

for key in device_info:
    if key == 'deviceName':
        self.name = device_info[key]
    elif key == 'deviceID':
        if len(device_info[key]) > 10:
            self.cam_id = device_info[key]
        else:
            self.cam_id = uuid.uuid4()
```

`get_event_triggers` then overwrites the type (lines 735–738). It is `NVR` when any
trigger names a channel or an input port above 1, and `CAM` otherwise. Core reads
`camera.get_type or "Camera"`.

The type decides how core lays out its devices: each recorder channel is a device
with the identifier `f"{device_id}_{channel}"`. It also decides how stream numbers
are computed. Existing entries should therefore keep pyHik's decision.

After:

```python
from typing import Final

from aiohikvision import Hikvision
from aiohikvision.isapi.model.features import linkage
from aiohikvision.isapi.model.inventory import TriggerLink

PYHIK_SHORT_ID: Final = 10
"""pyHik kept a deviceID longer than this; a shorter one got a new uuid4 at every start."""


def legacy_device_id(hik: Hikvision) -> str | None:
    """Return the id pyHik gave the device; None when pyHik's id was random."""
    device_id = hik.device.identity.device_id  # the raw deviceID, level 2's: hik.id is the serial
    return device_id if device_id is not None and len(device_id) > PYHIK_SHORT_ID else None


def channel_number(value: str | None) -> int:
    """Return a channel or port as pyHik counted it: a missing or zero one is 1."""
    return int(value) if value and value.isdigit() and int(value) > 0 else 1


async def read_triggers(hik: Hikvision) -> tuple[list[TriggerLink], bool]:
    """Return the event triggers, and whether the device listed them at all."""
    # Events are not in level 3 yet (S4): the trigger list is read on the link
    document = await hik.device.link.read_xml(linkage.LIST_PATH, optional=True)
    return linkage.parse_triggers(document), document is not None


def legacy_device_type(hik: Hikvision, triggers: list[TriggerLink], listed: bool) -> str:
    """Return pyHik's type: the triggers decide when listed, deviceType otherwise."""
    if listed:
        return "NVR" if any(channel_number(t.channel_id) > 1 for t in triggers) else "CAM"
    # pyHik's rule, not hik.kind's, so it reads the raw deviceType of level 2
    device_type = (hik.device.identity.device_type or "").lower()
    return "NVR" if "nvr" in device_type or "dvr" in device_type else "Camera"
```

This follows pyHik closely, with two differences:

- **Channel ids.** pyHik reads the `dyn*` ids of a trigger first, and `parse_triggers`
  reads the plain ones first. Compare them on a recorder before relying on them.
- **A device without a trigger list.** pyHik tries triggersCap when the list answers
  a 5xx, which is still Planned here (S4).

Two more choices are open:

- **The device model.** The device can now show its real model and firmware
  (`hik.model`, `str(hik.firmware)`, `hik.serial`) instead of
  `"NVR"`, `"CAM"` or `"Camera"`. This does not touch any unique ID.
- **The layout of new entries.** New entries could use the library's own reading,
  `hik.kind is Kind.RECORDER`, which also knows hybrid recorders, and `hik.cameras`
  for the channels.

### Event subscription and binary sensor state

Before: `homeassistant/components/hikvision/entity.py`, lines 61–77 (Home Assistant
core, Apache-2.0; docstrings left out).

```python
@property
@override
def available(self) -> bool:
    return self._camera.stream_connected

@override
async def async_added_to_hass(self) -> None:
    await super().async_added_to_hass()

    self._camera.add_update_callback(self._update_callback, self._callback_id)
    self.async_on_remove(
        lambda: self._camera.remove_update_callback(
            self._update_callback, self._callback_id
        )
    )
```

`homeassistant/components/hikvision/binary_sensor.py`, lines 227–235 (Home Assistant
core, Apache-2.0):

```python
def _get_sensor_attributes(self) -> tuple[bool, Any, Any, Any]:
    """Get sensor attributes from camera."""
    return self._camera.fetch_attributes(self._sensor_type, self._channel)

@property
@override
def is_on(self) -> bool:
    """Return true if sensor is on."""
    return self._get_sensor_attributes()[0]
```

pyHik's callbacks run on its stream thread. Core therefore uses
`schedule_update_ha_state` and `call_soon_threadsafe`. pyHik turns off every event that
got no update for 5 seconds (`update_stale`, `pyhik/hikvision.py` lines 1022–1042), but
only when another packet arrives.

After, in `__init__.py`. The feed is a task of the entry, and each frame goes to the
entities of its label and channel. Events are not in level 3 yet (S4), so the feed runs
on `hik.device.link`:

```python
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send

from aiohikvision import Hikvision, HikvisionError
from aiohikvision.isapi.wire.faults import BadCredentials
from aiohikvision.isapi.wire.feed import AlarmFeed, FeedFrame

from .const import DOMAIN, SENSOR_MAP


def start_feed(
    hass: HomeAssistant, entry: HikvisionConfigEntry, hik: Hikvision, device_id: str
) -> AlarmFeed:
    """Keep the alert stream open while the entry is loaded, routing each frame."""

    @callback
    def on_frame(frame: FeedFrame) -> None:  # in the event loop: no thread to hop from
        raw_type = frame.raw_type.lower()
        label = SENSOR_MAP.get(raw_type)
        # pyHik's choices, kept: video loss is no sensor, duration packets are skipped
        if label is None or raw_type == "videoloss" or frame.extra.get("via") == "duration":
            return
        channel = channel_number(frame.channel_id or frame.port_id)
        async_dispatcher_send(hass, f"{DOMAIN}_{device_id}_{label}_{channel}", frame)

    @callback
    def on_state(connected: bool, fault: HikvisionError | None) -> None:
        async_dispatcher_send(hass, f"{DOMAIN}_{device_id}_stream", connected)
        if isinstance(fault, BadCredentials):
            entry.async_start_reauth(hass)

    feed = AlarmFeed(hik.device.link, on_frame, on_state)
    feed.start(lambda coro, name: entry.async_create_background_task(hass, coro, name))
    entry.async_on_unload(feed.stop)
    return feed
```

The base entity's `available` returns `feed.connected`. Every entity listens to
`..._stream` and writes its state, as pyHik's broadcast did.

The binary sensor keeps its own state until S4 brings `EventStates`. A timer is what
pyHik's `update_stale` meant to be:

```python
from datetime import datetime, timedelta
from typing import Final, override

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.const import ATTR_LAST_TRIP_TIME
from homeassistant.core import CALLBACK_TYPE, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import async_call_later

from aiohikvision.isapi.wire.feed import FeedFrame

from .const import DOMAIN
from .entity import HikvisionEntity

STALE_AFTER: Final = timedelta(seconds=5)
"""pyHik's update_stale: many events post "active" and never "inactive"."""

# planned (S4): an `Events` service on `Device` whose `EventStates` keep each
# (event, channel) on or off and turn it off after a while, replacing the timer below.
# Its names and signatures are not settled; nothing of it exists in aiohikvision yet.
# states = device.events.states(off_after=STALE_AFTER)


class HikvisionBinarySensor(HikvisionEntity, BinarySensorEntity):
    """An event of one channel: on while the device reports it."""

    _attr_is_on = False
    _cancel_off: CALLBACK_TYPE | None = None

    @override
    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # The same key pyHik's callback id had: device id, label, channel
        signal = f"{DOMAIN}_{self._data.device_id}_{self._sensor_type}_{self._channel}"
        self.async_on_remove(async_dispatcher_connect(self.hass, signal, self._on_frame))
        self.async_on_remove(self._stop_timer)

    @callback
    def _on_frame(self, frame: FeedFrame) -> None:
        self._stop_timer()
        self._attr_is_on = frame.is_active
        self._attr_extra_state_attributes = {ATTR_LAST_TRIP_TIME: frame.received}
        if frame.is_active:
            self._cancel_off = async_call_later(self.hass, STALE_AFTER, self._turn_off)
        self.async_write_ha_state()

    @callback
    def _turn_off(self, _now: datetime) -> None:
        self._cancel_off = None
        self._attr_is_on = False
        self.async_write_ha_state()

    @callback
    def _stop_timer(self) -> None:
        if self._cancel_off is not None:
            self._cancel_off()
            self._cancel_off = None
```

The event entity follows the same pattern. It fires when a frame turns the event on,
with `frame.targets[0] if frame.targets else None` in place of pyHik's target. The
targets are already in lower case, as core's `DETECTION_TARGETS` are.

Some differences are decisions for the migration PR:

- **Duration packets.** pyHik ignored them. The library unwraps them into the event
  they continue, so taking them would keep ongoing events on.
- **Alerts without a channel.** pyHik dropped them, so for instance a disk alert
  without `channelID` never turned its sensor on. `channel_number` routes them to
  channel 1, where pyHik created that sensor.
- **Backlog replays.** The library drops the replays a device sends right after
  connecting, which pyHik delivered as live events.

### Snapshot and stream source

Before: `homeassistant/components/hikvision/camera.py`, lines 80–97 (Home Assistant
core, Apache-2.0; docstrings left out).

```python
@override
async def async_camera_image(
    self, width: int | None = None, height: int | None = None
) -> bytes | None:
    try:
        return await self.hass.async_add_executor_job(
            self._camera.get_snapshot, self._video_channel.id
        )
    except Exception as err:
        raise HomeAssistantError(
            f"Error getting image from {self._video_channel.name}: {err}"
        ) from err

@override
async def stream_source(self) -> str | None:
    return self._camera.get_stream_url(self._channel, stream_type=self._stream_type)
```

After:

```python
from typing import override

from homeassistant.components.camera import Camera
from homeassistant.exceptions import HomeAssistantError

from aiohikvision import HikvisionError, StreamId


class HikvisionCamera(HikvisionEntity, Camera):
    """One stream of a channel: the main stream, or the sub stream."""

    @override
    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        # planned (S4): a recorder channel without a picture of its own falls back to
        # /ISAPI/ContentMgmt/StreamingProxy/channels/<id>/picture, as pyHik does
        try:
            return await self._camera.snapshot()  # the main stream of the channel
        except HikvisionError as err:
            raise HomeAssistantError(
                f"Error getting image from {self._video_channel.name}: {err}"
            ) from err

    @override
    async def stream_source(self) -> str | None:
        return await self._camera.stream_url(StreamId(self._camera.channel, self._stream_type))
```

`self._camera` is now the `Camera` of the entity's channel, from `hik.cameras`, where it
was pyHik's `HikCamera`. A device whose capabilities rule out streaming has no `Camera`.

`StreamId(channel, 1)`, the main stream, is stream `<channel>01`, the same number pyHik
computed for a recorder. A camera's address changes from `/Streaming/Channels/1` (or `/2`)
to `/Streaming/Channels/101` (or `/102`). Hikvision firmware generally accepts both, but
check this on cameras before release.

The RTSP port is the one the device reports, not always 554. The address carries the
account, as players need it, so keep it out of logs.

Level 3's `camera.snapshot()` takes no size. pyHik ignored it too; a size is level 2's,
`hik.device.streaming.snapshot(stream_id, width=, height=)`.

## Keeping the unique IDs

The library will have no pyHik compatibility layer: that is the maintainer's
decision. The IDs that users' registries hold today are rebuilt inside the
integration, from two values the library keeps raw: `Identity.device_id`, and the
`raw_type` of `TriggerLink` and `FeedFrame`.

Core builds them from pyHik's id and its `SENSOR_MAP` labels:

| What | Built in core (today) | Example |
|---|---|---|
| Config entry | `async_set_unique_id(camera.get_id)` (`config_flow.py`, line 64) | `<deviceID>` |
| Device | `(DOMAIN, device_id)` (`__init__.py`, line 168) | `<deviceID>` |
| Recorder channel device | `(DOMAIN, f"{device_id}_{channel}")` (`entity.py`, line 40) | `<deviceID>_3` |
| Binary sensor, event | `f"{device_id}_{sensor_type}_{channel}"`, where `sensor_type` is a `SENSOR_MAP` label (`binary_sensor.py`, line 222; `event.py`, line 125) | `<deviceID>_Motion_1`, `<deviceID>_I/O_1`, `<deviceID>_Tamper Detection_1` |
| Camera | `f"{device_id}_{channel.id}"`, plus `_substream` (`camera.py`, lines 68 and 77) | `<deviceID>_1_substream` |

The integration keeps pyHik's labels in its own `const.py`. `binary_sensor.py` and
`event.py` keep `SENSOR_MAP["vmd"]` and the rest, and only their import changes, from
`pyhik.constants` to `.const`:

```python
from typing import Final

# The labels pyHik 0.5.0 gave each raw event type (pyhik.constants.SENSOR_MAP; pyHik,
# MIT, Copyright (c) John Mihalic 2016). They are part of the unique IDs in users'
# registries: copied once, never edited, never derived from `model.vocabulary.Kind`.
SENSOR_MAP: Final[dict[str, str]] = {
    "vmd": "Motion", "linedetection": "Line Crossing", "fielddetection": "Field Detection",
    "videoloss": "Video Loss", "tamperdetection": "Tamper Detection",
    "shelteralarm": "Tamper Detection", "defocus": "Tamper Detection",
    "diskfull": "Disk Full", "diskerror": "Disk Error", "nicbroken": "Net Interface Broken",
    "ipconflict": "IP Conflict", "illaccess": "Illegal Access",
    "videomismatch": "Video Mismatch", "badvideo": "Bad Video", "pir": "PIR Alarm",
    "facedetection": "Face Detection", "scenechangedetection": "Scene Change Detection",
    "io": "I/O", "unattendedbaggage": "Unattended Baggage",
    "attendedbaggage": "Attended Baggage", "recordingfailure": "Recording Failure",
    "regionexiting": "Exiting Region", "regionentrance": "Entering Region",
    "duration": "Ongoing Events", "thermometry": "Thermometry",
}
```

The triggers give the same keys pyHik's `current_event_states` had: a label and its
channels, in the device's order. `channel_number` is the function from
[Device id and type](#device-id-and-type).

```python
from typing import Final

from aiohikvision.isapi.model.inventory import TriggerLink

PYHIK_METHODS: Final = frozenset({"center", "http", "record", "email", "beep"})
"""pyHik's VALID_NOTIFICATION_METHODS, in lower case as `TriggerLink.methods` holds them."""


def legacy_sensors(triggers: list[TriggerLink]) -> dict[str, list[int]]:
    """Return each pyHik label with its channels, once each, in the device's order."""
    sensors: dict[str, list[int]] = {}
    for trigger in triggers:
        raw_type = trigger.raw_type.lower()
        label = SENSOR_MAP.get(raw_type)
        if label is None or raw_type == "videoloss" or not trigger.methods & PYHIK_METHODS:
            continue
        channels = sensors.setdefault(label, [])
        if (channel := channel_number(trigger.channel_id)) not in channels:
            channels.append(channel)
    return sensors
```

The rest stays as it is:

- **Unique IDs.** `f"{device_id}_{label}_{channel}"`, `f"{device_id}_{channel}"` and
  the device identifiers keep their code. `device_id` is `legacy_device_id(hik)`.
- **The NVR workaround.** Core's own merge of extended notification methods
  (`__init__.py`, lines 104–144) and `inject_events` go away, because pyHik 0.5.0
  already uses the same method set for every device.
- **The test.** Core's `tests/components/hikvision/snapshots/test_binary_sensor.ambr`
  and `test_camera.ambr` hold 25 unique IDs (21 binary sensors, 4 cameras). The
  migrated branch must reproduce them unchanged.

The IDs are not keyed on the vocabulary's `Kind`, which would merge or lose entities:

- `diskfull` and `diskerror` are both `Kind.STORAGE`;
- `nicbroken` and `ipconflict` are both `Kind.NETWORK`;
- `defocus` is `Kind.DEFOCUS`, where pyHik said "Tamper Detection";
- `videomismatch`, `badvideo`, `unattendedbaggage`, `attendedbaggage` and
  `recordingfailure` are `Kind.OTHER`.

The raw type is exact.

One case cannot be kept. For a `deviceID` of 10 characters or fewer, pyHik made a new
`uuid4` at every start, so those entities never kept a unique ID across restarts and
there is nothing stable to reproduce. `legacy_device_id` returns `None` there. The PR
can then pick a stable base, such as the entry's stored `unique_id` or
`hik.id` (the serial). This is a one-time change, for those devices only.

## Status

A migration PR cannot be opened yet. Here is what is missing.

- **No release on PyPI.** aiohikvision 0.2.0 is not on PyPI, and core can pin only a
  release. Everything marked Available above is in its unreleased source.
- **S4 is not done.** There is no `Events` service and no `EventStates`, so the state
  and its 5-second auto-off live in the integration for now. There is no `Recorder`,
  so recorders have no StreamingProxy snapshot fallback, and their channels still come
  from `discover` and `inventory`, which S4 removes. The `triggers` and `alert_stream`
  behaviours are declared, with their rules, but no code reads them yet. A PR written
  today on `isapi.wire.feed` and `isapi.model` would have to move once S4 lands.
- **Behaviour still to check.** It is not checked yet that hassfest accepts an extra
  (`aiohikvision[isapi]`) in a core manifest. The camera address change
  (`/1` → `/101`) and the trigger channel order (`dyn*` ids first) need checking on
  real cameras and recorders.
- **Users with Basic-only devices** need an error or repair text, since the library
  refuses to send their password readable.
- **The target is moving.** The open draft core PRs build on unreleased pyHik changes
  (reauth, diagnostics, image settings, detection switches, alarm I/O, holidays), and
  aiohikvision is only partly there for them: image settings, detection switches
  (PIR and face detection missing) and I/O (IOProxy and the bulk status missing) are
  Partial, and holidays are missing (S5).
- **No migrated branch yet.** Nobody has yet made a working branch of core
  `hikvision` on aiohikvision with core's tests and `.ambr` snapshots passing. The
  state snapshots also carry `last_tripped_time`, which the migrated entities must
  still set.
