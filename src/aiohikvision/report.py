"""What a device is and answers, to send to aiohikvision: the capability report.

``await device.report()`` reads the documents that describe a device, with GET only, and
returns them anonymized (:class:`~aiohikvision.isapi.wire.anonymize.Anonymizer`), with what
the library makes of them and what it is missing:

- the domains the device shows, and how this library covers each;
- its behaviours, and what decided each (a rule, with where it was seen, or the default);
- the values it did not recognise, and the documents that failed.

Attached to an issue (``python -m aiohikvision report`` writes it to a file), it becomes the
fixture and the rules that support the device. A path containing a word of
:data:`NEVER_READ` is never requested: those GETs act, or hand out secrets.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

from aiohikvision import __version__
from aiohikvision.errors import HikvisionError
from aiohikvision.isapi.wire.anonymize import Anonymizer
from aiohikvision.isapi.wire.faults import BadCredentials, Forbidden, LockedOut, Unsupported, detail
from aiohikvision.models._coded import CodedEnum, coded
from aiohikvision.models.capabilities import Domain, Support
from aiohikvision.models.streaming import AudioCodec, VideoCodec

if TYPE_CHECKING:
    from collections.abc import Iterable

    from aiohikvision.device import Device

NEVER_READ: Final = (
    "reboot",
    "factoryreset",
    "shutdown",
    "activate",
    "challenge",
    "updatefirmware",
    "onlineupgrade",
    "eaglefocusing",
    "ptzctrl",
    "/search",
    "configurationdata",
    "diagnoseddata",
    "dumpdata",
    "fileexport",
    "channelconfig",
    "download",
    "audiodata",
    "alertstream",
    "qrcode",
    "email",
    "certificate",
    "security/users",
    "userpermission",
    "lockedusers",
    "questionconfiguration",
    "secretkey",
    "ezviz",
    "ehome",
    "mailing",
    "ftp",
    "ddns",
    "httphosts",
    "socketip",
    "network/interfaces",
    "wireless",
    "picture",
    "userinfo",
    "cardinfo",
    "facedata",
    "acsevent",
    "deviceid",
)
"""Words (in lower case) of the paths a report never reads.

