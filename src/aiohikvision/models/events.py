"""The events of a device: where each one comes from, and how it stands."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime  # the dataclasses read their annotations


@dataclass(frozen=True, slots=True, order=True)
class EventSource:
    """An event a device notifies, on one channel: ``vmd`` on channel 2, ``io`` on input 1."""

    type: str
    """The type, as ISAPI names it, in lower case: ``vmd``, ``linedetection``, ``io``…"""
    channel: int = 1
    """The video channel, or the alarm input of an ``io`` event; 1 when the device names none."""

    def __str__(self) -> str:
        """Show the type and the channel: "vmd 2"."""
        return f"{self.type} {self.channel}"


@dataclass(frozen=True, slots=True)
class EventState:
    """How an event stands: on while the device reports it."""

    active: bool = False
    changed: datetime | None = None
    """When it last turned on or off; None while it never did."""
    count: int = 0
    """How many times the device posted it, as it counts (``activePostCount``)."""
    target: str | None = None
    """What the last detection saw, in lower case (``human``, ``vehicle``), when it said."""


@dataclass(frozen=True, slots=True)
class Trigger:
    """An event the device is set to notify, and how (``/ISAPI/Event/triggers``)."""

    source: EventSource
    methods: frozenset[str]
    """How it notifies, in lower case: ``center`` (the alert stream), ``http``, ``record``…"""
