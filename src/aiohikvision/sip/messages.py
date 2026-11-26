"""SIP responses outside the dialogs aiosipua keeps: to REGISTER and MESSAGE."""

from __future__ import annotations

import secrets
from email.utils import formatdate
from typing import TYPE_CHECKING

from aiosipua import SipResponse

if TYPE_CHECKING:
    from aiosipua import SipRequest

SERVER = "aiohikvision"


def response(request: SipRequest, status: int, reason: str) -> SipResponse:
    """Build a response to a request, with its Via, From, Call-ID and CSeq, and our tag on To."""
    reply = SipResponse(status_code=status, reason_phrase=reason)
    for via in request.headers.get("via"):
        reply.headers.append("Via", via)
    reply.headers.set_single("From", request.get_header("from") or "")
    to = request.get_header("to") or ""
    reply.headers.set_single("To", to if ";tag=" in to else f"{to};tag={secrets.token_hex(6)}")
    reply.headers.set_single("Call-ID", request.call_id or "")
    reply.headers.set_single("CSeq", request.get_header("cseq") or "")
    reply.headers.set_single("Date", formatdate(usegmt=True))
    reply.headers.set_single("Server", SERVER)
    return reply
