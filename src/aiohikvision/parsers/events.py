"""The events a device notifies, from ``/ISAPI/Event/triggers`` or ``/ISAPI/Event/triggersCap``."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from aiohikvision.models.events import EventSource, Trigger

if TYPE_CHECKING:
    from aiohikvision.isapi.wire.xmlview import XmlNode

EVENT_TRIGGERS: Final = "/ISAPI/Event/triggers"
TRIGGERS_CAP: Final = "/ISAPI/Event/triggersCap"

CHANNEL_ELEMENTS: Final = (
    "dynVideoInputChannelID",
    "videoInputChannelID",
    "dynInputIOPortID",
    "inputIOPortID",
)
"""Where a trigger names its channel, the dynamic id first: a recorder numbers its streams by it."""

CAP_SUFFIX: Final = "TriggerCap"
"""``triggersCap`` lists one ``<type>TriggerCap`` element per event the device can notify."""

CAP_TYPES: Final = {"motiondetection": "vmd", "illacces": "illaccess"}
"""Capabilities named unlike the events they stand for (as pyHik 0.5.0 found on cameras)."""


def parse_triggers(document: XmlNode | None) -> tuple[Trigger, ...]:
    """Return the triggers of an ``EventTriggerList``, in its order."""
    if document is None:
        return ()
    triggers = []
    for node in document.walk("EventTrigger"):
        event = (node.text("eventType") or "").lower()
        if event:
            methods = frozenset(
                method.value.lower() for method in node.walk("notificationMethod") if method.value
            )
            triggers.append(Trigger(EventSource(event, _channel(node)), methods))
    return tuple(triggers)


def _channel(node: XmlNode) -> int:
    return next((number for element in CHANNEL_ELEMENTS if (number := node.numeric(element))), 1)


def parse_triggers_cap(document: XmlNode | None) -> tuple[EventSource, ...]:
    """Return the events of a ``triggersCap`` document, once each, on channel 1.

    It says what the device can notify, not on which channel: the devices that need it are
    cameras of one channel.
    """
    if document is None:
        return ()
    types = (
        child.name.removesuffix(CAP_SUFFIX).lower()
        for child in document.children()
        if child.name.endswith(CAP_SUFFIX)
    )
    return tuple(dict.fromkeys(EventSource(CAP_TYPES.get(name, name)) for name in types))
