"""ISAPI, the HTTP API of Hikvision devices: how to talk to a device, and what it can do.

- ``aiohikvision.isapi.wire``: the connection. Digest authentication that respects the
  device's login lockout, TLS, the XML and JSON documents, the faults a device reports, the
  alert stream of events, and the scrubbing of credentials from logs.
- ``aiohikvision.isapi.model``: what a device is and can do, read without changing it.
  Discovery (cameras, recorders, door stations), the vocabulary of events, and one module per
  feature (intercom, two-way audio, detections, image, recordings, PTZ…).
"""

from aiohikvision._extras import require

require("isapi")
