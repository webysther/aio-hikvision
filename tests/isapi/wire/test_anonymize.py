"""Answers of a device made safe to share: no account, address, serial or name of a home."""

from __future__ import annotations

from aiohikvision.isapi.wire.anonymize import Anonymizer
from aiohikvision.isapi.wire.scrub import MASK


def test_addresses_are_replaced_the_same_way_everywhere() -> None:
    """Each address becomes a documentation address, the same one wherever it appears.

    The addresses replaced here are private ones (10.0.0.0/8), as a home's: they identify
    nobody, and the documentation ranges are left as they are by design.
    """
    anonymizer = Anonymizer()
    first = anonymizer.text("<ipAddress>10.1.2.3</ipAddress><gateway>10.1.2.1</gateway>")
    second = anonymizer.text('{"server": "10.1.2.3"}')
    assert first == "<ipAddress>192.0.2.2</ipAddress><gateway>192.0.2.3</gateway>"
    assert second == '{"server": "192.0.2.2"}'


def test_what_identifies_nobody_stays() -> None:
    """Loopback, masks, 0.0.0.0, the documentation ranges and versions are left as they are."""
    text = (
        "127.0.0.1 0.0.0.0 255.255.255.0 192.0.2.10 198.51.100.7 203.0.113.9 "
        "<bspVersion>V1.4.0.790168</bspVersion> <dspVersion>V2.9.20 build 20250610</dspVersion> 999.1.1.1"
    )
    assert Anonymizer().text(text) == text


def test_names_and_secrets_are_masked() -> None:
    """The names people give, the given secrets, serials and MAC addresses are masked."""
    anonymizer = Anonymizer(["s3cret", "", "SERIAL123"])
    text = anonymizer.text(
        "<deviceName>Casa Rossi</deviceName><channelName>Front</channelName><name>COM1</name>"
        "<serialNumber>X</serialNumber><macAddress>00:00:5e:00:53:01</macAddress>"
        '<note>s3cret in SERIAL123</note>{"doorName": "Gate", "doorNo": "1"}'
    )
    assert text == (
        f"<deviceName>{MASK}</deviceName><channelName>{MASK}</channelName><name>{MASK}</name>"
        f"<serialNumber>{MASK}</serialNumber><macAddress>{MASK}</macAddress>"
        f'<note>{MASK} in {MASK}</note>{{"doorName": "{MASK}", "doorNo": "1"}}'
    )


def test_more_addresses_than_a_range() -> None:
    """Past the first documentation range, addresses come from the second."""
    anonymizer = Anonymizer()
    replaced = [anonymizer.text(f"10.0.{index // 250}.{index % 250 + 1}") for index in range(260)]
    assert replaced[0] == "192.0.2.2"
    assert replaced[252] == "192.0.2.254"
    assert replaced[253] == "198.51.100.2"  # .1 of each range reads as a gateway: skipped
    assert len(set(replaced)) == 260
