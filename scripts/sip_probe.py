"""How a Hikvision door station calls over peer-to-peer SIP: a probe, not a library.

It stands in for the indoor station the door station calls when its button is pressed (firmware
V3.7.1 build250709 and later: standard SIP, P2P). Every SIP message is logged as it arrives or
leaves, and saved with the sound, the video and a summary in a folder of the capture, so the
answers of milestone 0 (docs/DEVICE_FINDINGS.md) come from real traffic.

Modes:
  ring     answer 180 Ringing and never pick up: how long it rings, whether the caller hears "busy"
  answer   pick up after a few seconds, record the visitor, play a sound to them, hang up
  reject   refuse with 486 (busy) or 603 (decline): which tone the visitor hears
  call     call the door station from here (does it answer by itself?)

Our G.711 goes in 40 ms packets, the size the door station sends: with 20 ms ones (--ptime 20,
or the ptime20 step) the KD8003 V3.7.1 sends its own sound at 2/3 of real time, seconds late.

The sequence mode is a battery for one trip to the door: a step per press of its button, and
our own calls to it (out-* steps) by themselves, --call-delay seconds after the call before.
  opus     answer Opus: record it to door.opus, send our sound as Opus once
  early    183 with SDP: our sound while the door still rings, then 200 OK
  p20own   20 ms packets on our own clock (ptime20 uses aiortp's pacer)
  vout     send video to the door station: does its screen show it?
  hold     never hang up: when does the door station end the call?
  out-*    call the door station: which INVITE does it take?

Run with the libraries it tests, outside Home Assistant (host network, port 5060 free):

  uv run --with aiosipua==0.7.1 --with aiortp==0.8.0 scripts/sip_probe.py \\
      --advertise <ha-ip> --allow <door-ip> answer --video
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import math
import random
import struct
import sys
import time
import wave
from collections import Counter
from collections.abc import Callable
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import Any

from aiortp import RTPSession, VideoRTPSession
from aiosipua import (
    IncomingCall,
    SipUAC,
    SipUAS,
    TcpSipTransport,
    UdpSipTransport,
)
from aiosipua.message import SipRequest, SipResponse
from aiosipua.sdp import SdpMessage, build_sdp, parse_sdp, serialize_sdp
from aiosipua.sdp_negotiate import negotiate_sdp
from aiosipua.sdp_video import negotiate_av_sdp

LOG = logging.getLogger("sip_probe")
RATE = 8000
FRAME_BYTES = 320  # 20 ms of 8 kHz 16-bit mono: what a G.711 packet carries
ANNEX_B = b"\x00\x00\x00\x01"
SMALL_VIDEO_FMTP = "profile-level-id=42801F;packetization-mode=1;max-fs=3600;max-mbps=108000"
# What the door station puts in its own INVITE (KD8003 V3.7.1)
SUBJECT = "This is a call for conversation"
DOOR_VIDEO_FMTP = "profile-level-id=42801F;packetization-mode=1"
# Made once with ffmpeg (assets/README.md): our sound as Opus, a picture with a name
ASSETS = Path(__file__).parent / "assets"
VIDEO_FPS = 10
# Our calls to the door station, each changing one more thing from the INVITE it refused with 400
# Our calls to the door station. The first ones add one change each to the call it refused; the
# mirror copies its own INVITE, and each mirror-* step takes one thing back from the mirror.
PLAIN = {
    "uri_port": False,  # Request-URI and To with the door's port
    "caller": "probe",  # From: probe@us, us (no user part), or our P2P call number
    "user_agent": None,  # None: no User-Agent header
    "supported": True,  # aiosipua's Supported: 100rel
    "codecs": (0,),
    "video": None,  # direction of the video m-line, if any
    "session": "-",  # the SDP s= line
    "subject": False,
    "ptime": 40,
    "port": None,  # another local SIP port to call from
    "seconds": None,  # talk, if answered (default --out-seconds)
    "direction": "sendrecv",  # of our audio m-line
    "talk": None,  # None: silence; "bursts": a 1 kHz tone, 2 s on and 2 s off, as push-to-talk
}
MIRROR = {
    **PLAIN,
    "uri_port": True,
    "caller": "bare",
    "user_agent": "HKVS/2.0",
    "supported": False,
    "codecs": (0, 8),
    "video": "sendrecv",
    "session": "Talk session",
    "subject": True,
}
OUTGOING: dict[str, tuple[str, dict[str, Any]]] = {
    "out-plain": ("the first call it refused", PLAIN),
    "out-subject": ("and its own Subject", {**PLAIN, "subject": True}),
    "out-video": ("and video in the offer", {**PLAIN, "subject": True, "video": "recvonly"}),
    "out-number": (
        "and From with our P2P call number",
        {**PLAIN, "subject": True, "video": "recvonly", "caller": "number"},
    ),
    "out-mirror": ("its own INVITE, mirrored", {**MIRROR, "seconds": 20}),
    "mirror-ua": ("the mirror without User-Agent", {**MIRROR, "user_agent": None}),
    "mirror-otherua": ("the mirror with another User-Agent", {**MIRROR, "user_agent": "HomeAssistant/2026"}),
    "mirror-uri": ("the mirror without the port in Request-URI and To", {**MIRROR, "uri_port": False}),
    "mirror-from": ("the mirror with a user part in From", {**MIRROR, "caller": "probe"}),
    "mirror-supported": ("the mirror with Supported: 100rel", {**MIRROR, "supported": True}),
    "mirror-pcmu": ("the mirror offering PCMU only", {**MIRROR, "codecs": (0,)}),
    "mirror-recvonly": ("the mirror with video recvonly", {**MIRROR, "video": "recvonly"}),
    "mirror-novideo": ("the mirror without video", {**MIRROR, "video": None}),
    "mirror-session": ("the mirror with s=-", {**MIRROR, "session": "-"}),
    "mirror-nosubject": ("the mirror without Subject", {**MIRROR, "subject": False}),
    "mirror-p20": ("the mirror sending 20 ms packets", {**MIRROR, "ptime": 20, "seconds": 20}),
    "mirror-port": ("the mirror from SIP port 5070, not the one in its P2P list", {**MIRROR, "port": 5070}),
    # The hybrid design: the call and our microphone over SIP (40 ms, no RTP from the door),
    # the door's sound and picture over RTSP
    "hybrid-sendonly": (
        "hybrid: audio sendonly, no video, push-to-talk bursts",
        {**MIRROR, "video": None, "direction": "sendonly", "talk": "bursts", "seconds": 30},
    ),
    "hybrid-sendrecv": (
        "hybrid: audio sendrecv, no video, push-to-talk bursts",
        {**MIRROR, "video": None, "talk": "bursts", "seconds": 30},
    ),
}


# ------------------------------------------------------------------ SIP on the wire


def guarded(base: type, allow: set[str], wire: Callable[[str, bytes, tuple[str, int]], None]) -> type:
    """A transport of aiosipua that logs every message as bytes and drops other addresses.

    aiosipua has no hook before it parses a message, so the check sits where the bytes arrive.
    """

    class Guarded(base):  # type: ignore[misc, valid-type]
        def _dispatch(self, data: bytes, addr: tuple[str, int]) -> None:
            if addr[0] not in allow:
                LOG.info("dropped %d bytes from %s:%d (not allowed)", len(data), *addr)
                return
            wire("RX", data, addr)
            super()._dispatch(data, addr)

        def send(self, message: Any, addr: tuple[str, int]) -> None:
            wire("TX", bytes(message), addr)
            connections = getattr(self, "_connections", None)
            if connections is not None and addr not in connections:
                # TCP: aiosipua answers to the port of the Via, which is not the port of the
                # caller's connection unless it asked for rport; answer on its connection instead
                addr = next((peer for peer in connections if peer[0] == addr[0]), addr)
            super().send(message, addr)

    Guarded.__name__ = f"Guarded{base.__name__}"
    return Guarded


# -------------------------------------------------------------------------- media


class Media:
    """The RTP of one call: the visitor's sound to a WAV, ours to them, the video to a file."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.audio: RTPSession | None = None
        self.video: VideoRTPSession | None = None
        self.wav: wave.Wave_write | None = None
        self.h264: Any = None
        self.received = 0
        self.first_audio: float | None = None
        self.nals = 0
        self.keyframes = 0
        self.dtmf: list[str] = []
        self.frames_delivered = 0
        self.packets: list[tuple[float, int, int, int, int, int]] = []
        self.video_packets: list[tuple[float, int, int, int, int, int, int, int]] = []
        self.bursts: list[float] = []  # push-to-talk bursts, seconds after the answer
        self.sent_bursts = 0
        self.video_arrivals: list[float] = []
        self.video_frames_sent = 0

    async def start(
        self,
        bind: str,
        port: int,
        remote: tuple[str, int],
        payload_type: int,
        dtmf_payload_type: int,
        video: tuple[tuple[str, int], int] | None,
        paced: bool = True,
    ) -> None:
        self.wav = wave.open(str(self.folder / "visitor.wav"), "wb")  # noqa: SIM115 (open for the whole call)
        self.wav.setnchannels(1)
        self.wav.setsampwidth(2)
        self.wav.setframerate(RATE)
        # skip_audio_gaps: without it the jitter buffer waits at the first lost packet and
        # drops the audio behind it, so a little loss on the network costs seconds of sound
        self.audio = await RTPSession.create(
            (bind, port),
            remote,
            payload_type,
            dtmf_payload_type=dtmf_payload_type,
            paced=paced,
            skip_audio_gaps=True,
        )
        self.audio.on_audio = self._on_audio
        self.audio.on_dtmf = self._on_dtmf
        self._tap_audio()
        LOG.info("audio RTP %s:%d <-> %s:%d, payload type %d", bind, port, *remote, payload_type)
        if video is not None:
            (address, video_pt) = video
            self.h264 = open(self.folder / "door.h264", "wb")  # noqa: SIM115
            self.video = await VideoRTPSession.create((bind, port + 2), address, payload_type=video_pt)
            self.video.on_frame = self._on_nal
            self._tap_video()
            LOG.info("video RTP %s:%d <-> %s:%d, payload type %d", bind, port + 2, *address, video_pt)

    def _tap_video(self) -> None:
        """Note when each video RTP packet arrives: early media counts the ones before our 200 OK."""
        transport = getattr(self.video, "_rtp_transport", None)
        deliver = getattr(transport, "_on_rtp", None)
        if transport is None or deliver is None:
            return

        def tap(data: bytes, addr: tuple[str, int]) -> None:
            self.video_arrivals.append(time.monotonic())
            deliver(data, addr)

        transport._on_rtp = tap

    def _tap_audio(self) -> None:
        """Note every audio RTP packet as it arrives, before aiortp's jitter buffer.

        aiortp has no hook for it: its transport keeps the callback in a private attribute.
        """
        transport = getattr(self.audio, "_rtp_transport", None)
        deliver = getattr(transport, "_on_rtp", None)
        if transport is None or deliver is None:
            LOG.warning("no raw RTP tap: aiortp changed")
            return

        def tap(data: bytes, addr: tuple[str, int]) -> None:
            if len(data) >= 12:
                csrc = data[0] & 0x0F
                header = 12 + 4 * csrc
                if data[0] & 0x10 and len(data) >= header + 4:  # extension
                    header += 4 + 4 * int.from_bytes(data[header + 2 : header + 4], "big")
                self.packets.append(
                    (
                        time.monotonic(),
                        int.from_bytes(data[2:4], "big"),
                        int.from_bytes(data[4:8], "big"),
                        data[1] & 0x7F,
                        data[1] >> 7,
                        len(data) - header,
                    )
                )
            deliver(data, addr)

        transport._on_rtp = tap

    def _tap_video(self) -> None:
        """Note every video RTP packet before aiortp: its frame (timestamp), size and H.264 NAL type.

        For FU-A fragments (type 28) it keeps the start/end bits and the fragmented NAL's type, so a
        frame aiortp drops can still be measured in packets.
        """
        transport = getattr(self.video, "_rtp_transport", None)
        deliver = getattr(transport, "_on_rtp", None)
        if transport is None or deliver is None:
            LOG.warning("no raw video RTP tap: aiortp changed")
            return

        def tap(data: bytes, addr: tuple[str, int]) -> None:
            header = 12 + 4 * (data[0] & 0x0F) if data else 0
            if len(data) > header + 1:
                nal = data[header] & 0x1F
                fu = data[header + 1] if nal == 28 else 0
                self.video_packets.append(
                    (
                        time.monotonic(),
                        int.from_bytes(data[2:4], "big"),
                        int.from_bytes(data[4:8], "big"),
                        data[1] >> 7,
                        len(data) - header,
                        nal,
                        fu >> 6,  # FU-A: 2 start, 1 end
                        fu & 0x1F,
                    )
                )
            deliver(data, addr)

        transport._on_rtp = tap

    def _write_video_packets(self) -> dict[str, Any]:
        """video_rtp.csv, and how many packets the door's frames take (aiortp holds 128 at most)."""
        if not self.video_packets:
            return {}
        first = self.video_packets[0][0]
        with (self.folder / "video_rtp.csv").open("w", encoding="utf-8") as out:
            out.write(
                "arrival_ms,sequence,timestamp,marker,payload_bytes,nal_type,fu_start_end,fu_nal_type\n"
            )
            for arrival, *rest in self.video_packets:
                out.write(f"{(arrival - first) * 1000:.1f}," + ",".join(map(str, rest)) + "\n")
        frames: dict[int, list[tuple[Any, ...]]] = {}
        for packet in self.video_packets:
            frames.setdefault(packet[2], []).append(packet)
        sizes = sorted(len(p) for p in frames.values())
        key_sizes = [
            len(p) for p in frames.values() if any(q[5] == 5 or (q[5] == 28 and q[7] == 5) for q in p)
        ]
        sequences = [p[1] for p in self.video_packets]
        steps = [(b - a) & 0xFFFF for a, b in zip(sequences, sequences[1:], strict=False)]
        nal_types: dict[int, int] = {}
        for packet in self.video_packets:
            nal_types[packet[5]] = nal_types.get(packet[5], 0) + 1
        return {
            "video_packets": len(self.video_packets),
            "video_frames_by_timestamp": len(frames),
            "video_packets_per_frame_median_max": [sizes[len(sizes) // 2], sizes[-1]],
            "video_keyframe_packets": sorted(key_sizes),
            "video_frames_over_128_packets": sum(size > 128 for size in sizes),
            "video_sequence_gaps": sum(step > 1 and step < 0x8000 for step in steps),
            "video_sequence_backsteps": sum(step >= 0x8000 for step in steps),
            "video_nal_types": dict(sorted(nal_types.items())),
            "video_payload_bytes_max": max(p[4] for p in self.video_packets),
        }

    def _write_packets(self) -> dict[str, Any]:
        """The packets in audio_rtp.csv, and what they say about the door's audio."""
        if not self.packets:
            return {}
        start = self.packets[0][0]
        with (self.folder / "audio_rtp.csv").open("w", encoding="utf-8") as out:
            out.write("arrival_ms,sequence,timestamp,payload_type,marker,payload_bytes\n")
            for arrival, *rest in self.packets:
                out.write(f"{(arrival - start) * 1000:.1f}," + ",".join(map(str, rest)) + "\n")
        audio = [p for p in self.packets if p[3] in (0, 8)]
        if len(audio) < 2:
            return {"audio_packets": len(audio)}
        steps = [b[2] - a[2] for a, b in zip(audio, audio[1:], strict=False)]
        span = audio[-1][0] - audio[0][0]
        timestamp_span = ((audio[-1][2] - audio[0][2]) & 0xFFFFFFFF) / RATE
        gaps = [(b[0] - a[0]) * 1000 for a, b in zip(audio, audio[1:], strict=False)]
        sizes = sorted({p[5] for p in audio})
        return {
            "audio_packets": len(audio),
            "audio_payload_bytes": sizes[:5],
            "audio_timestamp_step": sorted(set(steps))[:5],
            "audio_interval_ms_avg": round(sum(gaps) / len(gaps), 1),
            "audio_span_s": round(span, 1),
            # Below 1: the door sends less audio than the time that passes
            "audio_rate": round(timestamp_span / span, 2) if span else None,
            "audio_frames_delivered": self.frames_delivered,
        }

    def _on_audio(self, pcm: bytes, _timestamp: int) -> None:
        self.frames_delivered += 1
        if self.first_audio is None:
            self.first_audio = time.monotonic()
            LOG.info("first audio packet from the door station")
        self.received += len(pcm)
        if self.wav is not None:
            self.wav.writeframes(pcm)

    def _on_dtmf(self, digit: str, duration: int) -> None:
        self.dtmf.append(digit)
        LOG.info("DTMF %s (%d ms)", digit, duration * 1000 // RATE)

    def _on_nal(self, nal: bytes, _timestamp: int, keyframe: bool) -> None:
        self.nals += 1
        self.keyframes += keyframe
        if self.h264 is not None:
            self.h264.write(ANNEX_B + nal)

    async def play(self, pcm: bytes, keep_sending: bool = True) -> None:
        """Send 8 kHz 16-bit mono sound as paced 20 ms packets, then silence until cancelled.

        Without the silence our RTP stops with the sound, as a phone muted by some apps would.
        """
        if self.audio is None:
            return
        for offset in range(0, len(pcm) - FRAME_BYTES + 1, FRAME_BYTES):
            self.audio.send_audio_pcm_auto(pcm[offset : offset + FRAME_BYTES])
        await self.audio.drain()
        LOG.info("test sound played%s", "; silence from now on" if keep_sending else "; our RTP stops")
        silence = bytes(FRAME_BYTES)
        while keep_sending:
            for _ in range(50):  # a second at a time, so cancelling is quick
                self.audio.send_audio_pcm_auto(silence)
            await self.audio.drain()

    async def play_own_pace(self, pcm: bytes, frame_bytes: int, keep_sending: bool = True) -> None:
        """Send the sound in packets of our own size (16-bit PCM bytes each), paced here.

        aiortp's pacer sends 20 ms packets only; the door sends 40 ms ones.
        """
        if self.audio is None:
            return
        loop = asyncio.get_running_loop()
        start = loop.time()
        timestamp = int.from_bytes(struct.pack("<I", id(self) & 0xFFFFFFFF), "little")
        seconds = frame_bytes / 2 / RATE
        frames = [pcm[i : i + frame_bytes] for i in range(0, len(pcm) - frame_bytes + 1, frame_bytes)]
        silence = bytes(frame_bytes)
        sent = 0
        while True:
            if sent < len(frames):
                frame = frames[sent]
            elif keep_sending:
                frame = silence
            else:
                return
            self.audio.send_audio_pcm(frame, timestamp)
            timestamp = (timestamp + frame_bytes // 2) & 0xFFFFFFFF
            sent += 1
            await asyncio.sleep(max(0.0, start + sent * seconds - loop.time()))

    async def send_video(self, frames: list[tuple[list[bytes], bool]]) -> None:
        """Send a clip to the door station over and over, VIDEO_FPS frames a second, until cancelled."""
        if self.video is None or not frames:
            return
        loop = asyncio.get_running_loop()
        start = loop.time()
        timestamp = random.getrandbits(32)
        while True:
            nal_units, keyframe = frames[self.video_frames_sent % len(frames)]
            self.video.send_frame(nal_units, timestamp, keyframe=keyframe)
            self.video_frames_sent += 1
            timestamp = (timestamp + 90000 // VIDEO_FPS) & 0xFFFFFFFF
            await asyncio.sleep(max(0.0, start + self.video_frames_sent / VIDEO_FPS - loop.time()))

    async def play_bursts(self, frame_bytes: int, answered: float) -> None:
        """Push-to-talk: a 1 kHz tone for 2 s, then nothing for 2 s, again and again.

        Packets of frame_bytes PCM each on an absolute clock; the timestamp keeps counting
        through the silence and the first packet of each burst has the marker bit (RFC 3551).
        Each burst's start, in seconds after the answer, goes to self.bursts.
        """
        if self.audio is None or self.audio._sender is None:
            return
        loop = asyncio.get_running_loop()
        samples = frame_bytes // 2
        tone = struct.pack(
            f"<{samples}h", *(int(6000 * math.sin(2 * math.pi * 1000 * n / RATE)) for n in range(samples))
        )
        payload = self.audio._codec.encode(tone) if self.audio._codec is not None else tone
        period = samples / RATE
        start = loop.time()
        timestamp = int.from_bytes(struct.pack("<I", id(self) & 0xFFFFFFFF), "little")
        frames_per_half = round(2.0 / period)
        index = 0
        while True:
            if (index // frames_per_half) % 2 == 0:
                first = index % frames_per_half == 0
                if first:
                    self.bursts.append(round(time.monotonic() - answered, 2))
                self.audio._sender.send_frame(
                    payload, timestamp, marker=1 if first else 0, addr=self.audio._remote_addr
                )
                self.sent_bursts += 1
            timestamp = (timestamp + samples) & 0xFFFFFFFF
            index += 1
            await asyncio.sleep(max(0.0, start + index * period - loop.time()))

    async def close(self) -> dict[str, Any]:
        rtp = {}
        for name, session in (("audio_rtp", self.audio), ("video_rtp", self.video)):
            if session is not None:
                with suppress(Exception):
                    rtp[name] = {
                        key: value
                        for key, value in session.stats.items()
                        if key in ("packets_received", "packets_lost", "jitter", "packets_sent")
                    }
        for session in (self.audio, self.video):
            if session is not None:
                with suppress(Exception):
                    await session.close()
        if self.wav is not None:
            self.wav.close()
        if self.h264 is not None:
            self.h264.close()
        found = {
            **rtp,
            **self._write_packets(),
            **self._write_video_packets(),
            **(
                {"talk_bursts_at_s": self.bursts, "talk_packets_sent": self.sent_bursts}
                if self.bursts
                else {}
            ),
            "visitor_audio_seconds": round(self.received / 2 / RATE, 1),
            "dtmf": "".join(self.dtmf),
            "video_nal_units": self.nals,
            "video_keyframes": self.keyframes,
        }
        if self.video_frames_sent:
            found["video_frames_sent"] = self.video_frames_sent
        return found


def opus_ms(payload: bytes) -> float:
    """The audio in an Opus packet, from its first byte (RFC 6716, 3.1)."""
    if not payload:
        return 0.0
    config, code = payload[0] >> 3, payload[0] & 3
    if config < 12:
        frame = (10, 20, 40, 60)[config % 4]
    elif config < 16:
        frame = (10, 20)[config % 2]
    else:
        frame = (2.5, 5, 10, 20)[config % 4]
    frames = 1 if code == 0 else 2 if code in (1, 2) else (payload[1] & 0x3F if len(payload) > 1 else 1)
    return frame * frames


def opus_toc(payload: bytes) -> str:
    """What an Opus packet says it carries (RFC 6716, 3.1): mode, bandwidth, frame, packing."""
    config, stereo, code = payload[0] >> 3, payload[0] >> 2 & 1, payload[0] & 3
    if config < 12:
        mode, bandwidth, frame = "SILK", ("NB", "MB", "WB")[config // 4], (10, 20, 40, 60)[config % 4]
    elif config < 16:
        mode, bandwidth, frame = "Hybrid", ("SWB", "FB")[(config - 12) // 2], (10, 20)[config % 2]
    else:
        mode, bandwidth = "CELT", ("NB", "WB", "SWB", "FB")[(config - 16) // 4]
        frame = (2.5, 5, 10, 20)[config % 4]
    return f"config {config}: {mode} {bandwidth} {frame} ms, code {code}" + (" stereo" if stereo else "")


def _ogg_crc_table() -> list[int]:
    table = []
    for byte in range(256):
        crc = byte << 24
        for _ in range(8):
            crc = (crc << 1) ^ 0x04C11DB7 if crc & 0x80000000 else crc << 1
        table.append(crc & 0xFFFFFFFF)
    return table


OGG_CRC = _ogg_crc_table()


def ogg_page(data: bytes, granule: int, sequence: int, flags: int) -> bytes:
    """One Ogg page holding one packet (RFC 3533), CRC included."""
    lacing = bytes([255] * (len(data) // 255) + [len(data) % 255])
    page = struct.pack("<4sBBqIIIB", b"OggS", 0, flags, granule, 0x484B5653, sequence, 0, len(lacing))
    page += lacing + data
    crc = 0
    for byte in page:
        crc = ((crc << 8) & 0xFFFFFFFF) ^ OGG_CRC[(crc >> 24) ^ byte]
    return page[:22] + crc.to_bytes(4, "little") + page[26:]


def write_ogg_opus(path: Path, packets: list[bytes], input_rate: int) -> None:
    """Opus packets as a file ffmpeg and players decode (RFC 7845), without libraries."""
    head = b"OpusHead" + struct.pack("<BBHIhB", 1, 1, 0, input_rate, 0, 0)
    tags = b"OpusTags" + struct.pack("<I", 9) + b"sip_probe" + struct.pack("<I", 0)
    pages = [ogg_page(head, 0, 0, 0x02), ogg_page(tags, 0, 1, 0)]
    granule = 0
    for index, packet in enumerate(packets):
        granule += round(opus_ms(packet) * 48)  # the granule counts 48 kHz samples
        pages.append(ogg_page(packet, granule, index + 2, 0x04 if index == len(packets) - 1 else 0))
    path.write_bytes(b"".join(pages))


def read_packets(path: Path) -> list[bytes]:
    """Payloads stored as 2-byte big-endian length and bytes, one after the other."""
    data = path.read_bytes() if path.exists() else b""
    packets, position = [], 0
    while position + 2 <= len(data):
        size = int.from_bytes(data[position : position + 2], "big")
        packets.append(data[position + 2 : position + 2 + size])
        position += 2 + size
    return packets


def access_units(path: Path) -> list[tuple[list[bytes], bool]]:
    """The frames of an H.264 Annex B file with one slice each: the parameter sets go with the slice."""
    if not path.exists():
        return []
    frames, pending = [], []
    for chunk in path.read_bytes().split(b"\x00\x00\x01")[1:]:
        nal = chunk.rstrip(b"\x00")  # the zero of the next 4-byte start code
        kind = nal[0] & 0x1F if nal else 0
        if kind in (0, 6, 9):  # SEI and delimiters: nothing a decoder needs
            continue
        pending.append(nal)
        if kind in (1, 5):
            frames.append((pending, kind == 5))
            pending = []
    return frames


class RawAudio(asyncio.DatagramProtocol):
    """The door's RTP of a codec aiortp does not decode: kept as packets, measured, not played."""

    def __init__(self, folder: Path, clock: int, opus: bool) -> None:
        self.folder = folder
        self.clock = clock
        self.opus = opus
        self.packets: list[tuple[float, int, int, int, bytes]] = []
        self.transport: asyncio.DatagramTransport | None = None
        self.sent = 0

    async def send(self, remote: tuple[str, int], payload_type: int, packets: list[bytes], step: int) -> None:
        """Send ready payloads every 40 ms from our RTP port, as the door does: timestamp +step each."""
        loop = asyncio.get_running_loop()
        start = loop.time()
        sequence, timestamp, ssrc = random.getrandbits(16), random.getrandbits(32), random.getrandbits(32)
        for index, payload in enumerate(packets):
            if self.transport is None:
                return
            marker = 0x80 if index == 0 else 0
            header = struct.pack("!BBHII", 0x80, marker | payload_type, sequence, timestamp, ssrc)
            self.transport.sendto(header + payload, remote)
            self.sent += 1
            sequence = (sequence + 1) & 0xFFFF
            timestamp = (timestamp + step) & 0xFFFFFFFF
            await asyncio.sleep(max(0.0, start + (index + 1) * 0.04 - loop.time()))
        LOG.info("our sound sent: %d packets; nothing more from us", self.sent)

    async def start(self, bind: str, port: int) -> None:
        loop = asyncio.get_running_loop()
        await loop.create_datagram_endpoint(lambda: self, local_addr=(bind, port))

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if len(data) < 12 or data[0] >> 6 != 2:
            return
        header = 12 + 4 * (data[0] & 0x0F)
        if data[0] & 0x10 and len(data) >= header + 4:
            header += 4 + 4 * int.from_bytes(data[header + 2 : header + 4], "big")
        self.packets.append(
            (
                time.monotonic(),
                int.from_bytes(data[2:4], "big"),
                int.from_bytes(data[4:8], "big"),
                data[1] & 0x7F,
                data[header:],
            )
        )

    def close(self, payload_type: int) -> dict[str, Any]:
        if self.transport is not None:
            self.transport.close()
        media = [p for p in self.packets if p[3] == payload_type]
        with (self.folder / "audio_rtp.csv").open("w", encoding="utf-8") as out:
            out.write("arrival_ms,sequence,timestamp,payload_type,payload_bytes\n")
            start = self.packets[0][0] if self.packets else 0.0
            for arrival, sequence, timestamp, pt, payload in self.packets:
                out.write(f"{(arrival - start) * 1000:.1f},{sequence},{timestamp},{pt},{len(payload)}\n")
        if len(media) < 2:
            return {"audio_packets": len(media)}
        span = media[-1][0] - media[0][0]
        timestamp_span = ((media[-1][2] - media[0][2]) & 0xFFFFFFFF) / self.clock
        found: dict[str, Any] = {
            "audio_packets": len(media),
            "audio_payload_bytes": sorted({len(p[4]) for p in media})[:5],
            "audio_timestamp_step": sorted(
                {(b[2] - a[2]) & 0xFFFFFFFF for a, b in zip(media, media[1:], strict=False)}
            )[:5],
            "audio_interval_ms_avg": round(span / (len(media) - 1) * 1000, 1),
            "audio_span_s": round(span, 1),
            f"audio_rate_by_timestamp_at_{self.clock}": round(timestamp_span / span, 2) if span else None,
        }
        if self.opus:
            durations = [opus_ms(p[4]) for p in media]
            found["opus_frame_ms"] = sorted(set(durations))[:5]
            found["audio_rate_by_opus_frames"] = round(sum(durations[:-1]) / 1000 / span, 2) if span else None
            payloads = [p[4] for p in media if p[4]]
            found["opus_toc"] = dict(Counter(opus_toc(p) for p in payloads).most_common())
            # To listen to: ffmpeg -i door.opus door.wav
            write_ogg_opus(self.folder / "door.opus", payloads, self.clock)
        return found


# The codecs measured without decoding: payload type the door offers, RTP clock it declares
RAW_CODECS = {"opus": (115, 16000), "g7221": (98, 16000)}


def test_sound(path: Path | None) -> bytes:
    """The sound played to the visitor: a WAV of 8 kHz 16-bit mono, or two soft tones, once."""
    if path is None:
        tones = [(440, 1.0), (0, 0.5), (880, 1.0), (0, 1.5)]
        samples = []
        for frequency, seconds in tones:
            for n in range(int(seconds * RATE)):
                samples.append(int(3000 * math.sin(2 * math.pi * frequency * n / RATE)) if frequency else 0)
        return struct.pack(f"<{len(samples)}h", *samples)
    with wave.open(str(path), "rb") as sound:
        if (sound.getframerate(), sound.getnchannels(), sound.getsampwidth()) != (RATE, 1, 2):
            sys.exit(f"{path}: convert it first: ffmpeg -i {path} -ar 8000 -ac 1 -sample_fmt s16 out.wav")
        return sound.readframes(sound.getnframes())


# ---------------------------------------------------------------------------- SDP


def describe_offer(sdp: SdpMessage) -> dict[str, Any]:
    """What the door station offers, for the findings."""
    found: dict[str, Any] = {"connection": sdp.rtp_address}
    for media in sdp.media:
        found[f"m={media.media}"] = {
            "port": media.port,
            "direction": media.direction,
            "codecs": [f"{c.payload_type} {c.encoding_name}/{c.clock_rate}" for c in media.codecs],
            "ptime": media.attributes.get("ptime"),
            "fmtp": [c.fmtp for c in media.codecs if c.fmtp],
        }
    return found


def telephone_event(sdp: SdpMessage) -> int | None:
    audio = sdp.audio
    if audio is None:
        return None
    return next((c.payload_type for c in audio.codecs if c.encoding_name.lower() == "telephone-event"), None)


def our_offer(
    address: str,
    port: int,
    codecs: tuple[int, ...],
    video: str | None,
    session: str,
    ptime: int = 40,
    direction: str = "sendrecv",
) -> SdpMessage:
    """The offer of a call of ours: G.711 in ptime packets, and video in this direction, if any."""
    stamp = int(time.time())
    names = {0: "PCMU", 8: "PCMA"}
    lines = [
        "v=0",
        f"o=- {stamp} {stamp} IN IP4 {address}",
        f"s={session}",
        f"c=IN IP4 {address}",
        "t=0 0",
        f"m=audio {port} RTP/AVP {' '.join(map(str, codecs))} 101",
        *(f"a=rtpmap:{codec} {names[codec]}/8000" for codec in codecs),
        "a=rtpmap:101 telephone-event/8000",
        "a=fmtp:101 0-16",
        f"a=ptime:{ptime}",
        f"a={direction}",
    ]
    if video is not None:
        lines += [
            f"m=video {port + 2} RTP/AVP 96",
            "a=rtpmap:96 H264/90000",
            f"a=fmtp:96 {DOOR_VIDEO_FMTP}",
            f"a={video}",
        ]
    return parse_sdp("\r\n".join(lines) + "\r\n")


# -------------------------------------------------------------------------- probe


class Probe:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        host, _, port = args.bind.rpartition(":")
        self.bind = (host or "0.0.0.0", int(port))
        self.run_folder = Path(args.out) / datetime.now().strftime("%Y%m%d-%H%M%S")
        self.run_folder.mkdir(parents=True, exist_ok=True)
        self.folder = self.run_folder
        self.calls = 0
        self.sip_log = (self.run_folder / "sip.log").open("a", encoding="utf-8")
        self.call: IncomingCall | None = None
        self.ended: asyncio.Event = asyncio.Event()
        self.end_reason = ""
        self.cancelled_at: float | None = None
        self.tasks: set[asyncio.Task[None]] = set()
        self.uases: list[SipUAS] = []
        # The sequence: the next step, our calls in a row, and whether one of ours is due
        self.position = 0
        self.chain = 0
        self.ours_due = False
        self.uac: SipUAC | None = None
        door = getattr(args, "door", None) or args.allow[0]
        host, _, port = door.partition(":")
        self.door = (host, int(port or 5060))
        # Our INVITEs by Call-ID, where they went, and the answers each got
        self.invites: dict[str, tuple[SipRequest, tuple[str, int]]] = {}
        self.uacs_on: dict[int, SipUAC] = {}  # our calls from other local ports
        self.registrations = 0
        self.responses: dict[str, list[str]] = {}

    # ------------------------------------------------------------------ wire log

    def wire(self, direction: str, data: bytes, addr: tuple[str, int]) -> None:
        text = data.decode("utf-8", errors="replace")
        first = text.split("\r\n", 1)[0]
        LOG.info("%s %s:%d  %s", direction, *addr, first)
        stamp = datetime.now().isoformat(timespec="milliseconds")
        self.sip_log.write(f"----- {stamp} {direction} {addr[0]}:{addr[1]}\n{text}\n")
        self.sip_log.flush()

    # --------------------------------------------------------------- transports

    async def listen(self) -> SipUAS:
        allow = set(self.args.allow)
        advertised = (self.args.advertise, self.bind[1])
        bases = [UdpSipTransport] + ([TcpSipTransport] if self.args.tcp else [])
        first: SipUAS | None = None
        for base in bases:
            # The UAS starts its transport itself
            transport = guarded(base, allow, self.wire)(local_addr=self.bind)
            uac = None
            if base is UdpSipTransport:
                # Our calls leave from this port: the address the door station has in its P2P list
                uac = self.uac = SipUAC(transport, advertised_addr=advertised)
                self._watch_responses(uac)
            uas = SipUAS(
                transport,
                user_agent="hikvision-bridge-sip-probe",
                advertised_addr=advertised,
                uac=uac,
            )
            uas.on_invite = self._on_invite
            uas.on_cancel = self._on_cancel
            uas.on_bye = self._on_bye
            uas.on_ack_timeout = lambda _call: self._end("no ACK for our 200 OK (32 s)")
            # Standard SIP (the door's VoIP lines): we are its server too. aiosipua has no REGISTER
            # handler, so one goes into its table of methods.
            uas._handlers["REGISTER"] = lambda request, addr, uas=uas: self._on_register(uas, request, addr)
            await uas.start()
            self.uases.append(uas)
            LOG.info("listening on %s %s:%d, allowed: %s", base.__name__, *self.bind, ", ".join(allow))
            first = first or uas
        assert first is not None
        return first

    def _watch_responses(self, uac: SipUAC) -> None:
        """Keep the answers to our INVITEs for the summary, and ACK the refusals.

        aiosipua does not ACK a final answer other than 2xx (RFC 3261 17.1.1.3): the door would
        repeat it for 32 s and may refuse our next call as busy.
        """
        handle = uac.handle_response

        def watched(response: SipResponse, addr: tuple[str, int]) -> None:
            call_id = response.call_id or ""
            sent = self.invites.get(call_id)
            if sent is not None:
                cseq = response.cseq
                method = cseq.method.upper() if cseq is not None else "?"
                answer = f"{response.status_code} {response.reason_phrase}"
                self.responses.setdefault(call_id, []).append(
                    answer if method == "INVITE" else f"{answer} ({method})"
                )
                if method == "INVITE" and response.status_code >= 300:
                    self._ack_refusal(uac, *sent, response)
            handle(response, addr)

        uac.handle_response = watched  # type: ignore[method-assign]

    def _ack_refusal(
        self, uac: SipUAC, invite: SipRequest, destination: tuple[str, int], response: SipResponse
    ) -> None:
        ack = SipRequest(method="ACK", uri=invite.uri)
        ack.headers.append("Via", invite.get_header("via") or "")  # the INVITE's branch: same transaction
        ack.headers.set_single("From", invite.get_header("from") or "")
        ack.headers.set_single("To", response.get_header("to") or "")
        ack.headers.set_single("Call-ID", invite.call_id or "")
        ack.headers.set_single("CSeq", f"{invite.cseq.seq if invite.cseq else 1} ACK")
        ack.headers.set_single("Max-Forwards", "70")
        uac.transport.send(ack, destination)

    def _on_register(self, uas: SipUAS, request: SipRequest, addr: tuple[str, int]) -> None:
        """Accept the door station's registration, with no authentication, and note it."""
        contact = request.get_header("contact") or ""
        asked = request.get_header("expires")
        if "expires=" in contact:
            asked = contact.split("expires=")[1].split(";")[0].split(">")[0].strip()
        expires = int(asked) if asked and asked.isdigit() else 60
        response = SipResponse(status_code=200, reason_phrase="OK")
        for via in request.headers.get("via"):
            response.headers.append("Via", via)
        response.headers.set_single("From", request.get_header("from") or "")
        to = request.get_header("to") or ""
        response.headers.set_single("To", to if ";tag=" in to else f"{to};tag=probe{int(time.time())}")
        response.headers.set_single("Call-ID", request.call_id or "")
        response.headers.set_single("CSeq", request.get_header("cseq") or "")
        if contact and expires:
            bare = contact.split(";expires=")[0]
            response.headers.set_single("Contact", f"{bare};expires={expires}")
        response.headers.set_single("Expires", str(expires))
        response.headers.set_single("Date", time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime()))
        response.headers.set_single("User-Agent", "hikvision-bridge-sip-probe")
        uas.transport.send_reply(response)
        self.registrations += 1
        line = (
            f"{datetime.now():%H:%M:%S} REGISTER #{self.registrations} from {addr[0]}:{addr[1]}: "
            f"To {to}, Contact {contact or '-'}, expires {expires}, "
            f"User-Agent {request.get_header('user-agent') or '-'}, "
            f"Authorization {'yes' if request.get_header('authorization') else 'no'}"
        )
        LOG.info("%s", line)
        with (self.run_folder / "registrations.log").open("a", encoding="utf-8") as out:
            out.write(line + "\n")

    # ------------------------------------------------------------------ events

    def _on_invite(self, call: IncomingCall) -> None:
        if self.call is not None or self.ours_due:
            LOG.info(
                "INVITE while %s: 486", "in a call" if self.call is not None else "a call of ours is due"
            )
            call.reject(486)
            return
        self.call = call
        self.calls += 1
        self.folder = self.run_folder / f"call-{self.calls:02d}-{datetime.now():%H%M%S}"
        self.folder.mkdir()
        task = asyncio.get_running_loop().create_task(self._incoming(call))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    def _on_cancel(self, request: Any, _addr: tuple[str, int]) -> None:
        if self.call is not None and request.call_id == self.call.call_id:
            self.cancelled_at = time.monotonic()
            self._end("caller cancelled (CANCEL)")

    def _on_bye(self, _call: Any, _request: Any) -> None:
        self._end("door station hung up (BYE)")

    def _end(self, reason: str) -> None:
        if not self.ended.is_set():
            self.end_reason = reason
            LOG.info("call ended: %s", reason)
            self.ended.set()

    async def _wait_end(self, seconds: float) -> bool:
        """Whether the call ended from the other side within the time."""
        with suppress(TimeoutError):
            await asyncio.wait_for(self.ended.wait(), seconds)
        return self.ended.is_set()

    # ------------------------------------------------------------- incoming call

    def _announce(self, call: IncomingCall, name: str) -> None:
        """Send our name with 180 and 200, in the headers phones show the called party from.

        aiosipua takes extra headers only in a private method; ringing() and accept() use it.
        """
        send = call._send_response
        identity = f'"{name}" <sip:100@{self.args.advertise}>'

        def with_identity(status_code: int, reason: str, **kwargs: Any) -> Any:
            if status_code in (180, 183, 200):
                headers = dict(kwargs.get("extra_headers") or {})
                headers.setdefault("P-Asserted-Identity", identity)
                headers.setdefault("Remote-Party-ID", f"{identity};party=called;screen=yes;privacy=off")
                kwargs["extra_headers"] = headers
            return send(status_code, reason, **kwargs)

        call._send_response = with_identity  # type: ignore[method-assign]

    def _step(self) -> str:
        """What to do with this call: the mode, or the next step of the sequence for a press."""
        args = self.args
        if args.mode == "sequence":
            for _ in args.steps:
                step = args.steps[self.position % len(args.steps)]
                self.position += 1
                if step not in OUTGOING:
                    return step
                LOG.info("step %s skipped: the button was pressed instead", step)
            return "answer"
        if args.mode == "reject":
            return f"reject{args.code}"
        if args.mode == "answer" and args.quiet_after_play:
            return "quiet"
        return args.mode

    async def _incoming(self, call: IncomingCall) -> None:
        args = self.args
        started = time.monotonic()
        step = self._step()
        self.chain = 0
        LOG.info("call %d: %s", self.calls, step)
        summary: dict[str, Any] = {
            "mode": step,
            "from": call.caller,
            "to": call.callee,
            "source": call.source_addr,
            "user_agent": call.invite.get_header("user-agent"),
        }
        offer = call.sdp_offer
        if offer is not None:
            (self.folder / "offer.sdp").write_text(serialize_sdp(offer), encoding="utf-8")
            summary["offer"] = describe_offer(offer)
            LOG.info("offer: %s", summary["offer"])
        if getattr(args, "display_name", None):
            self._announce(call, args.display_name)
        try:
            if step.startswith("reject"):
                code = int(step.removeprefix("reject"))
                call.reject(code)
                summary["result"] = f"rejected with {code}"
                await self._wait_end(3)
            elif step == "ring":
                call.ringing()
                ended = await self._wait_end(args.max_ring)
                summary["rang_seconds"] = round(time.monotonic() - started, 1)
                summary["result"] = self.end_reason if ended else f"still ringing after {args.max_ring} s"
                if not ended:
                    call.reject(480)
            else:
                call.ringing()
                if await self._wait_end(args.after):
                    summary["result"] = f"{self.end_reason} before we answered"
                elif offer is None:
                    call.reject(488)
                    summary["result"] = "INVITE without SDP: 488"
                else:
                    summary.update(await self._answer(call, offer, step))
        finally:
            summary["seconds"] = round(time.monotonic() - started, 1)
            self._write_summary(summary)
            self.call = None
            self.ended = asyncio.Event()
            self.after_call()

    def _answer_sdp(
        self, offer: SdpMessage, step: str, video: bool, ptime: int, dtmf: int
    ) -> tuple[SdpMessage, int, int | None]:
        """Our answer: G.711 in packets of ptime ms, and the door's video when we take it."""
        args = self.args
        port = args.rtp_port
        video_pt = None
        if video and offer.video is not None:
            answer, audio_pt, video_pt = negotiate_av_sdp(
                offer,
                args.advertise,
                port,
                port + 2,
                supported_codecs=[0, 8],
                dtmf_payload_type=dtmf,
            )
            if video_pt is not None and answer.video is not None:
                for direction in ("sendrecv", "sendonly", "recvonly", "inactive"):
                    answer.video.attributes.pop(direction, None)
                # We only watch the door; vout shows it a picture too
                answer.video.attributes["sendrecv" if step == "vout" else "recvonly"] = []
                if step == "small":
                    # What we can take, per RFC 6184: up to 720p (3600 macroblocks a frame),
                    # the size of the door's sub stream, which its own offer says (level 3.1)
                    answer.video.attributes["fmtp"] = [f"{video_pt} {SMALL_VIDEO_FMTP}"]
        else:
            answer, audio_pt = negotiate_sdp(
                offer, args.advertise, port, supported_codecs=[0, 8], dtmf_payload_type=dtmf, ptime=ptime
            )
        if answer.audio is not None:
            # aiosipua keeps the offer's ptime when it has one, and the A/V answer has none
            answer.audio.attributes["ptime"] = [str(ptime)]
        return answer, audio_pt, video_pt

    async def _answer(self, call: IncomingCall, offer: SdpMessage, step: str) -> dict[str, Any]:
        args = self.args
        if step in RAW_CODECS:
            return await self._answer_raw(call, offer, step)
        keep_sending = step != "quiet"
        video = step == "vout" or (args.video and step in ("answer", "small", "quiet", "early", "hold"))
        # The door sends 40 ms packets; ours must be the same size (see the module docstring)
        ptime = 20 if step in ("ptime20", "p20own") else args.ptime
        # p20own: 20 ms on our clock, to tell the packet size from aiortp's pacer
        own_pace = ptime != 20 or step == "p20own"
        dtmf = telephone_event(offer) or 101
        answer, audio_pt, video_pt = self._answer_sdp(offer, step, video, ptime, dtmf)
        if step == "hybrid" and answer.audio is not None:
            # The hybrid design: only our microphone goes over SIP; the door's sound and picture
            # come over RTSP, so the door is asked to send us no RTP
            for direction in ("sendrecv", "sendonly", "recvonly", "inactive"):
                answer.audio.attributes.pop(direction, None)
            answer.audio.attributes["sendonly"] = []
        (self.folder / "answer.sdp").write_text(serialize_sdp(answer), encoding="utf-8")
        media = Media(self.folder)
        watch = (offer.video_rtp_address, video_pt) if video_pt is not None else None
        await media.start(
            self.bind[0], args.rtp_port, offer.rtp_address, audio_pt, dtmf, watch, paced=not own_pace
        )
        answered: float | None = None
        early: float | None = None
        if step == "early":
            # Early media: does the door play our sound while it still rings, and send its own?
            call._send_response(
                183, "Session Progress", body=serialize_sdp(answer), content_type="application/sdp"
            )
            early = time.monotonic()
            LOG.info("183 Session Progress with our SDP; 200 OK in %s s", args.early_seconds)
        else:
            call.accept(answer)
            answered = time.monotonic()
        sound = test_sound(args.play)
        if step == "hybrid":
            # Push-to-talk: 2 s of a 1 kHz tone, 2 s of nothing (the visitor talks then)
            playing = media.play_bursts(ptime * RATE // 1000 * 2, answered or time.monotonic())
        elif own_pace:
            playing = media.play_own_pace(sound, ptime * RATE // 1000 * 2, keep_sending)
        else:
            playing = media.play(sound, keep_sending)
        loop = asyncio.get_running_loop()
        tasks = [loop.create_task(playing)]
        if step == "vout":
            frames = access_units(ASSETS / "door_name.h264")
            if not frames:
                LOG.warning("no %s: nothing to show the door station", ASSETS / "door_name.h264")
            tasks.append(loop.create_task(media.send_video(frames)))
        found: dict[str, Any] = {}
        if early is not None and not await self._wait_end(args.early_seconds):
            call.accept(answer)
            answered = time.monotonic()
        if answered is not None:
            LOG.info("answered with %s, ptime %d", "PCMU" if audio_pt == 0 else "PCMA", ptime)
            talk = args.hold_seconds if step == "hold" else args.seconds
            hung_up_by_door = await self._wait_end(talk)
            if not hung_up_by_door:
                call.hangup()
                self._end(f"we hung up after {talk} s (BYE)")
            found["ended_by"] = "door station" if hung_up_by_door else "us"
        for task in tasks:
            task.cancel()
        found.update(await media.close())
        found["result"] = self.end_reason
        found["codec"] = "PCMU" if audio_pt == 0 else "PCMA"
        found["ptime_ms"] = ptime
        found["pacing"] = "ours" if own_pace else "aiortp"
        if early is not None:
            until = answered or time.monotonic()
            found["early_seconds"] = round(until - early, 1)
            found["early_audio_packets"] = sum(1 for packet in media.packets if packet[0] < until)
            found["early_video_packets"] = sum(1 for arrival in media.video_arrivals if arrival < until)
        if answered is not None:
            found["talk_seconds"] = round(time.monotonic() - answered, 1)
            if media.first_audio is not None:
                found["first_audio_after_answer_ms"] = round((media.first_audio - answered) * 1000)
        return found

    async def _answer_raw(self, call: IncomingCall, offer: SdpMessage, step: str) -> dict[str, Any]:
        """Answer with a codec aiortp does not decode; measure what arrives.

        Opus: also our sound, once, packed as the door packs its own (40 ms, timestamp +320).
        """
        args = self.args
        payload_type, clock = RAW_CODECS[step]
        if offer.audio is None or all(c.payload_type != payload_type for c in offer.audio.codecs):
            call.reject(488)
            return {"result": f"{step} (payload type {payload_type}) not offered: 488"}
        answer, _ = negotiate_sdp(
            offer,
            args.advertise,
            args.rtp_port,
            supported_codecs=[payload_type],
            dtmf_payload_type=telephone_event(offer) or 101,
        )
        (self.folder / "answer.sdp").write_text(serialize_sdp(answer), encoding="utf-8")
        recorder = RawAudio(self.folder, clock, opus=step == "opus")
        await recorder.start(self.bind[0], args.rtp_port)
        call.accept(answer)
        answered = time.monotonic()
        sender = None
        if step == "opus":
            packets = read_packets(ASSETS / "opus_tone.bin")
            if packets:
                sender = asyncio.get_running_loop().create_task(
                    recorder.send(offer.rtp_address, payload_type, packets, 320)
                )
            else:
                LOG.warning("no %s: recording only", ASSETS / "opus_tone.bin")
        LOG.info(
            "answered with %s (payload type %d), %s",
            step,
            payload_type,
            "sending our sound once" if sender else "recording only",
        )
        if not await self._wait_end(args.seconds):
            call.hangup()
            self._end(f"we hung up after {args.seconds} s (BYE)")
        if sender is not None:
            sender.cancel()
        found = recorder.close(payload_type)
        found["result"] = self.end_reason
        found["codec"] = step
        if step == "opus":
            found["opus_packets_sent"] = recorder.sent
        found["talk_seconds"] = round(time.monotonic() - answered, 1)
        return found

    # ------------------------------------------------------- our calls, in a sequence

    def after_call(self) -> None:
        """Start the next step by itself when it is a call of ours (sequence only)."""
        args = self.args
        if args.mode != "sequence":
            return
        step = args.steps[self.position % len(args.steps)]
        if step not in OUTGOING:
            return
        if self.chain >= len(args.steps):
            # A sequence of our calls only: once round, then the next press
            LOG.info("our calls went round once; waiting for a press")
            return
        self.position += 1
        self.chain += 1
        self.ours_due = True
        task = asyncio.get_running_loop().create_task(self._call_later(step))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def _call_later(self, step: str) -> None:
        LOG.info("calling the door station in %s s: %s", self.args.call_delay, step)
        try:
            await asyncio.sleep(self.args.call_delay)
            await self._call_door_as(step)
        except Exception:
            LOG.exception("our call %s failed", step)
        finally:
            self.ours_due = False
            self.ended = asyncio.Event()
            self.after_call()

    async def _uac_on(self, port: int) -> SipUAC:
        """A UAC on another local SIP port, with a UAS there for the door station's requests."""
        if port in self.uacs_on:
            return self.uacs_on[port]
        transport = guarded(UdpSipTransport, set(self.args.allow), self.wire)(local_addr=(self.bind[0], port))
        advertised = (self.args.advertise, port)
        uac = SipUAC(transport, advertised_addr=advertised)
        self._watch_responses(uac)
        uas = SipUAS(transport, user_agent="hikvision-bridge-sip-probe", advertised_addr=advertised, uac=uac)
        uas.on_invite = self._on_invite
        uas.on_cancel = self._on_cancel
        uas.on_bye = self._on_bye
        await uas.start()
        self.uases.append(uas)
        self.uacs_on[port] = uac
        return uac

    async def _call_door_as(self, step: str) -> None:
        """Call the door station with one variant of the INVITE; talk a little if it answers."""
        args = self.args
        assert self.uac is not None
        about, variant = OUTGOING[step]
        uac = await self._uac_on(variant["port"]) if variant["port"] else self.uac
        local_port = variant["port"] or self.bind[1]
        self.calls += 1
        self.folder = self.run_folder / f"call-{self.calls:02d}-{datetime.now():%H%M%S}"
        self.folder.mkdir()
        self.ended = asyncio.Event()
        self.end_reason = ""
        host, port = self.door
        target = f"sip:{host}:{port}" if variant["uri_port"] else f"sip:{host}"
        caller = {
            "probe": f"sip:probe@{args.advertise}",
            "bare": f"sip:{args.advertise}",
            "number": f"sip:{args.number}@{args.advertise}:{local_port}",
        }[variant["caller"]]
        offer = our_offer(
            args.advertise,
            args.rtp_port,
            variant["codecs"],
            variant["video"],
            variant["session"],
            variant["ptime"],
            variant["direction"],
        )
        (self.folder / "offer.sdp").write_text(serialize_sdp(offer), encoding="utf-8")
        LOG.info("call %d: %s (ours, no press): %s", self.calls, step, about)
        summary: dict[str, Any] = {
            "mode": step,
            "direction": "ours, to the door station",
            "variant": about,
            "request_uri": target,
            "from": caller,
            "local_sip_port": local_port,
            "user_agent": variant["user_agent"],
            "supported_100rel": variant["supported"],
            "subject": variant["subject"],
            "ptime_ms": variant["ptime"],
            "offer": describe_offer(offer),
        }
        started = time.monotonic()
        if not variant["supported"]:
            # The door's own INVITE has no Supported header; aiosipua always adds one
            build = uac._build_invite

            def without_supported(*parts: Any, **options: Any) -> SipRequest:
                invite = build(*parts, **options)
                invite.headers.remove("Supported")
                return invite

            uac._build_invite = without_supported  # type: ignore[method-assign]
        try:
            call = uac.send_invite(
                caller,
                target,
                self.door,
                sdp_offer=offer,
                extra_headers={"Subject": SUBJECT} if variant["subject"] else None,
                user_agent=variant["user_agent"],
            )
        finally:
            if not variant["supported"]:
                del uac._build_invite  # the class's method again
        self.invites[call.call_id] = (call.invite, self.door)
        try:
            await call.wait_answered(timeout=args.out_ring)
        except TimeoutError:
            summary["result"] = f"no answer in {args.out_ring} s: we cancelled"
            with suppress(Exception):
                call.cancel(uac)
            await asyncio.sleep(2)  # its 487, which we ACK
        except RuntimeError as err:
            summary["result"] = f"refused: {err}"
            await asyncio.sleep(1)  # repeats of the refusal, if our ACK went missing
        else:
            seconds = variant["seconds"] or args.out_seconds
            summary.update(
                await self._talk_on_our_call(call, started, uac, seconds, variant["ptime"], variant["talk"])
            )
        summary["responses"] = self.responses.pop(call.call_id, [])
        self.invites.pop(call.call_id, None)
        summary["seconds"] = round(time.monotonic() - started, 1)
        self._write_summary(summary)

    async def _talk_on_our_call(
        self, call: Any, started: float, uac: SipUAC, seconds: float, ptime: int, talk: str | None = None
    ) -> dict[str, Any]:
        """The door station took our call: silence to it (nobody is there), its sound and video to files."""
        args = self.args
        answered = time.monotonic()
        found: dict[str, Any] = {"answered_after_seconds": round(answered - started, 1)}
        answer = call.sdp_answer
        sound = (
            [c for c in answer.audio.codecs if c.encoding_name.lower() != "telephone-event"] if answer else []
        )
        if answer is None or answer.audio is None or not sound:
            call.hangup(uac)
            found["result"] = "answered without sound in its SDP: we hung up"
            return found
        (self.folder / "answer.sdp").write_text(serialize_sdp(answer), encoding="utf-8")
        found["answer"] = describe_offer(answer)
        watch = None
        if answer.video is not None and answer.video.port and answer.video.codecs:
            watch = (answer.video_rtp_address, answer.video.codecs[0].payload_type)
        media = Media(self.folder)
        dtmf = telephone_event(answer) or 101
        await media.start(
            self.bind[0], args.rtp_port, answer.rtp_address, sound[0].payload_type, dtmf, watch, paced=False
        )
        playing = (
            media.play_bursts(ptime * RATE // 1000 * 2, answered)
            if talk == "bursts"
            else media.play_own_pace(b"", ptime * RATE // 1000 * 2)
        )
        player = asyncio.get_running_loop().create_task(playing)
        if not await self._wait_end(seconds):
            call.hangup(uac)
            self._end(f"we hung up after {seconds} s (BYE)")
        player.cancel()
        found.update(await media.close())
        found["result"] = self.end_reason
        found["talk_seconds"] = round(time.monotonic() - answered, 1)
        return found

    # -------------------------------------------------------------- outgoing call

    async def call_door(self) -> None:
        args = self.args
        door = args.target.removeprefix("sip:").split("@")[-1]
        host, _, port = door.partition(":")
        remote = (host, int(port or 5060))
        # The UAC needs the transport, and only the UAS feeds it the responses
        transport = guarded(UdpSipTransport, set(args.allow), self.wire)(local_addr=self.bind)
        uac = self.uac = SipUAC(transport, advertised_addr=(args.advertise, self.bind[1]))
        self._watch_responses(uac)
        uas = SipUAS(transport, uac=uac, advertised_addr=(args.advertise, self.bind[1]))
        uas.on_bye = self._on_bye
        await uas.start()
        self.uases.append(uas)
        offer = build_sdp(args.advertise, args.rtp_port, 0, "PCMU", ptime=args.ptime)
        summary: dict[str, Any] = {"mode": "call", "target": args.target, "ptime_ms": args.ptime}
        started = time.monotonic()
        call = uac.send_invite(f"sip:probe@{args.advertise}", f"sip:{door}", remote, sdp_offer=offer)
        self.invites[call.call_id] = (call.invite, remote)
        call.on_ringing = lambda _call: LOG.info("door station is ringing / early media")
        try:
            await call.wait_answered(timeout=args.max_ring)
        except (TimeoutError, RuntimeError) as err:
            summary["result"] = f"not answered: {err}"
            with suppress(Exception):
                call.cancel(uac)
        else:
            summary["answered_after_seconds"] = round(time.monotonic() - started, 1)
            answer = call.sdp_answer
            (self.folder / "answer.sdp").write_text(serialize_sdp(answer), encoding="utf-8")
            summary["answer"] = describe_offer(answer)
            media = Media(self.folder)
            dtmf = telephone_event(answer) or 101
            await media.start(
                self.bind[0],
                args.rtp_port,
                answer.rtp_address,
                answer.audio.codecs[0].payload_type,
                dtmf,
                None,
                paced=args.ptime == 20,
            )
            sound = test_sound(args.play)
            playing = (
                media.play(sound)
                if args.ptime == 20
                else media.play_own_pace(sound, args.ptime * RATE // 1000 * 2)
            )
            player = asyncio.get_running_loop().create_task(playing)
            if not await self._wait_end(args.seconds):
                call.hangup(uac)
                self._end(f"we hung up after {args.seconds} s (BYE)")
            player.cancel()
            summary.update(await media.close())
            summary["result"] = self.end_reason
        await asyncio.sleep(1)  # repeats of a refusal, which we ACK
        summary["responses"] = self.responses.pop(call.call_id, [])
        self._write_summary(summary)

    # ---------------------------------------------------------------- summary

    def _write_summary(self, summary: dict[str, Any]) -> None:
        lines = [f"{key}: {value}" for key, value in summary.items()]
        (self.folder / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        LOG.info("summary in %s\n  %s", self.folder, "\n  ".join(lines))

    async def stop(self) -> None:
        for uas in self.uases:
            with suppress(Exception):
                await uas.stop()
        self.sip_log.close()


async def main(args: argparse.Namespace) -> None:
    probe = Probe(args)
    try:
        if args.mode == "call":
            await probe.call_door()
            return
        await probe.listen()
        LOG.info("waiting for the door station: press its button (Ctrl+C to stop)")
        probe.after_call()  # a sequence may start with a call of ours
        while True:
            await asyncio.sleep(3600)
    finally:
        await probe.stop()


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument(
        "--bind", default="0.0.0.0:5060", help="where to listen for SIP (default 0.0.0.0:5060)"
    )
    parser.add_argument(
        "--advertise", required=True, help="the LAN address of this machine, as the door station reaches it"
    )
    parser.add_argument(
        "--allow", action="append", required=True, help="address of the door station (repeat for more)"
    )
    parser.add_argument("--tcp", action="store_true", help="also listen for SIP over TCP")
    parser.add_argument(
        "--rtp-port", type=int, default=30000, help="audio RTP port (video uses +2); default 30000"
    )
    parser.add_argument("--out", default="captures", help="folder of the captures (default ./captures)")
    parser.add_argument("--max-ring", type=float, default=120, help="longest ring to wait for, in seconds")
    modes = parser.add_subparsers(dest="mode", required=True)
    modes.add_parser("ring", help="180 Ringing and never answer")
    answer = modes.add_parser("answer", help="answer, record, play, hang up")
    answer.add_argument(
        "--quiet-after-play", action="store_true", help="stop our RTP after the test sound (default: silence)"
    )
    sequence = modes.add_parser(
        "sequence",
        help="a step per press of the button, in turn (audio: no video; small: video up to 720p); "
        "out-* steps are our calls, made by themselves after the call before",
    )
    sequence.add_argument(
        "steps",
        nargs="+",
        choices=(
            "answer",
            "audio",
            "small",
            "ptime20",
            "p20own",
            "opus",
            "g7221",
            "early",
            "vout",
            "hold",
            "hybrid",
            "quiet",
            "ring",
            "reject486",
            "reject603",
            *OUTGOING,
        ),
    )
    sequence.add_argument(
        "--early-seconds", type=float, default=8, help="early: seconds of early media before the 200 OK"
    )
    sequence.add_argument(
        "--hold-seconds", type=float, default=150, help="hold: longest wait for the door station's BYE"
    )
    sequence.add_argument(
        "--call-delay", type=float, default=3, help="out-*: seconds after the call before, then we call"
    )
    sequence.add_argument("--out-ring", type=float, default=20, help="out-*: longest ring before CANCEL")
    sequence.add_argument("--out-seconds", type=float, default=15, help="out-*: talk, if the door answers")
    sequence.add_argument("--number", default="1", help="out-number: our P2P call number on the door station")
    sequence.add_argument(
        "--door", help="out-*: the door station's SIP address, ip[:port] (default: the first --allow, 5060)"
    )
    for parser_of_answers in (answer, sequence):
        parser_of_answers.add_argument(
            "--after", type=float, default=3, help="seconds of ringing before answering"
        )
        parser_of_answers.add_argument(
            "--seconds", type=float, default=20, help="seconds of call before our BYE"
        )
        parser_of_answers.add_argument(
            "--play", type=Path, help="WAV of 8 kHz 16-bit mono to play (default: test tones)"
        )
        parser_of_answers.add_argument(
            "--video", action="store_true", help="also take the video the door station offers"
        )
        parser_of_answers.add_argument(
            "--display-name", help="name sent with 180 and 200, to see whether the door station shows it"
        )
    reject = modes.add_parser("reject", help="refuse the call")
    reject.add_argument("--code", type=int, choices=(486, 603), default=486)
    call = modes.add_parser("call", help="call the door station from here")
    call.add_argument("target", help="sip:<door-ip>[:port]")
    call.add_argument("--seconds", type=float, default=20)
    call.add_argument("--play", type=Path)
    for parser_of_sound in (answer, sequence, call):
        parser_of_sound.add_argument(
            "--ptime", type=int, choices=(20, 40), default=40, help="ms of G.711 in each of our packets"
        )
    return parser.parse_args()


if __name__ == "__main__":
    options = arguments()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler()],
    )
    with suppress(KeyboardInterrupt):
        asyncio.run(main(options))
