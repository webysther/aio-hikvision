"""The extras of aiohikvision: each part installs what it needs, and nothing else.

``pip install aiohikvision`` installs no dependency: the models, the behaviours of the
devices, the digest authentication and the media codecs use the standard library only. A part
that needs more says so when it is imported, with :class:`~aiohikvision.errors.MissingExtra`.
"""

from __future__ import annotations

import importlib
from typing import Final

from aiohikvision.errors import MissingExtra

EXTRAS: Final[dict[str, tuple[str, ...]]] = {
    # defusedxml comes with [isapi] too, but is not required: without it the XML of the devices
    # is read by a guarded parser that refuses DTDs (isapi.wire.xmlview). Home Assistant does
    # not ship it, and checks only the version of a requirement, not its extras.
    "isapi": ("aiohttp", "yarl"),
    "rtp": (),
    "rtsp": (),
    "sip": ("aiosipua",),
    "scrambling": ("cryptography",),
}
"""The modules each part needs to import (``[rtp]`` and ``[rtsp]`` need none)."""


def require(extra: str) -> None:
    """Raise :class:`MissingExtra` when a module of the extra is not installed."""
    for module in EXTRAS[extra]:
        try:
            importlib.import_module(module)
        except ImportError as err:
            raise MissingExtra(extra, module) from err
