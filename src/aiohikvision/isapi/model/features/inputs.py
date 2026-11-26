"""What the inputs of a door station are used for: a door contact, an exit button, or nothing.

A DS-KD8003 (V3.7.3) has four alarm inputs; its web page sets what each one reads
(``IOUseType`` of ``/ISAPI/System/IO/inputs``): input 1 a door contact (``doorStatus``),
input 3 an exit button (``openDoor``), and inputs 2 and 4 either that or nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from aiohikvision.isapi.wire.link import IsapiLink
from aiohikvision.isapi.wire.xmlview import XmlNode

INPUTS_PATH = "/ISAPI/System/IO/inputs"
INPUTS_CAPABILITIES_PATH = "/ISAPI/System/IO/inputs/capabilities"


class InputUse(StrEnum):
    """What an input reads."""

    DOOR_CONTACT = "door_contact"
    EXIT_BUTTON = "exit_button"
    DISABLED = "disabled"
    OTHER = "other"


# The IOUseType of /ISAPI/System/IO/inputs, as a DS-KD8003 (V3.7.3) names them.
_USES = {
    "doorstatus": InputUse.DOOR_CONTACT,
    "opendoor": InputUse.EXIT_BUTTON,
    "disable": InputUse.DISABLED,
    "disabled": InputUse.DISABLED,
}


def input_use(value: str | None) -> InputUse:
    """The use of an input from its IOUseType; one this library does not know is OTHER."""
    return _USES.get((value or "").strip().lower(), InputUse.OTHER)


@dataclass(frozen=True, slots=True)
class Input:
    """An input of a door station and what it reads."""

    number: int
    name: str | None
    use: InputUse
    # The uses it can be set to, when the device says (empty: it does not say).
    options: tuple[InputUse, ...] = ()


def _options(capabilities: XmlNode | None) -> dict[int, tuple[InputUse, ...]]:
    """The uses each input offers, from the ``opt`` of its IOUseType in the capabilities."""
    if capabilities is None:
        return {}
    offered: dict[int, tuple[InputUse, ...]] = {}
    for node in capabilities.children("IOInputPort"):
        number = node.numeric("id")
        use = node.first("IOUseType")
        choices = use.attrs.get("opt") if use is not None else None
        if number is None or not choices:
            continue
        offered[number] = tuple(dict.fromkeys(input_use(choice) for choice in choices.split(",")))
    return offered


def parse_inputs(document: XmlNode | None, capabilities: XmlNode | None = None) -> tuple[Input, ...]:
    """The inputs of a door station, by number; none when it does not list them."""
    if document is None:
        return ()
    offered = _options(capabilities)
    inputs = []
    for node in document.children("IOInputPort"):
        number = node.numeric("id")
        if number is None:
            continue
        inputs.append(
            Input(
                number=number,
                name=node.text("name"),
                use=input_use(node.text("IOUseType")),
                options=offered.get(number, ()),
            )
        )
    return tuple(sorted(inputs, key=lambda item: item.number))


async def read_inputs(link: IsapiLink) -> tuple[Input, ...]:
    """Read what the inputs read (and what they could), if the device lists them."""
    document = await link.read_xml(INPUTS_PATH, optional=True)
    if document is None:
        return ()
    capabilities = await link.read_xml(INPUTS_CAPABILITIES_PATH, optional=True)
    return parse_inputs(document, capabilities)
