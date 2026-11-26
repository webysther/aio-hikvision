"""Make the probe's assets with ffmpeg: its soft test sound as Opus packets, a still H.264 clip with a name.

Run from anywhere: python make_assets.py <work folder> <this folder>
"""

import math
import struct
import subprocess
import sys
from pathlib import Path

work, assets = Path(sys.argv[1]), Path(sys.argv[2])
RATE = 8000

# The probe's default test sound (test_sound(None)): 440 Hz 1 s, 0.5 s pause, 880 Hz 1 s, 1.5 s pause
samples = []
for frequency, seconds in [(440, 1.0), (0, 0.5), (880, 1.0), (0, 1.5)]:
    for n in range(int(seconds * RATE)):
        samples.append(int(3000 * math.sin(2 * math.pi * frequency * n / RATE)) if frequency else 0)
(work / "tone.raw").write_bytes(struct.pack(f"<{len(samples)}h", *samples))
subprocess.run(
    [
        "ffmpeg",
        "-v",
        "error",
        "-y",
        "-f",
        "s16le",
        "-ar",
        "8000",
        "-ac",
        "1",
        "-i",
        str(work / "tone.raw"),
        "-ar",
        "16000",
        "-c:a",
        "libopus",
        "-application",
        "voip",
        "-frame_duration",
        "40",
        "-b:a",
        "32k",
        str(work / "tone.ogg"),
    ],
    check=True,
)


def ogg_packets(data: bytes):
    """Packets of an Ogg stream, joined across lacing (one logical stream)."""
    position, packet = 0, b""
    while position < len(data):
        assert data[position : position + 4] == b"OggS", "not an Ogg page"
        segments = data[position + 26]
        table = data[position + 27 : position + 27 + segments]
        body = position + 27 + segments
        for size in table:
            packet += data[body : body + size]
            body += size
            if size < 255:
                yield packet
                packet = b""
        position = body


packets = [
    p for p in ogg_packets((work / "tone.ogg").read_bytes()) if not p.startswith((b"OpusHead", b"OpusTags"))
]
with (assets / "opus_tone.bin").open("wb") as out:
    for packet in packets:
        out.write(len(packet).to_bytes(2, "big") + packet)
configs = sorted({p[0] >> 3 for p in packets})
sizes = sorted(map(len, packets))
print(f"opus_tone.bin: {len(packets)} packets, TOC configs {configs}, sizes {sizes[0]}-{sizes[-1]} B")

font = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
text = f"drawtext=fontfile={font}:text='REDACTED':fontcolor=white:fontsize=48:x=(w-text_w)/2:y=(h-text_h)/2"
subprocess.run(
    [
        "ffmpeg",
        "-v",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "color=c=0x1e293b:s=640x480:r=10:d=4",
        "-vf",
        text,
        "-c:v",
        "libx264",
        "-profile:v",
        "baseline",
        "-level",
        "3.0",
        "-pix_fmt",
        "yuv420p",
        "-bf",
        "0",
        "-g",
        "10",
        "-keyint_min",
        "10",
        "-sc_threshold",
        "0",
        "-x264-params",
        "repeat-headers=1:aud=0",
        "-f",
        "h264",
        str(assets / "door_name.h264"),
    ],
    check=True,
)
print("door_name.h264:", (assets / "door_name.h264").stat().st_size, "bytes")
