# aiohikvision

[English](https://github.com/webysther/aio-hikvision/blob/main/README.md) · [中文](https://github.com/webysther/aio-hikvision/blob/main/README.zh-CN.md) · [Español](https://github.com/webysther/aio-hikvision/blob/main/README.es.md) · [Português](https://github.com/webysther/aio-hikvision/blob/main/README.pt-BR.md) · [Français](https://github.com/webysther/aio-hikvision/blob/main/README.fr.md) · **العربية** · [Русский](https://github.com/webysther/aio-hikvision/blob/main/README.ru.md) · [Deutsch](https://github.com/webysther/aio-hikvision/blob/main/README.de.md) · [Italiano](https://github.com/webysther/aio-hikvision/blob/main/README.it.md)

<div dir="rtl">

مكتبة asyncio لأجهزة Hikvision: الكاميرات وأجهزة التسجيل وأجهزة الباب عبر ISAPI،
ومكالمات SIP لأجهزة الباب في أنظمة الإنترفون المرئي. وهي مُعرَّفة الأنواع بالكامل
(fully typed)، ولا تعتمد على Home Assistant، ولا تثبّت إلا الأجزاء التي تستخدمها. تطمح
لأن تكون المكتبة الوحيدة التي تحتاجها مشاريع Hikvision في Home Assistant؛ وأول من
يستخدمها هو
[Hikvision Virtual Indoor Station](https://github.com/webysther/ha-hikvision-virtual-indoor-station).

كل جهاز صادفته المكتبة يعمل لأن أحدهم أرسل تقريره. وقد يكون جهازك هو التالي: الخطوات
أدناه تستغرق خمس دقائق.

## جهازك، خطوة بخطوة

### 1. التثبيت

```sh
pip install "aiohikvision[isapi]"
```

تحتاج إلى Python 3.13 أو أحدث. كل جزء من المكتبة هو extra (إضافة اختيارية)، والتثبيت
الافتراضي لا يجلب أي اعتمادية:

| Extra | ما يثبّته | الغرض |
|---|---|---|
| (بلا) | لا شيء | نماذج البيانات، وكيف تختلف الأجهزة (`behaviours`)، والأخطاء |
| `isapi` | aiohttp, yarl, defusedxml | `HikvisionClient`، `Device`، `DoorStation`: واجهة HTTP البرمجية للأجهزة |
| `rtp` | لا شيء حاليًا | RTP: إرسال صوت الميكروفون إلى جهاز الباب أثناء المكالمة |
| `sip` | `[rtp]`, aiosipua | مكالمات SIP لأجهزة الباب |
| `scrambling` | `[isapi]`, cryptography | تدفقات البرنامج (program streams) المشفّرة للتسجيلات |
| `all` | كل شيء | |

الجزء الذي يُستخدم دون الـ extra الخاص به يُطلق `MissingExtra`، الذي يخبرك بما يجب
تثبيته.

### 2. تعرّف على جهازك

تقرأ `HikvisionClient(session).connect(...)`، مرة واحدة وبطلبات GET فقط، هوية الجهاز
وما يستطيع فعله وكيف يتصرف. لا يتغير أي شيء على الجهاز.

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

على جهاز الباب DS-KD8003 يطبع البرنامج:

```text
DS-KD8003-IME1(B) V3.7.3 build 260915
Domains: streaming, events, io, video_intercom, access_control, two_way_audio
Talk packets: 40ms
```

مرّر جلسة `aiohttp` الخاصة بتطبيقك عبر `HikvisionClient(session)`. تسرد
`device.streaming` تدفقات الجهاز (`await device.streaming.streams()`)، وتلتقط صورة
(`snapshot()`)، وتعطي عنوان RTSP لكل تدفق (`rtsp_url()`).

### 3. أنشئ تقريره

التقرير هو كل ما تقرؤه المكتبة من الجهاز وما تستخلصه منه: مستنداته **مُجهَّلة الهوية**
(بلا حساب أو عنوان أو رقم تسلسلي أو MAC أو أسماء أطلقتها أنت)، والمجالات (domains)
التي يعرضها وكيف تغطي المكتبة كلًّا منها، والسلوكيات (behaviours) التي تستخدمها
ولماذا، وما لم تتعرّف عليه. من الطرفية:

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

الأسطر التي تحمل `!` هي ما ينقص المكتبة من أجل جهازك: قيم لا تتعرّف عليها، أو مستندات
فشلت قراءتها، أو غياب قاعدة لطراز جهازك وبرنامجه الثابت (firmware). وفي شيفرتك الخاصة،
تُعيد `await device.report()` التقرير نفسه (`report.to_json()`).

### 4. أرسله

اقرأ الملف أولًا: يجب ألا يحتوي على أي شيء يخص منزلك، ويمكنك حذف أي شيء تفضّل عدم
مشاركته. ثم
[افتح تقرير جهاز](https://github.com/webysther/aio-hikvision/issues/new?template=device_report.yml)،
وأرفق الملف، واذكر ما يعمل وما لا يعمل. يتحوّل التقرير إلى fixture ضمن الاختبارات،
وإلى قاعدة لطراز جهازك وبرنامجه الثابت، وإلى الخدمات التي يحتاجها جهازك: وهكذا تتحسّن
المكتبة بالطريقة نفسها لكل جهاز.

### 5. عندما يحدث خطأ ما

سجل التصحيح (debug log) في المكتبة قصير ويذكر ما يهم، مرة واحدة فقط:

```python
import logging

logging.basicConfig()
logging.getLogger("aiohikvision").setLevel(logging.DEBUG)
```

- كيف تم التعرّف على الجهاز: طرازه وبرنامجه الثابت، والمجالات التي يعرضها وكيف يُغطّى
  كلٌّ منها، والسلوكيات غير الافتراضية والقاعدة التي حدّدتها؛
- تدفقاته، عند قراءتها أول مرة وعند تغيّرها؛
- كل طلب يفشل، في المرة الأولى، وعندما يعود الجهاز إلى الاستجابة؛ ولا يُكتب أي سطر
  للطلبات التي تنجح.

أرفق هذا السجل بالبلاغ (issue) مع التقرير. وفي Home Assistant، اختر **تفعيل تسجيل
التصحيح** (Enable debug logging) للتكامل: فيُسجَّل سجل المكتبة معه.

بقية التوثيق — كيف تختلف الأجهزة (السلوكيات والقواعد)، وأجهزة الباب، ومكالماتها عبر
SIP، والتطوير — موجودة في
[ملف README باللغة الإنجليزية](https://github.com/webysther/aio-hikvision/blob/main/README.md).

</div>
