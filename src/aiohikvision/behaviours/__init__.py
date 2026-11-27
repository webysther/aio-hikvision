"""How a device behaves where Hikvision devices differ: one named value per quirk.

Devices differ by model, and by firmware of the same model: a door station plays its sound
slowly unless it gets 40 ms packets, another answers its event stream with an empty 200.
Each such difference is a field of :class:`Behaviours`, whose value is a named enum and whose
default is what a generic Hikvision device does. :mod:`aiohikvision.behaviours.rules` sets the
values of a device from its model and firmware (``resolve``); the code that talks to the device
reads the value instead of testing models itself.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, fields

from aiohikvision.models._coded import CodedEnum, coded


@coded(MS_20=1, MS_40=2)
class PacketTime(CodedEnum):
    """How much sound each RTP packet sent to the device carries."""

    MS_20 = "20ms"
    """The default of RFC 3551."""
    MS_40 = "40ms"
    """Door stations that play 20 ms packets slowly (DS-KD8003: docs/DEVICE_FINDINGS.md)."""

    @property
    def milliseconds(self) -> int:
        """Return the duration of a packet."""
        return {PacketTime.MS_20: 20, PacketTime.MS_40: 40}[self]


@coded(MULTIPART=1, NONE=2)
class AlertStream(CodedEnum):
    """What ``/ISAPI/Event/notification/alertStream`` gives."""

    MULTIPART = "multipart"
    """A multipart stream of events, kept open."""
    NONE = "none"
    """No stream: a short answer, then the connection closes. The feed does not keep trying."""


@coded(ADVERTISED=1, ALWAYS=2)
class CallStatusRead(CodedEnum):
    """When the call status of a door station (``/ISAPI/VideoIntercom/callStatus``) is read."""

    ADVERTISED = "advertised"
    """When the capabilities offer it (``isSupportCallStatus``)."""
    ALWAYS = "always"
    """Always: the device answers it without offering it."""


@coded(EVENT_TRIGGERS=1, TRIGGERS_CAP=2)
class TriggerSource(CodedEnum):
    """Where the events a device can notify, and how, are read."""

    EVENT_TRIGGERS = "event_triggers"
    """``/ISAPI/Event/triggers``."""
    TRIGGERS_CAP = "triggers_cap"
    """``/ISAPI/Event/triggersCap``: the device fails on ``/ISAPI/Event/triggers``."""


@dataclass(frozen=True, slots=True)
class Behaviours:
    """How a device behaves; each default is what a generic Hikvision device does."""

    talk_packet: PacketTime = PacketTime.MS_20
    alert_stream: AlertStream = AlertStream.MULTIPART
    call_status: CallStatusRead = CallStatusRead.ADVERTISED
    triggers: TriggerSource = TriggerSource.EVENT_TRIGGERS


@dataclass(frozen=True, slots=True)
class BehaviourPatch:
    """Some behaviours of :class:`Behaviours` to change; None leaves one as it is."""

    talk_packet: PacketTime | None = None
    alert_stream: AlertStream | None = None
    call_status: CallStatusRead | None = None
    triggers: TriggerSource | None = None

    def apply(self, behaviours: Behaviours) -> Behaviours:
        """Return the behaviours with the ones of the patch changed."""
        return Behaviours(
            talk_packet=self.talk_packet or behaviours.talk_packet,
            alert_stream=self.alert_stream or behaviours.alert_stream,
            call_status=self.call_status or behaviours.call_status,
            triggers=self.triggers or behaviours.triggers,
        )

    def changes(self) -> dict[str, CodedEnum]:
        """Return the behaviours the patch changes, by name."""
        return {item.name: value for item in fields(self) if (value := getattr(self, item.name)) is not None}


@dataclass(frozen=True, slots=True)
class Measured:
    """Where a behaviour was seen: the device, its firmware, when, and who reported it."""

    model: str
    firmware: str
    on: dt.date
    source: str
