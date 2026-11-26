"""Access settings of an access-control device (``AccessControl/AcsCfg``, JSON).

A DS-KD8003 (V3.7.3) keeps here whether it says something when a door opens
(``openDoorVoicePromptEnabled``) and what (``openDoorVoicePromptType``: ``long``, ``short`` or
``doorIsOpen``). Its capabilities list each choice under ``@opt`` and come as JSON even
without ``format=json``.
"""

from __future__ import annotations

from typing import Any

from aiohikvision.isapi.model.features import patch_json_and_verify
from aiohikvision.isapi.model.features.image import ImageCapability, ImageSetting, ImageValue, Platform
from aiohikvision.isapi.wire.link import IsapiLink

ROOT = "AcsCfg"
ACS_PATH = "/ISAPI/AccessControl/AcsCfg?format=json"
CAPS_PATH = "/ISAPI/AccessControl/AcsCfg/capabilities"


def _s(key: str, platform: Platform, field: str) -> ImageSetting:
    return ImageSetting(key, platform, ROOT, "", (field,), enabled_default=True, source="access")


SETTINGS: tuple[ImageSetting, ...] = (
    _s("door_voice_prompt", "switch", "openDoorVoicePromptEnabled"),
    _s("door_voice_prompt_type", "select", "openDoorVoicePromptType"),
)
BY_KEY = {setting.key: setting for setting in SETTINGS}


def _body(document: Any) -> dict[str, Any]:
    body = document.get(ROOT) if isinstance(document, dict) else None
    return body if isinstance(body, dict) else {}


def _text(value: Any) -> str:
    """A JSON value as the text of a setting: booleans as ``true`` and ``false``."""
    return str(value).lower() if isinstance(value, bool) else str(value)


def parse_capabilities(document: Any) -> dict[str, ImageCapability]:
    """The settings whose choices the capabilities list."""
    body = _body(document)
    found: dict[str, ImageCapability] = {}
    for setting in SETTINGS:
        entry = body.get(setting.fields[0])
        offered = entry.get("@opt") if isinstance(entry, dict) else None
        if not isinstance(offered, list):
            continue
        options = tuple(_text(option) for option in offered)
        if setting.platform == "switch" and {"true", "false"} <= set(options):
            found[setting.key] = ImageCapability(setting.key)
        elif setting.platform == "select" and len(options) > 1:
            found[setting.key] = ImageCapability(setting.key, options=options)
    return found


def parse_values(document: Any, keys: set[str] | None = None) -> dict[str, ImageValue]:
    body = _body(document)
    values: dict[str, ImageValue] = {}
    for setting in SETTINGS:
        field = setting.fields[0]
        if (keys is None or setting.key in keys) and field in body:
            values[setting.key] = ImageValue(field, _text(body[field]))
    return values


async def read_capabilities(link: IsapiLink, channel_id: str) -> dict[str, ImageCapability]:
    """The access settings the device offers (they belong to the device, not a channel)."""
    return parse_capabilities(await link.read_json(CAPS_PATH, optional=True))


async def read_values(
    link: IsapiLink, channel_id: str, keys: set[str] | None = None
) -> dict[str, ImageValue] | None:
    document = await link.read_json(ACS_PATH, optional=True)
    return parse_values(document, keys) if document is not None else None


async def write(link: IsapiLink, channel_id: str, key: str, field: str, value: str) -> None:
    """Change one access setting and read it back; a switch is sent as a JSON boolean."""
    sent: Any = value == "true" if BY_KEY[key].platform == "switch" else value
    await patch_json_and_verify(link, ACS_PATH, ROOT, {field: sent})
