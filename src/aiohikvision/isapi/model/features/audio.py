"""Volumes of a device's audio input and output (``/ISAPI/System/Audio``).

Door stations keep their volumes here rather than on the two-way audio channel (see
``speaker``): the microphone in ``AudioIn/channels/<ch>``, the speaker in
``AudioOut/channels/<ch>``, which also has the volume of a call (``talkVolume``). Each has a
``capabilities`` document with the range of every volume (0-10 on a DS-KD8003, V3.7.3).
"""

from __future__ import annotations

from aiohikvision.isapi.model.features import patch_and_verify
from aiohikvision.isapi.model.features.image import ImageCapability, ImageSetting, ImageValue
from aiohikvision.isapi.model.ids import seg
from aiohikvision.isapi.wire.link import IsapiLink
from aiohikvision.isapi.wire.xmlview import XmlNode

AUDIO_PATH = "/ISAPI/System/Audio/{resource}/channels/{ch}"

SETTINGS: tuple[ImageSetting, ...] = (
    ImageSetting(
        "input_volume",
        "number",
        "",
        "AudioIn",
        ("AudioInVolumelist/AudioInVlome/volume",),
        enabled_default=True,
        source="audio",
    ),
    ImageSetting(
        "output_volume",
        "number",
        "",
        "AudioOut",
        ("AudioOutVolumelist/AudioOutVlome/volume",),
        enabled_default=True,
        source="audio",
    ),
    ImageSetting(
        "talk_volume",
        "number",
        "",
        "AudioOut",
        ("AudioOutVolumelist/AudioOutVlome/talkVolume",),
        enabled_default=True,
        source="audio",
    ),
)
BY_KEY = {setting.key: setting for setting in SETTINGS}
RESOURCES = tuple(dict.fromkeys(setting.resource for setting in SETTINGS))


def _path(resource: str, channel_id: str) -> str:
    return AUDIO_PATH.format(resource=resource, ch=seg(channel_id))


def parse_capabilities(resource: str, document: XmlNode | None) -> dict[str, ImageCapability]:
    """The volumes of one resource (AudioIn or AudioOut) with a range, from its capabilities."""
    if document is None:
        return {}
    found: dict[str, ImageCapability] = {}
    for setting in SETTINGS:
        if setting.resource != resource:
            continue
        node = document.first(setting.fields[0])
        if node is None:
            continue
        try:
            low, high = int(node.attrs["min"]), int(node.attrs["max"])
        except (KeyError, ValueError):
            continue
        if high > low:
            found[setting.key] = ImageCapability(setting.key, minimum=low, maximum=high)
    return found


def parse_values(
    resource: str, document: XmlNode | None, keys: set[str] | None = None
) -> dict[str, ImageValue]:
    """The volumes of one resource as they are now."""
    if document is None:
        return {}
    values: dict[str, ImageValue] = {}
    for setting in SETTINGS:
        if setting.resource != resource or (keys is not None and setting.key not in keys):
            continue
        text = document.text(setting.fields[0])
        if text is not None:
            values[setting.key] = ImageValue(setting.fields[0], text)
    return values


async def read_capabilities(link: IsapiLink, channel_id: str) -> dict[str, ImageCapability]:
    """The volumes a channel has, with their ranges; none when the device has no such audio."""
    found: dict[str, ImageCapability] = {}
    for resource in RESOURCES:
        document = await link.read_xml(f"{_path(resource, channel_id)}/capabilities", optional=True)
        found.update(parse_capabilities(resource, document))
    return found


async def read_values(
    link: IsapiLink, channel_id: str, keys: set[str] | None = None
) -> dict[str, ImageValue] | None:
    """The volumes of a channel now; None when neither resource answers."""
    values: dict[str, ImageValue] = {}
    answered = False
    for resource in RESOURCES:
        wanted = {s.key for s in SETTINGS if s.resource == resource}
        if keys is not None and not wanted & keys:
            continue
        document = await link.read_xml(_path(resource, channel_id), optional=True)
        answered = answered or document is not None
        values.update(parse_values(resource, document, keys))
    return values if answered else None


async def write(link: IsapiLink, channel_id: str, key: str, field: str, value: str) -> None:
    """Change one volume and read it back."""
    await patch_and_verify(link, _path(BY_KEY[key].resource, channel_id), {field: value})
