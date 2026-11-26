# Changelog

All notable changes to aiohikvision. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/). Before 1.0, a minor version may change the API.

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
