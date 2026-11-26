# Assets of sip_probe.py

Made once with `make_assets.py` (ffmpeg with libopus, libx264 and drawtext):

- `opus_tone.bin`: the probe's soft test sound (440 Hz 1 s, pause, 880 Hz 1 s, pause) encoded by
  libopus at 16 kHz mono, 40 ms frames, `-application voip`, 32 kbit/s. Each packet is stored as a
  2-byte big-endian length and its bytes. The `opus` step sends them every 40 ms with the RTP
  timestamp +320, as the KD8003 packs its own Opus.
- `door_name.h264`: 4 s of a dark picture with "REDACTED" in white, 640x480 at 10 fps,
  H.264 Constrained Baseline level 3.0, IDR every second with SPS/PPS before each, no B-frames.
  The `vout` step sends it in a loop to see whether the door station's screen shows our video.
