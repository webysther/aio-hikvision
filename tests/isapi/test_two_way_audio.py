"""The two-way audio session: the raw upload, the session of the firmware, the endings."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import aiohttp
import pytest

from aiohikvision.isapi.model.features.talk import TalkChannel, TalkEnd, TalkError, TwoWayAudio
from aiohikvision.isapi.wire.faults import BadCredentials, Unreachable
from aiohikvision.isapi.wire.link import UPLOAD_BACKLOG, Endpoint, IsapiLink
from tests.fakes import FakeTalkDevice

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

NS = 'xmlns="http://www.hikvision.com/ver20/XMLSchema"'
CHANNEL = TalkChannel("1", "G.711ulaw")
FRAME = bytes(range(160))


@pytest.fixture
async def device() -> AsyncIterator[FakeTalkDevice]:
    talker = FakeTalkDevice()
    yield talker
    await talker.close()


@pytest.fixture
async def link(device: FakeTalkDevice) -> AsyncIterator[IsapiLink]:
    host, port = await device.start()
    async with aiohttp.ClientSession() as session:
        yield IsapiLink(session, Endpoint(host, port), device.username, device.password)


async def started(link: IsapiLink, ends: list[TalkEnd]) -> TwoWayAudio:
    talk = TwoWayAudio(link, CHANNEL, ends.append)
    await talk.open()
    return talk


async def test_the_sound_reaches_the_device(device, link) -> None:
    ends: list[TalkEnd] = []
    session = await started(link, ends)
    for _ in range(3):
        session.send(FRAME)
    await asyncio.sleep(0.05)
    await session.close(TalkEnd.STOPPED)
    await asyncio.wait_for(device.uploads_closed.wait(), 2)

    assert bytes(device.audio) == FRAME * 3
    assert session.sent == len(FRAME) * 3
    assert ends == [TalkEnd.STOPPED]
    # A previous talk may still hold the channel: closed first, and again at the end.
    path = CHANNEL.path
    signed = [r for r in device.requests if r[1].startswith(path)]
    assert signed[0] == ("PUT", f"{path}/close")
    assert ("PUT", f"{path}/open") in signed
    assert ("PUT", f"{path}/audioData") in signed
    assert signed[-1] == ("PUT", f"{path}/close")
    # Ending twice ends once, and nothing is sent after the end.
    await session.close(TalkEnd.STOPPED)
    assert ends == [TalkEnd.STOPPED]
    session.send(FRAME)
    assert session.sent == len(FRAME) * 3


async def test_the_session_of_the_firmware_is_named(device, link) -> None:
    device.open_reply = f"<TwoWayAudioSession {NS}><sessionId>7</sessionId></TwoWayAudioSession>"
    session = await started(link, [])
    assert ("PUT", f"{CHANNEL.path}/audioData?sessionId=7") in device.requests
    await session.close(TalkEnd.STOPPED)


async def test_an_expired_nonce_is_renewed_for_the_upload(device, link) -> None:
    device.refuse_upload = 1
    session = await started(link, [])
    uploads = [r for r in device.requests if r[1].endswith("/audioData")]
    assert len(uploads) == 2
    await session.close(TalkEnd.STOPPED)


async def test_the_device_ending_the_talk(device, link) -> None:
    device.hang_up_after = len(FRAME)
    ends: list[TalkEnd] = []
    session = await started(link, ends)
    session.send(FRAME)
    await asyncio.wait_for(device.uploads_closed.wait(), 2)
    async with asyncio.timeout(2):
        while not ends:  # noqa: ASYNC110 (the end is told by a callback)
            await asyncio.sleep(0.02)
    assert ends == [TalkEnd.DEVICE]
    assert device.requests[-1] == ("PUT", f"{CHANNEL.path}/close")


async def test_a_refused_open_fails_and_frees_the_channel(device, link) -> None:
    device.open_status = 403
    device.open_reply = "<ResponseStatus><statusCode>4</statusCode></ResponseStatus>"
    with pytest.raises(TalkError) as caught:
        await started(link, [])
    assert caught.value.reason == "talk_failed"
    assert device.requests[-1] == ("PUT", f"{CHANNEL.path}/close")
    assert not any(r[1].endswith("/audioData") for r in device.requests)


async def test_wrong_credentials_never_reach_the_upload(device) -> None:
    host, port = await device.start()
    async with aiohttp.ClientSession() as session:
        link = IsapiLink(session, Endpoint(host, port), device.username, "wrong")
        with pytest.raises(BadCredentials):
            await link.open_upload(f"{CHANNEL.path}/audioData")


async def test_an_unreachable_device() -> None:
    async with aiohttp.ClientSession() as session:
        link = IsapiLink(session, Endpoint("127.0.0.1", 9), "u", "p", connect_timeout=1)
        link._auth_checked = True  # the upload is what fails here, not the probe
        with pytest.raises(Unreachable):
            await link.open_upload("/ISAPI/System/TwoWayAudio/channels/1/audioData")


async def test_frames_beyond_the_backlog_are_dropped(device, link) -> None:
    session = await started(link, [])
    upload = session._upload
    assert upload is not None
    transport = upload._writer.transport
    real = transport.get_write_buffer_size
    transport.get_write_buffer_size = lambda: UPLOAD_BACKLOG + 1
    session.send(FRAME)
    assert session.dropped == len(FRAME)
    transport.get_write_buffer_size = real
    await session.close(TalkEnd.STOPPED)
