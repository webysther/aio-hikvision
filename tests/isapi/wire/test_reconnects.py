"""When the event stream is connected again: the policy alone, without a device."""

from __future__ import annotations

import pytest

from aiohikvision.isapi.wire import feed
from aiohikvision.isapi.wire.feed import Reconnects, Retry, Session, SessionEnd, StreamBehaviour

CLOSED, QUIET = SessionEnd.CLOSED, SessionEnd.QUIET
# A door station on some firmware: 200 with a bare XML declaration, closed at once (#84 of
# hikvision_bridge).
BARE = Session(CLOSED, multipart=False, frames=0, seconds=0.1)
QUICK = Session(CLOSED, multipart=True, frames=0, seconds=0.1)
EVENTS = Session(CLOSED, multipart=True, frames=2, seconds=0.1)
LONG = Session(CLOSED, multipart=True, frames=0, seconds=feed.QUICK_CLOSE)
SILENT = Session(QUIET, multipart=True, frames=0, seconds=feed.SILENCE_LIMIT)


def judge(*sessions: Session) -> list[Retry]:
    reconnects = Reconnects()
    return [reconnects.after(session) for session in sessions]


def test_a_working_stream_reconnects_after_the_first_delay() -> None:
    assert judge(EVENTS, LONG, EVENTS) == [Retry(StreamBehaviour.LIVE, feed.BACKOFF_FIRST)] * 3


def test_a_quiet_stream_is_reopened_at_once() -> None:
    assert judge(SILENT) == [Retry(StreamBehaviour.QUIET, 0.0)]


def test_quick_closes_double_the_delay_up_to_the_limit() -> None:
    delays = [retry.delay for retry in judge(*[QUICK] * 9)]
    assert delays == [5.0, 10.0, 20.0, 40.0, 80.0, 160.0, 300.0, 300.0, 300.0]
    assert {retry.behaviour for retry in judge(QUICK)} == {StreamBehaviour.QUICK_CLOSE}


def test_a_working_connection_starts_the_backoff_again() -> None:
    reconnects = Reconnects()
    for _ in range(3):
        reconnects.after(QUICK)
    assert reconnects.after(EVENTS).delay == feed.BACKOFF_FIRST
    assert reconnects.after(QUICK).delay == 2 * feed.BACKOFF_FIRST


def test_bare_answers_give_up_on_the_stream() -> None:
    assert [retry.behaviour for retry in judge(BARE, BARE, BARE, BARE)] == [
        StreamBehaviour.BARE,
        StreamBehaviour.BARE,
        StreamBehaviour.NO_STREAM,
        StreamBehaviour.NO_STREAM,
    ]
    assert judge(BARE, BARE, BARE)[-1].delay == feed.UNSUPPORTED_RETRY


def test_bare_answers_back_off_until_then() -> None:
    assert [retry.delay for retry in judge(BARE, BARE)] == [5.0, 10.0]


def test_only_bare_answers_in_a_row_count() -> None:
    assert judge(BARE, BARE, EVENTS, BARE)[-1].behaviour is StreamBehaviour.BARE


def test_a_bare_answer_with_events_is_a_stream() -> None:
    # Some firmware may leave the boundary out and still send events: they are what counts.
    events_without_boundary = Session(CLOSED, multipart=False, frames=1, seconds=0.1)
    assert judge(*[events_without_boundary] * 4)[-1].behaviour is StreamBehaviour.LIVE


def test_failures_share_the_backoff_of_the_sessions() -> None:
    reconnects = Reconnects()
    assert reconnects.after(QUICK).delay == 5.0
    assert reconnects.after_failure() == 10.0
    assert reconnects.after(EVENTS).delay == 5.0


@pytest.mark.parametrize(
    ("behaviour", "error"),
    [
        (StreamBehaviour.LIVE, None),
        (StreamBehaviour.QUIET, None),
        (StreamBehaviour.QUICK_CLOSE, feed.QUICK_CLOSE_ERROR),
        (StreamBehaviour.BARE, feed.NO_STREAM),
        (StreamBehaviour.NO_STREAM, feed.NO_STREAM),
    ],
)
def test_the_error_each_behaviour_records(behaviour: StreamBehaviour, error: str | None) -> None:
    assert behaviour.error == error
