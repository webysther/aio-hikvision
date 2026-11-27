"""Level 3 of aiohikvision: a device as an integration sees it, answering real questions.

Like the patterns of the AWS CDK, each class here serves a whole use case with sensible
defaults, built only on level 2 (``Device`` and its services), which it always lets you reach
(``.device``) when it is not enough:

- level 1, ``isapi.wire`` and ``parsers``: one ISAPI document at a time, in full;
- level 2, ``Device``, ``services``, ``behaviours``: a domain with types, defaults and the
  rules of each model and firmware;
- level 3, ``patterns``: ``aiohikvision.connect()`` → ``Hikvision``, its ``cameras``, ``supports``.
"""

from aiohikvision._extras import require

require("isapi")
