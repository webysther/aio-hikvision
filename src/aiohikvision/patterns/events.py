"""The events of a device as an integration sees them: which, how each stands, and when they change.

::

    async for source, state in hik.events.watch():
        print(source, "on" if state.active else "off")

An integration runs :meth:`EventMonitor.run` as a task of its own and subscribes its entities:
each reads :meth:`EventMonitor.state` and :attr:`EventMonitor.connected` when called.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from aiohikvision.services.events import OFF_AFTER, EventStates

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable

    from aiohikvision.errors import HikvisionError
    from aiohikvision.models.events import EventSource, EventState
    from aiohikvision.services.events import Events, Frame

_LOGGER = logging.getLogger(__name__)


class EventMonitor:
    """The events of a device: its sources, how each stands, and who to tell when one changes."""

    def __init__(
        self, events: Events, sources: tuple[EventSource, ...], *, off_after: timedelta = OFF_AFTER
    ) -> None:
        """Watch the events of a device (level 2); an event turns off ``off_after`` after its last post."""
        self.events = events
        self.sources = sources
        """The events the device notifies, read when it connected."""
        self.connected = False
        """Whether the alert stream is open."""
        self.fault: HikvisionError | None = None
        """Why the alert stream last dropped; None while it is fine."""
        self._states = EventStates(sources, off_after)
        self._callbacks: dict[EventSource | None, list[Callable[[], object]]] = {}
        self._listeners: list[Callable[[tuple[EventSource, EventState]], object]] = []
        self._timer: asyncio.TimerHandle | None = None
        self._running = False

    def state(self, source: EventSource) -> EventState:
        """Return how an event stands; off when it never happened."""
        return self._states[source]

    def subscribe(
        self, callback: Callable[[], object], source: EventSource | None = None
    ) -> Callable[[], None]:
        """Call ``callback`` when ``source`` (any, if None) turns on or off, or the stream connects or drops.

        Return the function that stops it.
        """
        callbacks = self._callbacks.setdefault(source, [])
        callbacks.append(callback)

        def unsubscribe() -> None:
            with contextlib.suppress(ValueError):
                callbacks.remove(callback)

        return unsubscribe

    async def run(self) -> None:
        """Keep the alert stream open, until cancelled.

        It returns at once for a device without an alert stream, and when the device refuses
        the account: :attr:`fault` then says why.
        """
        feed = self.events.feed(self._on_frame, self._on_state)
        if feed is None:
            return
        self._running = True
        try:
            await feed.run()
        finally:
            self._running = False
            self._stop_timer()
            self._drop()

    async def watch(self) -> AsyncGenerator[tuple[EventSource, EventState]]:
        """Yield each event that turns on or off, with its state, running the alert stream meanwhile.

        Unless :meth:`run` already runs: then it only listens.
        """
        changes: asyncio.Queue[tuple[EventSource, EventState]] = asyncio.Queue()
        self._listeners.append(changes.put_nowait)
        runner = None if self._running else asyncio.create_task(self.run())
        try:
            while True:
                change = asyncio.ensure_future(changes.get())
                waiting: set[asyncio.Future[Any]] = {change} if runner is None else {change, runner}
                done, _ = await asyncio.wait(waiting, return_when=asyncio.FIRST_COMPLETED)
                if change not in done and runner is not None:
                    change.cancel()
                    runner.result()  # what stopped the stream
                    return
                yield change.result()  # the state the change brought, not a later one
        finally:
            self._listeners.remove(changes.put_nowait)
            if runner is not None:
                runner.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await runner

    def _on_frame(self, frame: Frame) -> None:
        source = self._states.apply(frame)
        if source is not None:
            self._changed(source)
        self._arm()

    def _on_state(self, connected: bool, fault: HikvisionError | None) -> None:  # noqa: FBT001  # the feed's handler
        self.connected, self.fault = connected, fault
        for callbacks in list(self._callbacks.values()):
            for callback in list(callbacks):
                _call(callback)

    def _drop(self) -> None:
        """Tell the subscribers the stream is closed, unless they know."""
        if self.connected:
            self._on_state(connected=False, fault=None)

    def _changed(self, source: EventSource) -> None:
        for callback in [*self._callbacks.get(source, ()), *self._callbacks.get(None, ())]:
            _call(callback)
        for listener in list(self._listeners):
            listener((source, self._states[source]))

    def _arm(self) -> None:
        """Wake when the next event turns off by itself."""
        self._stop_timer()
        expiry = self._states.next_expiry()
        if expiry is not None:
            delay = (expiry - datetime.now(UTC)).total_seconds()
            self._timer = asyncio.get_running_loop().call_later(max(delay, 0), self._expire)

    def _expire(self) -> None:
        self._timer = None
        for source in self._states.expire(datetime.now(UTC)):
            self._changed(source)
        self._arm()

    def _stop_timer(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None


def _call(callback: Callable[[], object]) -> None:
    try:
        callback()
    except Exception:
        _LOGGER.exception("An event callback failed")