From the ISAPI guide: these GETs act (reboot, calibrate, store a PTZ position, scan the
network), or hand out secrets and personal data (configuration exports, the microphone,
pictures, users, cards, faces, the access log, keys, Wi-Fi, the intercom address).
"""

REPORT_PATHS: Final[tuple[tuple[str, Domain | None], ...]] = (
    ("/ISAPI/System/deviceInfo", None),
    ("/ISAPI/System/capabilities", None),
    ("/ISAPI/System/status", None),
    ("/ISAPI/System/time/capabilities", None),
    ("/ISAPI/Security/capabilities", None),
    ("/ISAPI/Security/adminAccesses", None),
    ("/ISAPI/Security/illegalLoginLock", None),
    ("/ISAPI/Streaming/channels", Domain.STREAMING),
    ("/ISAPI/Streaming/status", Domain.STREAMING),
    ("/ISAPI/System/Video/inputs/channels", Domain.STREAMING),
    ("/ISAPI/Image/channels", Domain.STREAMING),
    ("/ISAPI/Image/channels/1/capabilities", Domain.STREAMING),
    ("/ISAPI/System/IO/capabilities", Domain.IO),
    ("/ISAPI/System/IO/inputs", Domain.IO),
    ("/ISAPI/System/IO/inputs/capabilities", Domain.IO),
    ("/ISAPI/System/IO/outputs", Domain.IO),
    ("/ISAPI/System/IO/outputs/capabilities", Domain.IO),
    ("/ISAPI/System/IO/status", Domain.IO),
    ("/ISAPI/System/Audio/capabilities", Domain.TWO_WAY_AUDIO),
    ("/ISAPI/System/Audio/AudioIn/channels/1/capabilities", Domain.TWO_WAY_AUDIO),
    ("/ISAPI/System/Audio/AudioOut/channels/1/capabilities", Domain.TWO_WAY_AUDIO),
    ("/ISAPI/System/TwoWayAudio/channels", Domain.TWO_WAY_AUDIO),
    ("/ISAPI/System/TwoWayAudio/channels/1/capabilities", Domain.TWO_WAY_AUDIO),
    ("/ISAPI/Event/capabilities", Domain.EVENTS),
    ("/ISAPI/Event/channels/capabilities", Domain.EVENTS),
    ("/ISAPI/Event/triggers", Domain.EVENTS),
    ("/ISAPI/Event/notification/subscribeEventCap", Domain.EVENTS),
    ("/ISAPI/Smart/capabilities", Domain.SMART),
    ("/ISAPI/ContentMgmt/capabilities", None),
    ("/ISAPI/ContentMgmt/Storage", None),
    ("/ISAPI/ContentMgmt/InputProxy/channels", None),
    ("/ISAPI/ContentMgmt/StreamingProxy/channels", None),
    ("/ISAPI/VideoIntercom/capabilities", Domain.VIDEO_INTERCOM),
    ("/ISAPI/VideoIntercom/callStatus?format=json", Domain.VIDEO_INTERCOM),
    ("/ISAPI/VideoIntercom/operationTime", Domain.VIDEO_INTERCOM),
    ("/ISAPI/AccessControl/capabilities", Domain.ACCESS_CONTROL),
    ("/ISAPI/AccessControl/RemoteControl/door/capabilities", Domain.ACCESS_CONTROL),
    ("/ISAPI/AccessControl/AcsCfg/capabilities", Domain.ACCESS_CONTROL),
)
"""The documents a report reads, GET only, each with the domain it belongs to: those of a
domain the capabilities say the device lacks are not asked. Each stream adds its capabilities.
"""


@coded(ANSWERED=1, UNSUPPORTED=2, FORBIDDEN=3, FAILED=4)
class Outcome(CodedEnum):
    """What became of a request of the report."""

    ANSWERED = "answered"
    UNSUPPORTED = "unsupported"
    """The device has no such resource (404, notSupport…): a result too."""
    FORBIDDEN = "forbidden"
    """The account may not read it."""
    FAILED = "failed"
    """Another error: worth a look."""


@coded(SERVICE=1, DOOR_STATION=2, NONE=3)
class Coverage(CodedEnum):
    """How this library covers a domain."""

    SERVICE = "service"
    """A service of :class:`~aiohikvision.Device`."""
    DOOR_STATION = "door_station"
    """``DoorStation`` and ``aiohikvision.isapi.model``, moving onto ``Device``."""
    NONE = "none"
    """Not yet: a report of such a device shows what to build."""


COVERAGE: Final[dict[Domain, Coverage]] = {
    Domain.STREAMING: Coverage.SERVICE,
    Domain.VIDEO_INTERCOM: Coverage.DOOR_STATION,
    Domain.ACCESS_CONTROL: Coverage.DOOR_STATION,
    Domain.TWO_WAY_AUDIO: Coverage.DOOR_STATION,
    Domain.IO: Coverage.DOOR_STATION,
    Domain.EVENTS: Coverage.DOOR_STATION,
    Domain.SMART: Coverage.NONE,
    Domain.PTZ: Coverage.NONE,
    Domain.HOLIDAYS: Coverage.NONE,
}
"""How this library covers each domain today."""


def readable(path: str) -> bool:
    """Return whether a report may read a path: none of :data:`NEVER_READ` is in it."""
    lowered = path.lower()
    return not any(word in lowered for word in NEVER_READ)


@dataclass(frozen=True, slots=True)
class ReportEntry:
    """A document the report asked for, and what came of it."""

    path: str
    outcome: Outcome
    body: str | None = None
    """The document, anonymized, when the device answered."""
    error: str | None = None


@dataclass(frozen=True, slots=True)
class CapabilityReport:
    """What a device is and answers, anonymized, and what this library makes of it."""

    library: str
    device: dict[str, str | None]
    domains: dict[str, str]
    coverage: dict[str, str]
    behaviours: dict[str, dict[str, Any]]
    unknown: tuple[str, ...]
    entries: tuple[ReportEntry, ...] = field(default=())

    @property
    def failed(self) -> tuple[ReportEntry, ...]:
        """Return the documents that failed for another reason than being absent."""
        return tuple(entry for entry in self.entries if entry.outcome is Outcome.FAILED)

    def as_dict(self) -> dict[str, Any]:
        """Return the report as JSON data."""
        return {
            "library": self.library,
            "device": self.device,
            "domains": self.domains,
            "coverage": self.coverage,
            "behaviours": self.behaviours,
            "unknown": list(self.unknown),
            "failed": [entry.path for entry in self.failed],
            "documents": [
                {"path": entry.path, "outcome": entry.outcome, "body": entry.body, "error": entry.error}
                for entry in self.entries
            ],
        }

    def to_json(self) -> str:
        """Return the report as indented JSON, to attach to an issue."""
        return json.dumps(self.as_dict(), indent=2, ensure_ascii=False)


async def collect_report(device: Device, *, secrets: Iterable[str] = ()) -> CapabilityReport:
    """Read the documents of a device and return them anonymized, with what is missing.

    ``secrets`` are masked wherever they appear (the address and the account are added). A
    refused login stops the report at once: the device's lockout is never approached.
    """
    identity = device.identity
    anonymizer = Anonymizer(
        (
            *secrets,
            device.link.endpoint.host,
            *device.link.credentials,
            identity.serial,
            identity.mac or "",
            identity.device_id or "",
        )
    )
    paths = [path for path, domain in REPORT_PATHS if _asked(device, domain)]
    streams = await device.streaming.streams() if device.streaming else ()
    paths += [f"/ISAPI/Streaming/channels/{stream.id.isapi}/capabilities" for stream in streams]
    entries = [await _read(device, path, anonymizer) for path in paths if readable(path)]
    unknown = [
        f"stream {stream.id.isapi}: video codec not recognised"
        for stream in streams
        if stream.video is not None and stream.video.codec is VideoCodec.OTHER
    ] + [
        f"stream {stream.id.isapi}: sound codec not recognised"
        for stream in streams
        if stream.audio is AudioCodec.OTHER
    ]
    if not any(decision.rule for decision in device.resolved.decisions.values()):
        unknown.append("no rule knows this model and firmware: its behaviours are the defaults")
    return CapabilityReport(
        library=__version__,
        device={
            "model": identity.model,
            "firmware": str(identity.firmware),
            "device_type": identity.device_type,
            "hardware": identity.hardware,
        },
        domains={domain: device.capabilities.support(domain) for domain in Domain},
        coverage={
            domain: COVERAGE[domain]
            for domain in Domain
            if device.capabilities.support(domain) is not Support.ABSENT
        },
        behaviours={
            name: {
                "value": getattr(device.behaviours, name),
                "decided_by": decision.source,
                "rule": decision.rule.match.model if decision.rule else None,
            }
            for name, decision in device.resolved.decisions.items()
        },
        unknown=tuple(unknown),
        entries=tuple(entries),
    )


def _asked(device: Device, domain: Domain | None) -> bool:
    return domain is None or device.capabilities.support(domain) is not Support.ABSENT


async def _read(device: Device, path: str, anonymizer: Anonymizer) -> ReportEntry:
    try:
        text = await device.link.read_text(path)
    except (BadCredentials, LockedOut):
        raise
    except Unsupported:
        return ReportEntry(path, Outcome.UNSUPPORTED)
    except Forbidden:
        return ReportEntry(path, Outcome.FORBIDDEN)
    except HikvisionError as err:
        return ReportEntry(path, Outcome.FAILED, error=anonymizer.text(detail(err)))
    return ReportEntry(path, Outcome.ANSWERED, body=anonymizer.text(text or ""))
