"""The behaviours of a device from its model and firmware: rules, the most specific winning.

A :class:`Rule` matches devices (a model, a glob of models, a range of firmware versions, a
device type) and sets some behaviours. :func:`resolve` starts from the defaults of
:class:`~aiohikvision.behaviours.Behaviours`, applies the rules that match a device from the
least to the most specific, then the caller's overrides, and says what decided each behaviour.

:data:`KNOWN_RULES` are the behaviours seen on real devices, each with where it was seen. A
consumer adds its own rules (a device the library does not know yet) and overrides
(``HikvisionClient(rules=..., overrides=...)``) without waiting for a release.
"""

from __future__ import annotations

import datetime as dt
import fnmatch
import operator
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from typing import TYPE_CHECKING, Final

from aiohikvision.behaviours import (
    AlertStream,
    BehaviourPatch,
    Behaviours,
    CallStatusRead,
    Measured,
    PacketTime,
    TriggerSource,
)
from aiohikvision.models._coded import CodedEnum, coded
from aiohikvision.models.firmware import Firmware

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from aiohikvision.models.identity import Identity

_CLAUSE: Final = re.compile(r"^\s*(==|>=|<=|>|<)\s*V?(\d+(?:\.\d+)*)\s*$")
"""One clause of a range of versions: an operator and a version (``>=3.7``, ``==V2.2.53``)."""

_GLOB: Final = re.compile(r"[*?]")

type Version = tuple[int, ...]


def _padded(version: Version, length: int) -> Version:
    """Return a version with zeros added to the given length: 3.7 compares as 3.7.0."""
    return version + (0,) * (length - len(version))


def _compare(left: Version, right: Version, compare: Callable[[Version, Version], bool]) -> bool:
    length = max(len(left), len(right))
    return compare(_padded(left, length), _padded(right, length))


@dataclass(frozen=True, slots=True)
class Bound:
    """One end of a range of versions."""

    version: Version
    inclusive: bool


@dataclass(frozen=True, slots=True)
class VersionRange:
    """Firmware versions between two bounds, either open: ``VersionRange.parse(">=3.7,<3.8")``."""

    lower: Bound | None = None
    upper: Bound | None = None

    @classmethod
    def parse(cls, text: str) -> VersionRange:
        """Return the range of clauses separated by commas: ``==``, ``>=``, ``<=``, ``>``, ``<``."""
        lower: Bound | None = None
        upper: Bound | None = None
        for clause in text.split(","):
            found = _CLAUSE.match(clause)
            if found is None:
                msg = f"not a range of versions: {text!r}"
                raise ValueError(msg)
            op, number = found.groups()
            version = tuple(int(part) for part in number.split("."))
            if op in {"==", ">=", ">"}:
                lower = Bound(version, op != ">")
            if op in {"==", "<=", "<"}:
                upper = Bound(version, op != "<")
        return cls(lower, upper)

    def __contains__(self, firmware: object) -> bool:
        """Return whether a firmware's version is in the range; an unread version never is."""
        if not isinstance(firmware, Firmware) or not firmware.known:
            return False
        version = firmware.parts
        if self.lower and not _compare(
            version, self.lower.version, operator.ge if self.lower.inclusive else operator.gt
        ):
            return False
        return not self.upper or _compare(
            version, self.upper.version, operator.le if self.upper.inclusive else operator.lt
        )

    @property
    def bounds(self) -> int:
        """Return how many ends the range has: a closed range is more specific than an open one."""
        return (self.lower is not None) + (self.upper is not None)

    def overlaps(self, other: VersionRange) -> bool:
        """Return whether some version is in both ranges."""
        lower = _highest_lower(self.lower, other.lower)
        upper = _lowest_upper(self.upper, other.upper)
        if lower is None or upper is None:
            return True
        if _compare(lower.version, upper.version, operator.lt):
            return True
        return _compare(lower.version, upper.version, operator.eq) and lower.inclusive and upper.inclusive


def _highest_lower(first: Bound | None, second: Bound | None) -> Bound | None:
    if first is None or second is None:
        return first or second
    if _compare(first.version, second.version, operator.eq):
        return first if not first.inclusive else second
    return first if _compare(first.version, second.version, operator.gt) else second


def _lowest_upper(first: Bound | None, second: Bound | None) -> Bound | None:
    if first is None or second is None:
        return first or second
    if _compare(first.version, second.version, operator.eq):
        return first if not first.inclusive else second
    return first if _compare(first.version, second.version, operator.lt) else second


@dataclass(frozen=True, slots=True)
class Match:
    """The devices a rule is for; a part left None matches every device.

    ``model`` is a model (``"DS-KD8003-IME1(B)"``) or a glob of models (``"DS-KD8003*"``),
    compared in upper case.
    """

    model: str | None = None
    firmware: VersionRange | None = None
    device_type: str | None = None

    def matches(self, identity: Identity) -> bool:
        """Return whether a device is one of these."""
        if self.model is not None and not fnmatch.fnmatchcase(identity.model.upper(), self.model.upper()):
            return False
        if self.firmware is not None and identity.firmware not in self.firmware:
            return False
        return self.device_type is None or (identity.device_type or "").upper() == self.device_type.upper()

    @property
    def specificity(self) -> tuple[int, int, int, int]:
        """Return how specific the match is, to compare matches.

        A model before a glob of models, and the glob that spells more of the model
        (``DS-KD8003*`` before ``DS-KD*``); then a closed range of versions before an open
        one; then a device type.
        """
        if self.model is None:
            model, spelled = 0, 0
        else:
            model, spelled = (1 if _GLOB.search(self.model) else 2), len(_GLOB.sub("", self.model))
        firmware = 0 if self.firmware is None else self.firmware.bounds
        return (model, spelled, firmware, int(self.device_type is not None))


