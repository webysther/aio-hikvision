"""Who a device is, from ``/ISAPI/System/deviceInfo``."""

from __future__ import annotations

from typing import TYPE_CHECKING

from aiohikvision.isapi.wire.faults import NotIsapi
from aiohikvision.models.firmware import Firmware
from aiohikvision.models.identity import Identity

if TYPE_CHECKING:
    from aiohikvision.isapi.wire.xmlview import XmlNode

DEVICE_INFO = "/ISAPI/System/deviceInfo"


def parse_identity(info: XmlNode | None) -> Identity:
    """Return who a device is; no document, or one with neither serial nor MAC, is no ISAPI device."""
    if info is None:
        msg = "no device information"
        raise NotIsapi(msg)
    serial = info.text("serialNumber") or ""
    mac = info.text("macAddress")
    if not serial and not mac:
        msg = "device reports neither serial number nor MAC address"
        raise NotIsapi(msg)
    model = info.text("model") or "Hikvision device"
    return Identity(
        serial=serial,
        model=model,
        name=info.text("deviceName") or model,
        firmware=Firmware.parse(info.text("firmwareVersion"), info.text("firmwareReleasedDate")),
        mac=mac,
        device_type=info.text("deviceType"),
        hardware=info.text("hardwareVersion"),
        device_id=info.text("deviceID"),
    )
