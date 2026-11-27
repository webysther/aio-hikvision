"""The domains of ISAPI a device offers, one class each: only the I/O.

A service fetches the documents of its domain through the device's link and turns them into
models with ``aiohikvision.parsers``. A :class:`~aiohikvision.Device` makes the services of
the domains its capabilities show, and gives each the device's behaviours.
"""

from aiohikvision._extras import require

require("isapi")