@dataclass(frozen=True, slots=True)
class Rule:
    """Some behaviours of the devices a :class:`Match` is for, and where they were seen."""

    match: Match
    sets: BehaviourPatch
    measured: Measured | None = None


@coded(DEFAULT=1, RULE=2, OVERRIDE=3)
class Source(CodedEnum):
    """What decided a behaviour."""

    DEFAULT = "default"
    RULE = "rule"
    OVERRIDE = "override"


@dataclass(frozen=True, slots=True)
class Decision:
    """What decided a behaviour: the default, a rule (which one), or the caller's override."""

    source: Source
    rule: Rule | None = None


@dataclass(frozen=True, slots=True)
class Resolved:
    """The behaviours of a device, and what decided each one."""

    behaviours: Behaviours
    decisions: Mapping[str, Decision] = field(default_factory=dict)


def resolve(
    identity: Identity,
    rules: Iterable[Rule] = (),
    overrides: BehaviourPatch | None = None,
) -> Resolved:
    """Return the behaviours of a device: the defaults, the matching rules, then the overrides.

    Rules apply from the least to the most specific (:attr:`Match.specificity`); between rules
    as specific, the later one wins, so the caller's rules, given after :data:`KNOWN_RULES`,
    win over the library's.
    """
    behaviours = Behaviours()
    decisions = {item.name: Decision(Source.DEFAULT) for item in fields(Behaviours)}
    matching = sorted((rule for rule in rules if rule.match.matches(identity)), key=_specificity)
    for rule in matching:
        behaviours = rule.sets.apply(behaviours)
        decisions |= dict.fromkeys(rule.sets.changes(), Decision(Source.RULE, rule))
    if overrides is not None:
        behaviours = overrides.apply(behaviours)
        decisions |= dict.fromkeys(overrides.changes(), Decision(Source.OVERRIDE))
    return Resolved(behaviours, decisions)


def _specificity(rule: Rule) -> tuple[int, int, int, int]:
    return rule.match.specificity


@dataclass(frozen=True, slots=True)
class Ambiguity:
    """Two rules as specific, for the same devices, that set a behaviour differently."""

    first: Rule
    second: Rule
    behaviour: str


def ambiguities(rules: Iterable[Rule]) -> list[Ambiguity]:
    """Return the pairs of rules whose order alone would decide a behaviour.

    Two rules clash when they are as specific, name the same model (or glob) and device type,
    their ranges of versions overlap, and they set a behaviour to different values.
    """
    listed = list(rules)
    found: list[Ambiguity] = []
    for index, first in enumerate(listed):
        for second in listed[index + 1 :]:
            if not _same_devices(first.match, second.match):
                continue
            theirs = second.sets.changes()
            found.extend(
                Ambiguity(first, second, name)
                for name, value in first.sets.changes().items()
                if name in theirs and theirs[name] != value
            )
    return found


def _same_devices(first: Match, second: Match) -> bool:
    if first.specificity != second.specificity:
        return False
    if (first.model or "").upper() != (second.model or "").upper():
        return False
    if (first.device_type or "").upper() != (second.device_type or "").upper():
        return False
    return first.firmware is None or second.firmware is None or first.firmware.overlaps(second.firmware)


KNOWN_RULES: Final[tuple[Rule, ...]] = (
    Rule(
        Match(model="DS-KD8003*"),
        BehaviourPatch(talk_packet=PacketTime.MS_40),
        Measured(
            "DS-KD8003-IME1(B)",
            "V3.7.3",
            dt.date(2026, 11, 24),
            "aiohikvision docs/DEVICE_FINDINGS.md: 20 ms packets play at about 0.65 speed",
        ),
    ),
    Rule(
        Match(model="SF-VI111", firmware=VersionRange.parse("==2.2.53")),
        BehaviourPatch(call_status=CallStatusRead.ALWAYS),
        Measured(
            "SF-VI111",
            "V2.2.53",
            dt.date(2026, 11, 26),
            "Hikvision Bridge: answers callStatus without isSupportCallStatus",
        ),
    ),
    Rule(
        Match(model="DS-KV8113-WME1(B)", firmware=VersionRange.parse("==2.2.53")),
        BehaviourPatch(alert_stream=AlertStream.NONE),
        Measured(
            "DS-KV8113-WME1(B)",
            "V2.2.53",
            dt.date(2026, 11, 26),
            "pyHik reports: the alert stream sends 40 bytes, then closes",
        ),
    ),
    Rule(
        Match(model="DS-2CD3366WDV3-I", firmware=VersionRange.parse("==5.8.22")),
        BehaviourPatch(triggers=TriggerSource.TRIGGERS_CAP),
        Measured(
            "DS-2CD3366WDV3-I",
            "V5.8.22",
            dt.date(2026, 11, 26),
            "pyHik reports: /ISAPI/Event/triggers answers 5xx without storage",
        ),
    ),
)
"""The behaviours seen on real devices (see :class:`~aiohikvision.behaviours.Measured`)."""
