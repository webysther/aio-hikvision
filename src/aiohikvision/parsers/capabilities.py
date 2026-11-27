"""What a device says it can do, from ``/ISAPI/System/capabilities``."""

from __future__ import annotations

from typing import TYPE_CHECKING

from aiohikvision.models.capabilities import Capabilities, CapabilityTree

if TYPE_CHECKING:
    from aiohikvision.isapi.wire.xmlview import XmlNode

SYSTEM_CAPABILITIES = "/ISAPI/System/capabilities"


def parse_capabilities(document: XmlNode | None) -> Capabilities:
    """Return every element of the document by its path; a device that sent none said nothing."""
    values: dict[str, str] = {}
    options: dict[str, tuple[str, ...]] = {}
    if document is not None:
        _collect(document, "", values, options)
    return Capabilities(CapabilityTree(values, options))


def _collect(node: XmlNode, prefix: str, values: dict[str, str], options: dict[str, tuple[str, ...]]) -> None:
    """Add the elements under a node; an element named twice keeps its first occurrence."""
    for child in node.children():
        path = f"{prefix}{child.name}"
        if path in values:
            continue
        values[path] = child.value or ""
        if offered := child.options(""):
            options[path] = tuple(offered)
        _collect(child, f"{path}/", values, options)
