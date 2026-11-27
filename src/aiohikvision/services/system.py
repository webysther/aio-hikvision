"""The system of a device: who it is and what it can do."""

from __future__ import annotations

from typing import TYPE_CHECKING

from aiohikvision.parsers.capabilities import SYSTEM_CAPABILITIES, parse_capabilities
from aiohikvision.parsers.identity import DEVICE_INFO, parse_identity

if TYPE_CHECKING:
    from aiohikvision.isapi.wire.link import IsapiLink
    from aiohikvision.models.capabilities import Capabilities
    from aiohikvision.models.identity import Identity


class System:
    """The system of a device, which every ISAPI device has."""

    def __init__(self, link: IsapiLink) -> None:
        """Talk to the device through its link."""
        self.link = link

    async def identity(self) -> Identity:
        """Return who the device is; an answer without device information is no ISAPI device."""
        return parse_identity(await self.link.read_xml(DEVICE_INFO))

    async def capabilities(self) -> Capabilities:
        """Return what the device says it can do; a device that does not say has UNKNOWN domains."""
        return parse_capabilities(await self.link.read_xml(SYSTEM_CAPABILITIES, optional=True))
