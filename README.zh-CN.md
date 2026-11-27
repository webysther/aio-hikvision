# aiohikvision

[English](https://github.com/webysther/aio-hikvision/blob/main/README.md) · **中文** · [Español](https://github.com/webysther/aio-hikvision/blob/main/README.es.md) · [Português](https://github.com/webysther/aio-hikvision/blob/main/README.pt-BR.md) · [Français](https://github.com/webysther/aio-hikvision/blob/main/README.fr.md) · [العربية](https://github.com/webysther/aio-hikvision/blob/main/README.ar.md) · [Русский](https://github.com/webysther/aio-hikvision/blob/main/README.ru.md) · [Deutsch](https://github.com/webysther/aio-hikvision/blob/main/README.de.md) · [Italiano](https://github.com/webysther/aio-hikvision/blob/main/README.it.md)

面向海康威视（Hikvision）设备的 asyncio 库：通过 ISAPI 访问摄像机、录像机和门口机，并处理可视对讲门口机的 SIP 通话。它有完整的类型标注，不依赖 Home Assistant，只安装你用到的部分。它的目标是成为 Home Assistant 上各个海康威视项目所需的唯一一个库；它的第一个用户是 [Hikvision Virtual Indoor Station](https://github.com/webysther/ha-hikvision-virtual-indoor-station)。

它接触过的每一台设备之所以能正常工作，都是因为有人发来了那台设备的报告。下一台可以是你的：下面的步骤只需五分钟。

## 你的设备，一步一步来

### 1. 安装

```sh
pip install "aiohikvision[isapi]"
```

需要 Python 3.13 或更高版本。库的每个部分都是一个 extra（可选依赖），默认安装不带任何依赖：

| Extra | 安装内容 | 用途 |
|---|---|---|
| （无） | 无 | 数据模型、设备之间的差异（`behaviours`）、错误类型 |
| `isapi` | aiohttp, yarl, defusedxml | `HikvisionClient`、`Device`、`DoorStation`：设备的 HTTP API |
| `rtp` | 暂无 | RTP：通话期间把麦克风的声音送到门口机 |
| `sip` | `[rtp]`, aiosipua | 门口机的 SIP 通话 |
| `scrambling` | `[isapi]`, cryptography | 录像的加密节目流（program stream） |
| `all` | 全部 | |

在没有安装对应 extra 的情况下使用某个部分，会抛出 `MissingExtra`，它会告诉你需要安装什么。

### 2. 认识你的设备

`HikvisionClient(session).connect(...)` 只读取一次，而且只用 GET 请求，了解设备是谁、能做什么、行为如何。设备上的任何东西都不会被改动。

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

在一台 DS-KD8003 门口机上，它会输出：

```text
DS-KD8003-IME1(B) V3.7.3 build 260915
Domains: streaming, events, io, video_intercom, access_control, two_way_audio
Talk packets: 40ms
```

用 `HikvisionClient(session)` 把你应用的 `aiohttp` 会话交给它。`device.streaming` 会列出设备的码流（`await device.streaming.streams()`），抓拍一张图片（`snapshot()`），并给出每路码流的 RTSP 地址（`rtsp_url()`）。

### 3. 生成设备报告

报告包含库从设备读取的全部内容，以及库从中得出的结论：设备的各项文档（已**匿名化**：不含账号、地址、序列号、MAC，也不含你起的名称）、设备展示的功能域（domains）以及库对每个功能域的支持方式、库采用的行为（behaviours）及其原因，还有库没能识别的内容。在终端中运行：

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

带 `!` 的行就是库对你的设备还缺少的东西：无法识别的值、读取失败的文档，或者还没有适用于你的型号和固件的规则。在你自己的代码中，`await device.report()` 会返回同样的报告（`report.to_json()`）。

### 4. 发送报告

请先读一遍这个文件：其中不应包含任何关于你家的信息，你也可以删掉任何不想分享的内容。然后[提交一份设备报告](https://github.com/webysther/aio-hikvision/issues/new?template=device_report.yml)，附上该文件，并说明哪些功能正常、哪些不正常。一份报告会变成测试的 fixture、适用于你的型号和固件的规则，以及你的设备所需的服务：库对每一台设备都以同样的方式不断改进。

### 5. 出现问题时

库的调试日志很简短，只说重要的事，而且只说一次：

```python
import logging

logging.basicConfig()
logging.getLogger("aiohikvision").setLevel(logging.DEBUG)
```

- 设备是如何被识别的：型号和固件、设备展示的功能域及每个功能域的支持方式、非默认的行为以及设定这些行为的规则；
- 设备的码流：首次读取时，以及发生变化时；
- 每个失败的请求：第一次失败时，以及设备重新响应时；成功的请求不会产生任何日志。

把这份日志和报告一起附到 issue 中。在 Home Assistant 中，为该集成打开**启用调试日志**（Enable debug logging）：库的日志也会随之记录。

其余文档——设备之间的差异（行为与规则）、门口机、门口机的 SIP 通话以及开发——请参阅[英文 README](https://github.com/webysther/aio-hikvision/blob/main/README.md)。
