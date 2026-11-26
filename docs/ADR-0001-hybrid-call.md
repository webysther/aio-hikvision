# ADR 0001: The call over SIP, the door's picture and sound over RTSP

- **Status:** accepted, 2026-11-24
- **Device:** DS-KD8003-IME1(B), firmware V3.7.3 build260915, in standard-SIP mode (VoIP1
  registered to Home Assistant)

## Context

Home Assistant has to act as the door station's indoor station. It must make the door ring, let
someone answer and hang up, and let both sides talk while showing the visitor.

We know four things about the door:

- **Talking through ISAPI only works outside a call.** ISAPI two-way audio plus RTSP works
  perfectly when no call is up, which is how the integration's card works today. But the door
  only "calls" when it has a callee. Without one, its screen shows nothing and it beeps "busy";
  without SIP, the only callee left is the Hik-Connect cloud. While a SIP call rings or is
  answered, ISAPI two-way audio does not reach the speaker.
- **Its SIP media is fragile.** It sends 40 ms packets and slows its own audio to 0.7 of real
  time if it receives 20 ms ones. Its Opus and G.722.1 are non-standard. Its 1080p keyframes are
  ~155 RTP packets long.
- **It is half duplex.** It plays what it receives and its echo canceller removes that from its
  microphone.

## Decision

The design is hybrid: the call goes over SIP, and the door's picture and sound come over RTSP.

- **SIP carries the call itself.**
  - Home Assistant is the door's SIP server (registrar) and the callee.
  - Ringing is 180, answering is 200 OK, hanging up is BYE, and rejecting is 486.
  - The door's screen shows the called number's name and the call timer.
- **SIP also carries the microphone, Home Assistant to the door, during a call.**
  - The answer has audio `a=sendonly` with PCMU and `a=ptime:40`, and `m=video 0`.
  - The packets are 40 ms each: two 20 ms G.711 frames from the browser are joined, with no
    transcoding. They are sent on an absolute clock, in bursts when someone presses to talk, and
    nothing is sent in silence.
- **RTSP carries the door's picture and sound, the door to Home Assistant,** exactly as the live
  card plays them today.
- **Outside a call** (monitoring), audio from Home Assistant uses ISAPI two-way audio, as today.

## Evidence (2026-11-24)

- **Calls placed by Home Assistant to the door** (runs `20261124-152254` and `20261124-152912`):
  - With an audio-only offer marked `a=sendonly`, the door answered with 200, sent **no RTP** to
    Home Assistant, and played our 40 ms bursts.
  - With `sendrecv`, its own audio stayed at 1.00 while we sent the bursts.
  - The RTSP audio kept arriving at 1.00 throughout both calls; the longest gap was 0.19 s.
  - Its answer said `sendrecv` and added a video m-line we never offered, but it honoured
    `sendonly` anyway.
- **A call from the button** (run `20261124-153248`):
  - 180, then the 200 answer marked `sendonly` with `m=video 0`, 8 tone bursts of 2 s (400
    packets of 40 ms), then BYE after 30 s.
  - The visitor heard the bursts, and the screen showed the name and the call timer.
  - RTSP carried 55 s of audio in 55 s.
  - The door's echo canceller kept the tone out of its microphone audio.
  - A 486 showed "busy".
- **Still to confirm:** a visitor's voice over RTSP during a call. Only ambient noise was recorded,
  so this goes into the first trip with the real implementation.

## Consequences

- **What the library needs:** the registrar, the call state machine and a 40 ms send-only RTP
  sender. It needs no RTP receiving, no jitter buffer, no SIP video and no codec negotiation
  beyond G.711.
- **Push-to-talk is the natural mode,** because the door is half duplex. A peer that sends audio
  all the time cuts the visitor off. That is what users of a generic SIP softphone heard.
- **The door's `talkTime` limit still applies:** it hangs up at 90 s by default, and the setting
  can be raised up to 1800 s.
- **If RTSP ever fails during calls,** the fallback is to answer `sendrecv` and play the door's RTP
  in the browser.
