# Migrating Hikvision Bridge to aiohikvision 0.2

[Hikvision Bridge](https://github.com/yannik2480/hikvision_bridge) (`hikvision_bridge`, by
yannik2480, Apache-2.0) is where the ISAPI layer of aiohikvision comes from, under that license
(see the [License](https://github.com/webysther/aio-hikvision/blob/main/README.md#license)). It
uses aiohikvision 0.1.x through two packages: `aiohikvision.isapi.wire` (the link, the faults,
the event feed, the scrubbing of logs) and `aiohikvision.isapi.model` (discovery, the
inventory, the vocabulary of events, and one module per feature).

aiohikvision 0.2 keeps the wire layer and replaces `isapi.model`, a slice at a time, with a
`Device` and one service per domain of ISAPI. This guide lists what the bridge imports today,
what replaces each import, in which slice, and how the code changes. The snippets of the
bridge's code are short excerpts of its files (Apache-2.0), with their paths.

0.2 has [three levels](https://github.com/webysther/aio-hikvision/blob/main/README.md#three-levels).
Level 3, `Hikvision` (`aiohikvision.connect()`, or `Hikvision.from_device()` on the bridge's own
link), answers what an integration asks: start there. `hik.device` (level 2, `Device`) and the
link (level 1) are for what level 3 does not answer yet, and each snippet that goes down says why.

## Stay on 0.1.x until the migration

**aiohikvision 0.2 removes the old API without shims.** The bridge keeps working on 0.1.x until
it migrates. It pins `aiohikvision==0.1.6` today, in `manifest.json` and
`requirements_test.txt`. 0.1.7, the latest 0.1 release, only adds the door's sound over SIP,
which the bridge does not use. The 0.2 series (each part of the plan a minor release, as
before 1.0 a minor may change the API) should be taken only on the branch that migrates,
pinned exactly, with the bridge's test suites passing against it.

These names are already gone in the 0.2 betas:

- `isapi.wire.faults.BridgeFault`, now `aiohikvision.errors.HikvisionError`;
- `isapi.model.discover.read_identity_only` and `read_identity`, now
  `services.system.System(link).identity()` or `Device.identity`;
- `isapi.wire.signer`, now `aiohikvision.auth.digest`, with the same names;
- the mutable `isapi.model.inventory.Identity`, now the frozen `aiohikvision.Identity`, whose
  `firmware` is a `Firmware` that includes the build (no more `firmware_build`).

A development environment that installs aiohikvision editable from a checkout of `main` runs
0.2: install 0.1.x from PyPI there until the branch migrates.

## What the bridge imports today

| Module (0.1.x) | Names | Where |
|---|---|---|
| `isapi.wire.link` | `IsapiLink`, `Endpoint` | `config_flow.py`, `camera.py`, `runtime/bridge.py`, `runtime/playback.py`, `runtime/sessions.py` |
| `isapi.wire.faults` | `BridgeFault`; `BadCredentials`, `LockedOut`, `AuthHiccup`, `NotIsapi`, `Unreachable`, `Unsupported`, `DeviceRejected`, `detail`; `faults` (`TlsUntrusted`) | almost every platform, `runtime/*` |
| `isapi.wire.feed` | `AlarmFeed`, `stream_missing`; `FeedFrame`, `MultipartSplitter`, `Part`, `boundary_of`, `frame_from_part` | `runtime/bridge.py`; `runtime/router.py`, `runtime/hookin.py` |
| `isapi.wire.scrub` | `scrubbed_logger`, `LOG_SCRUBBER`, `scrub_text`, `MASK` | most modules; `diagnostics.py`, `services.py` |
| `isapi.wire.signer` | `Signer`, `build_signer`, `parse_challenges`, `pick` | `runtime/live.py` |
| `isapi.model.discover` | `discover`; `read_identity_only`; `CLOUD_PATH`, `read_cloud_state` | `__init__.py`; `config_flow.py`, `runtime/bridge.py`; `runtime/refresh.py`, `runtime/playback.py` |
| `isapi.model.inventory` | `DeviceProfile`, `ChannelProfile`, `StreamSpec`, `IoPort`, `StorageUnit`, `CloudLinkState`, `Identity` | `runtime/bridge.py`, `runtime/identity.py`, `camera.py`, `binary_sensor.py`, `switch.py`, `sensor.py`, `runtime/refresh.py`, `config_flow.py` |
| `isapi.model.vocabulary` | `Kind`, `SMART`, `DEVICE_WIDE`, `canonical` | the platforms, `runtime/router.py`, `runtime/refresh.py`, `services.py` |
| `isapi.model.audit` | `audit` (`run_audit`, `AuditReport`, `AuditItem`, `Finding`, `clock_skew_of`) | `runtime/bridge.py` |
| `isapi.model.ids` | `numeric_id` | `runtime/refresh.py` |
| `isapi.model.features` | `patch_and_verify`, `VerifyMismatch` | `services.py` |
| `isapi.model.features.*` | `adjust`, `image` (`ImageCapability`, `ImageValue`, `option_key`), `detection` (`DetectionState`), `privacy` (`PrivacyState`), `io`, `health` (`DeviceHealth`), `storage` (`HEALTHY`), `recordings` (`Recording`, `MediaHead`), `scrambling` (`cipher_key`, `ProgramStream`, `PTS_WRAP`), `ptz`, `park`, `signals`, `linkage`, `intercom`, `acslog` | the platforms, `services.py`, `media_source.py`, `views.py`, `websocket.py`, `runtime/*` |

The bridge also writes two paths on the link itself: `/ISAPI/System/reboot` (`button.py`) and
`/ISAPI/Event/notification/httpHosts/{slot}` (`services.py`, through `patch_and_verify`).

## What replaces each, and when

- **Available**: the 0.2 replacement exists now, or the name stays as it is.
- **Partial**: the 0.2 replacement exists now, but does less; the cell says what is missing.
- **Planned (Sx)**: the slice that brings the replacement. Until then the 0.1 module is still
  in the 0.2 betas. It leaves without a shim in that slice. "Not itemised" means that the plan
  removes the whole module in that slice, without naming its replacement.
- **Open**: the plan removes the module but names no replacement yet. To settle with the bridge
  before that slice.

The slices: **S4**, events, cameras and recorders (an `Events` service with the triggers, the
switches with a mutex pre-check, the alert feed and `EventStates`; a `Recorder` with IP, analog
and proxied channels, the StreamingProxy picture and RTSP), after which `discover` and
`inventory` leave. **S5**, the rest of the parity (protocols, IOProxy and the bulk IO status,
holidays, httpHosts, reboot, PIR and FaceDetect, image settings from the capabilities, storage,
recordings without per-link globals), after which `isapi.model.features` leaves. **S6**, door
stations on `Device` (`video_intercom`, `access_control`, `two_way_audio`, a typed `settings`
service), after which `DoorStation` leaves, and 0.2.0 final. Below, `hik` is the bridge's
`Hikvision`, `device` is `hik.device`, and `camera` one of `hik.cameras`.

| 0.1.x | 0.2 | Status |
|---|---|---|
| `IsapiLink`, `Endpoint` | Unchanged. `await Hikvision.from_device(await Device.from_link(link))` builds level 3 on the bridge's own link (its TLS context, `trusted=True`): one link per device. | Available |
| `BridgeFault` | `aiohikvision.errors.HikvisionError`. | Available |
| `BadCredentials`, `LockedOut`, `AuthHiccup`, `NotIsapi`, `Unreachable`, `TlsUntrusted`, `Unsupported`, `DeviceRejected`, `detail` | Unchanged. A 501 without a sub status is now `Unsupported`. | Available |
| `AlarmFeed` | Unchanged in the wire layer; `on_state` gets a `HikvisionError`. S4 offers the feed on `Device` through `Events`, with `EventStates` (hold times) that can replace the timers of `runtime/router.py`. | Available |
| `stream_missing` | Unchanged; `device.behaviours.alert_stream` (`AlertStream.NONE`) also says it for the models a rule knows, without a request. | Available |
| `FeedFrame`, `MultipartSplitter`, `Part`, `boundary_of`, `frame_from_part` | Unchanged: the webhook path (`runtime/hookin.py`) keeps them. | Available |
| `scrubbed_logger`, `LOG_SCRUBBER`, `scrub_text`, `MASK` | Unchanged. New beside them: `isapi.wire.anonymize.Anonymizer`, and `await hik.report()` for the diagnostics. | Available |
| `isapi.wire.signer` (`Signer`, `build_signer`, `parse_challenges`, `pick`) | `aiohikvision.auth.digest`, same names. | Available |
| `read_identity_only` | `aiohikvision.connect(...)` → `hik.id`, `hik.name`, `hik.serial`; the whole `Identity` (with the MAC) is `hik.device.identity`. One GET only: `await System(link).identity()` (`aiohikvision.services.system`). | Available |
| `inventory.Identity` | `aiohikvision.Identity`, frozen: `str(identity.firmware)` replaces `firmware` and `firmware_build`; `device_id` is new. Level 3 has `hik.name`, `hik.model`, `hik.serial` and `hik.firmware`. | Available |
| `StreamSpec` | `aiohikvision.Stream` (`id`: `StreamId`, `name`, `video`: `VideoFormat`, `audio`: `AudioCodec`): the `streams` of each `Camera` of `hik.cameras` (`camera.main`, `camera.sub`). | Available |
| Snapshot paths in `camera.py` | `await camera.snapshot(stream_id)`; a size, such as the stream's own that the bridge asks for, is level 2's: `camera.streaming.snapshot(stream_id, width=, height=)`. JPEG checked, `DeviceRejected` otherwise. Missing: the StreamingProxy picture of recorders (S4), and remembering a refused size. | Partial |
| RTSP address in `camera.py` | `await camera.stream_url(stream_id)`: account escaped, the device's RTSP port (`device.streaming.rtsp_port()`). Missing: the bridge's port option and the port of a direct camera route (replace the port with yarl); the encrypted relay (`LiveRelay`) is the bridge's own. | Partial |
| `health` (`DeviceHealth`, `read_status`, `read_recording`) | Not itemised (S5). New, which the bridge does not read today: the open video sessions, `await device.streaming.sessions()`. | Planned (S5) |
| `discover` | `Hikvision.from_device(await Device.from_link(link))` (identity, capabilities, behaviours, cameras), then the `Recorder` and `Events` (S4); IO, storage and settings (S5). Until S4, `discover(link)` still runs beside it on the same link. | Planned (S4) |
| `DeviceProfile`, `ChannelProfile`, `DeviceShape` | `hik.kind` (`recorder`, `camera`, ...) and `hik.cameras` (a `Camera` per channel, with its streams). Missing: the IP, analog and proxied channels, their names and state: the `Recorder` (S4). | Partial |
| `Kind`, `SMART`, `DEVICE_WIDE`, `canonical` | The event models of `Events` (not `aiohikvision.Kind`, which is what a device is). | Planned (S4) |
| `detection` (`DetectionState`, `read`, `switch`) | `Events`: switch a detection on or off after the mutex pre-check. PIR and FaceDetect: S5. | Planned (S4) |
| `linkage` (`parse_triggers`, `ensure_center`) | The triggers of `Events`. | Planned (S4) |
| `io` (`read_state`, `read_armed`, `set_armed`, `set_output`), `IoPort` | An IO service, with IOProxy ports and the bulk `/ISAPI/System/IO/status`. | Planned (S5) |
| `storage` (`read`, `HEALTHY`), `StorageUnit` | A storage service. | Planned (S5) |
| `recordings` (`search`, `fix_basis`, `Recording`, `MediaHead`, ...) | A recordings service, without the per-link globals that `fix_basis(link, ...)` keeps today. | Planned (S5) |
| `scrambling` (`cipher_key`, `ProgramStream`, `PTS_WRAP`) | Moves with the recordings; still the `[scrambling]` extra. | Planned (S5) |
| `adjust`, `image` (`ImageCapability`, `ImageValue`, `option_key`) | Image settings read from the capabilities (S5); a typed `Settings.write(setting, value)` in S6. `ImageCapability` and `ImageValue` are also top-level names today, for the door station's settings. | Planned (S5) |
| `patch_and_verify`, `VerifyMismatch`; the httpHosts write of `services.py` | httpHosts (the webhook target) as a service; the services read their writes back. | Planned (S5) |
| Reboot by `link.write_xml("/ISAPI/System/reboot", "")` | Reboot as a service. | Planned (S5) |
| `privacy`, `signals`, `ptz`, `park` | Not itemised (S5). The target layout has a `ptz` service. | Planned (S5) |
| `intercom` (`remote_open_door`), `acslog` | Today `DoorStation.open_door()`, itself replaced in S6. Door stations on `Device` with the `access_control` service (the access log is not itemised). | Planned (S6) |
| `CLOUD_PATH`, `read_cloud_state`, `CloudLinkState` | `discover.py` leaves in S4; the EZVIZ state has no named home yet. | Open |
| `audit` | No named replacement; the report (`hik.report()`) covers what a device answers, not the findings (default password, center link, clock skew). | Open |
| `ids.numeric_id` | A small helper with no named home: keep a copy in the bridge. | Open |

## Before and after

Each "before" is an excerpt of the bridge on 0.1.x, quoted as it is, or wrapped in a function
so that it stands alone. Each "after" uses only names that exist in the 0.2 betas, or says
`# planned (Sx)`. The bridge's own helpers (`device_context`, `_raise_write_error`, `_fail`,
the constants) keep their names.

### Checking a login (config flow)

Before, `custom_components/hikvision_bridge/config_flow.py` (in the loop over the schemes):

```python
from aiohikvision.isapi.model.discover import read_identity_only
from aiohikvision.isapi.wire import faults
from aiohikvision.isapi.wire.link import Endpoint, IsapiLink


async def _attempt(session, data, port, scheme, verify):  # the loop body, as a function
    last: faults.BridgeFault | None = None
    link = IsapiLink(
        session,
        Endpoint(data[CONF_HOST].strip(), int(port), scheme),
        data[CONF_USERNAME],
        data[CONF_PASSWORD],
        ssl_context=device_context(verify),
    )
    identity = await read_identity_only(link)
```

After:

```python
import aiohikvision
from aiohikvision.errors import HikvisionError


async def _attempt(session, data, port, scheme, verify):
    last: HikvisionError | None = None
    async with aiohikvision.connect(
        data[CONF_HOST].strip(),
        data[CONF_USERNAME],
        data[CONF_PASSWORD],
        session=session,  # the bridge's session: left open
        port=int(port),
        https=scheme == SCHEME_HTTPS,
        ssl_context=device_context(verify),
    ) as hik:
        # hik.id, hik.name and hik.serial answer at level 3; the flow keeps the whole
        # Identity for its MAC, which only level 2 has
        identity = hik.device.identity
```

### Setting up a device

Before, `custom_components/hikvision_bridge/__init__.py` (`_async_setup_device`, abridged):

```python
async def _async_setup_device(hass: HomeAssistant, entry: BridgeConfigEntry) -> bool:
    link = build_link(hass, dict(entry.data))
    try:
        profile = await discover(link)
    except (BadCredentials, AuthHiccup) as err:
        # A refusal during setup is not retried: setup retries would each cost logins.
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN, translation_key="bad_credentials"
        ) from err
    except BridgeFault as err:
        raise ConfigEntryNotReady(str(err)) from err
```

After:

```python
from aiohikvision import Device, Hikvision
from aiohikvision.errors import HikvisionError
from aiohikvision.isapi.model.discover import discover  # until S4
from aiohikvision.isapi.wire.faults import AuthHiccup, BadCredentials


async def _async_setup_device(hass: HomeAssistant, entry: BridgeConfigEntry) -> bool:
    link = build_link(hass, dict(entry.data))
    try:
        # Level 3 on the bridge's own link: who the device is, what it supports, its cameras
        hik = await Hikvision.from_device(await Device.from_link(link))
        profile = await discover(link)  # the same link: one login state per device
    except (BadCredentials, AuthHiccup) as err:
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN, translation_key="bad_credentials"
        ) from err
    except HikvisionError as err:
        raise ConfigEntryNotReady(str(err)) from err
    # planned (S4): the Recorder's channels and the Events' triggers replace discover();
    # planned (S5): IO ports, storage and settings
```

### The device's firmware

Before, `custom_components/hikvision_bridge/runtime/identity.py`:

```python
def main_device_info(profile: DeviceProfile, base_url: str) -> DeviceInfo:
    identity = profile.identity
    info = DeviceInfo(
        identifiers={(DOMAIN, device_key(profile))},
        manufacturer=VENDOR,
        model=identity.model,
        name=identity.name,
        serial_number=identity.serial or None,
        sw_version=" ".join(p for p in (identity.firmware, identity.firmware_build) if p),
        hw_version=identity.hardware,
        configuration_url=base_url,
    )
    if identity.mac:
        info["connections"] = {("mac", identity.mac.lower())}
    return info
```

After (`device_key` keeps taking what it takes today, so the identifiers do not change):

```python
from aiohikvision import Hikvision


def main_device_info(hik: Hikvision, key: str, base_url: str) -> DeviceInfo:
    identity = hik.device.identity  # the hardware and the MAC have no level-3 answer yet
    info = DeviceInfo(
        identifiers={(DOMAIN, key)},
        manufacturer=VENDOR,
        model=hik.model,
        name=hik.name,
        serial_number=hik.serial or None,
        sw_version=str(hik.firmware),  # "V5.7.0 build 220112", as the device wrote it
        hw_version=identity.hardware,
        configuration_url=base_url,
    )
    if identity.mac:
        info["connections"] = {("mac", identity.mac.lower())}
    return info
```

### Snapshot and RTSP address

Before, `custom_components/hikvision_bridge/camera.py` (`ChannelCamera`, abridged):

```python
async def stream_source(self) -> str | None:  # the end of the method
    user = quote(data[CONF_USERNAME], safe="")
    password = quote(data[CONF_PASSWORD], safe="")
    host = link.endpoint.base.split("://", 1)[1].rsplit(":", 1)[0]
    return f"rtsp://{user}:{password}@{host}:{port}/Streaming/Channels/{stream_id}"


async def async_camera_image(self, width=None, height=None) -> bytes | None:
    link, stream_id, _ = self._source()
    paths = []
    if link is self.bridge.link and self.bridge.profile.shape.records:
        paths.append(f"/ISAPI/ContentMgmt/StreamingProxy/channels/{stream_id}/picture")
    paths.append(f"/ISAPI/Streaming/channels/{stream_id}/picture")
```

After (for a stream of the bridge's own link; `self._camera` is the `Camera` of the channel,
from `bridge.hik.cameras`, and `self._stream` one of its `streams`):

```python
from yarl import URL

from aiohikvision.errors import HikvisionError
from aiohikvision.isapi.wire.faults import detail


async def stream_source(self) -> str | None:
    address = await self._camera.stream_url(self._stream.id)  # on the device's RTSP port
    port = self.bridge.entry.options.get(OPT_RTSP_PORT)
    return str(URL(address).with_port(int(port))) if port else address


async def async_camera_image(self, width=None, height=None) -> bytes | None:
    video = self._stream.video
    # planned (S4): the Recorder's picture through the StreamingProxy for recorder channels
    try:
        # The stream's own size: level 3's camera.snapshot() takes none, its level-2 service does
        return await self._camera.streaming.snapshot(
            self._stream.id,
            width=video.width if video else None,
            height=video.height if video else None,
        )
    except HikvisionError as err:
        _LOGGER.debug("Snapshot of channel %s failed: %s", self.channel_id, detail(err))
        return None
```

### An alarm output

Before, `custom_components/hikvision_bridge/switch.py` (`AlarmOutputSwitch`):

```python
async def _apply(self, on: bool) -> None:
    try:
        await io.set_output(self.bridge.link, self._port, on)
    except BridgeFault as err:
        _raise_write_error(err)
        return
    self.coordinator.data.outputs[self._port.port_id] = on
    self.async_write_ha_state()
```

After, on the 0.2 betas until S5 (level 3 has no IO yet, so it stays on the bridge's link):

```python
from aiohikvision.errors import HikvisionError
from aiohikvision.isapi.model.features import io  # until S5


async def _apply(self, on: bool) -> None:
    try:
        await io.set_output(self.bridge.link, self._port, on)
    except HikvisionError as err:
        _raise_write_error(err)
        return
    self.coordinator.data.outputs[self._port.port_id] = on
    self.async_write_ha_state()
    # planned (S5): an IO service on the Device replaces io.set_output and io.read_state,
    # with IOProxy ports and the status of every port at once
```

The detections (`detection.switch`, S4), the restart button (`link.write_xml` of
`/ISAPI/System/reboot`, S5) and the webhook target (`patch_and_verify` of httpHosts, S5) change
the same way: `BridgeFault` becomes `HikvisionError` now, and the call becomes a service in its
slice.

### The event stream

Before, `custom_components/hikvision_bridge/runtime/bridge.py` (`async_probe_extras` and
`start_feeds`, abridged):

```python
async def async_probe_extras(self) -> None:
    profile = self.profile
    if self._wants_stream() and await stream_missing(self.link):
        profile.has_alert_stream = False


def start_feeds(self) -> None:
    main = AlarmFeed(
        self.link,
        self.router.make_handler(Origin(MAIN_FEED, exclusive_channels=camera_channels)),
        lambda up, fault: self.router.feed_state(MAIN_FEED, up, fault),
    )
```

After, on `hik.device`: level 3 has no events yet (S4).

```python
from aiohikvision import AlertStream, Hikvision
from aiohikvision.isapi.wire.feed import stream_missing


async def has_alert_stream(hik: Hikvision) -> bool:
    """Whether to open the alert stream: a rule may know the device has none."""
    if hik.device.behaviours.alert_stream is AlertStream.NONE:
        return False  # DS-KV8113-WME1(B) V2.2.53, for one: no request needed
    # planned (S4): Events opens the feed on the Device; AlarmFeed itself stays in the wire layer
    return not await stream_missing(hik.device.link)
```

`start_feeds` keeps `AlarmFeed` as it is. The handler of `feed_state` types its fault as
`HikvisionError | None`.

### Diagnostics

Before, `custom_components/hikvision_bridge/diagnostics.py`:

```python
def _profile(bridge) -> dict:  # the lines of async_get_config_entry_diagnostics
    profile = asdict(bridge.profile)
    identity = profile["identity"]
    identity["serial"] = MASK
    identity["mac"] = MASK
    return profile
```

After, beside the bridge's own data:

```python
async def _capabilities(bridge) -> dict:
    """What the device answers, anonymized: no account, address, serial, MAC or given names."""
    report = await bridge.hik.report()  # GET only, never NEVER_READ paths
    return report.as_dict()
```

`bridge.hik` is a field the bridge adds beside `link`. The report masks the address and the
account itself; level 2's `device.report(secrets=...)` takes more to mask. The bridge's
`report` field (the audit) keeps its name.

### The digest of the live relay

Before, `custom_components/hikvision_bridge/runtime/live.py`:

```python
from aiohikvision.isapi.wire.signer import Signer, build_signer, parse_challenges, pick
```

After:

```python
from aiohikvision.auth.digest import Signer, build_signer, parse_challenges, pick
```

## Pinning 0.2

- Require `aiohikvision[isapi,scrambling]` at an exact version
  (`"aiohikvision[isapi,scrambling]==0.2.0"`): the recordings use `cryptography`.
- Home Assistant compares only the name and the version of a requirement, not its extras,
  but it ships aiohttp, yarl and cryptography, all that `isapi` and `scrambling` need:
  defusedxml comes with the extra, and without it a guarded parser reads the XML.
- Keep `"loggers": ["aiohikvision"]`. The debug log now says, in one record, how each device was
  recognised: its domains, how the library covers each, and the behaviours a rule set.
