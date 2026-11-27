# Hikvision intercom projects, and what aiohikvision can take from them

A guide for the projects that the Home Assistant integration "Hikvision Virtual Indoor Station"
lists as related. For each one: what it relies on, what aiohikvision covers today, what is new to
the library, and how the project could do the same with aiohikvision.

- **Read on:** 2026-11-27, from local clones (no network). A `path:line` is relative to the
  root of that project's repository.
- **Already known, and not repeated as new:** the research notes of 2026-11-26
  (`intercom-projects.md`, `sip-and-hikvision-next.md`, cited as "notes P1#2" and so on),
  [DEVICE_FINDINGS.md](../DEVICE_FINDINGS.md), and the library's source.
- **Licenses:** aiohikvision is MIT, with the parts derived from Hikvision Bridge under
  Apache-2.0. Code under MIT or Apache-2.0 may be adapted: it keeps its license and is named in
  the [License](https://github.com/webysther/aio-hikvision/blob/main/README.md#license) section
  of the README, so the facts are preferred. A project without a license, and anything from the
  Hikvision SDK (its libraries, headers and manuals), gives **facts only**: the code is written
  clean-room.
- **Addresses** are documentation addresses (192.0.2.x). The projects' own example addresses,
  SIP numbers and names are left out.

## Licenses at a glance

| Project | License | Constraint |
|---|---|---|
| pergolafabio/Hikvision-Addons | none at the root; bundles the proprietary Hikvision SDK (`hikvision-doorbell/lib-amd64`, `lib-aarch64`) and its manuals; `hikvision-doorbell/examples/hikcli-main` alone is Apache-2.0 | facts only |
| arturzx/sip-indoor-station | none | facts only |
| arturzx/sip-indoor-station-integration | none | facts only |
| arturzx/sip-indoor-station-card | none (`"license": "MIT"` in `package.json` only, no license text) | facts only |
| arturzx/hass-addons | none | facts only |
| acardace/hikvision-doorbell-integration | Apache-2.0 | code may be adapted |
| acardace/hikvision-doorbell-server | Apache-2.0 | code may be adapted |
| schmidt-gabriel/hikvision-intercom-hass-integration | MIT | code may be adapted |
| TimLuist1/hikvision-intercom | MIT; its add-on downloads the proprietary SDK at build time (`hikvision_sdk_bridge/fetch-sdk.sh`) | MIT code may be adapted; SDK bindings: facts only |
| tomasbedrich/home-assistant-hikconnect | none (Hik-Connect cloud) | facts only |
| DmytryS/intercom-homekit | MIT, except the bundled proprietary HCNetSDK (`intercom_homekit/vendor/hcnetsdk`, README.md:97-103) | MIT code may be adapted; SDK: facts only |
| emilianogetino/hikvision-isapi-bridge | MIT | code may be adapted |

## 1. What each project relies on

"Not yet" names the research note that already plans it, when there is one.

### pergolafabio/Hikvision-Addons

| Item | Detail (where) | aiohikvision today |
|---|---|---|
| Does | MQTT add-on for door and indoor stations: SDK login on port 8000 for rings, door events and talk-back; ISAPI tunnelled through the SDK (`NET_DVR_STDXMLConfig`) for the rest | — |
| Call status | `GET /ISAPI/VideoIntercom/callStatus?format=json`, polled (`hikvision-doorbell/src/mqtt.py:261`) | `DoorStation.call_status()` |
| Call commands | `PUT /ISAPI/VideoIntercom/callSignal?format=json` `{"CallSignal":{"cmdType":"answer"\|"reject"\|"hangUp"}}`, SDK fallback on SDK error 23 (`hikvision-doorbell/src/mqtt_input.py:601-664`) | not covered: a no-op on doors (notes, "Do not") |
| Caller | `GET /ISAPI/VideoIntercom/callerInfo?format=json` (`hikvision-doorbell/src/mqtt_input.py:673`) | not yet (notes P3) |
| Open a door | `PUT /ISAPI/AccessControl/RemoteControl/door/{n}` `<cmd>open</cmd>`, after the SDK's `NET_DVR_RemoteControl` (`hikvision-doorbell/src/doorbell.py:167-196`) | `DoorStation.open_door()` |
| Door count | user option, SDK ability `IOOutNo@max`, `IO/outputs` count, `RemoteControl/door/capabilities` `doorNo@max`, `deviceInfo` `electroLockNum` (`hikvision-doorbell/src/doorbell.py:1000-1053`) | `DoorStationInfo.doors`, `DoorStation.read_outputs()`; `electroLockNum` not parsed |
| Volumes | `GET/PUT /ISAPI/System/Audio/AudioOut/channels/1` `volume`, `talkVolume`; mute = volume 0 (`hikvision-doorbell/src/doorbell.py:1138-1197`) | `DoorStation.read_settings()`: `output_volume`, `talk_volume`, `input_volume` |
| Snapshot | `GET /ISAPI/Streaming/channels/{ch}/picture?snapShotImageType=JPEG&videoResolutionWidth=1280&videoResolutionHeight=720&imageQuality=best` (`hikvision-doorbell/src/doorbell.py:316`) | `Camera.snapshot()`; a size: `Streaming.snapshot(width=, height=)`; `snapShotImageType` and `imageQuality` not sent |
| Reboot | `PUT /ISAPI/System/reboot` (`hikvision-doorbell/src/doorbell.py:906`) | not yet (notes P3) |
| Call button | `GET/PUT /ISAPI/VideoIntercom/keyCfg/1` (`doorbell/ISAPI.md:10-11`) | not yet (notes P3) |
| Relay | `PUT /ISAPI/System/IO/outputs/{n}/trigger` `outputState` high/low (`doorbell/ISAPI.md:20-21`) | `set_output()` in `aiohikvision.isapi.model.features.io`; not on `DoorStation` |
| Button backlight | `GET/PUT /ISAPI/VideoIntercom/SubModuleBacklight?format=json` (`doorbell/ISAPI.md:22-24`, `hikvision-doorbell/src/mqtt_input.py:814`) | not yet |
| Indoor station | `PUT /ISAPI/SecurityCP/control/outputs/{n}?format=json` `{"OutputsCtrl":{"switch":"open"\|"close"}}` (`hikvision-doorbell/src/doorbell.py:136-164`); `POST /ISAPI/SecurityCP/status/outputStatus?format=json` (`doorbell/ISAPI.md:13`); `GET/PUT /ISAPI/VideoIntercom/scene/nowMode` (`hikvision-doorbell/src/mqtt_input.py:264`, `831-874`); `GET/PUT /ISAPI/SecurityCP/AlarmControlByPhone` (`hikvision-doorbell/src/mqtt_input.py:305`, `887-902`) | not yet |
| Users and cards | `POST /ISAPI/AccessControl/UserInfo/Search?format=json`, `CardInfo/Search` (`hikvision-doorbell/src/doorbell.py:1114`, `1130`) | not yet |
| Rings, door events, talk | SDK alarm channel (`COMM_ALARM_VIDEO_INTERCOM`, `COMM_ALARM_ACS`: `hikvision-doorbell/src/event.py:197-207`) and SDK voice talk | rings: `CallServer` (SIP); door events: `AccessLog.poll()`; talk: `DoorStation.talk()`, `Talkback` |
| SIP (Asterisk as an indoor extension) | REGISTER to the indoor station's SIP server on UDP 5065, digest MD5, a `<regXML>` body (`asterisk/asterisk.as.indoor.md:39-64`, `asterisk/hikvision_register.py:69-76`, `190-208`) | not yet (`<regXML>`: notes P3) |
| SIP (to ring an indoor station) | commented-out INVITE with `a=doorFloor:0`, `a=responseType:0`, `a=doorType:1`, `a=isSpecialType:0` in the SDP (`hikvision-doorbell/src/doorbell.py:794-838`, inside a `'''` block) | not yet |

### arturzx/sip-indoor-station (SIS)

| Item | Detail (where) | aiohikvision today |
|---|---|---|
| Does | SIP registrar and callee for door stations, bridged to browsers over WebRTC with GStreamer; optional vendor HTTP APIs | — |
| REGISTER | digest MD5, `qop="auth"`, nonce TTL 300 s, `stale=true` (`src/sip_indoor_station/sip/digest.py:72`, `94-97`) | `DoorRegistrar` without challenge; digest: not yet (notes P2#4) |
| Methods | REGISTER, OPTIONS (200 with `Allow`), INVITE, ACK, BYE, CANCEL; others 405 (`src/sip_indoor_station/sip/server.py:138-150`) | `DoorRegistrar`, `CallServer`; OPTIONS answered by aiosipua's UAS |
| INVITE | retransmissions absorbed by Call-ID, CSeq and source; 403 from an unregistered source; 488 without SDP (`src/sip_indoor_station/sip/server.py:241-262`) | retransmissions: not yet (notes P1); unknown sources: `DoorTransport.allowed_hosts` drops them; 488 at once: not yet (notes P3) |
| Answer | PCMA first, else PCMU; `a=sendrecv`; video rejected with `m=video 0` (`src/sip_indoor_station/sip/sdp.py:58-88`) | `CallServer.answer()`: the door's first G.711, `a=ptime:40`, `m=video 0`, `a=sendrecv` with `on_audio` |
| Media | jitter buffer 60 ms (`src/sip_indoor_station/media/gstreamer_webrtc_bridge.py:56`) | `DoorSound` (no jitter buffer: the consumer plays) |
| ISAPI | `callStatus` (`src/sip_indoor_station/vendor/hikvision/call.py:18`), `callSignal` reject/hangUp (`src/sip_indoor_station/vendor/hikvision/call.py:25-38`), `RemoteControl/door/{relay}` (`src/sip_indoor_station/vendor/hikvision/door.py:43`), `Streaming/channels/{ch}/picture` (`src/sip_indoor_station/vendor/hikvision/snapshot.py:13`), `deviceInfo` as health check and `PUT /ISAPI/System/reboot` (`src/sip_indoor_station/vendor/hikvision/maintenance.py:17`, `25`) | `DoorStation.call_status()`, `DoorStation.open_door()`, `Camera.snapshot()`, `Hikvision.check()`; reboot not yet |

### arturzx/sip-indoor-station-integration

| Item | Detail (where) | aiohikvision today |
|---|---|---|
| Does | Home Assistant integration that polls the SIS add-on's HTTP API and opens its WebRTC socket | — |
| Relies on | SIS's `GET /api/state`, `/api/config`, `/api/call_history` (`custom_components/sip_indoor_station/api.py:59-96`); no ISAPI or SIP of its own | the same state in process: `CallServer(on_change=...)`, `DoorRegistrar(on_change=...)`, `CallServer.calls` (the latest ended calls) |

### arturzx/sip-indoor-station-card

| Item | Detail (where) | aiohikvision today |
|---|---|---|
| Does | Lovelace card: WebRTC to SIS, microphone, call history | — |
| Relies on | `/api/sip_indoor_station/webrtc/*` (`sip-indoor-station-card.js:1-4`); `getUserMedia` at 8 kHz with echo cancellation (`sip-indoor-station-card.js:309-314`) | server side: `DoorCall.push()` (20 ms G.711 frames in), `CallServer(on_audio=...)` (40 ms G.711 out) |

### arturzx/hass-addons

| Item | Detail (where) | aiohikvision today |
|---|---|---|
| Does | Packages SIS as a Home Assistant add-on | — |
| Relies on | UDP 5060 (SIP), a fixed RTP port 40000, UDP 8556 (ICE) (`sip_indoor_station/config.yaml:16-18`) | SIP port: `DoorTransport(local_addr=...)`; RTP: one ephemeral port per call (`Talkback`); a fixed range: not yet (notes P3) |

### acardace/hikvision-doorbell-integration

| Item | Detail (where) | aiohikvision today |
|---|---|---|
| Does | Home Assistant client of hikvision-doorbell-server: play a file at the door, abort, a camera from Frigate | — |
| Relies on | the server's `POST /api/audio/play-file` and `POST /api/abort` (`custom_components/hikvision_doorbell/coordinator.py:39-101`) | `DoorStation.talk()` → `TwoWayAudio.send()`; abort: `TwoWayAudio.close()`, `DoorStation.close()`; `aiohikvision.media.g711` |

### acardace/hikvision-doorbell-server

| Item | Detail (where) | aiohikvision today |
|---|---|---|
| Does | Go server: WebRTC two-way audio and file playback over ISAPI two-way audio | — |
| Channels | `GET /ISAPI/System/TwoWayAudio/channels`; takes the first with `enabled=false` as free (`internal/hikvision/client.go:120`, `internal/session/hikvision.go:40-47`) | `DoorStation.read_info()` → `DoorStationInfo.talk` (first G.711 channel, `enabled` ignored) |
| Open, close | `PUT .../channels/{id}/open` (reads `sessionId`), `PUT .../close` (`internal/hikvision/client.go:163-230`); abort closes every channel listed `enabled=true` (`internal/api/abort.go:161-181`) | `TwoWayAudio.open()` (closes first, then opens), `TwoWayAudio.close()` |
| Send | `PUT .../audioData` without `sessionId`, `Content-Length: 0`, then raw G.711 paced at 8000 bytes/s (`internal/hikvision/stream_writer.go:30-33`, `87-88`, `167-171`) | `TwoWayAudio.send()` (no pacing: frames go as they come) |
| Receive | `GET .../audioData?sessionId=` streams the door's microphone (`internal/hikvision/stream_reader.go:27-30`, `53-78`) | not yet (notes P3); during a SIP call: `CallServer(on_audio=...)` |
| Digest | retries once a 401 with an empty `WWW-Authenticate` (`internal/hikvision/client.go:93-104`) | known (notes P2#3) |

### schmidt-gabriel/hikvision-intercom-hass-integration

| Item | Detail (where) | aiohikvision today |
|---|---|---|
| Does | Home Assistant integration for a DS-KB8113-IME1(B) (V2.2.60): rings from `callStatus` polling, door, always-open, relays, two-way audio switch, capability probing | — |
| Identity | `deviceInfo`: `deviceType` VIS, `subDeviceType` villaDoorStation, `alarmInNum`/`alarmOutNum` (`docs/protocol.md:12-22`) | `Hikvision.kind` (`door_station` for VIS), from `Identity.device_type`; `subDeviceType` not parsed |
| Digest | fresh handshake per request; `uri` with the query; no empty `opaque` (`docs/protocol.md:24-62`, `custom_components/hikvision_intercom/isapi/client.py:136-155`) | digest signs the path with its query; empty `opaque` and nonce age: notes P2#3 |
| Formats | `?format=json` ignored by door control; errors as HTTP 200 with `ResponseStatus` (`docs/protocol.md:64-71`) | `IsapiLink` faults (200 with an embedded failure) |
| alertStream | 200, 40 bytes, closes (`docs/protocol.md:75-102`, `custom_components/hikvision_intercom/isapi/const.py:34-39`) | `AlarmFeed`, `AlertStream.NONE`; no rule for this model yet |
| httpHosts | `GET/PUT/DELETE /ISAPI/Event/notification/httpHosts`, `/capabilities` (`docs/protocol.md:104-152`) | not yet (notes P2#7; useless on intercoms) |
| Call status | `GET /ISAPI/VideoIntercom/callStatus?format=json`, `/callStatus/capabilities?format=json` (`custom_components/hikvision_intercom/isapi/const.py:16-17`) | `DoorStation.call_status()`; capabilities not read |
| Call commands | `callSignal` answer/reject/hangUp (`custom_components/hikvision_intercom/isapi/const.py:18`, `66-69`) | not covered (notes, "Do not") |
| Call times | `GET /ISAPI/VideoIntercom/operationTime`, `/capabilities` (`docs/protocol.md:216-235`) | `Device.report()` reads it; a setting: notes P2#8 |
| Door | `PUT RemoteControl/door/{n}` XML only; `cmd opt="open,alwaysOpen,resume"` (`docs/protocol.md:243-255`, `custom_components/hikvision_intercom/switch.py:63-91`) | `DoorStation.open_door()`; alwaysOpen/resume: notes P1#2 |
| Relays | `GET /ISAPI/System/IO/capabilities` `IOOutputPortNums`; `PUT IO/outputs/{n}/trigger` (`docs/protocol.md:257-263`) | `Supports.outputs`, `DoorStation.read_outputs()`, `set_output()` in `isapi.model.features.io` |
| Video | `Streaming/channels`, `/101/picture`, RTSP `/Streaming/Channels/101` (`docs/protocol.md:265-275`) | `Camera.streams`, `Camera.snapshot()`, `Camera.stream_url()` |
| Two-way audio | `PUT /ISAPI/System/TwoWayAudio/channels/{n}` with `<enabled>true</enabled>` (`custom_components/hikvision_intercom/isapi/client.py:269-282`) | not yet (see P2 below) |
| Other | `workStatus` 404 although advertised; `Event/triggers` lists only VMD; `GET /ISAPI/VideoIntercom/deviceCommunication` (`docs/protocol.md:287-314`) | `linkage.parse_triggers()`; the others not yet |

### TimLuist1/hikvision-intercom

| Item | Detail (where) | aiohikvision today |
|---|---|---|
| Does | Home Assistant integration plus an add-on that drives a 2-wire kit (DS-KIS701 class) through the SDK on port 8000 | — |
| Transport | ports 80 and 443 closed: no HTTP ISAPI; ISAPI tunnelled through `NET_DVR_STDXMLConfig` (`docs/PROTOCOL.md:6-18`, `46-59`) | none: aiohikvision speaks ISAPI over HTTP only |
| ISAPI (tunnelled) | `RemoteControl/door/{n}`, `callSignal`, `callerInfo`, `deviceInfo`, `reboot` (`docs/PROTOCOL.md:53-59`, `hikvision_sdk_bridge/rootfs/opt/bridge/intercom.py:193-222`) | `DoorStation.open_door()` etc., on devices with HTTP ISAPI |
| SIP | YATE 2.0.0 on UDP 5060: answers OPTIONS and INVITE (100), REGISTER 501, a blind INVITE ends with 487 (`docs/PROTOCOL.md:27-33`) | not used |

### tomasbedrich/home-assistant-hikconnect

| Item | Detail (where) | aiohikvision today |
|---|---|---|
| Does | Hik-Connect cloud integration (`hikconnect==3.2.7`, `cloud_polling`: `custom_components/hikconnect/manifest.json:17-24`) | — |
| Relies on | cloud call status polled every 3 s: `idle`, `ringing`, `call in progress` (`custom_components/hikconnect/sensor.py:25`, `62-112`); cloud unlock, the latch assumed relocked after 5 s (`custom_components/hikconnect/lock.py:17`, `86-106`); cloud snapshots at most once a minute, slow on DS-KD8003 (`custom_components/hikconnect/camera.py:25-31`); cloud video wrapped in MPEG-TS (`custom_components/hikconnect/tsmux.py:1-5`) | the LAN equivalents: `DoorStation.call_status()`, `DoorStation.open_door()`, `Camera.snapshot()`, `Camera.stream_url()`; no cloud API (out of scope) |

### DmytryS/intercom-homekit

| Item | Detail (where) | aiohikvision today |
|---|---|---|
| Does | HomeKit doorbell and MQTT entities for a DS-KV6113-WPE1(B) (V2.2.53); talk-back through the bundled SDK | — |
| Rings | `callStatus` polled every second (`intercom_homekit/src/drivers/hikvision/callMonitor.ts:24-36`, `intercom_homekit/src/drivers/hikvision/isapi.ts:166-178`), plus the SDK alarm channel: video intercom alarm type 17 ring, 18 dismissed (`intercom_homekit/src/drivers/hikvision/alarm.ts:4-21`) | `DoorStation.call_status()`; rings over SIP: `CallServer` |
| Call commands | `callSignal` `hangUp`/`reject`/`answer` before talk-back while it rings (`intercom_homekit/src/drivers/hikvision/talkback.ts:175-198`, `intercom_homekit/DOCS.md:186`) | not covered (notes, "Do not"; but see P2 below) |
| Door, reboot | `RemoteControl/door/{n}` (`intercom_homekit/src/drivers/hikvision/isapi.ts:187-191`), `PUT /ISAPI/System/reboot` (`intercom_homekit/src/drivers/hikvision/isapi.ts:193-195`) | `DoorStation.open_door()`; reboot not yet |
| Volumes | `AudioOut/channels/1` `volume` and `talkVolume`, `AudioIn/channels/1` `volume`, 0-10 (`intercom_homekit/src/drivers/hikvision/isapi.ts:47-52`, `197-218`) | `DoorStation.read_settings()`: `output_volume`, `talk_volume`, `input_volume` |
| Sessions | `GET /ISAPI/Streaming/status` (`totalStreamingSessions`, client addresses), `GET /ISAPI/Security/onlineUser` (`intercom_homekit/src/drivers/hikvision/isapi.ts:220-235`, `intercom_homekit/DOCS.md:200-214`) | `Streaming.sessions()`, `DoorStationHealth.video_sessions`; onlineUser not yet (notes P2#12) |
| Snapshot | `Streaming/channels/101/picture`, 3 s timeout, JPEG check, else a frame of RTSP (`intercom_homekit/src/drivers/hikvision/isapi.ts:237-246`, `intercom_homekit/CHANGELOG.md:49-51`) | `Camera.snapshot()` (JPEG check); no timeout parameter |
| Talk-back | ISAPI two-way audio refused (`invalidOperation`) on DS-KV61xx; SDK voice forwarding instead (`intercom_homekit/DOCS.md:279-282`) | `DoorStation.talk()` would fail there; talk in a SIP call: `DoorCall.push()` |

### emilianogetino/hikvision-isapi-bridge

| Item | Detail (where) | aiohikvision today |
|---|---|---|
| Does | MQTT add-on: door contact and lock relay of a DS-KV6124-WBE1 (V3.9.0), which the SDK and httpHosts do not report (`README.md:9`) | — |
| Events | `POST /ISAPI/Event/notification/subscribeEvent` `<heartbeat>5</heartbeat><eventMode>all</eventMode>`; JSON parts; `AccessControllerEvent` major 5, minor 21/22, 25/26, 92, 216, `currentEvent` true only (`hikvision_isapi_bridge/bridge.py:585-656`) | not yet (notes P1#1, P2#5) |
| Reconnect | wait `heartbeat × 3 + 3` s; a "Device hardware error" body while the old session is released (`hikvision_isapi_bridge/bridge.py:51-55`, `708-710`) | notes P2#5 |
| Access log | `POST /ISAPI/AccessControl/AcsEvent?format=json`, `AcsEventCond` with major 5, a minor, `timeReverseOrder`, pages while `responseStatusStrg` is `MORE` (`hikvision_isapi_bridge/bridge.py:389-446`) | `AccessLog.poll()` (all codes, new entries only) |
| Door names | `GET /ISAPI/AccessControl/Door/param/{n}` `doorName` (`hikvision_isapi_bridge/bridge.py:203`) | `open_time` setting from the same document; `doorName` not yet (notes P3) |

## 2. New to aiohikvision

Facts and features found in these projects that are neither in the research notes nor in the
library. "Reported" means the project states it from its device; nothing here was measured by
aiohikvision.

### P1

1. **Two more devices whose alertStream is empty.** DS-KB8113-IME1(B) V2.2.60 answers 200 with 40
   bytes and closes (schmidt-gabriel `docs/protocol.md:75-102`, MIT). DS-KV6113-WPE1(B) V2.2.53
   "returns an empty document" (DmytryS `intercom_homekit/DOCS.md:283-285`,
   `intercom_homekit/src/drivers/hikvision/callMonitor.ts:27-29`, MIT). `KNOWN_RULES` has only
   DS-KV8113-WME1(B). *Fit:* two `Rule`s in `KNOWN_RULES` with
   `BehaviourPatch(alert_stream=AlertStream.NONE)` and their `Measured`.
2. **No ISAPI two-way audio on DS-KV61xx (V2.2.53).**
   `PUT /ISAPI/System/TwoWayAudio/channels/1/open` answers `invalidOperation`, so go2rtc's
   `isapi://` cannot talk either (DmytryS `intercom_homekit/DOCS.md:279-282`, MIT).
   `DoorStation.talk()` only finds out when it opens. *Fit:* a behaviour enum (e.g. `TalkPath`:
   `ISAPI` | `SIP_ONLY`) with a rule for `DS-KV61*`, so a consumer hides talking outside a call, or
   talks through a SIP call to the door (DEVICE_FINDINGS, "Calling the door").
3. **`doorNo` is always 1 in subscribeEvent on V3.9.0 (DS-KV6124-WBE1), and `AcsEventCond` ignores
   `doorNo`.** The bridge finds the real door in the access log: the newest entry with the same
   minor within ±5 s of the event (emilianogetino `hikvision_isapi_bridge/bridge.py:416-419`,
   `462-497`, `README.md:14`, MIT). Needed as soon as the AccessControllerEvent table of notes P1#1
   lands, or door 2 shows up as door 1. *Fit:* a behaviour enum (e.g. `DoorNumberSource`: `EVENT` |
   `ACCESS_LOG`) with a rule for the model and firmware; the policy re-reads `AccessLog` for the
   door.

### P2

4. **`callStatus` does not say whether anyone answered.** On DS-KB8113-IME1(B) V2.2.60 an unanswered
   ring stays `ring` for 31.2 s, then `onCall` for 31.2 s while the visitor records a message
   (`messageTime` 30 s); answered, `ring` ends early (13.0 s at the indoor station, 4.4 s in the
   app). `maxRingTime` (65 s) is not the timer (schmidt-gabriel `docs/protocol.md:170-241`,
   `custom_components/hikvision_intercom/coordinator.py:196-232`, MIT). *Fit:* a pure policy class
   (e.g. `RingTimeline`) that turns `call_status()` transitions into answered or missed by the time
   spent ringing, with the threshold a parameter; and a docstring warning on
   `DoorStation.call_status()` that `on_call` is not "answered".
5. **`callStatus` can stay `idle` while the door rings** (DS-KV6113 with an indoor station, cause
   unknown; the SDK alarm channel still reports the press) (DmytryS
   `intercom_homekit/src/drivers/hikvision/callMonitor.ts:34-36`,
   `intercom_homekit/src/drivers/hikvision/alarmListener.ts:54-56`, MIT). *Fit:* documentation of
   `DoorStation.call_status()`; ring detection belongs to SIP (`CallServer`), which this does not
   affect.
6. **`enabled=false` is a real switch on DS-KB8113-IME1(B).** The channel ships disabled and
   go2rtc's backchannel stays silent until `PUT /ISAPI/System/TwoWayAudio/channels/1` with `<id>`,
   `<enabled>true</enabled>` and `<audioCompressionType>` (schmidt-gabriel
   `docs/protocol.md:277-285`, `custom_components/hikvision_intercom/isapi/client.py:269-282`, MIT).
   On a DS-KD8003 `enabled` reads false while it works (DEVICE_FINDINGS), and acardace's server
   reads `enabled=true` as busy. Reported, not measured. *Fit:* a behaviour enum (e.g.
   `TalkChannelSwitch`: `IGNORED` | `ENABLE_FIRST`) with a rule for the model; `TwoWayAudio.open()`
   enables the channel first.
7. **`callSignal hangUp` reportedly silences a ringing DS-KV6113** (the default `ring_action` before
   talk-back: `hangUp` silent, `reject` busy tone, `answer` needs Hik-Connect) (DmytryS
   `intercom_homekit/DOCS.md:186`, `intercom_homekit/src/drivers/hikvision/talkback.ts:175-198`,
   MIT). This contradicts the notes ("callSignal on doors: answers OK and does nothing"). *Fit:* an
   experiment on a DS-KD8003 first; if it holds, a `DoorStation` method gated by a behaviour enum by
   model.
8. **Seed each door's state from the access log at start-up.** Page `AcsEvent` with `major: 5`,
   `minor: 25` (then 26, 21, 22), `timeReverseOrder: true`, until every door has its newest entry or
   `responseStatusStrg` is not `MORE` (emilianogetino `hikvision_isapi_bridge/bridge.py:389-446`,
   MIT). `AccessLog`'s first poll only marks where the log stands. *Fit:* a service method (e.g.
   `AccessLog.latest(major, minor)`) returning the newest entry per door.
9. **More access-control codes.** Major 5: 0x13/0x14 always-open begin/end, 0x1F/0x20 always-close
   begin/end, 0x5D lock open timeout (0x5C lock open exception is in the notes); major 3:
   0x400-0x403 remote open, close, always open, always close (Hikvision-Addons
   `hikvision-doorbell/src/sdk/acsalarminfo.py:218-234`, `327-420`; SDK header values: facts only).
   They give the read-back the notes say the door modes lack (notes P1#2). Minor 216 is treated as
   an exception next to 92 by emilianogetino (`hikvision_isapi_bridge/bridge.py:305`, `606`, MIT),
   meaning undocumented. *Fit:* entries in the AccessControllerEvent table of notes P1#1 and in
   `acslog._KNOWN`; a door mode derived from the always-open/close events.
10. **More of `deviceInfo`:** `subDeviceType` (`villaDoorStation`) (schmidt-gabriel
    `docs/protocol.md:18`, `custom_components/hikvision_intercom/isapi/models.py:93`, MIT),
    `electroLockNum` (locks) and `alarmOutNum` (relays of an indoor station) (Hikvision-Addons
    `hikvision-doorbell/src/doorbell.py:1040-1050`, `1073-1081`, facts only). *Fit:* parser fields
    of `Identity`; `electroLockNum` as a fallback for `DoorStationInfo.doors` when the
    remote-control capabilities are missing.
11. **A snapshot can hang about 30 s and end in `deviceError` while video works** (DmytryS
    `intercom_homekit/CHANGELOG.md:49-51`, MIT); the Hik-Connect integration notes slow captures on
    a DS-KD8003 (tomasbedrich `custom_components/hikconnect/camera.py:29-31`, facts only). *Fit:* a
    timeout parameter on `Streaming.snapshot()`; the fallback to a video frame stays with the
    consumer.

### P3

12. **`/ISAPI/VideoIntercom/deviceCommunication`** shows the door's `manage` and `sip` server
    addresses (`0.0.0.0` when none) (schmidt-gabriel `docs/protocol.md:307-314`, MIT). *Fit:* a
    parser for a set-up check ("does the VoIP line point at us?"), once a full document is seen.
13. **Capabilities that lie, and health that is absent:** `isSupportWorkStatus=true` but
    `workStatus` answers 404 `invalidOperation` (schmidt-gabriel `docs/protocol.md:287-299`, MIT);
    `/ISAPI/System/status` answers `invalidOperation` on DS-KV6113 (DmytryS
    `intercom_homekit/DOCS.md:117-118`, MIT). *Fit:* tests that `DoorStation.read_health()` gives
    `cpu_percent=None` there.
14. **`talkTime` ranges by model:** 90-120 s on DS-KB8113-IME1(B) V2.2.60 (schmidt-gabriel
    `docs/protocol.md:224`), 90-1800 s on DS-KD8003. *Fit:* the `operationTime` setting of notes
    P2#8 reads its range from `/capabilities`, never a constant.
15. **Button backlight of a door station:** `/ISAPI/VideoIntercom/SubModuleBacklight?format=json`,
    `backlightMode` `auto`/`custom`, `customBacklightTime` `beginTime`/`endTime`, `hostSyncEnabled`
    (Hikvision-Addons `doorbell/ISAPI.md:22-24`, facts only). *Fit:* a select in
    `DOOR_STATION_SOURCES`, offered when the GET answers.
16. **Indoor-station ISAPI:** scene `nowMode` (`atHome`, `goOut`, `goToBed`, `custom`),
    `AlarmControlByPhone` `commandType` (`setupAlarm`, `closeAlarm`), relays through
    `SecurityCP/control/outputs` and `outputStatus` (Hikvision-Addons
    `hikvision-doorbell/src/mqtt_input.py:264-305`, `831-902`,
    `hikvision-doorbell/src/doorbell.py:136-164`, facts only). Its docs say indoor stations do not
    open port 80 (`doorbell/DOCS.md:143`). *Fit:* only if indoor stations with HTTP ISAPI turn up.
17. **Devices without HTTP ISAPI:** the 2-wire DS-KIS701-class kit has ports 80/443 closed and port
    8000 (SDK) open; its SIP is YATE 2.0.0 (OPTIONS answered, REGISTER 501, a blind INVITE 487)
    (TimLuist1 `docs/PROTOCOL.md:6-33`, MIT). *Fit:* a distinct fault from
    `HikvisionClient.connect()` ("no HTTP ISAPI; SDK port open") instead of a plain `Unreachable`.
18. **An indoor station is a SIP registrar on UDP 5065** for its extensions: digest MD5 (`qop`
    optional), REGISTER with `Content-Type: text/xml` and a `<regXML>` body (`regDevName`,
    `regDevSerial`, `regDevMacAddr`), Expires 900, the extension's user an 11-digit number ending in
    its index (Hikvision-Addons `asterisk/asterisk.as.indoor.md:39-64`,
    `asterisk/hikvision_register.py:69-76`, `190-208`, facts only). The door's call is forwarded to
    the extension without video. *Fit:* a possible "extension of an indoor station" mode, next to
    the door's own VoIP line.
19. **Hikvision SDP attributes of a call to an indoor station:** `a=doorFloor`, `a=responseType`,
    `a=doorType`, `a=isSpecialType` (Hikvision-Addons `hikvision-doorbell/src/doorbell.py:794-838`,
    commented-out code, unverified, facts only). *Fit:* names to look for in the door's INVITE
    (notes P2#9).
20. **httpHosts details:** one slot, URL at most 128 characters, an empty `<url>` refused with 400
    `badXmlFormat`, DELETE to unconfigure, then GET answers 400 `badParameters` (schmidt-gabriel
    `docs/protocol.md:110-152`, MIT). *Fit:* the httpHosts source of notes P2#7, for cameras.
21. **subscribeEvent details:** JSON parts in `multipart/form-data`, sometimes without a charset
    (emilianogetino `hikvision_isapi_bridge/CHANGELOG.md:4`,
    `hikvision_isapi_bridge/bridge.py:692-737`); the text "Device hardware error" while the previous
    session is still held (`hikvision_isapi_bridge/bridge.py:708-710`, MIT). *Fit:* the
    subscribeEvent feed of notes P2#5 treats that text as "retry after 3 × heartbeat".
22. **Pacing a recorded message:** the server writes `audioData` at 8000 bytes/s (acardace
    `internal/hikvision/stream_writer.go:167-171`, Apache-2.0); `TwoWayAudio.send()` assumes a
    real-time source. *Fit:* a helper (e.g. `TwoWayAudio.play(codes)`) that sends 20 ms frames on a
    clock.
23. **Snapshot query parameters** `snapShotImageType=JPEG` and `imageQuality=best` (Hikvision-Addons
    `hikvision-doorbell/src/doorbell.py:316`, facts only). *Fit:* optional arguments of
    `Streaming.snapshot()`, if a device needs them.

## 3. Using aiohikvision instead

Every name below exists in `src/aiohikvision` today, unless the line says `# planned: ...`.
Of the library's [three levels](https://github.com/webysther/aio-hikvision/blob/main/README.md#three-levels),
start at level 3, `Hikvision` (what the device is and supports, its camera), and go down to
`hik.device` only where it has no answer yet. Door stations and their calls have none yet, so
`DoorStation` and the SIP classes stand beside it. Level 3 shares the door's link, so one
lockout counter: `Hikvision.from_device(await Device.from_link(door.link))`.

### pergolafabio/Hikvision-Addons

The add-on needs the proprietary SDK for rings and talk-back and tunnels ISAPI through it. A
door station with HTTP ISAPI needs neither: rings come over SIP (`CallServer`, see SIS below),
the speaker over ISAPI, and the rest is typed.

```python
import asyncio

import aiohttp

from aiohikvision import Device, DoorStation, Hikvision


async def main() -> None:
    async with aiohttp.ClientSession() as session:
        door = DoorStation(session, "192.0.2.10", "admin", "password")
        hik = await Hikvision.from_device(await Device.from_link(door.link))  # level 3, one link
        info = await door.read_info()  # doors, the doors that open a lock, speaker
        print(hik.model, info.locks, await door.call_status())
        settings = {setting.key: setting for setting in await door.read_settings()}
        values = await door.read_setting_values(tuple(settings.values()))
        speaker = settings.get("output_volume")  # also talk_volume, input_volume
        value = values.get(speaker.ref) if speaker is not None else None
        if speaker is not None and value is not None:
            await door.write_setting(speaker, value.field, "0")  # mute: a volume of 0
        if hik.camera is not None:
            print(len(await hik.camera.snapshot()))
        await door.open_door(1)
        # planned: await door.set_door_mode(1, "alwaysOpen")  (notes P1#2)
        # planned: a SubModuleBacklight select among door.read_settings()  (P3 #15)


asyncio.run(main())
```

### arturzx/sip-indoor-station

SIS writes its own SIP stack, registrar and RTP. The library has them, with the door's quirks
(40 ms packets, `jaK` keepalives, `<locknumXML>`) built in.

```python
import asyncio

from aiohikvision import CallServer, CallState, DoorCall, DoorRegistrar, DoorTransport

DOOR = "192.0.2.10"  # the door station
ME = "192.0.2.2"  # this machine, as the door reaches it
MU_LAW_SILENCE = b"\xff" * 160  # 20 ms


def door_sound(call: DoorCall, payload: bytes) -> None:
    """40 ms of the door's G.711, in the law of call.talkback.codec: hand it to the browser."""


async def main() -> None:
    ringing: asyncio.Queue[DoorCall] = asyncio.Queue()

    def changed(call: DoorCall) -> None:
        if call.state is CallState.RINGING:
            ringing.put_nowait(call)

    transport = DoorTransport(local_addr=("0.0.0.0", 5060), allowed_hosts={DOOR})
    calls = CallServer(
        transport, advertise=ME, on_change=changed, on_audio=door_sound, registrar=DoorRegistrar()
    )
    await calls.start()
    try:
        call = await ringing.get()
        await calls.answer(call.id)  # 200 OK: G.711, a=ptime:40, a=sendrecv, m=video 0
        for _ in range(50):  # one second of the browser's microphone
            call.push(MU_LAW_SILENCE)
            await asyncio.sleep(0.02)
        await calls.hangup(call.id)
        # planned: INVITE retransmissions absorbed (notes P1)
        # planned: a registrar that challenges with digest (notes P2#4)
    finally:
        await calls.stop()


asyncio.run(main())
```

### arturzx/sip-indoor-station-integration

The integration polls an add-on over HTTP for state the library pushes in process.

```python
from aiohikvision import CallServer, CallState, DoorCall, DoorRegistrar, DoorTransport, Registration

CALL_STATE = {CallState.RINGING: "ringing", CallState.ANSWERED: "in_call", CallState.ENDED: "idle"}


class Station:
    """What the entities read: no add-on, no /api/state polling."""

    def __init__(self, door: str, advertise: str) -> None:
        self.call_state = "idle"
        self.registered = False
        self.registrar = DoorRegistrar(max_expires=300, on_change=self._registration)
        self.calls = CallServer(
            DoorTransport(local_addr=("0.0.0.0", 5060), allowed_hosts={door}),
            advertise=advertise,
            on_change=self._call,
            registrar=self.registrar,
        )

    def _call(self, call: DoorCall) -> None:
        self.call_state = CALL_STATE[call.state]  # call.end_reason says how it ended

    def _registration(self, registration: Registration, registered: bool) -> None:
        self.registered = registered

    def history(self) -> list[DoorCall]:
        """The latest ended calls the server keeps (aiohikvision.sip.calls.KEPT_ENDED_CALLS)."""
        return [call for call in self.calls.calls.values() if call.state is CallState.ENDED]

    def every_minute(self) -> None:
        self.registrar.prune()  # a line that let its registration run out
```

### arturzx/sip-indoor-station-card

The card can stay as it is; what changes is its server side, which needs no WebRTC or GStreamer
for the sound of a call.

```python
import base64
from collections.abc import Callable

from aiohikvision import CallServer, DoorCall


def microphone(calls: CallServer, call_id: str, frame: bytes) -> None:
    """A binary frame of the card: 20 ms of G.711, 160 bytes at 8 kHz."""
    call = calls.calls.get(call_id)
    if call is not None:
        call.push(frame)  # leaves as 40 ms RTP packets; ignored unless the call is answered


def door_sound_to(send: Callable[[dict[str, str]], None]) -> Callable[[DoorCall, bytes], None]:
    """The CallServer's on_audio: each 40 ms of the door, for the card to play with Web Audio."""

    def forward(call: DoorCall, payload: bytes) -> None:
        codec = call.talkback.codec if call.talkback is not None else "G.711ulaw"
        send({"call_id": call.id, "codec": codec, "audio": base64.b64encode(payload).decode()})

    return forward
```

### arturzx/hass-addons

The add-on runs SIS as a process with three fixed ports. With the library the process is a few
lines, and the RTP port of each call is ephemeral.

```python
import asyncio
import json
from pathlib import Path

from aiohikvision import CallServer, DoorRegistrar, DoorTransport


async def main() -> None:
    options = json.loads(Path("/data/options.json").read_text())  # the add-on's options
    transport = DoorTransport(local_addr=("0.0.0.0", 5060), allowed_hosts={options["door_host"]})
    calls = CallServer(transport, advertise=options["local_address"], registrar=DoorRegistrar())
    # planned: a fixed RTP port range for containers without host networking (notes P3)
    await calls.start()
    try:
        await asyncio.Event().wait()
    finally:
        await calls.stop()


asyncio.run(main())
```

### acardace/hikvision-doorbell-integration

The integration needs a separate Go server to play a file at the door. The library plays it
directly through the speaker.

```python
import asyncio
import wave

import aiohttp

from aiohikvision import DoorStation, TalkEnd
from aiohikvision.media import g711

FRAME_SECONDS = 0.02  # g711.frames cuts 20 ms frames


async def play(path: str) -> None:
    """Say a recorded message (8 kHz, 16-bit mono WAV) through the door's speaker."""
    async with aiohttp.ClientSession() as session:
        door = DoorStation(session, "192.0.2.10", "admin", "password")
        await door.read_info()
        taken_over = asyncio.Event()
        talk = await door.talk(lambda reason: taken_over.set())  # closes a stale session first
        law = g711.PCMU if talk.codec == "G.711ulaw" else g711.PCMA
        with wave.open(path) as wav:
            pcm = wav.readframes(wav.getnframes())
        for frame in g711.frames(g711.encode(pcm, law), law):
            if taken_over.is_set():  # aborted, or another talk took the speaker (TalkEnd.REPLACED)
                break
            talk.send(frame)
            await asyncio.sleep(FRAME_SECONDS)  # planned: talk.play(codes) paces it (P3 #22)
        await talk.close(TalkEnd.STOPPED)
```

### acardace/hikvision-doorbell-server

The server's ISAPI client, digest retry and channel bookkeeping are in `DoorStation.talk()`. The
door's microphone over ISAPI is not there yet; during a SIP call it comes from `on_audio`.

```python
import asyncio

from aiohikvision import DoorStation, TalkEnd


async def browser_to_door(door: DoorStation, from_browser: asyncio.Queue[bytes]) -> None:
    """The browser's microphone, as 20 ms G.711 frames, to the door's speaker."""
    talk = await door.talk(lambda reason: None)  # one talk at a time: a new one replaces it
    try:
        while not talk.ended:
            talk.send(await from_browser.get())  # raw G.711 on one PUT of audioData
    finally:
        await talk.close(TalkEnd.STOPPED)
    # planned: async for chunk in talk.receive(): ...  (GET audioData?sessionId=, notes P3)
```

### schmidt-gabriel/hikvision-intercom-hass-integration

The integration probes behaviour instead of trusting flags; the library does the same with rules
by model and firmware, and a rule can be passed today.

```python
import asyncio
import datetime as dt

import aiohttp

from aiohikvision import (
    AlertStream,
    BehaviourPatch,
    Device,
    DoorStation,
    Hikvision,
    Match,
    Measured,
    Rule,
    VersionRange,
)

KB8113 = Rule(
    Match(model="DS-KB8113-IME1(B)", firmware=VersionRange.parse("==2.2.60")),
    BehaviourPatch(alert_stream=AlertStream.NONE),
    Measured("DS-KB8113-IME1(B)", "V2.2.60", dt.date(2026, 9, 1), "alertStream: 40 bytes, closes"),
)


async def main() -> None:
    async with aiohttp.ClientSession() as session:
        door = DoorStation(session, "192.0.2.10", "admin", "password")
        info = await door.read_info()
        hik = await Hikvision.from_device(await Device.from_link(door.link, rules=[KB8113]))
        print(hik.kind, hik.supports.outputs)  # what it is, its relays
        print("\n".join(hik.device.summary()))  # which rule decided what: only level 2 says
        print(info.doors, [output.use for output in info.outputs])
        previous = None
        while True:
            status = await door.call_status()  # idle, ringing, on_call
            if status != previous:
                # planned: RingTimeline turns these into answered or missed (P2 #4)
                print(previous, "->", status)
                previous = status
            await asyncio.sleep(1)
        # planned: await door.set_door_mode(1, "alwaysOpen") / "resume"  (notes P1#2)


asyncio.run(main())
```

### TimLuist1/hikvision-intercom

This kit has no HTTP ISAPI, so aiohikvision cannot replace the SDK bridge for it. What the
library can do is say so at once, and serve the kits of the same family that do answer ISAPI.

```python
import asyncio

import aiohttp

from aiohikvision import Device, DoorStation, Hikvision, HikvisionError


async def main() -> None:
    async with aiohttp.ClientSession() as session:
        door = DoorStation(session, "192.0.2.10", "admin", "password")
        try:
            hik = await Hikvision.from_device(await Device.from_link(door.link))
        except HikvisionError as err:  # ports 80 and 443 closed on this kit
            # planned: a distinct fault for SDK-only devices (P3 #17)
            print("no ISAPI over HTTP:", err)
            return
        info = await door.read_info()  # its doors: door stations have no level-3 answer yet
        print(hik.model, hik.kind, info.doors)
        await door.open_door(1)  # what the bridge tunnels through NET_DVR_STDXMLConfig


asyncio.run(main())
```

### tomasbedrich/home-assistant-hikconnect

Every function the integration gets from the cloud has a LAN equivalent: no 3 s cloud poll, no
cloud relay for the lock, no MPEG-TS wrapping of cloud video.

```python
from aiohikvision import Device, DoorStation, Hikvision


async def local(door: DoorStation) -> None:
    print(await door.call_status())  # idle, ringing, on_call, over the LAN
    await door.open_door(1)  # the lock relay; its open time is the open_time setting
    hik = await Hikvision.from_device(await Device.from_link(door.link))
    if hik.camera is not None:
        url = await hik.camera.stream_url()  # H.264 and G.711 for Home Assistant's stream
        jpeg = await hik.camera.snapshot()  # the device's own picture, no cloud capture
        print(url.startswith("rtsp://"), len(jpeg))
```

### DmytryS/intercom-homekit

The add-on's ISAPI client, volumes, session counters and snapshot check are in the library;
talk-back on DS-KV61xx needs the SDK because ISAPI two-way audio is refused there, and the
library's way around it is a SIP call.

```python
from aiohikvision import DoorStation, TalkEnd, TalkError


async def poll(door: DoorStation) -> None:
    health = await door.read_health()  # cpu_percent is None where System/status is refused
    print(health.video_sessions)  # Streaming/status: the stream slots in use
    offered = await door.read_settings()  # a door's open_time has the door's number as channel
    print(sorted({setting.key for setting in offered}))  # input_volume, output_volume, ...
    try:
        talk = await door.talk(lambda reason: None)
    except TalkError as err:  # DS-KV61xx: TwoWayAudio open answers invalidOperation
        print(err.reason)  # planned: TalkPath.SIP_ONLY known before trying (P1 #2)
    else:
        await talk.close(TalkEnd.STOPPED)
    # planned: online users from /ISAPI/Security/onlineUser (notes P2#12)
```

### emilianogetino/hikvision-isapi-bridge

The bridge holds a subscribeEvent stream and pages the access log. The access log is there
today; the stream is planned.

```python
import asyncio

from aiohikvision import DoorStation
from aiohikvision.isapi.model.features.acslog import AccessLog

DOOR_OPEN = {25: True, 26: False}  # major 5: door opened, door closed


async def watch_doors(door: DoorStation) -> None:
    log = AccessLog(door.link)
    await log.poll()  # the first poll marks where the log stands
    # planned: AccessLog.latest(major=5, minor=25) to seed each door at start (P2 #8)
    # planned: a subscribeEvent feed (heartbeat 5 s, eventMode all) next to AlarmFeed (notes P2#5)
    while True:
        for frame in await log.poll():
            minor = frame.extra.get("minor")
            if frame.extra.get("major") == 5 and minor in DOOR_OPEN:
                print("door", frame.extra.get("door"), "open" if DOOR_OPEN[minor] else "closed")
        await asyncio.sleep(2)
```
