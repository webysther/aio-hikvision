# Changelog

All notable changes to aiohikvision. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/). Before 1.0, a minor version may change the API.

## [0.1.7] - Unreleased

### Added

- **The door's sound of a call, over SIP** (`CallServer(on_audio=...)`): the answer asks
  for the door's RTP (`a=sendrecv`), and each 40 ms G.711 payload of an answered call is
  handed on in order, for players that cannot play the sound of the RTSP stream (Home
  Assistant's HLS keeps no G.711). Without `on_audio` nothing changes (`a=sendonly`).
  `DoorSound` keeps the door's packets of the codec of the call and drops the rest
  (another address, a key press, a packet again or behind), counting them in
  `call.sound.stats`; `RtpPacket` reads an RTP datagram. See
  `docs/ADR-0002-door-sound-over-sip.md`.
- `Talkback(received=...)`: what arrives on the socket of the call.

## [0.1.6] - 2026-11-26

### Added

- **The settings of a door station** (`DoorStation.read_settings`, `read_setting_values`,
  `write_setting`): what it offers comes from its capabilities, each value is read back after
  a change. Besides the image of its camera:
  - its volumes (`/ISAPI/System/Audio`): the microphone (`input_volume`), the speaker
    (`output_volume`) and the speaker during a call (`talk_volume`), with their ranges;
  - how long each door stays open (`open_time`, its channel is the door's number), from
    `AccessControl/Door/param`;
  - what it says when a door opens (`door_voice_prompt`, `door_voice_prompt_type`), from
    `AccessControl/AcsCfg`.
- **How loaded a door station is** (`DoorStation.read_health`): its CPU, and how many clients
  stream its video (only the count: the addresses of the clients are never read).
- **What the inputs of a door station read** (`DoorStationInfo.inputs`,
  `DoorStation.read_inputs`): a door contact, an exit button, or nothing, with the choices
  each input offers.
- **How the event stream of a device behaves** (`AlarmFeed.behaviour`, a `StreamBehaviour`:
  `live`, `quiet`, `quick_close`, `bare`, `no_stream`). The decision to connect again lives
  in `Reconnects`, which judges each connection (`Session`) without I/O.

### Fixed

- The event stream of a door station that answers 200 with only an XML declaration and closes
  is no longer reopened every 5 seconds: after 3 such answers in a row (`BARE_LIMIT`) the
  stream is reported `Unsupported` (`NO_STREAM`) with one warning, and tried again every hour
  (`UNSUPPORTED_RETRY`). A stream that closes right after connecting without sending anything
  now backs off (5 s, 10 s, … up to 5 minutes) instead of retrying every 5 seconds. Reported
  and fixed in Hikvision Bridge
  ([#84](https://github.com/yannik2480/hikvision_bridge/issues/84)); the names and values are
  theirs, so it can drop its own subclass.

## [0.1.5] - 2026-11-26

### Fixed

- A response whose `statusCode` is 0 is a success, as the ISAPI guide lists it beside 1,
  no longer a `DeviceRejected`.

## [0.1.4] - 2026-11-26

### Added

- `BadCredentials.retries_left`: how many failed logins the device still allows before it
  locks the account, when it says.

### Fixed

- **The account is no longer brought to its lock.** When the device says that two failed
  logins or fewer remain, the link stops at once instead of trying again later: the last
  attempts are left to the person who types the password.
- A write the device applied but that takes effect after a reboot (`statusCode` 7, "Reboot
  Required") is a success, no longer a `DeviceRejected`.
- The lock fields are read under both of their names: `retryLoginTime` or `retryTimes`
  (failed logins left), `unlockTime` or `resLockTime` (seconds until the lock lifts).

## [0.1.3] - 2026-11-26

### Added

- **The main stream of a door station** (`DoorStationInfo.stream`): its codec and size,
  from `/ISAPI/Streaming/channels/101`, or None when the device does not say. Its pictures
  do not always have the shape of its stream (a DS-KD8003 takes them 11:9 while it streams
  16:9), so a picture can be shown in the shape of the live video. `read_stream` reads one
  stream of any device.

## [0.1.2] - 2026-11-26

### Added

- **What the outputs of a door station drive** (`/ISAPI/System/IO/outputs`): an electric
  lock, a mechanical doorbell, or nothing, as its web page sets them (Access Control → I/O
  Settings). `DoorStationInfo.outputs` lists them (`Output`, `OutputUse`), with the uses each
  can be set to when the device says, and `DoorStationInfo.locks` gives the doors that open.
  `DoorStation.read_outputs()` reads them again, as they can change at any time.

### Fixed

- `DoorStation.open_door` refuses a door whose output drives no lock (`NotALock`). A door
  station lists every door among those it can open remotely, even one whose relay rings a
  doorbell.

## [0.1.1] - 2026-11-26

### Fixed

- `aiohikvision.isapi` matches Hikvision Bridge 0.9.23b12, so that the integration can
  use it in place of its own copy: `model.audit.clock_skew_of` reads the clock error of a
  device whose heartbeats carry its local time as UTC.
- The task of an event stream is named after aiohikvision, not after an integration.
- A request without a TLS context of its own leaves the TLS settings of the session alone
  again (0.1.0 passed `ssl=True`, overriding a session made not to verify).

## [0.1.0] - 2026-11-26

The first version: Home Assistant can be the SIP server and the callee of a Hikvision door
station. The design is hybrid: the call and the microphone go over SIP, and the door's picture and
sound come over RTSP ([ADR 0001](docs/ADR-0001-hybrid-call.md)). It was measured on a
DS-KD8003-IME1(B), firmware V3.7.1 and V3.7.3 ([findings](docs/DEVICE_FINDINGS.md)).

### Added

- **`DoorTransport`:** UDP SIP that only hears the configured door stations. It drops eXosip2's
  `jaK` keepalives without logging a parse error, and counts them so the door is known to be
  alive.
- **`DoorRegistrar`:** the SIP server of the door's VoIP line. It grants a shorter registration
  than the hour the door asks, so the door comes back sooner after a restart, and reports when a
  line registers and when it expires.
- **`CallServer` and `DoorCall`:**
  - A call rings with 180 at once. Answering, rejecting (486, "busy") and hanging up happen on
    command, and every command names its call. Two answers at once (two phones) give the call
    to the first; a visitor who leaves while the answer is under way gets no 200 OK.
  - Stopping hangs up the answered calls and refuses the ringing ones; the calls that ended
    before are left as they were. Only the latest 20 ended calls are kept.
  - The answer is G.711 at `a=ptime:40` with `a=sendonly` and `m=video 0`.
  - A second press during a call gets "busy".
  - The `<locknumXML>` MESSAGE is answered and read.
  - A door that offers no G.711 is refused with a hint.
- **`Talkback`:** the microphone to the door.
  - The browser's 20 ms G.711 frames go two per packet. The door sends 40 ms packets, and slows
    its own audio to about 0.7 of real time while it receives 20 ms ones.
  - Packets leave on an absolute clock, in bursts, with nothing sent in silence. The marker bit
    starts each burst, and the timestamp counts the silence.
  - The delay is bounded: the oldest frames are dropped first.
- **`aiohikvision.media.g711`:** the reference µ-law and A-law encoders, identical to audioop on
  every 16-bit sample, plus tones and 20 ms framing.
- **`DoorStation`:** the ISAPI side of a door station. It reads what the device is (and refuses
  one that is no door station), its doors, its speaker and its RTSP port; it opens a door, takes
  a snapshot, gives the stream's RTSP address, checks that the device answers (`check`), and
  talks through the speaker outside a call (`TwoWayAudio`: one talk at a time, a new one takes
  the speaker over).
- **`aiohikvision.isapi`:** the ISAPI client and device model of Hikvision Bridge (see NOTICE).
- **`scripts/door_server.py`:** the library as the door's server, from a terminal. Its `facade`
  mode rings until the door gives up; its `hybrid` mode answers and talks in tone bursts.

[0.1.2]: https://github.com/webysther/aio-hikvision/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/webysther/aio-hikvision/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/webysther/aio-hikvision/releases/tag/v0.1.0
