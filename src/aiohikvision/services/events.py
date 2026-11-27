"""The events of a device: which it notifies, its alert stream, and how each one stands."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import TYPE_CHECKING, Final

from aiohikvision.behaviours import AlertStream, TriggerSource
from aiohikvision.isapi.wire.faults import DeviceRejected, Forbidden, Unsupported
from aiohikvision.isapi.wire.feed import AlarmFeed, FeedFrame
from aiohikvision.isapi.wire.scrub import scrubbed_logger
from aiohikvision.models.events import EventSource, EventState
from aiohikvision.parsers.events import EVENT_TRIGGERS, TRIGGERS_CAP, parse_triggers, parse_triggers_cap

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from datetime import datetime

    from aiohikvision.behaviours import Behaviours
    from aiohikvision.isapi.wire.feed import StateHandler
    from aiohikvision.isapi.wire.link import IsapiLink

_LOGGER = scrubbed_logger(__name__)

type Frame = FeedFrame
"""One event as the alert stream delivers it."""

NOTIFYING: Final = frozenset({"center", "http", "record", "email", "beep"})
"""The notification methods that bring a trigger's events to the alert stream, recorders
included (the set pyHik 0.5.0 settled on); a trigger with none of them is not notified."""

OFF_AFTER: Final = timedelta(seconds=5)
"""When an event the device stopped posting turns off: many post "active" and never
"inactive" (pyHik's update_stale waits 5 s too)."""

SERVER_ERROR: Final = 500
"""The first HTTP status of a server error: a device that has events but fails to list them."""

IDLE: Final = EventState()
"""The state of an event that never happened."""


class Events:
    """The events of a device: which it notifies, and its alert stream."""

    def __init__(self, link: IsapiLink, behaviours: Behaviours) -> None:
        """Talk to the device through its link, the way its behaviours say."""
        self.link = link
        self.behaviours = behaviours

    async def sources(self) -> tuple[EventSource, ...]:
        """Return the events the device notifies, once each, in its order."""
        if self.behaviours.triggers is TriggerSource.TRIGGERS_CAP:
            sources = await self._from_cap()
        else:
            sources = await self._from_triggers()
        _LOGGER.debug("Events of %s: %s", self.link.endpoint.host, describe(sources))
        return sources

    async def _from_triggers(self) -> tuple[EventSource, ...]:
        try:
            triggers = parse_triggers(await self.link.read_xml(EVENT_TRIGGERS))
        except (Unsupported, Forbidden):
            return ()
        except DeviceRejected as err:
            if err.status < SERVER_ERROR:
                return ()
            # Some cameras fail on the list without storage, and still say what they notify
            return await self._from_cap()
        return tuple(dict.fromkeys(trigger.source for trigger in triggers if trigger.methods & NOTIFYING))

    async def _from_cap(self) -> tuple[EventSource, ...]:
        return parse_triggers_cap(await self.link.read_xml(TRIGGERS_CAP, optional=True))

    def feed(self, on_frame: Callable[[Frame], None], on_state: StateHandler) -> AlarmFeed | None:
        """Return the alert stream of the device, to run; None when it has none."""
        if self.behaviours.alert_stream is AlertStream.NONE:
            return None
        return AlarmFeed(self.link, on_frame, on_state)


def describe(sources: Iterable[EventSource]) -> str:
    """Return events in a few words, for a log: "vmd 1-6, io 1,3, diskfull 1"."""
    channels: dict[str, list[int]] = {}
    for source in sources:
        channels.setdefault(source.type, []).append(source.channel)
    return ", ".join(f"{event} {_runs(numbers)}" for event, numbers in channels.items()) or "none"


def _runs(numbers: list[int]) -> str:
    """Write numbers as runs: 1, 2, 3, 5 is "1-3,5"."""
    runs: list[list[int]] = []
    for number in sorted(set(numbers)):
        if runs and number == runs[-1][-1] + 1:
            runs[-1].append(number)
        else:
            runs.append([number])
    return ",".join(f"{run[0]}-{run[-1]}" if len(run) > 1 else str(run[0]) for run in runs)


def source_of(frame: Frame) -> EventSource | None:
    """Return where a frame comes from; None for a heartbeat (an inactive video loss)."""
    if frame.heartbeat:
        return None
    channel = next((int(raw) for raw in (frame.channel_id, frame.port_id) if raw and raw.isdecimal()), 0)
    return EventSource(frame.raw_type.lower(), channel or 1)


class EventStates:
    """How each event of a device stands: on while the device posts it, off after a while.

    No I/O: each frame carries its time, and :meth:`expire` is given the time.
    """

    def __init__(self, sources: Iterable[EventSource] = (), off_after: timedelta = OFF_AFTER) -> None:
        """Start with every source off; an event turns off ``off_after`` after its last post."""
        self.off_after = off_after
        self._states = dict.fromkeys(sources, IDLE)
        self._posted: dict[EventSource, datetime] = {}

    def __getitem__(self, source: EventSource) -> EventState:
        """Return how an event stands; off when it never happened."""
        return self._states.get(source, IDLE)

    def apply(self, frame: Frame) -> EventSource | None:
        """Take a frame in; return its source when the frame turned it on or off."""
        source = source_of(frame)
        if source is None:
            return None
        before = self[source]
        if frame.is_active:
            self._posted[source] = frame.received
        else:
            self._posted.pop(source, None)
        turned = frame.is_active != before.active
        self._states[source] = EventState(
            active=frame.is_active,
            changed=frame.received if turned else before.changed,
            count=frame.extra.get("active_count") or before.count,
            target=frame.targets[0] if frame.targets else before.target,
        )
        return source if turned else None

    def expire(self, now: datetime) -> list[EventSource]:
        """Turn off the events not posted for ``off_after``, and return them."""
        stale = [source for source, posted in self._posted.items() if now - posted >= self.off_after]
        for source in stale:
            del self._posted[source]
            self._states[source] = replace(self._states[source], active=False, changed=now)
        return stale

    def next_expiry(self) -> datetime | None:
        """Return when the next event turns off by itself; None when none is on."""
        oldest = min(self._posted.values(), default=None)
        return None if oldest is None else oldest + self.off_after
