# aiohikvision

[English](https://github.com/webysther/aio-hikvision/blob/main/README.md) · [中文](https://github.com/webysther/aio-hikvision/blob/main/README.zh-CN.md) · **Español** · [Português](https://github.com/webysther/aio-hikvision/blob/main/README.pt-BR.md) · [Français](https://github.com/webysther/aio-hikvision/blob/main/README.fr.md) · [العربية](https://github.com/webysther/aio-hikvision/blob/main/README.ar.md) · [Русский](https://github.com/webysther/aio-hikvision/blob/main/README.ru.md) · [Deutsch](https://github.com/webysther/aio-hikvision/blob/main/README.de.md) · [Italiano](https://github.com/webysther/aio-hikvision/blob/main/README.it.md)

Biblioteca asyncio para dispositivos Hikvision: cámaras, grabadores y videoporteros por
ISAPI, y las llamadas SIP de los videoporteros. Está totalmente tipada, no depende de
Home Assistant e instala solo las partes que usas. Aspira a ser la única biblioteca que
necesiten los proyectos Hikvision de Home Assistant; su primer usuario es
[Hikvision Virtual Indoor Station](https://github.com/webysther/ha-hikvision-virtual-indoor-station).

Todos los dispositivos que ha conocido funcionan porque alguien envió su informe. El
tuyo puede ser el siguiente: los pasos de abajo llevan cinco minutos.

## Tu dispositivo, paso a paso

### 1. Instala

```sh
pip install "aiohikvision[isapi]"
```

Python 3.13 o posterior. Cada parte de la biblioteca es un extra, y la instalación
predeterminada no tiene ninguna dependencia:

| Extra | Instala | Para |
|---|---|---|
| (ninguno) | nada | los modelos, en qué difieren los dispositivos (`behaviours`), los errores |
| `isapi` | aiohttp, yarl, defusedxml | `HikvisionClient`, `Device`, `DoorStation`: la API HTTP de los dispositivos |
| `rtp` | nada por ahora | RTP: el micrófono hacia el videoportero durante una llamada |
| `sip` | `[rtp]`, aiosipua | las llamadas SIP de los videoporteros |
| `scrambling` | `[isapi]`, cryptography | los flujos de programa cifrados de las grabaciones |
| `all` | todo | |

Una parte usada sin su extra lanza `MissingExtra`, que indica qué instalar.

### 2. Conoce tu dispositivo

`HikvisionClient(session).connect(...)` lee, una sola vez y solo con GET, quién es el
dispositivo, qué puede hacer y cómo se comporta. Nada cambia en el dispositivo.

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

En un videoportero DS-KD8003 imprime:

```text
DS-KD8003-IME1(B) V3.7.3 build 260915
Domains: streaming, events, io, video_intercom, access_control, two_way_audio
Talk packets: 40ms
```

Pásale la sesión `aiohttp` de tu aplicación con `HikvisionClient(session)`.
`device.streaming` lista sus flujos (`await device.streaming.streams()`), captura una
imagen (`snapshot()`) y da la dirección RTSP de cada uno (`rtsp_url()`).

### 3. Genera su informe

El informe es todo lo que la biblioteca lee del dispositivo y lo que deduce de ello:
sus documentos, **anonimizados** (sin cuenta, dirección, número de serie, MAC ni los
nombres que le diste), los dominios que muestra y cómo la biblioteca cubre cada uno,
los comportamientos que usa y por qué, y lo que no reconoció. Desde una terminal:

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

Las líneas con `!` son lo que le falta a la biblioteca para tu dispositivo: valores que
no reconoce, documentos que fallaron o la falta de una regla para tu modelo y firmware.
En tu propio código, `await device.report()` devuelve el mismo informe
(`report.to_json()`).

### 4. Envíalo

Primero lee el archivo: no debería contener nada de tu casa, y puedes quitar todo lo
que prefieras no compartir. Después
[abre un informe de dispositivo](https://github.com/webysther/aio-hikvision/issues/new?template=device_report.yml),
adjúntalo y cuenta qué funciona y qué no. Un informe se convierte en un fixture de las
pruebas, en una regla para tu modelo y firmware, y en los servicios que necesita tu
dispositivo: la biblioteca mejora de la misma forma para todos los dispositivos.

### 5. Cuando algo falla

El registro de depuración de la biblioteca es breve y dice lo que importa, una sola vez:

```python
import logging

logging.basicConfig()
logging.getLogger("aiohikvision").setLevel(logging.DEBUG)
```

- cómo se reconoció el dispositivo: su modelo y firmware, los dominios que muestra y
  cómo se cubre cada uno, los comportamientos que no son los predeterminados y la regla
  que los definió;
- sus flujos, cuando se leen por primera vez y cuando cambian;
- cada petición que falla, la primera vez, y cuando vuelve a responder; ninguna línea
  para las peticiones que funcionan.

Adjunta ese registro al issue junto con el informe. En Home Assistant, usa **Habilitar
el registro de depuración** en la integración: el registro de la biblioteca viene
incluido.

El resto de la documentación (en qué difieren los dispositivos, con sus
comportamientos y reglas; los videoporteros; sus llamadas por SIP; el desarrollo) está
en el [README en inglés](https://github.com/webysther/aio-hikvision/blob/main/README.md).
