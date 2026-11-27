"""Who a device is: what ``/ISAPI/System/deviceInfo`` says about it."""

from __future__ import annotations

from dataclasses import dataclass

from aiohikvision.models.firmware import Firmware


@dataclass(frozen=True, slots=True)
class Identity:
    """Who a device is.

    ``serial`` and ``mac`` identify it; ``device_id`` is the ``deviceID`` it reports (a UUID
    on recent firmware, a short text on older ones), kept as it is for consumers whose
    identifiers were built from it.
    """

    serial: str
    model: str
    name: str
    firmware: Firmware
    mac: str | None = None
    device_type: str | None = None
    hardware: str | None = None
    device_id: str | None = None

    @property
    def stable_id(self) -> str:
        """Return the serial (or the MAC) without separators, in lower case: for identifiers."""
        return "".join(ch for ch in (self.serial or self.mac or "") if ch.isalnum()).lower()
