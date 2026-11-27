# AGENTS.md: aiohikvision

Guidance for AI coding agents and contributors working on this repository.
`CLAUDE.md` imports this file.

aiohikvision is an async Python library (asyncio) for Hikvision devices: ISAPI
(cameras, recorders, door stations), RTP and the SIP calls of video door
stations. It is fully typed, has no Home Assistant dependency and is published
to PyPI. Its goal is to be the one library the Hikvision projects of Home
Assistant need: the integration `hikvision` of the core (today on pyHik),
`hikvision_next` and Hikvision Bridge, besides the indoor station.

Its main user is the Home Assistant integration Hikvision Virtual Indoor
Station (`hikvision_virtual_indoor_station`), which pins an exact version and
makes Home Assistant the indoor station of a door station. Protocol fixes belong
here; Home Assistant code belongs in the integration.

## Ground rules

- **Do not commit, amend, push, tag, publish or move branches** (`reset`,
  `branch -f`, `rebase`). Leave every change uncommitted in the working tree;
  the maintainer reviews and commits it. Read-only git commands are fine.
- Ask before anything that leaves the machine: releases, PRs, issues,
  comments.
- Reply in the language the person writes in. Code, comments, docstrings,
  docs, the changelog and commit messages are in English.
- **Never write to a real device** without the maintainer's approval: ISAPI
  writes and SIP calls to a door station change what a household sees and
  hears.
- **No real addresses or identifying data, anywhere** (docs, tests, scripts,
  even ignored folders): masks in prose (`<door-ip>`, `<ha-ip>`); in data a
  parser reads, only loopback or the documentation ranges (192.0.2.0/24,
  198.51.100.0/24, 203.0.113.0/24, MAC 00:00:5e:00:53:xx); names and
  identifiers of real devices as `REDACTED`. Recordings and videos never go
  in the repository folder (`captures/` is ignored and holds redacted text
  only).
- **License: MIT, mixed.** The parts derived from Hikvision Bridge keep its
  Apache License 2.0 (`LICENSES/Apache-2.0.txt`), and the License section of
  the README, the only notice (there is no NOTICE file), lists them. New code
  is MIT: write it from the facts (ISAPI, the RFCs, measured behaviour), not
  from another project's code. Code adapted from an MIT or Apache-2.0
  project keeps its license and joins that list; from a project without a
  license, or from the Hikvision SDK, take facts only. A rewrite that keeps
  none of a derived file's text takes it off the list.

## Layout

From the simplest to the rawest, in three levels like the constructs of the AWS CDK
(each made only of the one below, more answer with less code and less flexibility):

```text
src/aiohikvision/
  patterns/      level 3: connect() → Hikvision (who it is, Supports, its cameras),
                 Camera (a channel: snapshot(), stream_url()); the questions an
                 integration asks, answered by attributes read once     [isapi]
  client.py      HikvisionClient(session, rules=, overrides=): connect() → Device  [isapi]
  device.py      Device: identity, capabilities and behaviours, read once; its services;
                 summary() (the debug record of how it was recognised)
  report.py      the report of a device (GET only, anonymized, what is missing);
                 __main__.py: python -m aiohikvision report <address>          [isapi]
  services/      one class per domain of ISAPI (system.py System, streaming.py
                 Streaming), I/O only                                          [isapi]
  parsers/       the documents of a domain as models, without I/O              [isapi]
  models/        frozen models: identity.py Identity, firmware.py Firmware,
                 streaming.py Stream, StreamId, VideoFormat,
                 capabilities.py Capabilities (Domain, Support), _coded.py
                 CodedEnum (every value has a numeric code that never changes)
  behaviours/    how devices differ: Behaviours (one named enum per quirk);
                 rules.py Rule, Match, VersionRange, resolve(), KNOWN_RULES
  auth/          digest.py: HTTP digest, for ISAPI and RTSP (from Hikvision Bridge)
  errors.py      HikvisionError, MissingExtra; _extras.py require()
  sip/           transport.py DoorTransport (only the configured doors; drops
                 their jaK keepalives), registrar.py DoorRegistrar, calls.py
                 CallServer and DoorCall (ring, answer, reject, hang up; every
                 command names its call), messages.py
  rtp/           talkback.py Talkback: the microphone to the door, 40 ms G.711
                 packets on an absolute clock, in bursts; door_sound.py
                 DoorSound: the door's sound of a call, in order (pure);
                 packets.py RtpPacket
  media/         g711.py: reference µ-law and A-law encoders, tones, frames
  isapi/         from Hikvision Bridge (Apache-2.0): wire/ (the authenticated
                 link, faults, the event feed, XML) and model/ (discovery and
                 features); door_station.py DoorStation, the ISAPI side of a
                 door station; model/features/talk.py TwoWayAudio
tests/           pytest; tests/fakes holds the doubles of the measured devices
                 (a door station's SIP on loopback, an ISAPI device with the
                 anonymized answers of real devices in fakes/fixtures, the
                 two-way audio endpoint)
scripts/         door_server.py (the library as a door's SIP server, from a
                 terminal) and sip_probe.py (the measuring tool of the findings)
docs/            DEVICE_FINDINGS.md (what the door station does, measured),
                 ADR-0001-hybrid-call.md (why the call is SIP and the picture
                 RTSP) and ADR-0002-door-sound-over-sip.md (the door's sound of
                 a call over SIP, for players without the RTSP sound)
```

