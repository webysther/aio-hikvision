"""A Hikvision device: who it is, what it can do, how it behaves, and its services.

Get one from :meth:`aiohikvision.HikvisionClient.connect`, or from a link of your own with
:meth:`Device.from_link`::

    async with HikvisionClient() as client:
        device = await client.connect("192.0.2.10", "admin", "password")
        print(device.identity.model, device.identity.firmware)  # DS-KD8003-IME1(B) V3.7.3 build 260915
        print(device.capabilities.domains)  # (Domain.STREAMING, Domain.EVENTS, ...)
        print(device.behaviours.talk_packet)  # 40ms

Who the device is and what it can do are read once; its behaviours come from its model and
firmware (:mod:`aiohikvision.behaviours.rules`). One device has one link: two links to one
device would add up their failed logins against its lockout.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aiohikvision.behaviours.rules import KNOWN_RULES, resolve
from aiohikvision.models.capabilities import Domain, Support
from aiohikvision.services.streaming import Streaming
from aiohikvision.services.system import System

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from aiohikvision.behaviours import BehaviourPatch, Behaviours
    from aiohikvision.behaviours.rules import Resolved, Rule
    from aiohikvision.isapi.wire.link import IsapiLink
    from aiohikvision.models.capabilities import Capabilities
    from aiohikvision.models.identity import Identity


class Device:
    """A Hikvision device reached over ISAPI."""

    def __init__(
        self,
        link: IsapiLink,
        identity: Identity,
        capabilities: Capabilities,
        resolved: Resolved,
    ) -> None:
        """Make a device of what was read from it; :meth:`from_link` reads it."""
        self.link = link
        self.identity = identity
        self.capabilities = capabilities
        self.resolved = resolved
        self.system = System(link)
        self.streaming = self._service(Domain.STREAMING, Streaming)

    def _service[S](self, domain: Domain, service: Callable[[IsapiLink], S]) -> S | None:
        """Return the service of a domain, unless the capabilities say the device has none."""
        return None if self.capabilities.support(domain) is Support.ABSENT else service(self.link)

    @classmethod
    async def from_link(
        cls,
        link: IsapiLink,
        *,
        rules: Iterable[Rule] = (),
        overrides: BehaviourPatch | None = None,
    ) -> Device:
        """Read who the device is and what it can do, and resolve how it behaves.

        ``rules`` are added after :data:`~aiohikvision.behaviours.rules.KNOWN_RULES` (as specific,
        they win); ``overrides`` win over every rule.
        """
        system = System(link)
        identity = await system.identity()
        capabilities = await system.capabilities()
        return cls(link, identity, capabilities, resolve(identity, (*KNOWN_RULES, *rules), overrides))

    @property
    def behaviours(self) -> Behaviours:
        """Return how the device behaves where devices differ."""
        return self.resolved.behaviours

    async def check(self) -> None:
        """Ask the device who it is: raises the fault of a device that is down or refuses us."""
        await self.system.identity()
