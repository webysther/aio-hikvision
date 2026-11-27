# aiohikvision

[English](https://github.com/webysther/aio-hikvision/blob/main/README.md) · [中文](https://github.com/webysther/aio-hikvision/blob/main/README.zh-CN.md) · [Español](https://github.com/webysther/aio-hikvision/blob/main/README.es.md) · [Português](https://github.com/webysther/aio-hikvision/blob/main/README.pt-BR.md) · **Français** · [العربية](https://github.com/webysther/aio-hikvision/blob/main/README.ar.md) · [Русский](https://github.com/webysther/aio-hikvision/blob/main/README.ru.md) · [Deutsch](https://github.com/webysther/aio-hikvision/blob/main/README.de.md) · [Italiano](https://github.com/webysther/aio-hikvision/blob/main/README.it.md)

Bibliothèque asyncio pour les appareils Hikvision : caméras, enregistreurs et portiers
vidéo via ISAPI, et les appels SIP des portiers vidéo. Elle est entièrement typée, ne
dépend pas de Home Assistant et n'installe que les parties que vous utilisez. Elle vise
à être la seule bibliothèque dont les projets Hikvision de Home Assistant ont besoin ;
sa première utilisatrice est
[Hikvision Virtual Indoor Station](https://github.com/webysther/ha-hikvision-virtual-indoor-station).

Chaque appareil qu'elle a rencontré fonctionne parce que quelqu'un a envoyé son
rapport. Le vôtre peut être le suivant : les étapes ci-dessous prennent cinq minutes.

## Votre appareil, étape par étape

### 1. Installer

```sh
pip install "aiohikvision[isapi]"
```

Python 3.13 ou plus récent. Chaque partie de la bibliothèque est un extra, et
l'installation par défaut n'a aucune dépendance :

| Extra | Installe | Pour |
|---|---|---|
| (aucun) | rien | les modèles, ce qui distingue les appareils (`behaviours`), les erreurs |
| `isapi` | aiohttp, yarl, defusedxml | `HikvisionClient`, `Device`, `DoorStation` : l'API HTTP des appareils |
| `rtp` | rien pour l'instant | RTP : le micro vers le portier pendant un appel |
| `sip` | `[rtp]`, aiosipua | les appels SIP des portiers vidéo |
| `scrambling` | `[isapi]`, cryptography | les flux de programme chiffrés des enregistrements |
| `all` | tout | |

Une partie utilisée sans son extra lève `MissingExtra`, qui indique quoi installer.

### 2. Faire connaissance avec votre appareil

`HikvisionClient(session).connect(...)` lit, une seule fois et uniquement en GET, qui
est l'appareil, ce qu'il sait faire et comment il se comporte. Rien ne change sur
l'appareil.

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

Sur un portier vidéo DS-KD8003, il affiche :

```text
DS-KD8003-IME1(B) V3.7.3 build 260915
Domains: streaming, events, io, video_intercom, access_control, two_way_audio
Talk packets: 40ms
```

Donnez-lui la session `aiohttp` de votre application avec `HikvisionClient(session)`.
`device.streaming` liste ses flux (`await device.streaming.streams()`), prend une photo
(`snapshot()`) et donne l'adresse RTSP de chacun (`rtsp_url()`).

### 3. Générer son rapport

Le rapport, c'est tout ce que la bibliothèque lit de l'appareil et ce qu'elle en
déduit : ses documents, **anonymisés** (ni compte, ni adresse, ni numéro de série, ni
MAC, ni les noms que vous lui avez donnés), les domaines qu'il présente et la façon
dont la bibliothèque couvre chacun, les comportements qu'elle utilise et pourquoi, et
ce qu'elle n'a pas reconnu. Depuis un terminal :

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

Les lignes avec `!` indiquent ce qui manque à la bibliothèque pour votre appareil : des
valeurs qu'elle ne reconnaît pas, des documents en échec, ou l'absence de règle pour
votre modèle et votre firmware. Dans votre propre code, `await device.report()` renvoie
le même rapport (`report.to_json()`).

### 4. L'envoyer

Lisez d'abord le fichier : il ne devrait rien contenir de votre domicile, et vous
pouvez retirer tout ce que vous préférez ne pas partager. Ensuite,
[ouvrez un rapport d'appareil](https://github.com/webysther/aio-hikvision/issues/new?template=device_report.yml),
joignez-y le fichier et dites ce qui fonctionne et ce qui ne fonctionne pas. Un rapport
devient une fixture des tests, une règle pour votre modèle et votre firmware, et les
services dont votre appareil a besoin : la bibliothèque s'améliore de la même façon
pour tous les appareils.

### 5. Quand quelque chose ne va pas

Le journal de débogage de la bibliothèque est court et dit ce qui compte, une seule
fois :

```python
import logging

logging.basicConfig()
logging.getLogger("aiohikvision").setLevel(logging.DEBUG)
```

- comment l'appareil a été reconnu : son modèle et son firmware, les domaines qu'il
  présente et la façon dont chacun est couvert, les comportements qui ne sont pas ceux
  par défaut et la règle qui les a fixés ;
- ses flux, quand ils sont lus pour la première fois et quand ils changent ;
- chaque requête qui échoue, la première fois, puis quand elle répond de nouveau ;
  aucune ligne pour les requêtes qui fonctionnent.

Joignez ce journal à l'issue, avec le rapport. Dans Home Assistant, choisissez
**Activer la journalisation de débogage** dans l'intégration : le journal de la
bibliothèque est inclus.

Le reste de la documentation (les différences entre appareils, avec leurs comportements
et leurs règles ; les portiers vidéo ; leurs appels en SIP ; le développement) se
trouve dans le
[README en anglais](https://github.com/webysther/aio-hikvision/blob/main/README.md).
