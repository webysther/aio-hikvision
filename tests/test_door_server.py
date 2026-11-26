"""scripts/door_server.py against the fake door station: the library as the door's server."""

from __future__ import annotations

import asyncio
import importlib.util
import struct
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aiohikvision import CallState, EndReason
from tests.fakes import FakeDoorStation

if TYPE_CHECKING:
    from collections.abc import Callable

HOST = "127.0.0.1"
SCRIPT = Path(__file__).parent.parent / "scripts" / "door_server.py"


def load() -> Any:  # noqa: ANN401 (a script loaded by path)
    """Import the script, which is not part of the package."""
    spec = importlib.util.spec_from_file_location("door_server", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def until(condition: Callable[[], object], timeout: float = 3.0) -> None:  # noqa: ASYNC109
    """Wait for a condition to hold."""
    async with asyncio.timeout(timeout):
        while not condition():  # noqa: ASYNC110 (polls state that no event announces)
            await asyncio.sleep(0.01)


async def start(mode: list[str]) -> tuple[Any, asyncio.Event, asyncio.Task[None], tuple[str, int]]:
    """Start the script's server on loopback and return it, its stop event, its task and address."""
    module = load()
    args = module.arguments(["--bind", f"{HOST}:0", "--advertise", HOST, "--door", HOST, *mode])
    server = module.DoorServer(args)
    stop = asyncio.Event()
    ready: asyncio.Future[tuple[str, int]] = asyncio.get_running_loop().create_future()
    task = asyncio.create_task(server.run(stop, ready.set_result))
    return server, stop, task, await asyncio.wait_for(ready, 2)


async def test_hybrid() -> None:
    """It answers, sends tone bursts of 40 ms packets with a marker each, and hangs up."""
    server, stop, task, address = await start(
        ["hybrid", "--answer-after", "0.1", "--seconds", "0.5", "--burst", "0.2"]
    )
    door = FakeDoorStation(HOST)
    await door.start(address)
    try:
        door.register()
        fake = door.call("REDACTED")
        await fake.answered()
        await asyncio.wait_for(fake.ended.wait(), 3)
        assert server.registrar.registration(HOST) is not None
        packets = fake.rtp
        assert len(packets) >= 5
        assert {len(p) for p in packets} == {12 + 320}
        markers = [bool(struct.unpack("!B", p[1:2])[0] & 0x80) for p in packets]
        assert markers[0]
        assert sum(markers) >= 2  # one per burst
        call = next(iter(server.calls.calls.values()))
        assert call.state is CallState.ENDED
        assert call.end_reason is EndReason.HUNG_UP
    finally:
        stop.set()
        await task
        await door.stop()


async def test_facade() -> None:
    """It only rings: the call ends when the door gives up."""
    server, stop, task, address = await start(["facade"])
    door = FakeDoorStation(HOST)
    await door.start(address)
    try:
        fake = door.call("REDACTED")
        await asyncio.wait_for(fake.ringing.wait(), 2)
        await asyncio.sleep(0.2)
        call = next(iter(server.calls.calls.values()))
        assert call.state is CallState.RINGING
        fake.cancel()
        await until(lambda: call.state is CallState.ENDED)
        assert call.end_reason is EndReason.CANCELLED
    finally:
        stop.set()
        await task
        await door.stop()


def test_arguments() -> None:
    """The defaults of the command line."""
    args = load().arguments(["--advertise", "192.0.2.20", "--door", "192.0.2.10", "facade"])
    assert args.bind == "0.0.0.0:5060"
    assert args.max_expires == 600
    assert args.door == ["192.0.2.10"]
