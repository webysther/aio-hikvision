# aiohikvision

Asyncio library for Hikvision devices: ISAPI (cameras, recorders, door stations)
and the SIP calls of video door stations. It is fully typed and has no Home
Assistant dependency; its main user is
[Hikvision Virtual Indoor Station](https://github.com/webysther/ha-hikvision-virtual-indoor-station),
which makes Home Assistant the indoor station of a door station.

```sh
pip install aiohikvision
```

Python 3.13 or newer.

## A door station, over ISAPI

`DoorStation` is what a door station does for its indoor station, on one
authenticated link: what it is, its doors, its picture, and its speaker.

```python
import asyncio
import os

import aiohttp

from aiohikvision import DoorStation


async def main() -> None:
    async with aiohttp.ClientSession() as session:
        door = DoorStation(
            session,
            os.environ["DOOR_HOST"],
            os.environ["DOOR_USERNAME"],
            os.environ["DOOR_PASSWORD"],
            port=int(os.environ.get("DOOR_PORT", "80")),
        )
        info = await door.read_info()
        print(info.identity.model, info.identity.firmware)
        print("Doors:", info.doors, "Speaker:", info.talk)
        # await door.open_door(1)  # opens the lock of door 1


asyncio.run(main())
```

It also takes a snapshot (`snapshot()`), gives the RTSP address of the stream with
its sound (`rtsp_url()`), checks that the device answers (`check()`), and plays
G.711 through the speaker outside a call (`talk()`, a `TwoWayAudio`: one talk at a
time, a new one takes the speaker over).

## Its calls, over SIP

The door station calls over SIP; its picture and sound are read over RTSP. The
library is the SIP server of the door's VoIP line and the callee of its calls
([why](https://github.com/webysther/aiohikvision/blob/main/docs/ADR-0001-hybrid-call.md)):

```python
import asyncio
import os

from aiohikvision import CallServer, CallState, DoorCall, DoorRegistrar, DoorTransport


async def main() -> None:
    door_ip = os.environ["DOOR_IP"]  # the address its SIP packets come from
    port = int(os.environ.get("SIP_PORT", "5060"))
    transport = DoorTransport(local_addr=("0.0.0.0", port), allowed_hosts={door_ip})
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
        await asyncio.sleep(float(os.environ.get("SECONDS", "600")))
    finally:
        await calls.stop()


asyncio.run(main())
```

- **`DoorTransport`:** UDP SIP that only hears the configured door stations, and
  drops their `jaK` keepalives quietly (`on_keepalive` tells they are alive).
- **`DoorRegistrar`:** accepts the REGISTER of the door's VoIP line, grants a
  shorter registration than it asks, and says when it registers and expires.
- **`CallServer` / `DoorCall`:** a call rings with 180 at once, then is answered,
  refused or hung up on command; every command names its call. Two answers at once
  give the call to the first. The answer is G.711 at `a=ptime:40`, `a=sendonly`,
  `m=video 0`.
- **`Talkback`:** the microphone to the door during a call: `call.push(frame)` takes
  20 ms G.711 frames, and they leave as 40 ms RTP packets on an absolute clock, in
  bursts. The door slows its own audio when it receives 20 ms packets.
- **`aiohikvision.media.g711`:** reference µ-law and A-law encoders, identical to
  audioop on every sample, tones and 20 ms frames.

### From a terminal

`scripts/door_server.py` runs the library as the server of a real door station,
with port 5060 free and the door's VoIP line pointing at this machine:

```sh
# Ring until the door gives up: the visitor hears the ringback
uv run python scripts/door_server.py --advertise <ha-ip> --door <door-ip> facade
# Answer after 5 s, talk in 1 kHz bursts (2 s on, 2 s off), hang up after 30 s
uv run python scripts/door_server.py --advertise <ha-ip> --door <door-ip> hybrid --answer-after 5
```

## What the door station does

Measured on a DS-KD8003-IME1(B) with firmware V3.7.1 and V3.7.3:
[docs/DEVICE_FINDINGS.md](https://github.com/webysther/aiohikvision/blob/main/docs/DEVICE_FINDINGS.md).
In short: point its VoIP line at your server, set its SIP audio to G.711 only
(its Opus is non-standard), and expect it to cancel after its ring time (60 s)
and hang up at its talk time (90 s by default).

## Development

```sh
uv sync
uv run pytest --cov
uv run mypy
uv run ruff check . && uv run ruff format --check .
```

The tests never reach a device: they run against doubles of the measured ones
(`tests/fakes`), with anonymized answers. `scripts/sip_probe.py` is the measuring
tool of the findings; its captures stay out of the repository.

## License

Apache License 2.0. The ISAPI subpackage comes from
[Hikvision Bridge](https://github.com/yannik2480/hikvision_bridge), by yannik2480,
under the same license: see
[NOTICE](https://github.com/webysther/aiohikvision/blob/main/NOTICE). Hikvision is
a trademark of its owner; this project is not affiliated with it.
