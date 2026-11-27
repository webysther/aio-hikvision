"""Asyncio library for Hikvision devices: ISAPI, RTP, RTSP and the SIP calls of door stations.

Install only the parts you use. ``pip install aiohikvision`` has no dependency: the models,
the behaviours of the devices (``aiohikvision.behaviours``) and the errors. The extras add the
rest, and a name of a part without its extra raises :class:`MissingExtra` with how to install
it:

- ``aiohikvision[isapi]``: :class:`HikvisionClient` and :class:`Device`, the HTTP API of
  cameras, recorders and door stations (``aiohikvision.isapi``);
- ``aiohikvision[rtp]``: RTP, the microphone to a door during a call (``aiohikvision.rtp``);
- ``aiohikvision[sip]``: the SIP calls of door stations (``aiohikvision.sip``, see
  docs/ADR-0001-hybrid-call.md);
- ``aiohikvision[all]``: everything.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any, Final

from aiohikvision._extras import require
from aiohikvision.behaviours import (
    AlertStream,
    BehaviourPatch,
    Behaviours,
    CallStatusRead,
    Measured,
    PacketTime,
    TriggerSource,
)
from aiohikvision.behaviours.rules import KNOWN_RULES, Match, Resolved, Rule, VersionRange, resolve
from aiohikvision.errors import HikvisionError, MissingExtra
from aiohikvision.models.capabilities import Capabilities, Domain, Support
from aiohikvision.models.firmware import Firmware
from aiohikvision.models.identity import Identity
from aiohikvision.models.streaming import AudioCodec, Stream, StreamId, StreamKind, VideoCodec, VideoFormat

if TYPE_CHECKING:
    from aiohikvision.client import HikvisionClient
    from aiohikvision.device import Device
    from aiohikvision.isapi.door_station import (
        DoorStation,
        DoorStationHealth,
        DoorStationInfo,
        NotADoorStation,
        NotALock,
        Setting,
    )
    from aiohikvision.isapi.model.features.image import ImageCapability, ImageValue
    from aiohikvision.isapi.model.features.inputs import Input, InputUse
    from aiohikvision.isapi.model.features.outputs import Output, OutputUse
    from aiohikvision.isapi.model.features.talk import TalkEnd, TalkError, TwoWayAudio
    from aiohikvision.rtp.door_sound import DoorSound, DoorSoundStats, Dropped
    from aiohikvision.rtp.packets import RtpPacket
    from aiohikvision.rtp.talkback import Packetizer, Talkback, TalkbackStats
    from aiohikvision.services.streaming import Streaming
    from aiohikvision.sip.calls import CallError, CallServer, CallState, DoorCall, EndReason
    from aiohikvision.sip.registrar import DoorRegistrar, Registration
    from aiohikvision.sip.transport import DoorTransport, is_keepalive

__version__ = "0.2.0"

_LAZY: Final[dict[str, tuple[str, str]]] = {
    **dict.fromkeys(("HikvisionClient",), ("aiohikvision.client", "isapi")),
    **dict.fromkeys(("Device",), ("aiohikvision.device", "isapi")),
    **dict.fromkeys(("Streaming",), ("aiohikvision.services.streaming", "isapi")),
    **dict.fromkeys(
        ("DoorStation", "DoorStationHealth", "DoorStationInfo", "NotADoorStation", "NotALock", "Setting"),
        ("aiohikvision.isapi.door_station", "isapi"),
    ),
    **dict.fromkeys(("ImageCapability", "ImageValue"), ("aiohikvision.isapi.model.features.image", "isapi")),
    **dict.fromkeys(("Input", "InputUse"), ("aiohikvision.isapi.model.features.inputs", "isapi")),
    **dict.fromkeys(("Output", "OutputUse"), ("aiohikvision.isapi.model.features.outputs", "isapi")),
    **dict.fromkeys(
        ("TalkEnd", "TalkError", "TwoWayAudio"), ("aiohikvision.isapi.model.features.talk", "isapi")
    ),
    **dict.fromkeys(("DoorSound", "DoorSoundStats", "Dropped"), ("aiohikvision.rtp.door_sound", "rtp")),
    **dict.fromkeys(("RtpPacket",), ("aiohikvision.rtp.packets", "rtp")),
    **dict.fromkeys(("Packetizer", "Talkback", "TalkbackStats"), ("aiohikvision.rtp.talkback", "rtp")),
    **dict.fromkeys(
        ("CallError", "CallServer", "CallState", "DoorCall", "EndReason"), ("aiohikvision.sip.calls", "sip")
    ),
    **dict.fromkeys(("DoorRegistrar", "Registration"), ("aiohikvision.sip.registrar", "sip")),
    **dict.fromkeys(("DoorTransport", "is_keepalive"), ("aiohikvision.sip.transport", "sip")),
}
"""The names of the parts behind an extra: their module, and the extra that installs what it needs."""


def __getattr__(name: str) -> Any:  # noqa: ANN401  # any name of the parts behind an extra
    """Import a name of a part on first use, saying which extra it needs when it is missing."""
    if name not in _LAZY:
        msg = f"module 'aiohikvision' has no attribute {name!r}"
        raise AttributeError(msg)
    module, extra = _LAZY[name]
    require(extra)
    value = getattr(importlib.import_module(module), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """List the names of the package, those behind an extra too."""
    return sorted(__all__)


__all__ = [
    "KNOWN_RULES",
    "AlertStream",
    "AudioCodec",
    "BehaviourPatch",
    "Behaviours",
    "CallError",
    "CallServer",
    "CallState",
    "CallStatusRead",
    "Capabilities",
    "Device",
    "Domain",
    "DoorCall",
    "DoorRegistrar",
    "DoorSound",
    "DoorSoundStats",
    "DoorStation",
    "DoorStationHealth",
    "DoorStationInfo",
    "DoorTransport",
    "Dropped",
    "EndReason",
    "Firmware",
    "HikvisionClient",
    "HikvisionError",
    "Identity",
    "ImageCapability",
    "ImageValue",
    "Input",
    "InputUse",
    "Match",
    "Measured",
    "MissingExtra",
    "NotADoorStation",
    "NotALock",
    "Output",
    "OutputUse",
    "PacketTime",
    "Packetizer",
    "Registration",
    "Resolved",
    "RtpPacket",
    "Rule",
    "Setting",
    "Stream",
    "StreamId",
    "StreamKind",
    "Streaming",
    "Support",
    "TalkEnd",
    "TalkError",
    "Talkback",
    "TalkbackStats",
    "TriggerSource",
    "TwoWayAudio",
    "VersionRange",
    "VideoCodec",
    "VideoFormat",
    "__version__",
    "is_keepalive",
    "resolve",
]
