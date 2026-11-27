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

from aiohikvision.behaviours.rules import KNOWN_RULES, Source, resolve
from aiohikvision.isapi.wire.scrub import scrubbed_logger
from aiohikvision.models.capabilities import Domain, Support
from aiohikvision.report import COVERAGE, collect_report
from aiohikvision.services.events import Events
from aiohikvision.services.streaming import Streaming
from aiohikvision.services.system import System

_LOGGER = scrubbed_logger(__name__)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from aiohikvision.behaviours import BehaviourPatch, Behaviours
    from aiohikvision.behaviours.rules import Resolved, Rule
    from aiohikvision.isapi.wire.link import IsapiLink
    from aiohikvision.models.capabilities import Capabilities
    from aiohikvision.models.identity import Identity
    from aiohikvision.report import CapabilityReport


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
        self.events = self._service(Domain.EVENTS, lambda link: Events(link, resolved.behaviours))

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
        device = cls(link, identity, capabilities, resolve(identity, (*KNOWN_RULES, *rules), overrides))
        _LOGGER.debug("%s", "\n  ".join(device.summary()))
        return device

    def summary(self) -> list[str]:
        """Return how the library recognised the device, in a few lines for a log.

        Who it is; the domains it shows and how the library covers each; the behaviours
        that are not the defaults, with what decided them and where it was seen.
        """
        identity = self.identity
        lines = [
            f"Recognised {identity.model} {identity.firmware} on {self.link.endpoint.host}"
            f" (type {identity.device_type or '?'}, hardware {identity.hardware or '?'})"
        ]
        if not self.capabilities.tree:
            lines.append("Domains: unknown, the device sent no capabilities: each service asks it")
        else:
            present = ", ".join(f"{domain} ({COVERAGE[domain]})" for domain in self.capabilities.domains)
            absent = ", ".join(domain for domain in Domain if domain not in self.capabilities.domains)
            lines.append(f"Domains: {present or 'none'}; absent: {absent or 'none'}")
        decided = [
            _decision_line(name, getattr(self.behaviours, name), decision.source, decision.rule)
            for name, decision in self.resolved.decisions.items()
            if decision.source is not Source.DEFAULT
        ]
        lines.extend(decided or ["Behaviours: the defaults, no rule knows this model and firmware"])
        return lines

    @property
    def behaviours(self) -> Behaviours:
        """Return how the device behaves where devices differ."""
        return self.resolved.behaviours

    async def report(self, *, secrets: Iterable[str] = ()) -> CapabilityReport:
        """Return what the device is and answers, anonymized, to send to aiohikvision.

        GET only; the address, the account and the serial are masked, with ``secrets``.
        """
        return await collect_report(self, secrets=secrets)

    async def check(self) -> None:
        """Ask the device who it is: raises the fault of a device that is down or refuses us."""
        await self.system.identity()


def _decision_line(name: str, value: object, source: Source, rule: Rule | None) -> str:
    """Return a behaviour that is not the default, with what decided it and where it was seen."""
    if rule is None:
        return f"Behaviour {name}={value}: the caller's override"
    seen = (
        f", seen on {rule.measured.model} {rule.measured.firmware} ({rule.measured.source})"
        if rule.measured
        else ""
    )
    return f"Behaviour {name}={value}: {source} {rule.match.model or 'any model'}{seen}"
