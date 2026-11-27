"""Each part needs its extra only: the default install imports no dependency.

Every check runs in a new interpreter where the modules of the missing extras cannot be
imported (``sys.modules[name] = None``), as after ``pip install aiohikvision`` alone.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest

from aiohikvision import MissingExtra
from aiohikvision._extras import EXTRAS, require

DEPENDENCIES = sorted({module for modules in EXTRAS.values() for module in modules})


def run_without(missing: list[str], code: str) -> str:
    """Run code where the given modules cannot be imported; return what it printed."""
    blocked = "".join(f"sys.modules[{name!r}] = None\n" for name in missing)
    script = f"import sys\n{blocked}{textwrap.dedent(code)}"
    done = subprocess.run(  # noqa: S603  # our own interpreter and script
        [sys.executable, "-c", script], capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stderr
    return done.stdout


def test_the_core_needs_no_dependency() -> None:
    """Without any extra the models, the behaviours and the errors work, and load nothing else."""
    printed = run_without(
        DEPENDENCIES,
        """
        import aiohikvision
        from aiohikvision import Firmware, Identity, KNOWN_RULES, resolve

        door = Identity("S", "DS-KD8003-IME1(B)", "N", Firmware.parse("V3.7.3"))
        print(resolve(door, KNOWN_RULES).behaviours.talk_packet)
        loaded = {name.split(".")[0] for name, module in sys.modules.items() if module is not None}
        print(sorted(loaded & {"aiohttp", "yarl", "defusedxml", "aiosipua", "cryptography"}))
        """,
    )
    assert printed.split() == ["40ms", "[]"]


@pytest.mark.parametrize(
    ("missing", "code", "extra"),
    [
        (["aiohttp"], "aiohikvision.HikvisionClient", "isapi"),
        (["aiohttp"], "aiohikvision.DoorStation", "isapi"),
        (["defusedxml"], "aiohikvision.Device", "isapi"),
        (["aiosipua"], "aiohikvision.CallServer", "sip"),
        (["aiohttp"], "__import__('aiohikvision.isapi')", "isapi"),
        (["aiohttp"], "__import__('aiohikvision.parsers')", "isapi"),
        (["aiohttp"], "__import__('aiohikvision.services')", "isapi"),
        (["aiohttp"], "__import__('aiohikvision.client')", "isapi"),
        (["aiosipua"], "__import__('aiohikvision.sip')", "sip"),
    ],
)
def test_a_part_without_its_extra_says_how_to_install_it(missing: list[str], code: str, extra: str) -> None:
    """A name or a module of a part without its extra raises MissingExtra, with the pip command."""
    printed = run_without(
        missing,
        f"""
        import aiohikvision

        try:
            {code}
        except aiohikvision.MissingExtra as err:
            print(err.extra, "|", err)
        """,
    )
    assert printed.startswith(f"{extra} | aiohikvision[{extra}] is needed")
    assert f'pip install "aiohikvision[{extra}]"' in printed


def test_rtp_needs_no_extra_dependency() -> None:
    """RTP works with the standard library alone."""
    printed = run_without(
        DEPENDENCIES,
        """
        import aiohikvision

        print(aiohikvision.RtpPacket.parse(b"") is None, aiohikvision.Packetizer.__name__)
        """,
    )
    assert printed.split() == ["True", "Packetizer"]


def test_the_names_of_the_package() -> None:
    """Every name of the package is listed and reachable; an unknown one is an AttributeError."""
    import aiohikvision  # noqa: PLC0415  # the module under test

    assert dir(aiohikvision) == sorted(aiohikvision.__all__)
    for name in aiohikvision.__all__:
        assert getattr(aiohikvision, name) is not None
    with pytest.raises(AttributeError, match="no attribute 'Nothing'"):
        _ = aiohikvision.Nothing


def test_require_an_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    """An extra whose modules are installed is required silently; a missing one raises."""
    require("isapi")
    require("rtp")
    monkeypatch.setitem(sys.modules, "aiosipua", None)
    with pytest.raises(MissingExtra, match=r'pip install "aiohikvision\[sip\]"'):
        require("sip")
    error = MissingExtra("sip", "aiosipua")
    assert isinstance(error, ImportError)
    assert error.name == "aiosipua"
    assert error.translation_key == "missing_extra"
