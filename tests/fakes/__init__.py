"""Doubles of the devices for the tests: they behave as the measured ones.

- ``door``: a door station's SIP side on loopback (registers, keeps alive, calls, cancels,
  hangs up, receives RTP), with its captured INVITE and SDP.
- ``isapi``: an ISAPI device over HTTP with digest authentication, serving the anonymized
  answers of real devices in ``fixtures/`` (``door_station`` is a DS-KD8003).
- ``talk``: the two-way audio endpoint, whose upload an HTTP test server cannot serve.
"""

from tests.fakes.door import FULL_OFFER, G711_OFFER, FakeCall, FakeDoorStation
from tests.fakes.isapi import FakeIsapiDevice
from tests.fakes.talk import FakeTalkDevice

__all__ = ["FULL_OFFER", "G711_OFFER", "FakeCall", "FakeDoorStation", "FakeIsapiDevice", "FakeTalkDevice"]
