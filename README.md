# aiohikvision

**English** · [中文](https://github.com/webysther/aio-hikvision/blob/main/README.zh-CN.md) · [Español](https://github.com/webysther/aio-hikvision/blob/main/README.es.md) · [Português](https://github.com/webysther/aio-hikvision/blob/main/README.pt-BR.md) · [Français](https://github.com/webysther/aio-hikvision/blob/main/README.fr.md) · [العربية](https://github.com/webysther/aio-hikvision/blob/main/README.ar.md) · [Русский](https://github.com/webysther/aio-hikvision/blob/main/README.ru.md) · [Deutsch](https://github.com/webysther/aio-hikvision/blob/main/README.de.md) · [Italiano](https://github.com/webysther/aio-hikvision/blob/main/README.it.md)

Talk to Hikvision cameras, recorders and door stations from asyncio. Typed, without
Home Assistant, and only the parts you install.

```sh
pip install "aiohikvision[isapi]"
```

Python 3.13 or newer.

## First steps

Connect, and ask the device what it is:

```python
import asyncio
import os

import aiohikvision


async def main() -> None:
    async with aiohikvision.connect(
        os.environ["DEVICE_HOST"], os.environ["DEVICE_USERNAME"], os.environ["DEVICE_PASSWORD"]
    ) as hik:
        print(hik.name, "·", hik.model, hik.firmware)


asyncio.run(main())
```

```text
Door Station · DS-KD8003-IME1(B) V3.7.3 build 260915
```

`connect` reads the device once, with GET only: nothing on it changes. Everything that
follows starts from `hik`.

## A picture and a stream

Every camera of the device takes a picture and gives its RTSP address:

```python
import asyncio
import os
from pathlib import Path

import aiohikvision


async def main() -> None:
    async with aiohikvision.connect(
        os.environ["DEVICE_HOST"], os.environ["DEVICE_USERNAME"], os.environ["DEVICE_PASSWORD"]
    ) as hik:
        camera = hik.camera
        Path("picture.jpg").write_bytes(await camera.snapshot())
        print(await camera.stream_url(credentials=False))


asyncio.run(main())
```

```text
rtsp://192.0.2.10:554/Streaming/Channels/101
```

Both take the main stream; `camera.snapshot(StreamKind.SUB)` takes the sub stream, a
smaller picture. A camera or a door station has one camera, `hik.camera`; a recorder
has one per channel, `hik.cameras`.

## What it supports

`hik.kind` says what the device is, and `hik.supports` what it can do:

```python
import asyncio
import os

import aiohikvision


async def main() -> None:
    async with aiohikvision.connect(
        os.environ["DEVICE_HOST"], os.environ["DEVICE_USERNAME"], os.environ["DEVICE_PASSWORD"]
    ) as hik:
        print(hik.kind, hik.supports)
        for camera in hik.cameras:
            print(camera)


asyncio.run(main())
```

```text
door_station Supports(snapshot=True, streaming=True, events=True, smart=False, ptz=False, two_way_audio=True, intercom=True, doors=True, holidays=False, inputs=4, outputs=2)
<Camera 1: 101, 102>
```

`None` in `Supports` means the device did not say.

## Its events

`hik.events` says which events the device notifies, and follows them as they turn on and
off:

```python
import asyncio
import os

import aiohikvision


async def main() -> None:
    async with aiohikvision.connect(
        os.environ["DEVICE_HOST"], os.environ["DEVICE_USERNAME"], os.environ["DEVICE_PASSWORD"]
    ) as hik:
        print(", ".join(map(str, hik.events.sources)))
        async for source, state in hik.events.watch():
            print(source, "on" if state.active else "off")


asyncio.run(main())
```

```text
io 1, vmd 1, tamperdetection 1, diskfull 1, diskerror 1, nicbroken 1, ipconflict 1, …
vmd 1 on
vmd 1 off
```

An event the device stops posting turns off after 5 seconds: many never say when they
end. An integration runs `hik.events.run()` as a task of its own and subscribes each
entity, `hik.events.subscribe(entity.update, source)`, which then reads
`hik.events.state(source)`. A device without events has `hik.events` None.

## When something does not work

Make the report of your device, and send it to us:

```sh
python -m aiohikvision report 192.0.2.10 --username admin
```

It asks for the password, prints what the library makes of the device, and writes a
file. The file holds the device's answers, **anonymized** (no account, address, serial
or names), and the lines marked `!` are what the library is missing for it. Read it,
then [open a device report](https://github.com/webysther/aio-hikvision/issues/new?template=device_report.yml)
and attach it: it becomes a test, and support for your model.

For the debug log, turn on the `aiohikvision` logger:

```python
import logging

logging.basicConfig()
logging.getLogger("aiohikvision").setLevel(logging.DEBUG)
```

It says once how the device was recognised, its streams, and each request that fails,
and nothing for the requests that work.

## Going further

### Three levels

The library is built in three levels, like the constructs of the
[AWS CDK](https://docs.aws.amazon.com/cdk/v2/guide/constructs.html). Each level is made of
the one below, answers more with less code, and is less flexible; when one is not
enough, go down:

| Level | What | Way down |
|---|---|---|
| 3 | `aiohikvision.connect()` → `Hikvision`, `Camera`, `Supports`: the questions an integration asks | `hik.device` |
| 2 | `Device`: identity, capabilities, the rules of each model and firmware, one service per domain (`device.streaming`) | `device.link` |
| 1 | `IsapiLink` and the parsers: one ISAPI document at a time, in full | |

```python
import asyncio
import os

import aiohikvision
from aiohikvision import Domain


async def main() -> None:
    async with aiohikvision.connect(
        os.environ["DEVICE_HOST"], os.environ["DEVICE_USERNAME"], os.environ["DEVICE_PASSWORD"]
    ) as hik:
        print(hik.supports.ptz)  # level 3: the answer
        print(hik.device.capabilities.support(Domain.PTZ))  # level 2: present, absent or unknown
        print(await hik.device.link.read_text("/ISAPI/System/time"))  # level 1: the document


asyncio.run(main())
```

### How devices differ

Devices differ by model, and by firmware of the same model: a DS-KD8003 plays the sound
of a call slowly unless each RTP packet carries 40 ms. Each difference is a behaviour,
set by rules of model and firmware (`KNOWN_RULES`, each with where it was seen). For a
device the library does not know yet, give your own rules:

```python
import asyncio
import os

import aiohikvision
from aiohikvision import BehaviourPatch, Match, PacketTime, Rule, VersionRange

RULES = [
    Rule(
        Match(model="DS-KD9403*", firmware=VersionRange.parse(">=2.2,<2.3")),
        BehaviourPatch(talk_packet=PacketTime.MS_40),
    )
]


async def main() -> None:
    async with aiohikvision.connect(
        os.environ["DEVICE_HOST"], os.environ["DEVICE_USERNAME"], os.environ["DEVICE_PASSWORD"], rules=RULES
    ) as hik:
        decision = hik.device.resolved.decisions["talk_packet"]
        print(hik.device.behaviours.talk_packet, "decided by", decision.source)


asyncio.run(main())
```

```text
40ms decided by rule
```

`overrides=BehaviourPatch(...)` wins over every rule.

## Door stations

### Doors and speaker

`DoorStation` opens the doors of a door station, reads what it has, and plays sound
through its speaker outside a call:

```python
import asyncio
import os

import aiohttp

from aiohikvision import DoorStation


async def main() -> None:
    async with aiohttp.ClientSession() as session:
        door = DoorStation(
            session, os.environ["DEVICE_HOST"], os.environ["DEVICE_USERNAME"], os.environ["DEVICE_PASSWORD"]
        )
        info = await door.read_info()
        print("Doors:", info.doors, "Speaker:", info.talk)
        # await door.open_door(1)  # opens the lock of door 1


asyncio.run(main())
```

### Its calls, over SIP

A door station calls over SIP (`pip install "aiohikvision[sip]"`): the library is the
server of its VoIP line and answers, refuses or hangs up its calls
([why SIP](https://github.com/webysther/aio-hikvision/blob/main/docs/ADR-0001-hybrid-call.md)):

```python
import asyncio
import os

from aiohikvision import CallServer, CallState, DoorCall, DoorRegistrar, DoorTransport


async def main() -> None:
    door_ip = os.environ["DOOR_IP"]  # the address its SIP packets come from
    transport = DoorTransport(local_addr=("0.0.0.0", 5060), allowed_hosts={door_ip})
    tasks: set[asyncio.Task[object]] = set()

    def changed(call: DoorCall) -> None:
        print(call.state.value, call.callee, call.end_reason)
        if call.state is CallState.RINGING:
            # Refuse it: the door shows "busy". calls.answer(call.id) would answer
            task = asyncio.get_running_loop().create_task(calls.reject(call.id))
            tasks.add(task)
            task.add_done_callback(tasks.discard)

    calls = CallServer(
        transport,
        advertise=os.environ["MY_IP"],  # this machine's address, as the door reaches it
        on_change=changed,
        registrar=DoorRegistrar(),
    )
    await calls.start()
    try:
        await asyncio.sleep(600)
    finally:
        await calls.stop()


asyncio.run(main())
```

During an answered call, `call.push(frame)` sends your microphone to the door (G.711,
in the 40 ms packets it needs), and `CallServer(on_audio=...)` hands on the door's
sound ([why](https://github.com/webysther/aio-hikvision/blob/main/docs/ADR-0002-door-sound-over-sip.md)).
`scripts/door_server.py` runs the library as the server of a real door station, from
a terminal. What the door station does, measured, is in
[docs/DEVICE_FINDINGS.md](https://github.com/webysther/aio-hikvision/blob/main/docs/DEVICE_FINDINGS.md):
point its VoIP line at your server, and set its SIP audio to G.711 only.

## What it covers, and migrating to it

| Part | Today |
|---|---|
| Who a device is, what it supports, its cameras, pictures and streams | Available |
| Rules of model and firmware, the device report, the debug log | Available |
| Door stations: doors, inputs and outputs, settings, speaker, calls over SIP | Available |
| Events: which a device notifies, their state, the alert stream | Available |
| Recorders: a camera per channel, its name, the relayed picture of a channel | Available |
| Live video in the browser, PTZ, smart detections, recordings | Planned |

aiohikvision aims to be the one library the Hikvision projects of Home Assistant need.
These guides map what each one uses to aiohikvision, with the code before and after:

- [from pyHik](https://github.com/webysther/aio-hikvision/blob/main/docs/migration/from-pyhik.md), the `hikvision` integration of Home Assistant core;
- [from the ISAPI client of hikvision_next](https://github.com/webysther/aio-hikvision/blob/main/docs/migration/from-hikvision-next.md);
- [from aiohikvision 0.1](https://github.com/webysther/aio-hikvision/blob/main/docs/migration/hikvision-bridge.md), Hikvision Bridge;
- [for the intercom projects](https://github.com/webysther/aio-hikvision/blob/main/docs/migration/intercom-projects.md) of Home Assistant.

## Extras

Each part is an extra; the default install has no dependency, and a part used without
its extra raises `MissingExtra`, which says what to install.

| Extra | Installs | For |
|---|---|---|
| `isapi` | aiohttp, yarl, defusedxml | the devices over ISAPI: everything above but the calls |
| `sip` | aiosipua | the calls of door stations |
| `rtp` | nothing yet | RTP, which `sip` uses |
| `scrambling` | cryptography | encrypted program streams of recordings |
| `all` | everything | |

## Development

```sh
uv sync
uv run pytest --cov
uv run mypy
uv run ruff check . && uv run ruff format --check .
```

The tests never reach a device: they run against doubles of the measured ones
(`tests/fakes`), with anonymized answers.

## License

MIT, except the parts derived from
[Hikvision Bridge](https://github.com/yannik2480/hikvision_bridge), by yannik2480 and its
contributors, which keep its
[Apache License 2.0](https://github.com/webysther/aio-hikvision/blob/main/LICENSES/Apache-2.0.txt)
and were changed for this library: the ISAPI layer (`aiohikvision.isapi.wire`,
`aiohikvision.isapi.model`), the digest authentication (`aiohikvision.auth.digest`), and,
in the tests, the fake ISAPI device with its answers (`tests/fakes`) and the tests of
`aiohikvision.isapi`. Hikvision is a trademark of its owner; this project is not
affiliated with it.
