# ADR 0002: The door's sound over SIP during a call, when the caller asks

- **Status:** accepted, 2026-11-27. It amends ADR-0001 for the sound of an answered call;
  the picture, and the sound outside a call, still come over RTSP.
- **Device:** DS-KD8003-IME1(B), firmware V3.7.3 build260915, in standard-SIP mode

## Context

ADR-0001 reads the door's picture and sound over RTSP, and asks the door to send no RTP
(`a=sendonly`). It names the fallback: answer `sendrecv` and play the door's RTP in the
browser.

That fallback is now needed. Home Assistant plays the RTSP stream with WebRTC when it can, and
with HLS otherwise. Its HLS keeps only AAC and MP3 audio, and the door's audio is G.711. A
browser that falls back to HLS, as an iPad does, shows the visitor without their voice, and
with the delay of HLS.

## Decision

- **`CallServer(on_audio=...)`** answers `a=sendrecv` and hands on the door's sound of each
  answered call: its 40 ms G.711 payloads, in order, in the law of the call. Without
  `on_audio` the answer stays `a=sendonly`, as before.
- **The same socket** carries both directions: the one our SDP names, on which `Talkback`
  sends the microphone. What arrives on it goes to a `DoorSound`.
- **`DoorSound` is pure.** It keeps the packets of the door's addresses and of the payload type
  of the call, and drops a packet that comes again or behind one already handed on. It counts
  what it drops, by why. It has no jitter buffer: the player has one.
- **`RtpPacket`** reads a datagram (RFC 3550): the contributing sources, the header extension
  and the padding are skipped.

## Evidence (docs/DEVICE_FINDINGS.md, 2026-11-24)

- **With `sendrecv`, the door's audio stays in real time** (1.00) while we send our 40 ms
  bursts. It slows to 0.70 only when it receives 20 ms packets, which we never send.
- **Its packets:** 40 ms PCMU, a backlog of about 200 ms in the first 0.5 s, then a median gap
  of 33 ms. They arrive up to 106 ms late against their timestamps, so a player needs a jitter
  buffer of 100–120 ms. No packet was lost on the LAN.
- **Echo:** our own tones came back at least 40 dB lower: the door is half duplex, and a player
  should still mute the door while someone talks to it.
- **No keepalive is needed:** the door kept sending for the whole call without any RTP from us.

## Consequences

- **The library now receives RTP,** but only to hand it on: no jitter buffer, no decoding, no
  transcoding. A G.711 payload is decoded with a table, in the player.
- **A caller that plays the RTSP sound as well** must mute it during the call, or the visitor
  is heard twice.
- **The door sends about 64 kbit/s to us for the whole answered call,** whether someone listens
  or not.
