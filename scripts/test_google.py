"""Teste rapido da integracao Google (Gmail, Drive, Calendar)."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from thina.integrations.google import (
    google_status,
    is_google_authorized,
    list_calendar_events,
    list_drive_files,
    list_gmail_messages,
)


async def main() -> int:
    status = google_status()
    print("Status:", json.dumps(status, ensure_ascii=False, indent=2))

    if not status["configured"]:
        print("ERRO: Google nao configurado.")
        return 1

    if not is_google_authorized():
        print("ERRO: Token ausente. Abra http://localhost:8080/v1/google/setup")
        return 1

    print("\n--- Gmail (3 recentes) ---")
    gmail = await list_gmail_messages("", 3)
    print(json.dumps(gmail, ensure_ascii=False, indent=2))

    print("\n--- Drive (5 recentes) ---")
    drive = await list_drive_files("", 5)
    print(json.dumps(drive, ensure_ascii=False, indent=2))

    print("\n--- Calendar (proximos 7 dias) ---")
    cal = await list_calendar_events(7, 5)
    print(json.dumps(cal, ensure_ascii=False, indent=2))

    print("\nOK: integracao Google funcionando.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
