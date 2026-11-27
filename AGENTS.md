# AGENTS.md: aiohikvision

Guidance for AI coding agents and contributors working on this repository.
`CLAUDE.md` imports this file.

aiohikvision is an async Python library (asyncio, aiohttp) for Hikvision
devices: ISAPI (cameras, recorders, door stations) and the SIP calls of video
door stations. It is fully typed, has no Home Assistant dependency and is
published to PyPI.

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

## Layout

```text
src/aiohikvision/
  sip/           transport.py DoorTransport (only the configured doors; drops
                 their jaK keepalives), registrar.py DoorRegistrar, calls.py
                 CallServer and DoorCall (ring, answer, reject, hang up; every
                 command names its call), messages.py
  rtp/           talkback.py Talkback: the microphone to the door, 40 ms G.711
                 packets on an absolute clock, in bursts; door_sound.py
                 DoorSound: the door's sound of a call, in order (pure);
                 packets.py RtpPacket
  media/         g711.py: reference µ-law and A-law encoders, tones, frames
  isapi/         from Hikvision Bridge (see NOTICE): wire/ (the authenticated
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
the documented subpackages. It is layered, from the simplest to the rawest:
`DoorStation` and `CallServer` answer the caller's real questions ("open the door",
"answer this call"); `isapi.wire` (the link) and `isapi.model` (discovery, features)
stay for what they do not cover. Add higher-level methods rather than making callers
combine low-level calls.

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

CI runs the same on Python 3.13 and 3.14. Warnings are errors in pytest. The
code inherited from Hikvision Bridge (`isapi/`) has some rules relaxed per file
in `pyproject.toml`, to be tightened one at a time; the coverage floor is the
total measured when it moved (77%), while the library's own code stays above
95%.

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
