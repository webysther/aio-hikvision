# aiohikvision

[English](https://github.com/webysther/aio-hikvision/blob/main/README.md) · [中文](https://github.com/webysther/aio-hikvision/blob/main/README.zh-CN.md) · [Español](https://github.com/webysther/aio-hikvision/blob/main/README.es.md) · [Português](https://github.com/webysther/aio-hikvision/blob/main/README.pt-BR.md) · [Français](https://github.com/webysther/aio-hikvision/blob/main/README.fr.md) · [العربية](https://github.com/webysther/aio-hikvision/blob/main/README.ar.md) · **Русский** · [Deutsch](https://github.com/webysther/aio-hikvision/blob/main/README.de.md) · [Italiano](https://github.com/webysther/aio-hikvision/blob/main/README.it.md)

Asyncio-библиотека для устройств Hikvision: камер, видеорегистраторов и вызывных
панелей через ISAPI, а также SIP-вызовов вызывных панелей видеодомофонов. Она
полностью типизирована, не зависит от Home Assistant и устанавливает только те части,
которыми вы пользуетесь. Её цель — стать единственной библиотекой, которая нужна
проектам Hikvision для Home Assistant; её первый пользователь —
[Hikvision Virtual Indoor Station](https://github.com/webysther/ha-hikvision-virtual-indoor-station).

Каждое устройство, с которым она уже встречалась, работает благодаря тому, что кто-то
прислал его отчёт. Следующим может стать ваше: шаги ниже займут пять минут.

## Ваше устройство, шаг за шагом

### 1. Установка

```sh
pip install "aiohikvision[isapi]"
```

Нужен Python 3.13 или новее. Каждая часть библиотеки — это extra (необязательная
зависимость), а установка по умолчанию не тянет никаких зависимостей:

| Extra | Устанавливает | Для чего |
|---|---|---|
| (нет) | ничего | модели данных, различия между устройствами (`behaviours`), ошибки |
| `isapi` | aiohttp, yarl, defusedxml | `HikvisionClient`, `Device`, `DoorStation`: HTTP API устройств |
| `rtp` | пока ничего | RTP: микрофон на вызывную панель во время вызова |
| `sip` | `[rtp]`, aiosipua | SIP-вызовы вызывных панелей |
| `scrambling` | `[isapi]`, cryptography | зашифрованные программные потоки (program stream) записей |
| `all` | всё | |

Часть, используемая без своего extra, выбрасывает `MissingExtra`, где сказано, что
нужно установить.

### 2. Знакомство с устройством

`aiohikvision.connect(...)` один раз и только GET-запросами считывает, что
это за устройство, что оно умеет и как себя ведёт. На устройстве ничего не меняется.

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

На вызывной панели DS-KD8003 скрипт выводит:

```text
Door Station · DS-KD8003-IME1(B) V3.7.3 build 260915 · door_station
Supports(snapshot=True, streaming=True, events=True, smart=False, ptz=False, two_way_audio=True, intercom=True, doors=True, holidays=False, inputs=4, outputs=2)
<Camera 1: 101, 102> rtsp://192.0.2.10:554/Streaming/Channels/101
```

Чтобы использовать `aiohttp`-сессию вашего приложения, передайте её в
`aiohikvision.connect(..., session=session)`. `hik.camera` перечисляет потоки устройства
(`camera.streams`), делает снимок (`snapshot()`) и выдаёт RTSP-адрес
каждого потока (`stream_url()`).

### 3. Создание отчёта

Отчёт — это всё, что библиотека считывает с устройства, и выводы, которые она из этого
делает: его документы в **анонимизированном** виде (без учётной записи, адресов,
серийного номера, MAC и заданных вами имён), домены, которые оно показывает, и то, как
библиотека покрывает каждый из них, особенности поведения (behaviours), которые она
применяет, и почему, а также то, что она не распознала. Из терминала:

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

Строки с `!` — это то, чего библиотеке не хватает для вашего устройства: значения,
которые она не распознаёт, документы, которые не удалось получить, или отсутствие
правила для вашей модели и прошивки. В вашем собственном коде `await hik.report()`
возвращает тот же отчёт (`report.to_json()`).

### 4. Отправка

Сначала прочитайте файл: в нём не должно быть ничего о вашем доме, и вы можете удалить
всё, чем предпочли бы не делиться. Затем
[создайте отчёт об устройстве](https://github.com/webysther/aio-hikvision/issues/new?template=device_report.yml),
прикрепите к нему файл и напишите, что работает, а что нет. Отчёт превращается в
фикстуру для тестов, в правило для вашей модели и прошивки и в сервисы, которые нужны
вашему устройству: так библиотека одинаково улучшается для каждого устройства.

### 5. Если что-то пошло не так

Отладочный журнал библиотеки краток и сообщает только важное, причём один раз:

```python
import logging

logging.basicConfig()
logging.getLogger("aiohikvision").setLevel(logging.DEBUG)
```

- как было распознано устройство: его модель и прошивка, домены, которые оно
  показывает, и то, как покрыт каждый из них, особенности поведения, отличные от
  значений по умолчанию, и правило, которое их задало;
- его потоки — при первом чтении и при изменении;
- каждый неудачный запрос — в первый раз и когда устройство снова начинает отвечать;
  для успешных запросов строк нет.

Приложите этот журнал к issue вместе с отчётом. В Home Assistant выберите для
интеграции **Начать отладку** (Enable debug logging): журнал библиотеки включится
вместе с ней.

Остальная документация — чем различаются устройства (особенности поведения и правила),
вызывные панели, их вызовы по SIP, разработка — находится в
[README на английском](https://github.com/webysther/aio-hikvision/blob/main/README.md).
