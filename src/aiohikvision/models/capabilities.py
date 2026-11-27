"""What a device says it can do: every flag of ``/ISAPI/System/capabilities``, and its domains.

The capabilities are read once, when a :class:`~aiohikvision.Device` is made. A domain (the
door station's calls, the inputs and outputs, two-way audio…) is PRESENT when the document
shows evidence of it, ABSENT when the document has none, and UNKNOWN when the device sent no
document: then the services of the domain ask the device instead of trusting a flag.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Final

from aiohikvision.models._coded import CodedEnum, coded


@coded(PRESENT=1, ABSENT=2, UNKNOWN=3)
class Support(CodedEnum):
    """Whether a device has something."""

    PRESENT = "present"
    ABSENT = "absent"
    UNKNOWN = "unknown"
    """The device did not say: ask it."""


@coded(
    STREAMING=1,
    EVENTS=2,
    IO=3,
    VIDEO_INTERCOM=4,
    ACCESS_CONTROL=5,
    TWO_WAY_AUDIO=6,
    SMART=7,
    PTZ=8,
    HOLIDAYS=9,
)
class Domain(CodedEnum):
    """A part of ISAPI a device may offer."""

    STREAMING = "streaming"
    """Video channels, their streams and pictures."""
    EVENTS = "events"
    """Alarms and the events stream."""
    IO = "io"
    """Alarm inputs and relay outputs."""
    VIDEO_INTERCOM = "video_intercom"
    """The calls of a door station or an indoor station."""
    ACCESS_CONTROL = "access_control"
    """Doors and their locks."""
    TWO_WAY_AUDIO = "two_way_audio"
    """Sound to the device's speaker."""
    SMART = "smart"
    """Smart detections: line crossing, intrusion, region entrance…"""
    PTZ = "ptz"
    """Pan, tilt and zoom."""
    HOLIDAYS = "holidays"
    """Holidays of the schedules."""


class Evidence(Enum):
    """How an element of the capabilities shows a domain."""

    SECTION = "section"
    """The element is there."""
    FLAG = "flag"
    """The element says ``true``."""
    COUNT = "count"
    """The element counts more than zero."""


DOMAIN_EVIDENCE: Final[Mapping[Domain, tuple[tuple[str, Evidence], ...]]] = {
    Domain.STREAMING: (("isSupportSnapshot", Evidence.FLAG), ("VideoCap", Evidence.SECTION)),
    Domain.EVENTS: (("EventCap", Evidence.SECTION),),
    Domain.IO: (("IOInputPortNums", Evidence.COUNT), ("IOOutputPortNums", Evidence.COUNT)),
    Domain.VIDEO_INTERCOM: (("VideoIntercomCap", Evidence.SECTION),),
    Domain.ACCESS_CONTROL: (("isSupportAccessControlCap", Evidence.FLAG),),
    # A door station counts its speaker (audioOutputNums) but no voice talk (voicetalkNums)
    Domain.TWO_WAY_AUDIO: (("voicetalkNums", Evidence.COUNT), ("audioOutputNums", Evidence.COUNT)),
    Domain.SMART: (("SmartCap", Evidence.SECTION),),
    Domain.PTZ: (("PTZCtrlCap", Evidence.SECTION),),
    # Spelled so by the devices
    Domain.HOLIDAYS: (("isSupportHolidy", Evidence.FLAG),),
}
"""The elements (by name, anywhere in the document) that show each domain, the first that does wins."""


@dataclass(frozen=True, slots=True)
class CapabilityTree:
    """Every element of a capabilities document, by its path: ``"SysCap/IOCap/IOInputPortNums"``.

    A section (an element with elements in it) is there with an empty text. ``options`` holds
    the values an element offers (its ``opt`` attribute).
    """

    values: Mapping[str, str] = field(default_factory=dict)
    options: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def __bool__(self) -> bool:
        """Return whether the device sent a document."""
        return bool(self.values)

    def find(self, name: str) -> str | None:
        """Return the path of the first element named so, anywhere in the document."""
        return next(
            (path for path in self.values if path == name or path.endswith(f"/{name}")),
            None,
        )

    def text(self, name: str) -> str | None:
        """Return the text of the first element named so; None when there is none."""
        path = self.find(name)
        return None if path is None else self.values[path]

    def flag(self, name: str) -> Support:
        """Return whether the first element named so says ``true``."""
        text = self.text(name)
        if text is None:
            return Support.UNKNOWN if not self else Support.ABSENT
        return Support.PRESENT if text.strip().lower() == "true" else Support.ABSENT

    def count(self, name: str) -> int | None:
        """Return the number in the first element named so; None when it holds none."""
        text = (self.text(name) or "").strip()
        return int(text) if text.isdigit() else None


@dataclass(frozen=True, slots=True)
class Capabilities:
    """What a device says it can do (``/ISAPI/System/capabilities``)."""

    tree: CapabilityTree = field(default_factory=CapabilityTree)

    def support(self, domain: Domain) -> Support:
        """Return whether the device has a domain, from the evidence of :data:`DOMAIN_EVIDENCE`."""
        if not self.tree:
            return Support.UNKNOWN
        for name, evidence in DOMAIN_EVIDENCE[domain]:
            if _shows(self.tree, name, evidence):
                return Support.PRESENT
        return Support.ABSENT

    @property
    def domains(self) -> tuple[Domain, ...]:
        """Return the domains the device has."""
        return tuple(domain for domain in Domain if self.support(domain) is Support.PRESENT)


def _shows(tree: CapabilityTree, name: str, evidence: Evidence) -> bool:
    """Return whether an element shows its domain."""
    if evidence is Evidence.SECTION:
        return tree.find(name) is not None
    if evidence is Evidence.FLAG:
        return tree.flag(name) is Support.PRESENT
    return (tree.count(name) or 0) > 0
