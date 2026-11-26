"""All adjustable settings behind one interface.

``SOURCES`` are the settings of the channels of cameras and recorders (image, strobe, siren,
speaker, park action): their users walk them for every channel. ``DOOR_STATION_SOURCES`` are
those of a door station alone (its volumes, how long each door stays open, its voice prompt),
read by ``DoorStation``: kept apart so that walking ``SOURCES`` asks a camera nothing new.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from aiohikvision.isapi.model.features import access, audio, doors, image, park, signals, speaker
from aiohikvision.isapi.model.features.image import ImageCapability, ImageSetting, ImageValue
from aiohikvision.isapi.wire.link import IsapiLink


@dataclass(frozen=True, slots=True)
class Source:
    settings: tuple[ImageSetting, ...]
    # Camera settings that a recorder does not pass through: only read over a direct
    # connection (or from a camera configured on its own).
    direct_only: bool
    read_capabilities: Callable[[IsapiLink, str], Awaitable[dict[str, ImageCapability]]]
    read_values: Callable[[IsapiLink, str, set[str] | None], Awaitable[dict[str, ImageValue] | None]]
    write: Callable[[IsapiLink, str, str, str, str], Awaitable[None]]


SOURCES: dict[str, Source] = {
    "image": Source(image.SETTINGS, False, image.read_capabilities, image.read_values, image.write),
    "strobe": Source(
        signals.STROBE,
        False,
        signals.read_strobe_capabilities,
        signals.read_strobe_values,
        signals.write_strobe,
    ),
    "siren": Source(
        signals.SIREN,
        True,
        signals.read_siren_capabilities,
        signals.read_siren_values,
        signals.write_siren,
    ),
    "speaker": Source(speaker.SETTINGS, True, speaker.read_capabilities, speaker.read_values, speaker.write),
    "park": Source(park.SETTINGS, False, park.read_capabilities, park.read_values, park.write),
}
DOOR_STATION_SOURCES: dict[str, Source] = {
    "audio": Source(audio.SETTINGS, True, audio.read_capabilities, audio.read_values, audio.write),
    # The channel of a door's settings is the door's number.
    "door": Source(doors.SETTINGS, True, doors.read_capabilities, doors.read_values, doors.write),
    # Access settings belong to the device: their channel is ignored.
    "access": Source(access.SETTINGS, True, access.read_capabilities, access.read_values, access.write),
}
_ALL_SOURCES = {**SOURCES, **DOOR_STATION_SOURCES}
BY_KEY: dict[str, ImageSetting] = {
    setting.key: setting for source in _ALL_SOURCES.values() for setting in source.settings
}


def source_of(name: str) -> Source:
    """A source by its name, among those of channels and those of door stations."""
    return _ALL_SOURCES[name]


async def write(link: IsapiLink, channel_id: str, key: str, field: str, value: str) -> None:
    await _ALL_SOURCES[BY_KEY[key].source].write(link, channel_id, key, field, value)
