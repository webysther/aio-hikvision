"""aiohikvision from a terminal: ``python -m aiohikvision report <host>``.

It reads a device the way :meth:`aiohikvision.Device.report` does (GET only, nothing is
changed), prints what the library makes of it, and writes the anonymized report to a file
to attach to an issue. The password is read from ``AIOHIKVISION_PASSWORD`` or asked for:
never from the command line, where the shell's history keeps it.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import re
import sys
from pathlib import Path
from typing import Final

from aiohikvision._extras import require

PASSWORD_VARIABLE: Final = "AIOHIKVISION_PASSWORD"  # noqa: S105  # the name of a variable
ISSUE_URL: Final = "https://github.com/webysther/aio-hikvision/issues/new?template=device_report.yml"


def main(argv: list[str] | None = None) -> int:
    """Run a command of the terminal; return the exit status."""
    parser = argparse.ArgumentParser(prog="python -m aiohikvision", description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    report = commands.add_parser("report", help="read a device and write its anonymized report")
    report.add_argument("host", help="the address of the device")
    report.add_argument("--port", type=int, help="its HTTP(S) port (80, or 443 with --https)")
    report.add_argument("--https", action="store_true", help="reach it over HTTPS")
    report.add_argument("--username", default="admin", help="the account (default: admin)")
    report.add_argument("--output", type=Path, help="the file to write (default: named after the model)")
    args = parser.parse_args(argv)
    password = os.environ.get(PASSWORD_VARIABLE) or getpass.getpass(f"Password of {args.username}: ")
    return asyncio.run(
        run_report(args.host, args.username, password, port=args.port, https=args.https, output=args.output)
    )


async def run_report(
    host: str, username: str, password: str, *, port: int | None, https: bool, output: Path | None
) -> int:
    """Read a device, print what the library makes of it, and write its report."""
    require("isapi")
    from aiohikvision.client import HikvisionClient  # noqa: PLC0415  # needs aiohikvision[isapi]
    from aiohikvision.errors import HikvisionError  # noqa: PLC0415

    try:
        async with HikvisionClient() as client:
            device = await client.connect(host, username, password, port=port, https=https)
            report = await device.report()
    except HikvisionError as err:
        print(f"The device could not be read: {type(err).__name__} {err}", file=sys.stderr)
        return 1
    model = re.sub(r"[^A-Za-z0-9.-]+", "-", report.device["model"] or "device").strip("-")
    target = output or Path(f"aiohikvision-report-{model}.json")
    target.write_text(report.to_json() + "\n", encoding="utf-8")
    print(f"{report.device['model']} {report.device['firmware']} ({report.device['device_type']})")
    print("Domains:", ", ".join(f"{domain} ({how})" for domain, how in report.coverage.items()))
    for name, behaviour in report.behaviours.items():
        print(f"  {name}: {behaviour['value']} ({behaviour['decided_by']})")
    for note in (*report.unknown, *(f"failed: {entry.path}" for entry in report.failed)):
        print(f"  ! {note}")
    print(f"Report written to {target}: read it, then attach it to {ISSUE_URL}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
