"""
Integracao OAuth com Gmail, Google Drive e Google Calendar.

Fluxo inicial: credenciais OAuth (Desktop) em data/google_credentials.json,
autorizacao via scripts/google_auth.py, token em data/google_token.json.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from thina.core.config import BASE_DIR, get_settings

logger = logging.getLogger(__name__)

SCOPES = (
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/calendar.events",
)


class GoogleError(Exception):
    """Erro base na integracao Google."""


class GoogleNotConfiguredError(GoogleError):
    """Integracao desabilitada ou credenciais ausentes."""


class GoogleAuthError(GoogleError):
    """Token invalido ou autorizacao pendente."""


def _resolve_path(relative: str) -> Path:
    path = Path(relative)
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


def credentials_path() -> Path:
    return _resolve_path(get_settings().google_credentials_file)


def token_path() -> Path:
    return _resolve_path(get_settings().google_token_file)


def is_google_configured() -> bool:
    settings = get_settings()
    if not settings.google_enabled:
        return False
    if credentials_path().exists():
        return True
    return bool(settings.google_client_id.strip() and settings.google_client_secret.strip())


def is_google_authorized() -> bool:
    return is_google_configured() and token_path().exists()


def _client_config_from_env() -> dict[str, Any] | None:
    settings = get_settings()
    client_id = settings.google_client_id.strip()
    client_secret = settings.google_client_secret.strip()
    if not client_id or not client_secret:
        return None
    return {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }


def _require_configured() -> None:
    settings = get_settings()
    if not settings.google_enabled:
        raise GoogleNotConfiguredError(
            "Integracao Google desabilitada. Defina GOOGLE_ENABLED=true no .env."
        )
    if credentials_path().exists() or _client_config_from_env():
        return
    raise GoogleNotConfiguredError(
        f"Credenciais OAuth ausentes. Coloque o JSON em {credentials_path()} "
        "ou defina GOOGLE_CLIENT_ID e GOOGLE_CLIENT_SECRET no .env, "
        "depois rode scripts/google_auth.py."
    )


def _oauth_flow():
    from google_auth_oauthlib.flow import InstalledAppFlow

    _require_configured()
    client_config = _client_config_from_env()
    if client_config:
        return InstalledAppFlow.from_client_config(client_config, SCOPES)
    return InstalledAppFlow.from_client_secrets_file(str(credentials_path()), SCOPES)


def _credentials_have_scopes(creds: Any) -> bool:
    granted = set(creds.scopes or [])
    return set(SCOPES).issubset(granted)


def needs_reauth() -> bool:
    """True se o token existir mas nao cobrir os scopes atuais."""
    if not token_path().exists():
        return True
    try:
        from google.oauth2.credentials import Credentials

        creds = Credentials.from_authorized_user_file(str(token_path()), SCOPES)
        return not _credentials_have_scopes(creds)
    except Exception:
        return True


def _load_credentials_sync():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    _require_configured()
    token_file = token_path()
    creds = None

    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)
        if not _credentials_have_scopes(creds):
            raise GoogleAuthError(
                "Token Google com permissoes antigas. Apague data/google_token.json "
                "e rode: python scripts/google_auth.py"
            )

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        save_token_sync(creds)
        return creds

    raise GoogleAuthError(
        "Conta Google nao autorizada. Rode: python scripts/google_auth.py"
    )


def save_token_sync(creds: Any) -> None:
    path = token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(creds.to_json(), encoding="utf-8")


def run_oauth_flow_sync() -> None:
    """Abre o navegador para autorizar e salva o token."""
    flow = _oauth_flow()
    creds = flow.run_local_server(port=0)
    save_token_sync(creds)
    logger.info("Token Google salvo em %s", token_path())


def _build_service(api: str, version: str):
    from googleapiclient.discovery import build

    creds = _load_credentials_sync()
    return build(api, version, credentials=creds, cache_discovery=False)


def _decode_b64(data: str) -> str:
    padded = data + "=" * (-len(data) % 4)
    raw = base64.urlsafe_b64decode(padded.encode("ascii"))
    return raw.decode("utf-8", errors="replace")


def _extract_email_body(payload: dict[str, Any]) -> str:
    body = payload.get("body") or {}
    if body.get("data"):
        return _decode_b64(body["data"])

    parts = payload.get("parts") or []
    plain_parts: list[str] = []
    html_parts: list[str] = []
    for part in parts:
        mime = part.get("mimeType", "")
        if mime == "text/plain":
            part_body = part.get("body") or {}
            if part_body.get("data"):
                plain_parts.append(_decode_b64(part_body["data"]))
        elif mime == "text/html":
            part_body = part.get("body") or {}
            if part_body.get("data"):
                html_parts.append(_decode_b64(part_body["data"]))
        elif part.get("parts"):
            nested = _extract_email_body(part)
            if nested:
                plain_parts.append(nested)

    if plain_parts:
        return "\n".join(plain_parts)
    if html_parts:
        return html_parts[0]
    return ""


def _headers_map(payload: dict[str, Any]) -> dict[str, str]:
    headers = payload.get("headers") or []
    return {item.get("name", ""): item.get("value", "") for item in headers}


def _list_gmail_messages_sync(query: str, max_results: int) -> dict[str, Any]:
    service = _build_service("gmail", "v1")
    listed = (
        service.users()
        .messages()
        .list(userId="me", q=query or None, maxResults=max_results)
        .execute()
    )
    refs = listed.get("messages") or []
    emails: list[dict[str, Any]] = []

    for ref in refs:
        msg = (
            service.users()
            .messages()
            .get(
                userId="me",
                id=ref["id"],
                format="metadata",
                metadataHeaders=["From", "Subject", "Date"],
            )
            .execute()
        )
        headers = _headers_map(msg.get("payload") or {})
        emails.append(
            {
                "id": ref["id"],
                "from": headers.get("From", ""),
                "subject": headers.get("Subject", ""),
                "date": headers.get("Date", ""),
                "snippet": msg.get("snippet", ""),
            }
        )

    return {"total": len(emails), "emails": emails}


def _get_gmail_message_sync(message_id: str) -> dict[str, Any]:
    service = _build_service("gmail", "v1")
    msg = (
        service.users()
        .messages()
        .get(userId="me", id=message_id, format="full")
        .execute()
    )
    payload = msg.get("payload") or {}
    headers = _headers_map(payload)
    body = _extract_email_body(payload)
    if len(body) > 8000:
        body = body[:8000] + "\n...[truncado]"

    return {
        "id": message_id,
        "from": headers.get("From", ""),
        "to": headers.get("To", ""),
        "subject": headers.get("Subject", ""),
        "date": headers.get("Date", ""),
        "snippet": msg.get("snippet", ""),
        "body": body,
    }


def _list_drive_files_sync(query: str, max_results: int) -> dict[str, Any]:
    service = _build_service("drive", "v3")
    params: dict[str, Any] = {
        "pageSize": max_results,
        "fields": "files(id,name,mimeType,modifiedTime,size,webViewLink)",
        "orderBy": "modifiedTime desc",
    }
    if query.strip():
        params["q"] = query

    result = service.files().list(**params).execute()
    files = result.get("files") or []
    return {"total": len(files), "arquivos": files}


def _read_drive_file_sync(file_id: str) -> dict[str, Any]:
    service = _build_service("drive", "v3")
    meta = (
        service.files()
        .get(fileId=file_id, fields="id,name,mimeType,modifiedTime,size,webViewLink")
        .execute()
    )
    mime = meta.get("mimeType", "")

    if mime == "application/vnd.google-apps.document":
        raw = (
            service.files()
            .export(fileId=file_id, mimeType="text/plain")
            .execute()
        )
        if isinstance(raw, bytes):
            content = raw.decode("utf-8", errors="replace")
        else:
            content = str(raw)
    elif mime.startswith("text/") or mime in (
        "application/json",
        "application/javascript",
        "application/xml",
    ):
        raw = service.files().get_media(fileId=file_id).execute()
        if isinstance(raw, bytes):
            content = raw.decode("utf-8", errors="replace")
        else:
            content = str(raw)
    else:
        return {
            "ok": False,
            "id": file_id,
            "name": meta.get("name", ""),
            "mimeType": mime,
            "erro": "Tipo de arquivo nao suportado para leitura de texto.",
            "webViewLink": meta.get("webViewLink", ""),
        }

    if len(content) > 12000:
        content = content[:12000] + "\n...[truncado]"

    return {
        "ok": True,
        "id": file_id,
        "name": meta.get("name", ""),
        "mimeType": mime,
        "modifiedTime": meta.get("modifiedTime", ""),
        "webViewLink": meta.get("webViewLink", ""),
        "conteudo": content,
    }


def _list_calendar_events_sync(days_ahead: int, max_results: int) -> dict[str, Any]:
    service = _build_service("calendar", "v3")
    now = datetime.now(timezone.utc)
    time_max = now + timedelta(days=max(1, days_ahead))

    result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=now.isoformat(),
            timeMax=time_max.isoformat(),
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )

    events: list[dict[str, Any]] = []
    for item in result.get("items") or []:
        start = item.get("start") or {}
        end = item.get("end") or {}
        events.append(
            {
                "id": item.get("id", ""),
                "summary": item.get("summary", "(sem titulo)"),
                "start": start.get("dateTime") or start.get("date", ""),
                "end": end.get("dateTime") or end.get("date", ""),
                "location": item.get("location", ""),
                "description": (item.get("description") or "")[:500],
            }
        )

    return {"total": len(events), "eventos": events}


def _get_drive_file_link_sync(file_id: str) -> dict[str, Any]:
    service = _build_service("drive", "v3")
    meta = (
        service.files()
        .get(fileId=file_id, fields="id,name,mimeType,webViewLink")
        .execute()
    )
    link = meta.get("webViewLink", "")
    if not link:
        return {"ok": False, "erro": "Arquivo sem link de visualizacao.", "id": file_id}
    return {
        "ok": True,
        "id": file_id,
        "name": meta.get("name", ""),
        "mimeType": meta.get("mimeType", ""),
        "webViewLink": link,
    }


def _create_calendar_event_sync(
    summary: str,
    start: str,
    end: str,
    location: str = "",
    description: str = "",
) -> dict[str, Any]:
    settings = get_settings()
    service = _build_service("calendar", "v3")
    event: dict[str, Any] = {
        "summary": summary.strip(),
        "start": {"dateTime": start.strip(), "timeZone": settings.google_timezone},
        "end": {"dateTime": end.strip(), "timeZone": settings.google_timezone},
    }
    if location.strip():
        event["location"] = location.strip()
    if description.strip():
        event["description"] = description.strip()

    created = service.events().insert(calendarId="primary", body=event).execute()
    start_info = created.get("start") or {}
    end_info = created.get("end") or {}
    return {
        "ok": True,
        "id": created.get("id", ""),
        "summary": created.get("summary", summary),
        "start": start_info.get("dateTime") or start_info.get("date", ""),
        "end": end_info.get("dateTime") or end_info.get("date", ""),
        "htmlLink": created.get("htmlLink", ""),
    }


def _send_gmail_message_sync(to: str, subject: str, body: str) -> dict[str, Any]:
    from email.mime.text import MIMEText

    service = _build_service("gmail", "v1")
    message = MIMEText(body, "plain", "utf-8")
    message["to"] = to.strip()
    message["subject"] = subject.strip()
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()
    return {
        "ok": True,
        "id": sent.get("id", ""),
        "to": to.strip(),
        "subject": subject.strip(),
    }


def _mark_gmail_read_sync(message_id: str) -> dict[str, Any]:
    service = _build_service("gmail", "v1")
    service.users().messages().modify(
        userId="me",
        id=message_id.strip(),
        body={"removeLabelIds": ["UNREAD"]},
    ).execute()
    return {"ok": True, "id": message_id.strip(), "lido": True}


async def list_gmail_messages(query: str = "", max_results: int = 10) -> dict[str, Any]:
    return await asyncio.to_thread(_list_gmail_messages_sync, query, max_results)


async def get_gmail_message(message_id: str) -> dict[str, Any]:
    return await asyncio.to_thread(_get_gmail_message_sync, message_id)


async def list_drive_files(query: str = "", max_results: int = 15) -> dict[str, Any]:
    return await asyncio.to_thread(_list_drive_files_sync, query, max_results)


async def read_drive_file(file_id: str) -> dict[str, Any]:
    return await asyncio.to_thread(_read_drive_file_sync, file_id)


async def list_calendar_events(days_ahead: int = 7, max_results: int = 10) -> dict[str, Any]:
    return await asyncio.to_thread(_list_calendar_events_sync, days_ahead, max_results)


async def get_drive_file_link(file_id: str) -> dict[str, Any]:
    return await asyncio.to_thread(_get_drive_file_link_sync, file_id)


async def create_calendar_event(
    summary: str,
    start: str,
    end: str,
    location: str = "",
    description: str = "",
) -> dict[str, Any]:
    return await asyncio.to_thread(
        _create_calendar_event_sync,
        summary,
        start,
        end,
        location,
        description,
    )


async def send_gmail_message(to: str, subject: str, body: str) -> dict[str, Any]:
    return await asyncio.to_thread(_send_gmail_message_sync, to, subject, body)


async def mark_gmail_read(message_id: str) -> dict[str, Any]:
    return await asyncio.to_thread(_mark_gmail_read_sync, message_id)


def google_status() -> dict[str, Any]:
    """Estado da integracao para diagnostico."""
    settings = get_settings()
    return {
        "enabled": settings.google_enabled,
        "credentials_file": credentials_path().exists(),
        "client_env": bool(settings.google_client_id.strip() and settings.google_client_secret.strip()),
        "configured": is_google_configured(),
        "authorized": is_google_authorized(),
        "needs_reauth": needs_reauth() if is_google_authorized() else False,
        "scopes": list(SCOPES),
    }
