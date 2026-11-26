"""How long each door of an access-control device stays open (``AccessControl/Door/param``).

``/ISAPI/AccessControl/Door/param/<door>`` holds a door's name and ``openDuration``: how long
its lock relay stays released when the door is opened, in seconds (1 s for door 1 and 7 s for
door 2 on a DS-KD8003, V3.7.3). The channel of these settings is the door's number.
"""

from __future__ import annotations

from typing import Final

from aiohikvision.isapi.model.features import patch_and_verify
from aiohikvision.isapi.model.features.image import ImageCapability, ImageSetting, ImageValue
from aiohikvision.isapi.model.ids import seg
from aiohikvision.isapi.wire.link import IsapiLink
from aiohikvision.isapi.wire.xmlview import XmlNode

DOOR_PATH = "/ISAPI/AccessControl/Door/param/{door}"
OPEN_TIME_FIELD = "openDuration"
# The range of openDuration in Hikvision's access control guide (seconds), used when the door
# has no capabilities document; the device itself refuses a value outside its own range.
DEFAULT_OPEN_TIME: Final = (1, 255)

SETTINGS: tuple[ImageSetting, ...] = (
    ImageSetting(
        "open_time",
        "number",
        "",
        "",
        (OPEN_TIME_FIELD,),
        enabled_default=True,
        seconds=True,
        source="door",
    ),
)


def _path(door: str) -> str:
    return DOOR_PATH.format(door=seg(door))


def parse_capabilities(document: XmlNode | None, capabilities: XmlNode | None) -> dict[str, ImageCapability]:
    """The open time of a door, when its parameters have it, with the range it takes."""
    if document is None or document.text(OPEN_TIME_FIELD) is None:
        return {}
    low, high = DEFAULT_OPEN_TIME
    node = capabilities.first(OPEN_TIME_FIELD) if capabilities is not None else None
    if node is not None:
        try:
            low, high = int(node.attrs["min"]), int(node.attrs["max"])
        except (KeyError, ValueError):
            low, high = DEFAULT_OPEN_TIME
    if high <= low:
        low, high = DEFAULT_OPEN_TIME
    return {"open_time": ImageCapability("open_time", minimum=low, maximum=high)}


def parse_values(document: XmlNode | None, keys: set[str] | None = None) -> dict[str, ImageValue]:
    """The open time of a door now."""
    if document is None or (keys is not None and "open_time" not in keys):
        return {}
    text = document.text(OPEN_TIME_FIELD)
    return {"open_time": ImageValue(OPEN_TIME_FIELD, text)} if text is not None else {}


async def read_capabilities(link: IsapiLink, channel_id: str) -> dict[str, ImageCapability]:
    """The open time of door ``channel_id``, if the device has door parameters."""
    document = await link.read_xml(_path(channel_id), optional=True)
    if document is None:
        return {}
    capabilities = await link.read_xml(f"{_path(channel_id)}/capabilities", optional=True)
    return parse_capabilities(document, capabilities)


async def read_values(
    link: IsapiLink, channel_id: str, keys: set[str] | None = None
) -> dict[str, ImageValue] | None:
    document = await link.read_xml(_path(channel_id), optional=True)
    return parse_values(document, keys) if document is not None else None


async def write(link: IsapiLink, channel_id: str, key: str, field: str, value: str) -> None:
    """Change how long a door stays open and read it back."""
    await patch_and_verify(link, _path(channel_id), {field: value})
