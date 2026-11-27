"""Every value has a numeric code that never changes: the codes released are frozen here."""

from __future__ import annotations

import pytest

from aiohikvision import AlertStream, CallStatusRead, Domain, PacketTime, Support, TriggerSource
from aiohikvision.behaviours.rules import Source
from aiohikvision.models._coded import CodedEnum, coded
from aiohikvision.models.streaming import AudioCodec, StreamKind, VideoCodec
from aiohikvision.patterns.hikvision import Kind

RELEASED = {
    Support: {"PRESENT": 1, "ABSENT": 2, "UNKNOWN": 3},
    Domain: {
        "STREAMING": 1,
        "EVENTS": 2,
        "IO": 3,
        "VIDEO_INTERCOM": 4,
        "ACCESS_CONTROL": 5,
        "TWO_WAY_AUDIO": 6,
        "SMART": 7,
        "PTZ": 8,
        "HOLIDAYS": 9,
    },
    PacketTime: {"MS_20": 1, "MS_40": 2},
    AlertStream: {"MULTIPART": 1, "NONE": 2},
    CallStatusRead: {"ADVERTISED": 1, "ALWAYS": 2},
    TriggerSource: {"EVENT_TRIGGERS": 1, "TRIGGERS_CAP": 2},
    Source: {"DEFAULT": 1, "RULE": 2, "OVERRIDE": 3},
    StreamKind: {"MAIN": 1, "SUB": 2, "THIRD": 3, "OTHER": 4},
    Kind: {"CAMERA": 1, "RECORDER": 2, "DOOR_STATION": 3, "OTHER": 4},
    VideoCodec: {"H264": 1, "H265": 2, "MJPEG": 3, "OTHER": 4},
    AudioCodec: {
        "G711_ULAW": 1,
        "G711_ALAW": 2,
        "G722": 3,
        "G726": 4,
        "AAC": 5,
        "MP2L2": 6,
        "MP3": 7,
        "PCM": 8,
        "OPUS": 9,
        "OTHER": 10,
    },
}


@pytest.mark.parametrize("values", list(RELEASED), ids=lambda values: values.__name__)
def test_the_codes_never_change(values: type[CodedEnum]) -> None:
    """A released code keeps its value, and a value is found by its code."""
    assert {member.name: member.code for member in values} == RELEASED[values]
    for member in values:
        assert values.from_code(member.code) is member
    assert values.from_code(0) is None


def test_every_value_needs_its_own_code() -> None:
    """A value without a code, or two values with one code, are found when the class is made."""

    class Colour(CodedEnum):
        RED = "red"
        GREEN = "green"

    with pytest.raises(TypeError, match="GREEN"):
        coded(RED=1)(Colour)
    with pytest.raises(TypeError, match="share"):
        coded(RED=1, GREEN=1)(Colour)
    assert coded(RED=1, GREEN=2)(Colour).GREEN.code == 2
