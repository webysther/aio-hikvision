# aiohikvision

[English](https://github.com/webysther/aio-hikvision/blob/main/README.md) · [中文](https://github.com/webysther/aio-hikvision/blob/main/README.zh-CN.md) · [Español](https://github.com/webysther/aio-hikvision/blob/main/README.es.md) · [Português](https://github.com/webysther/aio-hikvision/blob/main/README.pt-BR.md) · [Français](https://github.com/webysther/aio-hikvision/blob/main/README.fr.md) · [العربية](https://github.com/webysther/aio-hikvision/blob/main/README.ar.md) · [Русский](https://github.com/webysther/aio-hikvision/blob/main/README.ru.md) · **Deutsch** · [Italiano](https://github.com/webysther/aio-hikvision/blob/main/README.it.md)

Asyncio-Bibliothek für Hikvision-Geräte: Kameras, Rekorder und Türstationen über ISAPI
sowie die SIP-Anrufe von Video-Türstationen. Sie ist vollständig typisiert, hängt
nicht von Home Assistant ab und installiert nur die Teile, die du nutzt. Sie will die
eine Bibliothek sein, die die Hikvision-Projekte von Home Assistant brauchen; ihr
erster Nutzer ist
[Hikvision Virtual Indoor Station](https://github.com/webysther/ha-hikvision-virtual-indoor-station).

Jedes Gerät, dem sie bisher begegnet ist, funktioniert, weil jemand seinen Bericht
geschickt hat. Deins kann das nächste sein: Die Schritte unten dauern fünf Minuten.

## Dein Gerät, Schritt für Schritt

### 1. Installieren

```sh
pip install "aiohikvision[isapi]"
```

Python 3.13 oder neuer. Jeder Teil der Bibliothek ist ein Extra, und die
Standardinstallation hat keine Abhängigkeiten:

| Extra | Installiert | Wofür |
|---|---|---|
| (keins) | nichts | die Datenmodelle, wie sich Geräte unterscheiden (`behaviours`), die Fehlerklassen |
| `isapi` | aiohttp, yarl, defusedxml | `HikvisionClient`, `Device`, `DoorStation`: die HTTP-API der Geräte |
| `rtp` | noch nichts | RTP: das Mikrofon zur Türstation während eines Anrufs |
| `sip` | `[rtp]`, aiosipua | die SIP-Anrufe von Türstationen |
| `scrambling` | `[isapi]`, cryptography | verschlüsselte Program Streams von Aufzeichnungen |
| `all` | alles | |

Wird ein Teil ohne sein Extra verwendet, löst er `MissingExtra` aus, und die Meldung
sagt dir, was du installieren musst.

### 2. Lerne dein Gerät kennen

`aiohikvision.connect(...)` liest einmal und nur per GET, wer das Gerät
ist, was es kann und wie es sich verhält. Am Gerät ändert sich nichts.

```python
import asyncio
import os
from pathlib import Path

import aiohikvision


async def main() -> None:
    async with aiohikvision.connect(
        os.environ["DEVICE_HOST"],
        os.environ["DEVICE_USERNAME"],
        os.environ["DEVICE_PASSWORD"],
        port=int(os.environ.get("DEVICE_PORT", "80")),
    ) as hik:
        print(hik.name, "·", hik.model, hik.firmware, "·", hik.kind)
        print(hik.supports)
        print(hik.camera, await hik.camera.stream_url(credentials=False))
        Path("picture.jpg").write_bytes(await hik.camera.snapshot())


asyncio.run(main())
```

Auf einer DS-KD8003-Türstation gibt das Skript aus:

```text
Door Station · DS-KD8003-IME1(B) V3.7.3 build 260915 · door_station
Supports(snapshot=True, streaming=True, events=True, smart=False, ptz=False, two_way_audio=True, intercom=True, doors=True, holidays=False, inputs=4, outputs=2)
<Camera 1: 101, 102> rtsp://192.0.2.10:554/Streaming/Channels/101
```

Mit `aiohikvision.connect(..., session=session)` übergibst du die `aiohttp`-Session deiner Anwendung.
`hik.camera` listet die Streams des Geräts auf
(`camera.streams`), nimmt ein Bild auf (`snapshot()`) und liefert
die RTSP-Adresse jedes Streams (`stream_url()`).

### 3. Erstelle seinen Bericht

Der Bericht enthält alles, was die Bibliothek vom Gerät liest, und was sie daraus
macht: seine Dokumente, **anonymisiert** (ohne Konto, Adresse, Seriennummer, MAC oder
von dir vergebene Namen), die Domänen, die es anbietet, und wie die Bibliothek jede
davon abdeckt, die Verhaltensweisen (behaviours), die sie verwendet, und warum, und
was sie nicht erkannt hat. Im Terminal:

```sh
export AIOHIKVISION_PASSWORD='the password'   # or leave it out to be asked
python -m aiohikvision report 192.0.2.10 --username admin
```

```text
DS-KD8003-IME1(B) V3.7.3 build 260915 (VIS)
Domains: streaming (service), events (door_station), io (door_station), video_intercom (door_station), access_control (door_station), two_way_audio (door_station)
  talk_packet: 40ms (rule)
  alert_stream: multipart (default)
  call_status: advertised (default)
  triggers: event_triggers (default)
Report written to aiohikvision-report-DS-KD8003-IME1-B.json: read it, then attach it to https://github.com/webysther/aio-hikvision/issues/new?template=device_report.yml
```

Die Zeilen mit `!` zeigen, was der Bibliothek für dein Gerät fehlt: Werte, die sie
nicht erkennt, Dokumente, deren Abruf fehlgeschlagen ist, oder eine fehlende Regel für
dein Modell und deine Firmware. In deinem eigenen Code liefert `await hik.report()`
denselben Bericht (`report.to_json()`).

### 4. Schick ihn ab

Lies die Datei zuerst: Sie sollte nichts über dein Zuhause enthalten, und du kannst
alles entfernen, was du lieber nicht teilen möchtest. Dann
[eröffne einen Gerätebericht](https://github.com/webysther/aio-hikvision/issues/new?template=device_report.yml),
hänge die Datei an und schreib, was funktioniert und was nicht. Aus einem Bericht
werden ein Test-Fixture, eine Regel für dein Modell und deine Firmware und die
Dienste, die dein Gerät braucht: So wird die Bibliothek für jedes Gerät auf dieselbe
Weise besser.

### 5. Wenn etwas schiefgeht

Das Debug-Log der Bibliothek ist kurz und sagt, was wichtig ist, und zwar nur einmal:

```python
import logging

logging.basicConfig()
logging.getLogger("aiohikvision").setLevel(logging.DEBUG)
```

- wie das Gerät erkannt wurde: sein Modell und seine Firmware, die Domänen, die es
  anbietet, und wie jede abgedeckt ist, die Verhaltensweisen, die von den
  Standardwerten abweichen, und die Regel, die sie festgelegt hat;
- seine Streams, wenn sie zum ersten Mal gelesen werden und wenn sie sich ändern;
- jede fehlschlagende Anfrage, beim ersten Mal und wenn das Gerät wieder antwortet;
  keine Zeile für Anfragen, die funktionieren.

Hänge dieses Log zusammen mit dem Bericht an das Issue an. Wähle in Home Assistant bei
der Integration **Debug-Protokoll aktivieren** (Enable debug logging): Das Log der
Bibliothek wird dann mit aufgezeichnet.

Der Rest der Dokumentation – wie sich Geräte unterscheiden (Verhaltensweisen und
Regeln), Türstationen, ihre Anrufe über SIP und die Entwicklung – steht im
[englischen README](https://github.com/webysther/aio-hikvision/blob/main/README.md).
