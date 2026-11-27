"""The firmware of a device, read from what deviceInfo says."""

from __future__ import annotations

import pytest

from aiohikvision import Firmware


@pytest.mark.parametrize(
    ("version", "released", "parts", "build"),
    [
        ("V3.7.3", "build 260915", (3, 7, 3), 260915),
        ("V4.62.210", "build 230225", (4, 62, 210), 230225),
        ("5.5.800", None, (5, 5, 800), None),
        ("V2.2.53", "build 20250610", (2, 2, 53), 20250610),
        ("", "", (), None),
        (None, None, (), None),
        ("beta", "soon", (), None),
    ],
)
def test_the_version_and_build_as_numbers(
    version: str | None, released: str | None, parts: tuple[int, ...], build: int | None
) -> None:
    """The numbers of the version and the build are read; what is not a number is not guessed."""
    firmware = Firmware.parse(version, released)
    assert firmware.parts == parts
    assert firmware.build == build
    assert firmware.known is bool(parts)


def test_written_as_the_device_wrote_it() -> None:
    """A firmware reads as the device wrote it, and one it did not give as unknown."""
    assert str(Firmware.parse("V3.7.3", "build 260915")) == "V3.7.3 build 260915"
    assert str(Firmware.parse("V3.7.3")) == "V3.7.3"
    assert str(Firmware.parse(None)) == "unknown"
    # What the device wrote does not make two firmwares different
    assert Firmware.parse("V3.7.3", "build 260915") == Firmware((3, 7, 3), 260915)
