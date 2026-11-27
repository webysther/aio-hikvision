"""The behaviours of a device from its model and firmware: the most specific rule wins."""

from __future__ import annotations

import datetime as dt
from dataclasses import fields

import pytest

from aiohikvision import (
    KNOWN_RULES,
    AlertStream,
    BehaviourPatch,
    Behaviours,
    CallStatusRead,
    Firmware,
    Identity,
    Match,
    Measured,
    PacketTime,
    Rule,
    TriggerSource,
    VersionRange,
    resolve,
)
from aiohikvision.behaviours.rules import Source, ambiguities


def device(model: str = "DS-KD8003-IME1(B)", firmware: str = "V3.7.3", device_type: str = "VIS") -> Identity:
    """Return a device of a model, on a firmware."""
    return Identity("S", model, "N", Firmware.parse(firmware), device_type=device_type)


@pytest.mark.parametrize(
    ("text", "inside", "outside"),
    [
        (">=3.7,<3.8", ["V3.7", "V3.7.0", "V3.7.3", "V3.7.99"], ["V3.6.9", "V3.8", "V3.8.0", "V4.0"]),
        ("==2.2.53", ["V2.2.53", "V2.2.53.0"], ["V2.2.52", "V2.2.54"]),
        ("<=V1.2", ["V1.2", "V1.1.9", "V0.1"], ["V1.2.1"]),
        (">5", ["V5.0.1", "V6"], ["V5", "V5.0.0", "V4.9"]),
    ],
)
def test_a_range_of_versions(text: str, inside: list[str], outside: list[str]) -> None:
    """A range holds the versions between its bounds; a missing digit counts as zero."""
    versions = VersionRange.parse(text)
    for version in inside:
        assert Firmware.parse(version) in versions, version
    for version in outside:
        assert Firmware.parse(version) not in versions, version
    # A version that could not be read, or anything else, is in no range
    assert Firmware.parse("beta") not in versions
    assert "V3.7.3" not in versions


@pytest.mark.parametrize("text", ["", "3.7", "~=3.7", ">=3.x", ">=3.7;<4"])
def test_a_range_that_does_not_parse(text: str) -> None:
    """A range of versions is written with operators and numbers only."""
    with pytest.raises(ValueError, match="range of versions"):
        VersionRange.parse(text)


@pytest.mark.parametrize(
    ("first", "second", "overlap"),
    [
        (">=3.7,<3.8", ">=3.7.5", True),
        (">=3.7,<3.8", ">=3.8", False),
        (">=3.7,<=3.8", ">=3.8", True),
        ("<3.7", ">3.7", False),
        ("<=3.7", ">3.7", False),
        ("<3.7", ">=3.7", False),
        ("<=3.7", ">=3.7", True),
        ("==2.2.53", "==2.2.53", True),
        ("==2.2.53", "==2.2.54", False),
        (">=1", "<=9", True),
        (">=1", ">=2", True),
        ("<1", "<=2", True),
    ],
)
def test_ranges_that_overlap(first: str, second: str, overlap: bool) -> None:
    """Two ranges overlap when a version is in both."""
    assert VersionRange.parse(first).overlaps(VersionRange.parse(second)) is overlap
    assert VersionRange.parse(second).overlaps(VersionRange.parse(first)) is overlap


def test_what_a_match_is_for() -> None:
    """A match is for a model or a glob of models, a range of versions and a device type."""
    door = device()
    assert Match().matches(door)
    assert Match(model="ds-kd8003*").matches(door)
    assert Match(model="DS-KD8003-IME1(B)").matches(door)
    assert not Match(model="DS-KV*").matches(door)
    assert Match(firmware=VersionRange.parse(">=3.7")).matches(door)
    assert not Match(firmware=VersionRange.parse("<3.7")).matches(door)
    assert Match(device_type="vis").matches(door)
    assert not Match(device_type="NVR").matches(door)
    assert not Match(device_type="VIS").matches(device(device_type=""))


def test_the_more_specific_match() -> None:
    """A model before a glob, then a closed range before an open one, then a device type."""
    order = [
        Match(),
        Match(device_type="VIS"),
        Match(firmware=VersionRange.parse(">=3")),
        Match(firmware=VersionRange.parse(">=3,<4")),
        Match(model="DS-KD*"),
        Match(model="DS-KD*", firmware=VersionRange.parse("==3.7.3")),
        Match(model="DS-KD8003-IME1(B)"),
    ]
    assert sorted(order, key=lambda match: match.specificity) == order


def test_a_generic_device_behaves_by_default() -> None:
    """A device no rule is for behaves as a generic Hikvision device."""
    resolved = resolve(device(model="DS-2CD2043G2-I", device_type="IPCamera"), KNOWN_RULES)
    assert resolved.behaviours == Behaviours()
    assert {decision.source for decision in resolved.decisions.values()} == {Source.DEFAULT}
    assert set(resolved.decisions) == {item.name for item in fields(Behaviours)}


def test_the_door_station_of_the_findings() -> None:
    """A DS-KD8003 takes 40 ms packets, as measured, and says which rule decided it."""
    resolved = resolve(device(), KNOWN_RULES)
    assert resolved.behaviours.talk_packet is PacketTime.MS_40
    assert resolved.behaviours.talk_packet.milliseconds == 40
    decision = resolved.decisions["talk_packet"]
    assert decision.source is Source.RULE
    assert decision.rule is KNOWN_RULES[0]
    assert decision.rule.measured is not None
    assert decision.rule.measured.firmware == "V3.7.3"
    assert resolved.decisions["alert_stream"].source is Source.DEFAULT


