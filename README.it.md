# aiohikvision

[English](https://github.com/webysther/aio-hikvision/blob/main/README.md) · [中文](https://github.com/webysther/aio-hikvision/blob/main/README.zh-CN.md) · [Español](https://github.com/webysther/aio-hikvision/blob/main/README.es.md) · [Português](https://github.com/webysther/aio-hikvision/blob/main/README.pt-BR.md) · [Français](https://github.com/webysther/aio-hikvision/blob/main/README.fr.md) · [العربية](https://github.com/webysther/aio-hikvision/blob/main/README.ar.md) · [Русский](https://github.com/webysther/aio-hikvision/blob/main/README.ru.md) · [Deutsch](https://github.com/webysther/aio-hikvision/blob/main/README.de.md) · **Italiano**

Libreria asyncio per i dispositivi Hikvision: telecamere, videoregistratori e citofoni
via ISAPI, e le chiamate SIP dei videocitofoni. È completamente tipizzata, non dipende
da Home Assistant e installa solo le parti che usi. Punta a essere l'unica libreria di
cui hanno bisogno i progetti Hikvision di Home Assistant; la prima a usarla è
[Hikvision Virtual Indoor Station](https://github.com/webysther/ha-hikvision-virtual-indoor-station).

Ogni dispositivo che ha incontrato funziona perché qualcuno ne ha inviato il rapporto.
Il tuo può essere il prossimo: i passi qui sotto richiedono cinque minuti.

## Il tuo dispositivo, passo dopo passo

### 1. Installa

```sh
pip install "aiohikvision[isapi]"
```

Python 3.13 o più recente. Ogni parte della libreria è un extra, e l'installazione
predefinita non ha alcuna dipendenza:

| Extra | Installa | Per |
|---|---|---|
| (nessuno) | niente | i modelli, come differiscono i dispositivi (`behaviours`), gli errori |
| `isapi` | aiohttp, yarl, defusedxml | `HikvisionClient`, `Device`, `DoorStation`: l'API HTTP dei dispositivi |
| `rtp` | ancora niente | RTP: il microfono verso il citofono durante una chiamata |
| `sip` | `[rtp]`, aiosipua | le chiamate SIP dei citofoni |
| `scrambling` | `[isapi]`, cryptography | i flussi di programma cifrati delle registrazioni |
| `all` | tutto | |

Una parte usata senza il suo extra solleva `MissingExtra`, che dice cosa installare.

### 2. Conosci il tuo dispositivo

`HikvisionClient(session).connect(...)` legge, una sola volta e solo con GET, chi è il
dispositivo, cosa sa fare e come si comporta. Sul dispositivo non cambia nulla.

```python
import asyncio
import os

from aiohikvision import HikvisionClient


async def main() -> None:
    async with HikvisionClient() as client:
        device = await client.connect(
            os.environ["DEVICE_HOST"],
            os.environ["DEVICE_USERNAME"],
            os.environ["DEVICE_PASSWORD"],
            port=int(os.environ.get("DEVICE_PORT", "80")),
        )
        print(device.identity.model, device.identity.firmware)
        print("Domains:", ", ".join(device.capabilities.domains))
        print("Talk packets:", device.behaviours.talk_packet)


asyncio.run(main())
```

Su un citofono DS-KD8003 stampa:

```text
DS-KD8003-IME1(B) V3.7.3 build 260915
Domains: streaming, events, io, video_intercom, access_control, two_way_audio
Talk packets: 40ms
```

Passagli la sessione `aiohttp` della tua applicazione con `HikvisionClient(session)`.
`device.streaming` elenca i suoi flussi (`await device.streaming.streams()`), scatta
una foto (`snapshot()`) e dà l'indirizzo RTSP di ciascuno (`rtsp_url()`).

### 3. Genera il suo rapporto

Il rapporto è tutto ciò che la libreria legge del dispositivo e ciò che ne ricava: i
suoi documenti, **anonimizzati** (niente account, indirizzo, numero di serie, MAC né i
nomi che gli hai dato), i domini che mostra e come la libreria copre ciascuno, i
comportamenti che usa e perché, e ciò che non ha riconosciuto. Da un terminale:

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

Le righe con `!` sono ciò che manca alla libreria per il tuo dispositivo: valori che
non riconosce, documenti che non è riuscita a leggere, o la mancanza di una regola per
il tuo modello e firmware. Nel tuo codice, `await device.report()` restituisce lo
stesso rapporto (`report.to_json()`).

### 4. Invialo

Leggi prima il file: non dovrebbe contenere nulla di casa tua, e puoi togliere tutto
ciò che preferisci non condividere. Poi
[apri un rapporto del dispositivo](https://github.com/webysther/aio-hikvision/issues/new?template=device_report.yml),
allegalo e racconta cosa funziona e cosa no. Un rapporto diventa una fixture dei test,
una regola per il tuo modello e firmware, e i servizi di cui ha bisogno il tuo
dispositivo: la libreria migliora allo stesso modo per ogni dispositivo.

### 5. Quando qualcosa va storto

Il log di debug della libreria è breve e dice ciò che conta, una volta sola:

```python
import logging

logging.basicConfig()
logging.getLogger("aiohikvision").setLevel(logging.DEBUG)
```

- come è stato riconosciuto il dispositivo: il suo modello e firmware, i domini che
  mostra e come è coperto ciascuno, i comportamenti che non sono quelli predefiniti e
  la regola che li ha impostati;
- i suoi flussi, quando vengono letti la prima volta e quando cambiano;
- ogni richiesta che fallisce, la prima volta, e quando torna a rispondere; nessuna
  riga per le richieste che funzionano.

Allega quel log alla issue insieme al rapporto. In Home Assistant, usa **Abilita la
registrazione di debug** dell'integrazione: il log della libreria è incluso.

Il resto della documentazione (come differiscono i dispositivi, con i comportamenti e
le regole; i citofoni; le loro chiamate via SIP; lo sviluppo) è nel
[README in inglese](https://github.com/webysther/aio-hikvision/blob/main/README.md).
