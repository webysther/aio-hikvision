"""Be the SIP server of a Hikvision door station with aiohikvision, from a terminal.

The door station's VoIP line registers here, and its button calls here. It replaces the probe of
milestone 0 as the door's server between tests, and tests the library against the real door:

  facade  ring (180) until the door gives up: the visitor hears the ringback, nobody answers.
  hybrid  answer after --answer-after seconds, then send a 1 kHz tone for 2 s every 4 s (the
          way push-to-talk sends), in 40 ms packets, and hang up after --seconds.

Run it where Home Assistant runs, with port 5060 free (stop any other SIP server first):

  uv run python scripts/door_server.py --advertise <ha-ip> --door <door-ip> facade
  uv run python scripts/door_server.py --advertise <ha-ip> --door <door-ip> hybrid --answer-after 5
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import signal
import sys
from typing import TYPE_CHECKING, Any

from aiohikvision import CallError, CallServer, CallState, DoorRegistrar, DoorTransport
from aiohikvision.media.g711 import encode, frames, tone

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine, Sequence

    from aiohikvision import DoorCall, Registration

_LOGGER = logging.getLogger("door_server")


class DoorServer:
    """The registrar and the call server, driven by the chosen mode."""

    def __init__(self, args: argparse.Namespace) -> None:
        """Build the server from the command line."""
        self.args = args
        host, _, port = args.bind.rpartition(":")
        self.transport = DoorTransport(local_addr=(host, int(port)), allowed_hosts=set(args.door))
        self.registrar = DoorRegistrar(max_expires=args.max_expires, on_change=self._registration)
        self.calls = CallServer(
            self.transport,
            advertise=args.advertise,
            rtp_host=host,
            on_change=self._changed,
            registrar=self.registrar,
        )
        self._tasks: set[asyncio.Task[None]] = set()
        self._tone = frames(encode(tone(1000, args.burst)))

    @property
    def address(self) -> tuple[str, int]:
        """Where the door stations send, once started."""
        udp = self.transport._udp_transport  # noqa: SLF001
        if udp is None:
            return self.transport.local_addr
        host, port = udp.get_extra_info("sockname")[:2]
        return str(host), int(port)

    async def run(self, stop: asyncio.Event, ready: Callable[[tuple[str, int]], None] | None = None) -> None:
        """Serve until stopped, forgetting the registrations that run out."""
        await self.calls.start()
        _LOGGER.info(
            "SIP server on %s:%d for %s (%s mode)", *self.address, ", ".join(self.args.door), self.args.mode
        )
        if ready is not None:
            ready(self.address)
        try:
            while not stop.is_set():
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), 30)
                self.registrar.prune()
        finally:
            for task in list(self._tasks):
                task.cancel()
            await self.calls.stop()

    def _registration(self, registration: Registration, registered: bool) -> None:  # noqa: FBT001 (callback)
        if registered:
            _LOGGER.info("Door station %s registered line %s", registration.host, registration.user)
        else:
            _LOGGER.warning(
                "Door station %s is no longer registered (line %s)", registration.host, registration.user
            )

    def _changed(self, call: DoorCall) -> None:
        if call.state is CallState.RINGING:
            _LOGGER.info("Door station %s calls %s (%s)", call.door, call.callee, call.id)
            if self.args.mode == "hybrid":
                self._spawn(self._answer_later(call))
        elif call.state is CallState.ANSWERED:
            _LOGGER.info("Answered %s", call.id)
            self._spawn(self._talk(call))
        else:
            _LOGGER.info("Call %s ended: %s", call.id, call.end_reason)

    async def _answer_later(self, call: DoorCall) -> None:
        await asyncio.sleep(self.args.answer_after)
        with contextlib.suppress(CallError):  # the visitor may have walked away
            await self.calls.answer(call.id)

    async def _talk(self, call: DoorCall) -> None:
        """Push-to-talk with a tone: the frames go at the pace a browser sends them."""
        loop = asyncio.get_running_loop()
        end = loop.time() + self.args.seconds
        while call.state is CallState.ANSWERED and loop.time() < end:
            for frame in self._tone:
                call.push(frame)
                await asyncio.sleep(0.02)
            await asyncio.sleep(self.args.burst)
        if call.state is CallState.ANSWERED and call.talkback is not None:
            _LOGGER.info("Hanging up %s: %s", call.id, call.talkback.stats)
        with contextlib.suppress(CallError):
            await self.calls.hangup(call.id)

    def _spawn(self, coroutine: Coroutine[Any, Any, None]) -> None:
        task = asyncio.get_running_loop().create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)


def arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Read the command line."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n", 1)[0])
    parser.add_argument(
        "--bind", default="0.0.0.0:5060", help="where to listen for SIP (default 0.0.0.0:5060)"
    )
    parser.add_argument(
        "--advertise", required=True, help="this machine's address, as the door stations reach it"
    )
    parser.add_argument(
        "--door", action="append", required=True, help="a door station's address (repeatable)"
    )
    parser.add_argument(
        "--max-expires", type=int, default=600, help="longest registration granted, in seconds (default 600)"
    )
    modes = parser.add_subparsers(dest="mode", required=True)
    facade = modes.add_parser("facade", help="ring until the door gives up")
    facade.set_defaults(burst=2.0)
    hybrid = modes.add_parser("hybrid", help="answer, talk in tone bursts, hang up")
    hybrid.add_argument("--answer-after", type=float, default=5, help="seconds of ringing first (default 5)")
    hybrid.add_argument(
        "--seconds", type=float, default=30, help="seconds of talk before hanging up (default 30)"
    )
    hybrid.add_argument(
        "--burst", type=float, default=2.0, help="seconds of tone, then of silence (default 2)"
    )
    return parser.parse_args(argv)


async def serve(args: argparse.Namespace, stop: asyncio.Event | None = None) -> None:
    """Run until Ctrl+C (or until ``stop`` is set)."""
    stop = stop or asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError, RuntimeError):
            loop.add_signal_handler(signum, stop.set)
    await DoorServer(args).run(stop)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(serve(arguments(sys.argv[1:])))