@pytest.mark.parametrize(
    ("identity", "behaviour", "value"),
    [
        (device("SF-VI111", "V2.2.53"), "call_status", CallStatusRead.ALWAYS),
        (device("DS-KV8113-WME1(B)", "V2.2.53"), "alert_stream", AlertStream.NONE),
        (device("DS-2CD3366WDV3-I", "V5.8.22", "IPCamera"), "triggers", TriggerSource.TRIGGERS_CAP),
    ],
)
def test_the_devices_reported(identity: Identity, behaviour: str, value: object) -> None:
    """The behaviours reported on other devices hold on their firmware only."""
    assert getattr(resolve(identity, KNOWN_RULES).behaviours, behaviour) is value
    newer = Identity(identity.serial, identity.model, "N", Firmware.parse("V9.9.9"))
    assert getattr(resolve(newer, KNOWN_RULES).behaviours, behaviour) == getattr(Behaviours(), behaviour)


def test_the_most_specific_rule_wins_and_overrides_win_over_all() -> None:
    """Rules apply from the least to the most specific, the caller's last; then its overrides."""
    family = Rule(Match(model="DS-KD*"), BehaviourPatch(talk_packet=PacketTime.MS_20))
    exact = Rule(
        Match(model="DS-KD8003-IME1(B)", firmware=VersionRange.parse("==3.7.3")),
        BehaviourPatch(alert_stream=AlertStream.NONE),
    )
    # Given first, the most specific still wins
    resolved = resolve(device(), (exact, *KNOWN_RULES, family))
    assert resolved.behaviours.talk_packet is PacketTime.MS_40  # DS-KD8003* is more specific than DS-KD*
    assert resolved.behaviours.alert_stream is AlertStream.NONE
    assert resolved.decisions["alert_stream"].rule is exact
    # As specific as a known rule, the caller's rule given after it wins
    mine = Rule(Match(model="DS-KD8003*"), BehaviourPatch(talk_packet=PacketTime.MS_20))
    assert resolve(device(), (*KNOWN_RULES, mine)).behaviours.talk_packet is PacketTime.MS_20
    # Overrides win over every rule
    overridden = resolve(device(), KNOWN_RULES, BehaviourPatch(talk_packet=PacketTime.MS_20))
    assert overridden.behaviours.talk_packet is PacketTime.MS_20
    assert overridden.decisions["talk_packet"].source is Source.OVERRIDE
    assert overridden.decisions["talk_packet"].rule is None


def test_a_patch_changes_what_it_names() -> None:
    """A patch has the behaviours of Behaviours, and changes only those it sets."""
    assert [item.name for item in fields(BehaviourPatch)] == [item.name for item in fields(Behaviours)]
    every = BehaviourPatch(
        talk_packet=PacketTime.MS_40,
        alert_stream=AlertStream.NONE,
        call_status=CallStatusRead.ALWAYS,
        triggers=TriggerSource.TRIGGERS_CAP,
    )
    changed = every.apply(Behaviours())
    for item in fields(Behaviours):
        assert getattr(changed, item.name) != getattr(Behaviours(), item.name)
    assert set(every.changes()) == {item.name for item in fields(Behaviours)}
    assert BehaviourPatch().apply(changed) == changed
    assert BehaviourPatch().changes() == {}


def test_the_known_rules_are_not_ambiguous() -> None:
    """No two known rules leave a behaviour to their order, and each says where it was seen."""
    assert ambiguities(KNOWN_RULES) == []
    for rule in KNOWN_RULES:
        assert isinstance(rule.measured, Measured)
        assert rule.measured.on <= dt.date(2026, 11, 27)


def test_rules_that_clash() -> None:
    """Two rules as specific, for the same devices, that set a behaviour differently, clash."""
    forty = Rule(Match(model="DS-KD8003*"), BehaviourPatch(talk_packet=PacketTime.MS_40))
    twenty = Rule(Match(model="ds-kd8003*"), BehaviourPatch(talk_packet=PacketTime.MS_20))
    found = ambiguities([forty, twenty])
    assert [(clash.first, clash.second, clash.behaviour) for clash in found] == [
        (forty, twenty, "talk_packet")
    ]
    # The same value, other behaviours, other devices or another specificity do not clash
    same = Rule(Match(model="DS-KD8003*"), BehaviourPatch(talk_packet=PacketTime.MS_40))
    other = Rule(Match(model="DS-KD8003*"), BehaviourPatch(alert_stream=AlertStream.NONE))
    elsewhere = Rule(Match(model="DS-KV8113*"), BehaviourPatch(talk_packet=PacketTime.MS_20))
    typed = Rule(Match(model="DS-KD8003*", device_type="VIS"), BehaviourPatch(talk_packet=PacketTime.MS_20))
    assert ambiguities([forty, same, other, elsewhere, typed]) == []
    old = Rule(
        Match(model="X", firmware=VersionRange.parse("<2")), BehaviourPatch(alert_stream=AlertStream.NONE)
    )
    new = Rule(
        Match(model="X", firmware=VersionRange.parse(">=2")),
        BehaviourPatch(alert_stream=AlertStream.MULTIPART),
    )
    assert ambiguities([old, new]) == []
    typed_other = Rule(
        Match(model="DS-KD8003*", device_type="NVR"), BehaviourPatch(talk_packet=PacketTime.MS_40)
    )
    assert ambiguities([typed, typed_other]) == []
