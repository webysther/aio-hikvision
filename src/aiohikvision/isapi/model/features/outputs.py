"""What the outputs of a door station are used for: a door's lock, a doorbell, or nothing.

A door station has a relay output per door it can open (COM1 for door 1, COM2 for door 2 on
a DS-KD8003). Its web page sets what each output drives (Access Control → I/O Settings): the
first is always an electric lock, the others an electric lock, a mechanical doorbell, or
nothing. A door whose output drives no lock cannot be opened, though the door station still
lists it among the doors it can open remotely.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from aiohikvision.isapi.wire.link import IsapiLink
from aiohikvision.isapi.wire.xmlview import XmlNode

OUTPUTS_PATH = "/ISAPI/System/IO/outputs"
OUTPUTS_CAPABILITIES_PATH = "/ISAPI/System/IO/outputs/capabilities"


class OutputUse(StrEnum):
    """What an output drives."""

    ELECTRIC_LOCK = "electric_lock"
    DOORBELL = "doorbell"
    DISABLED = "disabled"
    OTHER = "other"


# The IOUseType of /ISAPI/System/IO/outputs, as a DS-KD8003 (V3.7.3) names them.
_USES = {
    "electriclock": OutputUse.ELECTRIC_LOCK,
    "mechanicaldoorbell": OutputUse.DOORBELL,
    "doorbell": OutputUse.DOORBELL,
    "disable": OutputUse.DISABLED,
    "disabled": OutputUse.DISABLED,
}


def output_use(value: str | None) -> OutputUse:
    """The use of an output from its IOUseType; one this library does not know is OTHER."""
    return _USES.get((value or "").strip().lower(), OutputUse.OTHER)


@dataclass(frozen=True, slots=True)
class Output:
    """An output of a door station and what it drives."""

    number: int
    name: str | None
    use: OutputUse
    # The uses it can be set to, when the device says (empty: it does not say).
    options: tuple[OutputUse, ...] = ()


def _options(capabilities: XmlNode | None) -> dict[int, tuple[OutputUse, ...]]:
    """The uses each output offers, from the ``opt`` of its IOUseType in the capabilities."""
    if capabilities is None:
        return {}
    offered: dict[int, tuple[OutputUse, ...]] = {}
    for node in capabilities.children("IOOutputPort"):
        number = node.numeric("id")
        use = node.first("IOUseType")
        choices = use.attrs.get("opt") if use is not None else None
        if number is None or not choices:
            continue
        offered[number] = tuple(dict.fromkeys(output_use(choice) for choice in choices.split(",")))
    return offered


def parse_outputs(document: XmlNode | None, capabilities: XmlNode | None = None) -> tuple[Output, ...]:
    """The outputs of a door station, by number; none when it does not list them."""
    if document is None:
        return ()
    offered = _options(capabilities)
    outputs = []
    for node in document.children("IOOutputPort"):
        number = node.numeric("id")
        if number is None:
            continue
        outputs.append(
            Output(
                number=number,
                name=node.text("name"),
                use=output_use(node.text("IOUseType")),
                options=offered.get(number, ()),
            )
        )
    return tuple(sorted(outputs, key=lambda output: output.number))


async def read_outputs(link: IsapiLink) -> tuple[Output, ...]:
    """Read what the outputs drive (and what they could), if the device lists them."""
    document = await link.read_xml(OUTPUTS_PATH, optional=True)
    if document is None:
        return ()
    capabilities = await link.read_xml(OUTPUTS_CAPABILITIES_PATH, optional=True)
    return parse_outputs(document, capabilities)
