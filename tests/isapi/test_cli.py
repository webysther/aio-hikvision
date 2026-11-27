"""``python -m aiohikvision report``: a device's report from a terminal, to attach to an issue."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

from aiohikvision.__main__ import PASSWORD_VARIABLE, main, run_report
from tests.fakes import FakeIsapiDevice

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path

    import pytest
    from aiohttp.test_utils import TestServer

type Serve = Callable[[FakeIsapiDevice], Awaitable[TestServer]]


async def test_a_report_from_the_terminal(
    serve: Serve, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The command reads the device, says what it found and writes the report to a file."""
    fake = FakeIsapiDevice("door_station")
    server = await serve(fake)
    monkeypatch.setenv(PASSWORD_VARIABLE, fake.password)
    monkeypatch.chdir(tmp_path)
    argv = ["report", "127.0.0.1", "--port", str(server.port), "--username", fake.username]
    # The command runs its own event loop: in a thread, while the fake device answers here
    assert await asyncio.to_thread(main, argv) == 0
    report = json.loads((tmp_path / "aiohikvision-report-DS-KD8003-IME1-B.json").read_text())
    assert report["device"]["model"] == "DS-KD8003-IME1(B)"
    printed = capsys.readouterr().out
    assert "DS-KD8003-IME1(B) V3.7.3 build 260915 (VIS)" in printed
    assert "talk_packet: 40ms (rule)" in printed
    assert "attach it to https://github.com/webysther/aio-hikvision/issues/new" in printed
    assert fake.password not in printed


async def test_what_the_terminal_says_of_a_device_it_cannot_read(
    serve: Serve, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A refused account is said, and no file is written."""
    fake = FakeIsapiDevice("door_station")
    server = await serve(fake)
    output = tmp_path / "report.json"
    status = await run_report(
        "127.0.0.1", fake.username, "wrong", port=server.port, https=False, output=output
    )
    assert status == 1
    assert "BadCredentials" in capsys.readouterr().err
    assert not output.exists()


async def test_what_was_not_recognised_is_printed(
    serve: Serve, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A model no rule knows, and the documents that failed, are pointed out."""
    fake = FakeIsapiDevice("camera_g3", overrides={"/ISAPI/System/status": (500, "")})
    server = await serve(fake)
    output = tmp_path / "camera.json"
    assert (
        await run_report(
            "127.0.0.1", fake.username, fake.password, port=server.port, https=False, output=output
        )
        == 0
    )
    printed = capsys.readouterr().out
    assert "! no rule knows this model and firmware" in printed
    assert "! failed: /ISAPI/System/status" in printed
    assert output.exists()


def test_the_password_is_asked_for(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without the variable the password is asked for, never taken from the command line."""
    monkeypatch.delenv(PASSWORD_VARIABLE, raising=False)
    asked: list[str] = []

    def getpass(prompt: str) -> str:
        asked.append(prompt)
        return "pw"

    monkeypatch.setattr("getpass.getpass", getpass)
    monkeypatch.setattr("aiohikvision.__main__.asyncio.run", lambda coroutine: coroutine.close() or 7)
    assert main(["report", "192.0.2.10"]) == 7
    assert asked == ["Password of admin: "]
