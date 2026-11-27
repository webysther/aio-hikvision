"""What devices say they can do, read from their /ISAPI/System/capabilities."""

from __future__ import annotations

from pathlib import Path

import pytest

from aiohikvision import Capabilities, Domain, Support
from aiohikvision.isapi.wire.faults import NotIsapi
from aiohikvision.isapi.wire.xmlview import parse
from aiohikvision.models.capabilities import DOMAIN_EVIDENCE
from aiohikvision.parsers.capabilities import parse_capabilities
from aiohikvision.parsers.identity import parse_identity

FIXTURES = Path(__file__).parents[1] / "fakes" / "fixtures"


def capabilities_of(profile: str) -> Capabilities:
    """Return the capabilities of a device of the fixtures."""
    return parse_capabilities(parse((FIXTURES / profile / "ISAPI_System_capabilities.xml").read_text()))


@pytest.mark.parametrize(
    ("profile", "domains"),
    [
        (
            "door_station",
            {Domain.STREAMING, Domain.EVENTS, Domain.IO, Domain.VIDEO_INTERCOM, Domain.ACCESS_CONTROL}
            | {Domain.TWO_WAY_AUDIO},
        ),
        ("camera_g3", {Domain.STREAMING, Domain.EVENTS, Domain.IO, Domain.TWO_WAY_AUDIO, Domain.SMART}),
        ("camera_noio", {Domain.STREAMING, Domain.EVENTS, Domain.SMART}),
        (
            "nvr",
            {Domain.STREAMING, Domain.EVENTS, Domain.IO, Domain.TWO_WAY_AUDIO, Domain.SMART, Domain.PTZ}
            | {Domain.HOLIDAYS},
        ),
    ],
)
def test_the_domains_each_device_shows(profile: str, domains: set[Domain]) -> None:
    """A domain is present when the document shows it, absent otherwise."""
    capabilities = capabilities_of(profile)
    assert set(capabilities.domains) == domains
    for domain in set(Domain) - domains:
        assert capabilities.support(domain) is Support.ABSENT


def test_a_device_that_says_nothing() -> None:
    """Without a document, every domain is unknown: the services ask the device."""
    capabilities = parse_capabilities(None)
    assert not capabilities.tree
    assert {capabilities.support(domain) for domain in Domain} == {Support.UNKNOWN}
    assert capabilities.domains == ()
    assert capabilities.tree.flag("isSupportSnapshot") is Support.UNKNOWN
    assert Capabilities() == capabilities


def test_every_element_by_its_path() -> None:
    """Each element is found by its path or by its name, with what it offers."""
    tree = capabilities_of("door_station").tree
    assert tree.values["SysCap/IOCap/IOInputPortNums"] == "4"
    assert tree.find("IOOutputPortNums") == "SysCap/IOCap/IOOutputPortNums"
    assert tree.count("IOOutputPortNums") == 2
    assert tree.count("SysCap") is None  # a section holds no number
    assert tree.text("NetworkCap") == ""  # a section is there, empty
    assert tree.flag("isSupportHttps") is Support.PRESENT
    assert tree.flag("isSupportWireless") is Support.ABSENT
    assert tree.flag("isSupportTeleportation") is Support.ABSENT  # not in a document that came
    assert tree.text("isSupportTeleportation") is None
    assert tree.options["SecurityCap/RSAKeyLength"] == ("1024", "2048")


def test_an_element_named_twice_keeps_the_first() -> None:
    """Some devices write an element twice (the NVR's isSupportTokenAuthenticate): the first counts."""
    document = parse("<DeviceCap><a>1</a><a>2</a><b><c>x</c></b></DeviceCap>")
    tree = parse_capabilities(document).tree
    assert tree.values == {"a": "1", "b": "", "b/c": "x"}


def test_every_domain_has_evidence() -> None:
    """No domain is left without the elements that show it."""
    assert set(DOMAIN_EVIDENCE) == set(Domain)


def test_no_device_information() -> None:
    """No document, or one naming neither serial nor MAC, is no ISAPI device."""
    with pytest.raises(NotIsapi):
        parse_identity(None)
    with pytest.raises(NotIsapi, match="neither serial"):
        parse_identity(parse("<DeviceInfo><model>X</model></DeviceInfo>"))
    # A device that gives its MAC only is named after its model
    identity = parse_identity(parse("<DeviceInfo><macAddress>00:00:5e:00:53:01</macAddress></DeviceInfo>"))
    assert (identity.model, identity.name, identity.stable_id) == (
        "Hikvision device",
        "Hikvision device",
        "00005e005301",
    )
