"""The events of a device: its sources, their state, and the alert stream (levels 2 and 3)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

import aiohikvision
from aiohikvision import (
    BehaviourPatch,
    EventMonitor,
    EventSource,
    EventState,
    Match,
    Rule,
    Trigger,
    TriggerSource,
)
from aiohikvision.behaviours import AlertStream
from aiohikvision.isapi.wire import faults
from aiohikvision.isapi.wire.feed import FeedFrame
from aiohikvision.isapi.wire.xmlview import parse
from aiohikvision.parsers.events import parse_triggers, parse_triggers_cap
from aiohikvision.services.events import EventStates, describe, source_of
from tests.fakes import FakeIsapiDevice
from tests.fakes.isapi import event_xml, xml_part

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from aiohttp.test_utils import TestServer

type Serve = Callable[[FakeIsapiDevice], Awaitable[TestServer]]

T0 = datetime(2026, 11, 27, 12, 0, tzinfo=UTC)
VMD = EventSource("vmd")
NOT_SUPPORTED = (
    "<ResponseStatus><statusCode>4</statusCode><subStatusCode>notSupport</subStatusCode></ResponseStatus>"
)
SERVER_ERROR = (
    "<ResponseStatus><statusCode>6</statusCode><subStatusCode>deviceError</subStatusCode></ResponseStatus>"
)
TRIGGERS_CAP = """<EventTriggerCapType xmlns="http://www.hikvision.com/ver20/XMLSchema">
<isSupportCenter>true</isSupportCenter>
<VMDTriggerCap><isSupportCenter>true</isSupportCenter></VMDTriggerCap>
<motionDetectionTriggerCap/>
<tamperDetectionTriggerCap/>
<illAccesTriggerCap/>
</EventTriggerCapType>"""


def _now(offset: float = 0) -> str:
    return (datetime.now(UTC) + timedelta(seconds=offset)).isoformat()


def _frame(state: str = "active", at: float = 0, **fields: object) -> FeedFrame:
    return FeedFrame(raw_type="VMD", state=state, received=T0 + timedelta(seconds=at), **fields)


# Level 1 → models: the parsers


def test_triggers_name_their_channel_and_how_they_notify() -> None:
    document = parse("""<EventTriggerList>
    <EventTrigger><id>VMD-2</id><eventType>VMD</eventType>
      <videoInputChannelID>34</videoInputChannelID><dynVideoInputChannelID>2</dynVideoInputChannelID>
      <EventTriggerNotificationList><EventTriggerNotification>
        <notificationMethod>center</notificationMethod></EventTriggerNotification>
      <EventTriggerNotification><notificationMethod>HTTP</notificationMethod></EventTriggerNotification>
      </EventTriggerNotificationList></EventTrigger>
    <EventTrigger><id>diskfull</id><eventType>diskfull</eventType><videoInputChannelID>0</videoInputChannelID>
      <EventTriggerNotificationList/></EventTrigger>
    <EventTrigger><id>empty</id><eventType/></EventTrigger>
    </EventTriggerList>""")
    assert parse_triggers(document) == (
        Trigger(EventSource("vmd", 2), frozenset({"center", "http"})),
        Trigger(EventSource("diskfull", 1), frozenset()),
    )
    assert parse_triggers(None) == ()


def test_triggers_cap_names_events_on_channel_one() -> None:
    assert parse_triggers_cap(parse(TRIGGERS_CAP)) == (
        EventSource("vmd"),
        EventSource("tamperdetection"),
        EventSource("illaccess"),
    )
    assert parse_triggers_cap(None) == ()


def test_where_a_frame_comes_from() -> None:
    assert source_of(_frame(channel_id="3")) == EventSource("vmd", 3)
    assert source_of(FeedFrame("IO", "active", port_id="2")) == EventSource("io", 2)
    assert source_of(_frame(channel_id="0")) == VMD
    assert source_of(FeedFrame("videoloss", "inactive")) is None  # a heartbeat
    assert str(EventSource("vmd", 2)) == "vmd 2"


def test_event_states_turn_on_off_and_expire() -> None:
    states = EventStates([VMD], timedelta(seconds=5))
    assert states[VMD] == EventState()
    assert states.next_expiry() is None
    assert states.apply(_frame(targets=("human",), extra={"active_count": 1})) == VMD
    assert states[VMD] == EventState(active=True, changed=T0, count=1, target="human")
    assert states.apply(_frame(at=2, extra={"active_count": 2})) is None  # still on, posted again
    assert states[VMD] == EventState(active=True, changed=T0, count=2, target="human")
    assert states.next_expiry() == T0 + timedelta(seconds=7)
    assert states.expire(T0 + timedelta(seconds=6)) == []
    assert states.expire(T0 + timedelta(seconds=7)) == [VMD]
    assert states[VMD] == EventState(active=False, changed=T0 + timedelta(seconds=7), count=2, target="human")
    assert states.apply(_frame(at=8)) == VMD
    assert states.apply(_frame("inactive", at=9)) == VMD  # a device that says when it ends
    assert states.next_expiry() is None
    assert states.apply(FeedFrame("videoloss", "inactive")) is None
    assert states[EventSource("io", 4)] == EventState()


def test_events_in_a_few_words() -> None:
    sources = [EventSource("vmd", n) for n in (3, 1, 2, 5)] + [EventSource("io"), EventSource("vmd", 2)]
    assert describe(sources) == "vmd 1-3,5, io 1"
    assert describe([]) == "none"


# Level 2: the events service


async def test_the_events_a_camera_notifies(serve: Serve) -> None:
    fake = FakeIsapiDevice("camera_g3")
    server = await serve(fake)
    async with aiohikvision.connect("127.0.0.1", fake.username, fake.password, port=server.port) as hik:
        assert hik.events is not None
        assert hik.events.sources[:3] == (EventSource("io"), VMD, EventSource("tamperdetection"))
        assert len(hik.events.sources) == 14
        assert hik.events.events is hik.device.events


async def test_a_recorder_lists_the_events_of_each_channel_once(serve: Serve) -> None:
    fake = FakeIsapiDevice("nvr")
    server = await serve(fake)
    async with aiohikvision.connect("127.0.0.1", fake.username, fake.password, port=server.port) as hik:
        assert hik.events is not None
        sources = hik.events.sources
        assert sources[:2] == (EventSource("vmd", 1), EventSource("vmd", 2))
        assert len(sources) == len(set(sources)) == 93
        assert EventSource("io", 1) not in sources  # its trigger notifies nobody


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (500, SERVER_ERROR, (VMD, EventSource("tamperdetection"), EventSource("illaccess"))),
        (404, NOT_SUPPORTED, ()),
        (
            400,
            "<ResponseStatus><statusCode>4</statusCode><subStatusCode>badParameters</subStatusCode></ResponseStatus>",
            (),
        ),
    ],
)
async def test_a_device_that_fails_on_its_triggers(
    serve: Serve, status: int, body: str, expected: tuple[EventSource, ...]
) -> None:
    """A server error means events it cannot list: triggersCap says which; others mean none."""
    fake = FakeIsapiDevice("camera_g3")
    fake.overrides["/ISAPI/Event/triggers"] = (status, body)
    fake.overrides["/ISAPI/Event/triggersCap"] = (200, TRIGGERS_CAP)
    server = await serve(fake)
    async with aiohikvision.connect("127.0.0.1", fake.username, fake.password, port=server.port) as hik:
        assert hik.events is not None
        assert hik.events.sources == expected


async def test_a_rule_reads_triggers_cap_first(serve: Serve) -> None:
    fake = FakeIsapiDevice("camera_g3")
    fake.overrides["/ISAPI/Event/triggersCap"] = (200, TRIGGERS_CAP)
    server = await serve(fake)
    rule = Rule(Match(model="*"), BehaviourPatch(triggers=TriggerSource.TRIGGERS_CAP))
    async with aiohikvision.connect(
        "127.0.0.1", fake.username, fake.password, port=server.port, rules=[rule]
    ) as hik:
        assert hik.events is not None
        assert hik.events.sources[0] == VMD
        assert ("GET", "/ISAPI/Event/triggers") not in fake.requests


# Level 3: the monitor


async def test_events_turn_on_tell_their_subscribers_and_turn_off(serve: Serve) -> None:
    fake = FakeIsapiDevice("camera_g3")
    fake.stream_parts = [
        xml_part(event_xml("VMD", when=_now(), extra="<targetType>human</targetType>")),
        xml_part(event_xml("VMD", when=_now())),  # posted again: no change
    ]
    fake.stream_hold = 5
    server = await serve(fake)
    async with aiohikvision.connect("127.0.0.1", fake.username, fake.password, port=server.port) as hik:
        assert hik.events is not None
        events = EventMonitor(hik.events.events, hik.events.sources, off_after=timedelta(milliseconds=200))
        changed = asyncio.Event()
        seen: list[tuple[bool, bool]] = []

        def on_change() -> None:
            seen.append((events.connected, events.state(VMD).active))
            changed.set()

        events.subscribe(on_change, VMD)
        stop = events.subscribe(on_change, EventSource("io"))
        stop()
        stop()  # twice is fine
        runner = asyncio.create_task(events.run())
        async with asyncio.timeout(5):
            while (True, False) not in seen[1:]:
                changed.clear()
                await changed.wait()
        assert seen[:2] == [(True, False), (True, True)]  # connected, then the motion
        assert events.state(VMD).target == "human"
        runner.cancel()
        with pytest.raises(asyncio.CancelledError):
            await runner
        assert seen[-1] == (False, False)
        assert not events.connected


async def test_watch_runs_the_stream_and_yields_each_change(serve: Serve) -> None:
    fake = FakeIsapiDevice("camera_g3")
    fake.stream_parts = [
        xml_part(event_xml("VMD", when=_now())),
        xml_part(event_xml("VMD", "inactive", when=_now())),
    ]
    fake.stream_hold = 5
    server = await serve(fake)
    async with aiohikvision.connect("127.0.0.1", fake.username, fake.password, port=server.port) as hik:
        assert hik.events is not None
        changes = []
        async with asyncio.timeout(5), contextlib.aclosing(hik.events.watch()) as watching:
            async for source, state in watching:
                changes.append((source, state.active))
                if len(changes) == 2:
                    break
        assert changes == [(VMD, True), (VMD, False)]
        assert not hik.events.connected


async def test_watch_listens_to_a_stream_already_running(serve: Serve) -> None:
    fake = FakeIsapiDevice("camera_g3")
    fake.stream_parts = [
        lambda: xml_part(event_xml("videoloss", "inactive", when=_now())),  # a heartbeat first
        lambda: xml_part(event_xml("VMD", when=_now())),
    ]
    fake.stream_gap = 0.3
    fake.stream_hold = 5
    server = await serve(fake)
    async with aiohikvision.connect("127.0.0.1", fake.username, fake.password, port=server.port) as hik:
        events = hik.events
        assert events is not None
        runner = asyncio.create_task(events.run())
        await asyncio.sleep(0.1)
        async with asyncio.timeout(5):
            source, state = await anext(aiter(events.watch()))
        assert (source, state.active) == (VMD, True)
        assert not runner.done()  # watch only listened
        runner.cancel()


async def test_a_device_without_an_alert_stream(serve: Serve) -> None:
    fake = FakeIsapiDevice("camera_g3")
    server = await serve(fake)
    rule = Rule(Match(model="*"), BehaviourPatch(alert_stream=AlertStream.NONE))
    async with aiohikvision.connect(
        "127.0.0.1", fake.username, fake.password, port=server.port, rules=[rule]
    ) as hik:
        assert hik.events is not None
        await hik.events.run()  # returns at once
        assert [change async for change in hik.events.watch()] == []
        assert ("GET", "/ISAPI/Event/notification/alertStream") not in fake.requests


async def test_a_failing_callback_is_logged(serve: Serve, caplog: pytest.LogCaptureFixture) -> None:
    fake = FakeIsapiDevice("camera_g3")
    fake.stream_hold = 5
    server = await serve(fake)
    async with aiohikvision.connect("127.0.0.1", fake.username, fake.password, port=server.port) as hik:
        events = hik.events
        assert events is not None
        called = asyncio.Event()

        def broken() -> None:
            called.set()
            raise RuntimeError

        events.subscribe(broken)
        runner = asyncio.create_task(events.run())
        with caplog.at_level(logging.ERROR, "aiohikvision.patterns.events"):
            async with asyncio.timeout(5):
                await called.wait()
        assert "An event callback failed" in caplog.text
        runner.cancel()


async def test_a_stream_cancelled_before_it_connects(serve: Serve) -> None:
    fake = FakeIsapiDevice("camera_g3")
    server = await serve(fake)
    async with aiohikvision.connect("127.0.0.1", fake.username, fake.password, port=server.port) as hik:
        assert hik.events is not None
        runner = asyncio.create_task(hik.events.run())
        await asyncio.sleep(0)
        runner.cancel()
        with pytest.raises(asyncio.CancelledError):
            await runner
        assert (hik.events.connected, hik.events.fault) == (False, None)


# The cameras of recorders


async def test_a_recorder_channel_gives_its_relayed_picture(serve: Serve) -> None:
    fake = FakeIsapiDevice("nvr")
    fake.overrides["/ISAPI/Streaming/channels/201/picture"] = (404, NOT_SUPPORTED)
    server = await serve(fake)
    async with aiohikvision.connect("127.0.0.1", fake.username, fake.password, port=server.port) as hik:
        camera = hik.cameras[1]
        assert camera.name == "201"
        assert (await camera.snapshot()).startswith(b"\xff\xd8")
        assert fake.requests[-1] == ("GET", "/ISAPI/ContentMgmt/StreamingProxy/channels/201/picture")
        fake.overrides["/ISAPI/ContentMgmt/StreamingProxy/channels/201/picture"] = (404, NOT_SUPPORTED)
        with pytest.raises(faults.Unsupported):
            await camera.snapshot()


def test_the_faults_are_names_of_the_package() -> None:
    assert aiohikvision.BadCredentials is faults.BadCredentials
    assert aiohikvision.Unreachable is faults.Unreachable
    assert aiohikvision.EventMonitor is EventMonitor
