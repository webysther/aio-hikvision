"""The errors of aiohikvision: every one is a :class:`HikvisionError`.

The faults a device reports over ISAPI (unreachable, bad credentials, locked out, unsupported…)
are in ``aiohikvision.isapi.wire.faults``; they derive from :class:`HikvisionError` too, so
that a caller can catch everything this library raises with one class.
"""

from __future__ import annotations


class HikvisionError(Exception):
    """Base of every error raised by aiohikvision."""

    translation_key = "unknown"
    """A key a caller can translate the error with (Home Assistant's exception keys)."""


class MissingExtra(HikvisionError, ImportError):  # noqa: N818  # named for what is missing
    """A part of aiohikvision was used without the extra that installs what it needs.

    The message says how to install it, e.g. ``pip install "aiohikvision[sip]"``.
    """

    translation_key = "missing_extra"

    def __init__(self, extra: str, module: str) -> None:
        """Name the extra to install and the module that is missing."""
        super().__init__(
            f"aiohikvision[{extra}] is needed ({module} is not installed): "
            f'pip install "aiohikvision[{extra}]"',
            name=module,
        )
        self.extra = extra