The public API is what `aiohikvision/__init__.py` exports in `__all__`, plus
the documented subpackages. It has three levels:

- **Level 3** (`patterns`): what an integration asks, as pyHik and aiodpc answer it
  (`hik.name`, `hik.supports.ptz`, `await hik.camera.snapshot()`). Attributes are
  read once when the device connects; only verbs do I/O; a verb has sensible
  defaults (the main stream, the account in the RTSP address) and few parameters.
- **Level 2** (`Device`, `services`, `models`, `behaviours`): one domain of ISAPI
  with types, defaults and the rules of each model and firmware.
- **Level 1** (`isapi.wire`, `parsers`): one document at a time, in full.

Rules: level 3 imports only level 2, never `isapi` nor `parsers`
(`tests/isapi/test_patterns.py` checks it); level 2 never imports level 3; every
level-3 object has `.device`, and every `Device` has `.link`, the way down. When a
consumer has to combine level-2 calls to answer a question, the answer belongs
in level 3.

The 0.2 series moves the library onto this layout, a part at a time (see
CHANGELOG): `DoorStation`, `isapi.model` (discovery and the features) and the
`Door*` classes of SIP leave in the release that brings their replacement,
without shims (before 1.0 a minor version may change the API), and the
consumers move with it.

### Extras

Each part is an extra, and the default install has no dependency:

| Extra | Installs | For |
|---|---|---|
| (none) | nothing | models, behaviours and rules, errors, digest |
| `isapi` | aiohttp, yarl, defusedxml | `HikvisionClient`, `Device`, `isapi`, `services`, `parsers` |
| `rtp` | nothing yet | `rtp/` (a place for an optional accelerator) |
| `rtsp` | `[rtp]` | the RTSP client (to come) |
| `sip` | `[rtp]`, aiosipua | `sip/` |
| `scrambling` | `[isapi]`, cryptography | the program streams of `isapi.model.features.scrambling` |
| `all` | everything | |

A subpackage that needs an extra calls `_extras.require("<extra>")` in its
`__init__.py`, and the names of `aiohikvision/__init__.py` behind an extra are
imported on first use (`_LAZY`): a missing extra raises `MissingExtra` with the
`pip install` that fixes it. `tests/test_extras.py` checks each part without
the others, and the `Without extras` job of CI installs the package alone.

### How devices differ: behaviours

A difference between devices (a model, or a firmware of the same model) is a
field of `behaviours.Behaviours`: a named enum whose default is what a generic
Hikvision device does, with a docstring saying which devices differ. A
`rules.Rule` sets it for the devices of a `Match` (a model or a glob of models,
a `VersionRange` of firmware, a device type) and says where it was seen
(`Measured`). `resolve()` applies the matching rules from the least to the most
specific, then the caller's overrides, and records what decided each behaviour;
`Device.behaviours` is the result. The code that talks to a device reads the
behaviour, never the model.

- A new behaviour: a field of `Behaviours` and of `BehaviourPatch` (and its
  `apply`), a `CodedEnum` with its codes in `tests/models/test_codes.py`, and a
  rule in `KNOWN_RULES` for each device it was seen on.
