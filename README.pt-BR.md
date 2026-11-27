# aiohikvision

[English](https://github.com/webysther/aio-hikvision/blob/main/README.md) · [中文](https://github.com/webysther/aio-hikvision/blob/main/README.zh-CN.md) · [Español](https://github.com/webysther/aio-hikvision/blob/main/README.es.md) · **Português** · [Français](https://github.com/webysther/aio-hikvision/blob/main/README.fr.md) · [العربية](https://github.com/webysther/aio-hikvision/blob/main/README.ar.md) · [Русский](https://github.com/webysther/aio-hikvision/blob/main/README.ru.md) · [Deutsch](https://github.com/webysther/aio-hikvision/blob/main/README.de.md) · [Italiano](https://github.com/webysther/aio-hikvision/blob/main/README.it.md)

Biblioteca asyncio para dispositivos Hikvision: câmeras, gravadores e porteiros por
ISAPI, e as chamadas SIP dos porteiros com vídeo. Ela é toda tipada, não depende do Home
Assistant e instala só as partes que você usa. Ela quer ser a única biblioteca de que
os projetos Hikvision do Home Assistant precisam; a primeira a usá-la é a integração
[Hikvision Virtual Indoor Station](https://github.com/webysther/ha-hikvision-virtual-indoor-station).

Todo dispositivo que ela já conheceu funciona porque alguém mandou o relatório dele. O
seu pode ser o próximo: os passos abaixo levam cinco minutos.

## O seu dispositivo, passo a passo

### 1. Instale

```sh
pip install "aiohikvision[isapi]"
```

Python 3.13 ou mais novo. Cada parte da biblioteca é um extra, e a instalação padrão
não tem nenhuma dependência:

| Extra | Instala | Para |
|---|---|---|
| (nenhum) | nada | os modelos, como os dispositivos diferem (`behaviours`), os erros |
| `isapi` | aiohttp, yarl, defusedxml | `HikvisionClient`, `Device`, `DoorStation`: a API HTTP dos dispositivos |
| `rtp` | nada por enquanto | RTP: o microfone até o porteiro durante uma chamada |
| `sip` | `[rtp]`, aiosipua | as chamadas SIP dos porteiros |
| `scrambling` | `[isapi]`, cryptography | os fluxos de programa criptografados das gravações |
| `all` | tudo | |

Uma parte usada sem o extra dela levanta `MissingExtra`, que diz o que instalar.

### 2. Conheça o seu dispositivo

`HikvisionClient(session).connect(...)` lê, uma vez só e apenas com GET, quem o
dispositivo é, o que ele sabe fazer e como ele se comporta. Nada muda no dispositivo.

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

Num porteiro DS-KD8003, ele imprime:

```text
DS-KD8003-IME1(B) V3.7.3 build 260915
Domains: streaming, events, io, video_intercom, access_control, two_way_audio
Talk packets: 40ms
```

Passe a sessão `aiohttp` da sua aplicação com `HikvisionClient(session)`.
`device.streaming` lista os streams dele (`await device.streaming.streams()`), tira uma
foto (`snapshot()`) e dá o endereço RTSP de cada um (`rtsp_url()`).

### 3. Gere o relatório dele

O relatório é tudo o que a biblioteca lê do dispositivo e o que ela entende disso: os
documentos dele, **anonimizados** (sem conta, endereço, número de série, MAC nem os
nomes que você deu), os domínios que ele mostra e como a biblioteca cobre cada um, os
comportamentos que ela usa e por quê, e o que ela não reconheceu. Num terminal:

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

As linhas com `!` são o que falta à biblioteca para o seu dispositivo: valores que ela
não reconhece, documentos que falharam ou a falta de uma regra para o seu modelo e
firmware. No seu próprio código, `await device.report()` devolve o mesmo relatório
(`report.to_json()`).

### 4. Envie

Leia o arquivo antes: ele não deve ter nada da sua casa, e você pode tirar o que
preferir não compartilhar. Depois
[abra um relatório de dispositivo](https://github.com/webysther/aio-hikvision/issues/new?template=device_report.yml),
anexe o arquivo e conte o que funciona e o que não funciona. Um relatório vira uma
fixture dos testes, uma regra para o seu modelo e firmware, e os serviços de que o seu
dispositivo precisa: a biblioteca melhora do mesmo jeito para todo dispositivo.

### 5. Quando algo dá errado

O log de depuração da biblioteca é curto e diz o que importa, uma vez só:

```python
import logging

logging.basicConfig()
logging.getLogger("aiohikvision").setLevel(logging.DEBUG)
```

- como o dispositivo foi reconhecido: o modelo e o firmware dele, os domínios que ele
  mostra e como cada um é coberto, os comportamentos que não são os padrões e a regra
  que os definiu;
- os streams dele, quando são lidos pela primeira vez e quando mudam;
- cada requisição que falha, na primeira vez, e quando ela volta a responder; nenhuma
  linha para as requisições que funcionam.

Anexe esse log à issue, junto com o relatório. No Home Assistant, use **Habilitar log
de depuração** na integração: o log da biblioteca vem junto.

O resto da documentação (como os dispositivos diferem, com os comportamentos e as
regras; os porteiros; as chamadas deles por SIP; o desenvolvimento) está no
[README em inglês](https://github.com/webysther/aio-hikvision/blob/main/README.md).
