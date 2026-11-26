# Hikvision DS-KD8003 over peer-to-peer SIP: measured behaviour

What a Hikvision door station really does when it calls a SIP peer directly (no PBX, no
registration), measured from real traffic. Each answer comes from a capture, not from a
datasheet, and the facts still being tested are marked as open.

- **Device:** DS-KD8003-IME1(B), firmware V3.7.1 build250819, with a touch-screen module and an
  access module. A Synology NVR also records its RTSP stream.
- **Peer:** a Home Assistant host on the same LAN. The probe ran in a Docker container with host
  networking.
- **Tool:** `scripts/sip_probe.py` (aiosipua 0.7.1, aiortp 0.8.0). It logs every SIP message raw
  and records the door's audio (WAV) and video (Annex B H.264). It also keeps the arrival time of
  every audio RTP packet (CSV) and a summary per call.
- **Data:** 27 calls from the door and 5 calls to the door, on 2026-11-24. The captures are in
  `captures/<run>/call-NN-HHMMSS/` (see the [call log](#call-log)).
- **Addresses:** masked as `<door-ip>` (the door station) and `<ha-ip>` (the peer, Home Assistant). The screen
  messages are given in English, as the English UI words them.

## The short version

1. **The door calls the peer directly.** It sends an INVITE over UDP to the configured IP and
   port. The INVITE carries no called number, so two P2P numbers on the same IP and port can't be
   told apart.
2. **Send 40 ms audio packets, never 20 ms.** The door always sends 40 ms packets. While it
   *receives* 20 ms packets, its own audio slows to about 2/3 of real time. It never catches up
   and builds 6 to 9 s of delay in 20 to 30 s. With 40 ms packets, or with no packets at all, the
   whole stream arrives with about 30 ms of jitter.
3. **The video is 720p30 H.264 Baseline at level 5.0**, with an IDR every 2 s, at about
   1.85 Mbit/s. The SDP says level 3.1 (`42801F`).
4. **The ring lasts as long as the Call Priority entry (60 s here)**, then the door sends CANCEL.
   A call lasts at most `talkTime` (90 s by default): the door sent BYE at 90.0 s.
5. **486 and 603 both show "busy".** For button calls, the screen shows the peer's IP and ignores
   any display name the peer sends.
6. **ISAPI two-way audio does not reach the speaker during a SIP call.** While a call is up,
   talking must go over the call's RTP.
7. **The peer can call the door, but only with an INVITE shaped like the door's own.** Then the
   door answers by itself in 1 s, silently: nothing rings and nothing shows on its screen. It
   sends audio and video, and announces its lock count in a SIP `MESSAGE`. Four other INVITEs got
   `400 Bad Request`.
8. **The door's Opus is real wideband speech** that standard libopus decodes. Its RTP timestamps,
   like G.722.1's, advance at half the declared clock.

## Door configuration

Settings from the web UI (V3.7.1, English), with the ISAPI resources behind them:

| Setting | Where | ISAPI |
|---|---|---|
| P2P SIP on, VoIP gateway off | System and Maintenance → Network → Device Access → VoIP | `GET /ISAPI/System/Network/SIP/SIPMgr/SIPP2PParams?format=json` → `{"enabled": true}`; the standard SIP servers in `/ISAPI/System/Network/SIP` stay disabled |
| P2P number: call number 1 → `<ha-ip>:5060` | Video Intercom → Number Settings → P2P No. Configuration | `.../SIPMgr/{Search,Add,Modify,Delete}SIPP2PCallInfo?format=json`; capabilities: up to 64 entries, `callNumber` 1–9999, IPv4 only, any port (default 5060) |
| Call Priority 1 = Telephone Gateway (VoIP), 60 s | Video Intercom → Call Priority | `/ISAPI/VideoIntercom/callPriority?format=json`; the other targets are the platform (Hik-Connect) and indoor stations |
| Time limits | Video Intercom → time parameters | `GET /ISAPI/VideoIntercom/operationTime`: `talkTime` 90 s (90–1800), `maxRingTime` 65 s (65–255), `messageTime` 30 s (30–60) |

The device ID is `GET /ISAPI/VideoIntercom/deviceId`: unit type outdoor, period, building, unit
and floor 1, index 0.

The `customInfo` field of a call button in `keyCfg` (0–32 characters) labels the virtual call
buttons on the touch screen's "Press Button to Call" page. Whether it also renames the physical
button's call is not tested.

## Signalling

A button press sends this INVITE. Calls started from the contact list on the screen look the
same:

```
INVITE sip:<ha-ip>:5060 SIP/2.0
Via: SIP/2.0/UDP <door-ip>:5060;rport;branch=z9hG4bK560374968
From: <sip:<door-ip>>;tag=387900620
To: <sip:<ha-ip>:5060>
Call-ID: 2124082855
CSeq: 20 INVITE
Contact: <sip:<door-ip>:5060>
Content-Type: application/sdp
Max-Forwards: 70
User-Agent: HKVS/2.0
Subject: This is a call for conversation
```

- **Request-URI and To:** both are the configured target, without the P2P call number. A peer
  that serves several numbers needs one port (or address) per number.
- **From:** it has no user part. The door uses UDP and asks for `rport`.
- **Missing headers:** the INVITE has no `Supported`, `Allow` or `Session-Expires` header, so the
  door uses no reliable provisionals and no session timers.

**Call outcomes**, as seen from the peer and on the door's screen:

| Peer does | Door does | Visitor sees or hears |
|---|---|---|
| `180 Ringing` and waits | sends CANCEL after 60.2 s (the Call Priority time) | a ringback tone; then "No answer." |
| `486 Busy Here` or `603 Decline` | ACKs | "The called user is busy." for both codes |
| `200 OK` | ACKs about 0.3 s later; its media starts 0.4–1.1 s after the 200 OK | talk |
| BYE | 200 OK | "Call ended." |
| nothing listening on the target | — | "no answer" |
| — | the visitor cancels while it rings: CANCEL | — |
| — | the visitor ends the call: BYE | — |
| — | the visitor presses the call button during a call: BYE, then a new INVITE about 1 s later | — |

- **The screen shows the peer's IP.** A button call shows "<ha-ip> Call started". A
  display name in `P-Asserted-Identity` or `Remote-Party-ID` on our 180/200 changes nothing. A
  call started from the screen's contact list shows the contact's name instead.
- **The old bell still rings.** The bell wired to output 2 (an output linkage) rings in SIP mode
  too.

### Calling the door from the peer

Each variant adds one change to the one before it:

| Variant | INVITE | Door's answers |
|---|---|---|
| first try | R-URI `sip:<door-ip>`, From `sip:probe@<ha-ip>`, `Supported: 100rel`, audio-only PCMU offer | 100, 101, 400 |
| + Subject | adds `Subject: This is a call for conversation` | 100, 101, 400 |
| + video | adds a video m-line (H.264 PT 96, the door's fmtp, recvonly) | 100, 101, 400 |
| + number | From `<sip:1@<ha-ip>:5060>` (the P2P call number of this address) | 100, 101, 400 |
| **mirror** | the door's own INVITE: R-URI and To `sip:<door-ip>:5060`, From `<sip:<ha-ip>>`, `User-Agent: HKVS/2.0`, no `Supported`, offer PCMU and PCMA with ptime 40, video sendrecv, `s=Talk session` | 100, 101, **180** after 48 ms, an in-dialog `MESSAGE`, **200 OK** 1.0 s after the 180 |

The refusals look like this:

```
SIP/2.0 100 Trying
SIP/2.0 101 Dialog Establishement      (with a To tag: not a standard status code)
SIP/2.0 400 Bad Request                (20 ms later, no Warning or reason)
```

So the door parses the request, builds a dialog and then rejects something in it. The mirrored
INVITE was answered by the door itself, with nobody touching it. Nothing at the door showed it:
no ring, nothing on the screen, no video. A visitor standing there only heard the peer's short
test sound from the speaker. It behaves like an indoor station monitoring the door, not like a
call. The refused variants left no trace at the door. Its audio arrived at full rate
(14.6 s in 15 s) and so did its video. Which change of the mirror matters is not tested yet. The
candidates are the port in the R-URI, the From without a user part, the User-Agent, the missing
`Supported`, PCMA in the offer, and video `sendrecv`.

Right after its 180, the door sends this in the dialog:

```
MESSAGE sip:<ha-ip>:5060 SIP/2.0
CSeq: 2 MESSAGE
Content-Type: text/plain

<locknumXML>
<lockNum>1</lockNum>
</locknumXML>
```

Its 200 OK carries the same fact in the SDP, as a session-level `a=lockNum:1`:

```
v=0
o=FX0000000 0 0 IN IP4 <door-ip>        (user part redacted)
s=Talk session
c=IN IP4 <door-ip>
t=0 0
a=lockNum:1
m=audio 9654 RTP/AVP 0
a=rtpmap:0 PCMU/8000
a=rtpmap:101 telephone-event/8000
a=fmtp:101 0-16
a=sendrecv
m=video 9856 RTP/AVP 96
a=rtpmap:96 H264/90000
a=fmtp:96 profile-level-id=42801F;packetization-mode=1
a=sendrecv
```

- **What the MESSAGE is for:** it is presumably what an indoor station uses to draw its unlock
  buttons. The door sent it only when it was the one called; it never sent one in its own 27
  calls.
- **Our reply to it:** the probe answered `405 Method Not Allowed`, and the door went on anyway.
  A peer should answer 200.
- **A quirk in the answer:** telephone-event 101 has an rtpmap but is missing from the `m=` line.

### Early media

Here the peer answered the INVITE with 180, then `183 Session Progress` with its SDP 3 s later,
and sent audio until the 200 OK 8 s after that. The door sent no RTP, audio or video, before the
200. At the door, the ringback stopped when the 183 arrived. The visitor did not report hearing
the peer's tones before the answer.

## SDP offer

```
v=0
o=FX0000000 0 0 IN IP4 <door-ip>        (user part redacted)
s=Talk session
c=IN IP4 <door-ip>
t=0 0
m=audio 9654 RTP/AVP 98 115 0 8 103 104 100 18 101
a=rtpmap:98 G7221/16000
a=rtpmap:115 OPUS/16000
a=rtpmap:0 PCMU/8000
a=rtpmap:8 PCMA/8000
a=rtpmap:103 G726-32/8000
a=rtpmap:104 MP4A-LATM/16000
a=rtpmap:100 MP4A-LATM/16000
a=rtpmap:18 G729/8000
a=rtpmap:101 telephone-event/8000
a=fmtp:101 0-16
a=sendrecv
m=video 9856 RTP/AVP 96
a=rtpmap:96 H264/90000
a=fmtp:96 profile-level-id=42801F;packetization-mode=1
a=sendrecv
```

- **No `a=ptime`.** The offer says nothing about packet size, yet the door always sends 40 ms
  packets.
- **Two `MP4A-LATM/16000` entries** (PT 104 and 100), neither with an fmtp line.
- **The video fmtp understates the stream.** `42801F` means Baseline, level 3.1, but the stream
  is level 5.0. Adding `max-fs=3600;max-mbps=108000` to our answer did not change it.
- **Our working answer:** PCMU plus telephone-event with `a=ptime:40`, and video `recvonly` (we
  don't send video).

## Audio

### The 40 ms rule

The door's own audio (its microphone, toward the peer) depends on the packet size the peer
sends back:

| Run / call | Peer sends | Door audio arriving | Delay built up |
|---|---|---|---|
| 080131 / 01 | 20 ms PCMU (aiortp's pacer), 30 s | 0.67 (20.2 s of 30) | 9.2 s |
| 080131 / 02 | same | 0.67 | 9.4 s |
| 082421 / 01 | 20 ms PCMU, no video | 0.70 | 7.2 s |
| 082421 / 02 | 20 ms PCMU, with video | 0.67 | 7.1 s |
| 082421 / 03 | 20 ms PCMU, video limited to 720p | 0.69 | 6.5 s |
| 083224 / 01 | **40 ms PCMU (own clock)**, no video | **1.01** | 0.2 s at start, then ≤ 31 ms (p90) |
| 083224 / 02 | **nothing** (Opus answer) | **1.00** | 43 ms max |
| 083224 / 03 | **nothing** (G.722.1 answer) | **1.00** | 64 ms max |
| 084345 / 01 | **40 ms PCMU**, with video, visitor speaking | **1.00** (742 packets, 0 lost) | 47 ms (p99) |
| 090953 / 07 | **20 ms PCMU on our own clock** | **0.70** | 6.0 s |
| 090953 / 09 | 40 ms PCMU, with video, 90 s | 1.00 (2240 packets) | 66 ms max |

*Door audio arriving* counts the audio packets received against the wall-clock time; *delay
built up* is how far a packet arrived behind its own RTP timestamp. Both come from the raw RTP
tap (`audio_rtp.csv`). The earlier runs 071511 and 072908 were measured only from the decoded
audio, and they agree: 0.61 and 0.65.

- **What triggers it:** receiving 20 ms packets, whatever paces them. With 20 ms packets on the
  probe's own clock (090953 / 07) the door fell to 0.70 again. The answers in 083224 / 02 and 03
  said `ptime:20` too, but the peer sent nothing there, and the door kept real time.
- **Video, network loss and the peer's jitter buffer are ruled out.** The slowdown is the same
  with and without video, no packet is lost, and frames delivered match packets received.
- **How the slowdown sounds:** choppy, as if chunks of the visitor's sound were missing, with a
  delay that keeps growing.

**With 40 ms packets:**

- **The start comes in a burst.** About 200 ms of backlog arrives in the first 0.5 s, then the
  stream is steady.
- **Inter-arrival times:** median 33 ms, p90 65 ms, max 73–109 ms (the door alternates short and
  long gaps). Packets arrive at most 31 ms (p90) to 106 ms late against their timestamps, so a
  100–120 ms jitter buffer is enough.
- **Levels:** a visitor speaking normally reaches about −24 dBFS (median), with no clipping. The
  background before they spoke was about −51 dBFS. That is ambient noise at the installation
  site, not the device.
- **Echo:** our own test tones (−12 dBFS) came back in the door's audio at least 40 dB lower.
- **The peer's audio reaches the speaker:** the visitor heard the peer's G.711 test tones on the
  door's speaker.
- **No keepalive is needed:** without any RTP from the peer, the door kept sending for the whole
  call (20 s measured).

### The 16 kHz codecs

Both 16 kHz codecs keep 40 ms packets and the real-time rate, but their RTP timestamps advance
320 per packet. That is an 8 kHz pace, although the rtpmap declares 16000:

| Codec (PT) | Payload | Bitrate | Notes |
|---|---|---|---|
| Opus (115) | 293–300 bytes: one 40 ms SILK wideband frame (TOC config 10, in all 493 packets) | ~60 kbit/s | Standard libopus (ffmpeg) decodes it to clean wideband speech, about 10% of whose energy is above 4 kHz. RFC 7587 requires `opus/48000/2` and a 48 kHz clock, so a receiver that times Opus by its RTP timestamps gets it wrong. Whether the door plays Opus from the peer is still open |
| G.722.1 (98) | 160 bytes = two 20 ms frames at 32 kbit/s | 32 kbit/s | Recorded only, not decoded |

### ISAPI two-way audio

This is how the bridge's microphone works today, outside SIP calls:

1. `GET /ISAPI/System/TwoWayAudio/channels` lists channel 1 as G.711ulaw, with
   `enabled=false` even while it works.
2. `PUT .../channels/1/close`, then `PUT .../open`, which may return a `sessionId`.
3. `PUT .../audioData` with `Content-Length: 0`, followed by raw G.711 on the same socket.

Outside a call this works. During a SIP call, audio sent this way did not come out of the
speaker. One related note: a sized snapshot request was once refused while two-way audio was
open, so it is better to retry than to fall back to the default size.

## Video

- **Format:** H.264 Baseline, 1280×720, about 30 fps (886 frames in 29.6 s), level 5.0,
  packetization mode 1, at about 1.85 Mbit/s.
- **IDR every 2 s:** 15 IDR frames in 30 s, each with an SPS and PPS before it.
- **The stream starts in the middle of a GOP.** A decoder reports a missing PPS until the first
  IDR, so a receiver waits up to 2 s for a picture.
- **The first video packet arrives 75–430 ms after our 200 OK,** sometimes before the door's ACK.
- **No video to the door:** the peer answered `sendrecv` and sent 200 frames of a name card
  (640×480, 10 fps), but the screen kept showing only the peer's IP.
- **The SIP video is its own encoding.** It is not the RTSP main or sub stream, and limiting
  `max-fs` in the answer still gives 720p. The `streamSwitch` setting chooses the camera source
  (the local camera or USB), not main or sub.

## ISAPI during SIP calls

- **`callStatus` follows the SIP call:** `ringing` → `on_call` → `idle`.
- **The doorbell event fires** on a SIP call, as it does on any other call.
- **The output linkage (old bell) still works** in SIP mode.

## What this means for a SIP peer (Home Assistant)

1. **Listening:** listen on UDP at the configured port, accept INVITEs without a user part and
   answer `180` at once (the visitor then hears a ringback). Answer before the Call Priority time
   (60 s here), or the door cancels.
2. **Audio:** answer G.711 with `a=ptime:40` and send exactly one 40 ms packet every 40 ms from
   your own clock (aiortp's pacer only does 20 ms). There is no need to send anything to keep the
   door's audio flowing.
3. **Jitter buffer:** about 120 ms, and expect a burst at the start.
4. **Video:** pass the H.264 through as is (720p30 Baseline plays in browsers). Wait for the first
   IDR and ignore the level in the SDP.
5. **Talk limit:** the door sends BYE after `talkTime` (90 s by default, up to 1800 s through
   ISAPI `operationTime`).
6. **Microphone during a call:** it must feed the call's RTP, not ISAPI two-way audio.
7. **Rejecting:** 486 and 603 give the same "busy" screen.
8. **Several P2P numbers** need one port or address each.
9. **Codec:** G.711 is the simple start. Opus is the quality upgrade: it decodes with standard
   libopus and carries wideband speech, but its RTP timestamps need rewriting, since they
   advance at 8 kHz.
10. **Calling the door:** send an INVITE shaped like the door's own (see above). The door answers by
    itself in about 1 s, silently, with audio and video, so it is a way to listen and talk at
    the door from the peer, not to make the door ring. Answer its `MESSAGE` with 200.

## Still open

- **Calls to the door:** which change of the mirrored INVITE the door needs. This can be tested
  one change at a time, with nobody at the door.
- **Early media:** the ringback stops at the 183, but did the door play the peer's audio then?
- **Opus from the peer:** the door received 101 Opus packets (40 ms each, timestamps +320). Did it
  play them?
- **The microphone's 20 ms frames:** ISAPI talk sends 20 ms G.711 frames, and they may slow the
  door's RTSP audio the same way. With the microphone off, RTSP audio arrives at 1.00, in
  320-byte (40 ms) packets.
- **Unlocking over SIP:** the door announces one lock, but how an indoor station opens it during
  a call is not tested. The integration opens the lock through ISAPI.

## Call log

All calls of 2026-11-24. "Rate" is the door's audio arriving per second of call.

| Run | Call | Step | Result |
|---|---|---|---|
| 064755 | 01–02 | answer + video, 20 ms (probe's jitter buffer not yet fixed) | the visitor pressed the button again after 24 s: BYE and a new call 1 s later, which ended after 11.3 s with 6.1 s of audio (only its summary was kept) |
| 071511 | 01 | answer + video, 20 ms, 30 s | 18.2 s of audio in 30 s (0.61); we hung up |
| 072908 | 01 | answer + video, 20 ms, 40 s | 26.0 s in 40 s (0.65); we hung up |
| 072908 | 02 | ring | door CANCEL after 60.2 s |
| 072908 | 03 | reject 486 | "busy" |
| 072908 | 04 | reject 603 | "busy" |
| 072908 | 05 | answer + video, 20 ms | visitor hung up after 16.2 s |
| 080131 | 01–02 | answer + video + display name, 20 ms, 30 s | rate 0.67; delay up to 9.4 s; name not shown |
| 080131 | 03 | ring + display name | CANCEL after 60.2 s |
| 080131 | 04 | reject 486 | "busy" |
| 080131 | 05–06 | answer | visitor hung up after 3.8 s and 4.5 s |
| 080131 | 07 | ring | visitor cancelled after 12 s |
| 082421 | 01 | audio only, 20 ms | rate 0.70 |
| 082421 | 02 | answer + video, 20 ms | rate 0.67 |
| 082421 | 03 | answer + video with `max-fs` (720p), 20 ms | rate 0.69; video still 1280×720 |
| 083224 | 01 | audio only, `ptime:40`, 40 ms packets | rate 1.01 |
| 083224 | 02 | Opus answer, nothing sent | rate 1.00 (by Opus frames) |
| 083224 | 03 | G.722.1 answer, nothing sent | rate 1.00 (by packet interval) |
| 084345 | 01 | answer + video, 40 ms, visitor speaking, 30 s | rate 1.00, 742 packets, 0 lost; 886 video frames |
| 085213 | — | peer calls the door (audio only, no Subject) | 100, 101 "Dialog Establishement", 400 Bad Request |
| 090953 | 01 | Opus answer; the peer sends its tone as Opus | rate 1.00; SILK WB 40 ms; decodes with libopus |
| 090953 | 02 | peer calls the door: + Subject | 400 |
| 090953 | 03 | peer calls the door: + video | 400 |
| 090953 | 04 | peer calls the door: + From with call number 1 | 400 |
| 090953 | 05 | peer calls the door: mirror of the door's INVITE | 180, MESSAGE lockNum 1, 200 OK after 1 s; 15 s of talk, audio 1.00, video; at the door, only the short test sound |
| 090953 | 06 | 180, then 183 with SDP for 8 s, then 200 OK | the ringback stopped at the 183; no RTP from the door before the 200; rate 1.00 after it |
| 090953 | 07 | 20 ms PCMU on our own clock | rate 0.70, delay up to 6.0 s |
| 090953 | 08 | answer `sendrecv`; the peer sends a name card as H.264 | rate 1.01; 200 frames sent; the screen showed only the IP |
| 090953 | 09 | answer + video, never hang up | the door sent BYE at 90.0 s; rate 1.00 throughout |
