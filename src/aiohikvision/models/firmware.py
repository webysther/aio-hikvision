"""The firmware of a device, as numbers: "V3.7.3 build 260915" is version (3, 7, 3), build 260915."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Final

_VERSION: Final = re.compile(r"(\d+(?:\.\d+)*)")
"""The numbers of a version: "V3.7.3" and "V4.62.210" as Hikvision writes them in deviceInfo."""

_BUILD: Final = re.compile(r"(\d{6,8})")
"""The build of a firmware: "build 260915" (yymmdd) in ``firmwareReleasedDate``; some write yyyymmdd."""


@dataclass(frozen=True, slots=True)
class Firmware:
    """The firmware of a device: its version as numbers, and its build.

    A range of versions (``behaviours.rules.VersionRange``) matches it by ``parts``. One whose
    version this library cannot read has no ``parts`` and matches no range (``raw`` keeps
    what the device said).
    """

    parts: tuple[int, ...]
    build: int | None = None
    raw: str = field(default="", compare=False)

    @classmethod
    def parse(cls, version: str | None, released: str | None = None) -> Firmware:
        """Return the firmware of ``firmwareVersion`` and ``firmwareReleasedDate``."""
        version = (version or "").strip()
        released = (released or "").strip()
        numbers = _VERSION.search(version)
        build = _BUILD.search(released)
        return cls(
            parts=tuple(int(part) for part in numbers.group(1).split(".")) if numbers else (),
            build=int(build.group(1)) if build else None,
            raw=" ".join(part for part in (version, released) if part),
        )

    @property
    def known(self) -> bool:
        """Whether the version could be read."""
        return bool(self.parts)

    def __str__(self) -> str:
        """Return the firmware as the device wrote it: "V3.7.3 build 260915"."""
        return self.raw or "unknown"
