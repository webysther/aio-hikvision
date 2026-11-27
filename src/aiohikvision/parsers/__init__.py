"""The documents of a device as models, without I/O: one module per domain of ISAPI.

Each function takes the parsed document (``XmlNode``, or JSON) and returns frozen models of
``aiohikvision.models``; a document the device did not send (None) gives the model of a device
that said nothing. The services (``aiohikvision.services``) fetch the documents and call these.
"""

from aiohikvision._extras import require

require("isapi")
