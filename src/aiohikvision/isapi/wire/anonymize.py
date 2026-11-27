"""Make the answers of a device safe to share: in an issue, a fixture, a diagnostics file.

On top of :func:`~aiohikvision.isapi.wire.scrub.scrub_text` (credentials, serials, MAC
addresses, the elements whose names hold secrets), an :class:`Anonymizer` replaces:

- the IPv4 addresses, each by an address of the documentation ranges (192.0.2.0/24, then
  198.51.100.0/24), the same one wherever it appears, so the document keeps its sense;
- the names people give (the device, its channels, its doors and ports, the host name,
  the Wi-Fi network, the location), which can say whose home it is;
- the literal secrets it is given (the account, the address, the serial).

Addresses that identify nobody stay: loopback, 0.0.0.0, masks (255.x) and the documentation
ranges themselves. Versions such as ``V1.4.0.790168`` are not addresses.
"""

from __future__ import annotations

import ipaddress
import re
from typing import TYPE_CHECKING, Final

from aiohikvision.isapi.wire.scrub import MASK, scrub_text

if TYPE_CHECKING:
    from collections.abc import Iterable

_OCTET: Final = r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
_IPV4: Final = re.compile(rf"(?<![\w.]){_OCTET}(?:\.{_OCTET}){{3}}(?![\w.])")

NAMED: Final = frozenset(
    {
        "devicename",
        "channelname",
        "doorname",
        "name",
        "hostname",
        "ssid",
        "displayname",
        "devicelocation",
        "systemcontact",
        "location",
    }
)
"""The elements (and JSON keys) whose values are names people gave, in lower case."""

_XML_NAMED: Final = re.compile(r"<(?P<tag>[A-Za-z_][\w.-]*)(?P<attrs>[^<>]*?)>(?P<val>[^<]+)</(?P=tag)>")
_JSON_NAMED: Final = re.compile(r'"(?P<key>[A-Za-z_][\w-]*)"\s*:\s*"(?P<val>[^"]*)"')

_DOCUMENTATION: Final = (
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
)
_REPLACEMENTS: Final = tuple(
    str(address) for network in _DOCUMENTATION[:2] for address in list(network.hosts())[1:]
)
"""The addresses given in turn: 192.0.2.2 onwards (192.0.2.1 reads as a gateway), then 198.51.100.x."""


class Anonymizer:
    """Replaces what identifies a household in the documents of a device.

    One anonymizer is used for all the documents of one device: an address replaced in one
    is replaced by the same address in the others.
    """

    def __init__(self, secrets: Iterable[str] = ()) -> None:
        """Mask the given literal secrets (the account, the address, the serial) too."""
        self._secrets = tuple(secret for secret in secrets if secret)
        self._addresses: dict[str, str] = {}

    def text(self, text: str) -> str:
        """Return a document with nothing that identifies a household."""
        text = scrub_text(text, self._secrets)
        text = _XML_NAMED.sub(self._xml_name, text)
        text = _JSON_NAMED.sub(self._json_name, text)
        return _IPV4.sub(self._address, text)

    def _address(self, match: re.Match[str]) -> str:
        found = match[0]
        address = ipaddress.ip_address(found)
        keep = (
            address.is_loopback
            or address.is_unspecified
            or found.startswith("255.")
            or any(address in network for network in _DOCUMENTATION)
        )
        if keep:
            return found
        if found not in self._addresses:
            self._addresses[found] = _REPLACEMENTS[len(self._addresses) % len(_REPLACEMENTS)]
        return self._addresses[found]

    @staticmethod
    def _xml_name(match: re.Match[str]) -> str:
        if match["tag"].lower() in NAMED:
            return f"<{match['tag']}{match['attrs']}>{MASK}</{match['tag']}>"
        return match[0]

    @staticmethod
    def _json_name(match: re.Match[str]) -> str:
        if match["key"].lower() in NAMED and match["val"]:
            return f'"{match["key"]}": "{MASK}"'
        return match[0]