- What can be judged from how a device answers stays judged at runtime (as the
  event feed's `Reconnects` does): a rule gives the starting point.
- `ambiguities(KNOWN_RULES)` must stay empty.

## Checks

```bash
uv sync
uv run ruff format --check . && uv run ruff check .  # every rule ("ALL")
uv run mypy                                          # strict, src and tests
uv run pytest --cov
```

The dotfiles say how each file is written: `.editorconfig` (LF, UTF-8,
indentation), `.prettierrc` (Prettier for the YAML of the workflows, `printWidth`
100; `.prettierignore` leaves out the Markdown and the JSON), `.gitattributes` (LF;
`tests/fakes/fixtures` byte for byte) and `.python-version` (3.14, the newest version
CI tests). `npx prettier --check .` checks the YAML.

CI runs the same on Python 3.13 and 3.14, and installs the package without
extras once (`lean`). Warnings are errors in pytest. The code inherited from
Hikvision Bridge (`isapi/`, `auth/digest.py`) has some rules relaxed per file in
`pyproject.toml`, to be tightened one at a time; the coverage floor is the total
measured when it moved (77%), while the library's own code stays at 100%.

## Tests

- Never reach a device: `tests/fakes` holds the doubles of the measured ones (the SIP
  side of a door station on loopback, an ISAPI device over HTTP with digest
  authentication, the two-way audio endpoint).
- `tests/fakes/fixtures` holds answers of real devices, anonymized and otherwise
  unmodified: they guard the formats. Never edit them by hand; add a new profile from
  a new capture, anonymized as the ground rules say.
- Never depend on the clock or on timing luck: wait for a condition with a timeout
  (`until()`), and inject clocks where a module takes one (`DoorRegistrar(clock=)`).

## Documentation

- The README is also the PyPI page: link the repository files with absolute GitHub
  URLs.
- Every Python example of the README is a complete script (imports,
  `async def main()`, `asyncio.run(main())`) that works when copied and pasted, with
  its settings from environment variables (never an address in the text). Run each
  one before changing it, against the doubles of `tests/fakes` or, with the
  maintainer's approval, a real device.
- The README is read by someone meeting the library for the first time: it starts with
  the simplest thing (connect, ask what the device is), and each section builds on the
  one before, level 3 first, down to the lower levels and the door stations. Say a
  thing once, briefly; details go to `docs/`.
- `README.<language>.md` (zh-CN, es, pt-BR, fr, ar, ru, de, it, chosen by where
  Hikvision sells and where Home Assistant is used) are synced with the English README
  only when the maintainer asks; until then they may lag behind it. The line of
  languages on top links them all.
- The debug log is lean: a record says something once (how a device was recognised,
  the streams when they change, a request when it starts failing and when it answers
  again); a request that works logs nothing. Keep it so: whoever sends a log should
  send everything needed to fix or extend, and nothing more.
- `docs/DEVICE_FINDINGS.md` holds what was measured on a real door station, with the
  firmware and the date; add what you measure to it. `docs/ADR-*.md` hold the
  decisions and why.

## The door station

Read [docs/DEVICE_FINDINGS.md](docs/DEVICE_FINDINGS.md) before changing the SIP
side. Facts that are easy to get wrong:

- The door sends 40 ms G.711 packets, and slows its own audio to about 0.7 of
  real time while it receives 20 ms ones: send 40 ms, or nothing.
- It never answers a re-INVITE; it cancels after its ring time (60 s) and hangs
  up at its talk time (90 s by default).
- Its Opus and G.722.1 are non-standard: G.711 only.
- During a SIP call its speaker does not play ISAPI two-way audio.

## Versioning and releases

- Semantic Versioning: before 1.0 a minor version may change the API.
- To prepare a release, add a `## [X.Y.Z] - Unreleased` section to
  `CHANGELOG.md` ([Keep a Changelog](https://keepachangelog.com/en/1.1.0/)),
  written for the users of the library, with its link at the end of the file,
  and set `__version__` in `src/aiohikvision/__init__.py` to `X.Y.Z`.
- The maintainer commits and runs `./publish.sh X.Y.Z [--dry-run]`: it dates
  the section, creates the GitHub release, and the release workflow tests,
  builds and publishes to PyPI (trusted publishing).

## Code style

- Readable, descriptive code over clever code: descriptive names, typed models and
  enums instead of raw dicts, small focused helpers, docstrings that say what and why.
- No magic numbers: a constant whose comment or docstring says where its value comes
  from (see `KEPT_ENDED_CALLS`, the 40 ms of `Talkback`).
- Pure parsing and I/O apart: SDP, SIP headers and XML are read without sockets.
- mypy strict, ruff with every rule. A `# noqa` or `# type: ignore[code]` needs a
  reason.
- Comments explain why, not what.
