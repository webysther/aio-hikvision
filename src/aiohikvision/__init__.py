"""Asyncio library for Hikvision devices, and to be the indoor station of their door stations.

A door station calls over SIP (``aiohikvision.sip``: a registrar for its VoIP line, the call,
and the microphone to the door in 40 ms packets, see docs/ADR-0001-hybrid-call.md); everything
else is ISAPI (``aiohikvision.isapi``: ``DoorStation`` opens its doors, gives its picture and
stream, and plays sound through its speaker outside a call).
"""

from aiohikvision.isapi.door_station import DoorStation, DoorStationInfo, NotADoorStation, NotALock
from aiohikvision.isapi.model.features.outputs import Output, OutputUse
from aiohikvision.isapi.model.features.talk import TalkEnd, TalkError, TwoWayAudio
from aiohikvision.rtp.talkback import Packetizer, Talkback, TalkbackStats
from aiohikvision.sip.calls import CallError, CallServer, CallState, DoorCall, EndReason
from aiohikvision.sip.registrar import DoorRegistrar, Registration
from aiohikvision.sip.transport import DoorTransport, is_keepalive

__version__ = "0.1.4"

__all__ = [
    "CallError",
    "CallServer",
    "CallState",
    "DoorCall",
    "DoorRegistrar",
    "DoorStation",
    "DoorStationInfo",
    "DoorTransport",
    "EndReason",
    "NotADoorStation",
    "NotALock",
    "Output",
    "OutputUse",
    "Packetizer",
    "Registration",
    "TalkEnd",
    "TalkError",
    "Talkback",
    "TalkbackStats",
    "TwoWayAudio",
    "__version__",
    "is_keepalive",
]
