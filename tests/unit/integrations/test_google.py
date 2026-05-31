"""Testes da integracao Google (OAuth + APIs mockadas)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from thina.integrations.google import (
    GoogleAuthError,
    GoogleNotConfiguredError,
    credentials_path,
    google_status,
    is_google_configured,
    is_google_authorized,
    list_calendar_events,
    list_drive_files,
    list_gmail_messages,
    read_drive_file,
    token_path,
)
from thina.llm.gemini_mcp import (
    _needs_google_tools,
    _needs_mcp_tools,
)


@pytest.fixture
def google_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[Path, Path]:
    creds = tmp_path / "google_credentials.json"
    token = tmp_path / "google_token.json"
    creds.write_text(
        '{"installed": {"client_id": "x", "client_secret": "y", "redirect_uris": ["http://localhost"]}}',
        encoding="utf-8",
    )
    token.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("GOOGLE_ENABLED", "true")
    monkeypatch.setenv("GOOGLE_CREDENTIALS_FILE", str(creds))
    monkeypatch.setenv("GOOGLE_TOKEN_FILE", str(token))
    return creds, token


def test_google_disabled_by_default(test_env: None) -> None:
    assert is_google_configured() is False
    assert is_google_authorized() is False


def test_google_configured_when_enabled(google_env: tuple[Path, Path]) -> None:
    creds, token = google_env
    assert credentials_path() == creds
    assert token_path() == token
    assert is_google_configured() is True
    assert is_google_authorized() is True


def test_google_status(google_env: tuple[Path, Path]) -> None:
    status = google_status()
    assert status["enabled"] is True
    assert status["credentials_file"] is True
    assert status["configured"] is True
    assert status["authorized"] is True
    assert "gmail.modify" in status["scopes"][0]


def test_needs_google_tools_when_enabled(google_env: tuple[Path, Path]) -> None:
    assert _needs_google_tools("tenho email novo no gmail") is True
    assert _needs_google_tools("o que tenho na agenda amanha") is True
    assert _needs_google_tools("lista arquivos no meu drive") is True
    assert _needs_mcp_tools("meus emails de hoje") is True


def test_needs_google_tools_when_disabled(test_env: None) -> None:
    assert _needs_google_tools("tenho email novo no gmail") is False


@pytest.mark.asyncio
async def test_list_gmail_messages_mock(google_env: tuple[Path, Path]) -> None:
    mock_service = MagicMock()
    mock_service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
        "messages": [{"id": "abc123"}],
    }
    mock_service.users.return_value.messages.return_value.get.return_value.execute.return_value = {
        "snippet": "Ola mundo",
        "payload": {
            "headers": [
                {"name": "From", "value": "fulano@example.com"},
                {"name": "Subject", "value": "Teste"},
                {"name": "Date", "value": "Sat, 30 May 2026 10:00:00 +0000"},
            ]
        },
    }

    with patch("thina.integrations.google._build_service", return_value=mock_service):
        result = await list_gmail_messages("", 5)

    assert result["total"] == 1
    assert result["emails"][0]["id"] == "abc123"
    assert result["emails"][0]["subject"] == "Teste"


@pytest.mark.asyncio
async def test_list_drive_files_mock(google_env: tuple[Path, Path]) -> None:
    mock_service = MagicMock()
    mock_service.files.return_value.list.return_value.execute.return_value = {
        "files": [{"id": "file1", "name": "notas.txt", "mimeType": "text/plain"}],
    }

    with patch("thina.integrations.google._build_service", return_value=mock_service):
        result = await list_drive_files("name contains 'notas'", 10)

    assert result["total"] == 1
    assert result["arquivos"][0]["name"] == "notas.txt"


@pytest.mark.asyncio
async def test_read_drive_text_file_mock(google_env: tuple[Path, Path]) -> None:
    mock_service = MagicMock()
    mock_service.files.return_value.get.return_value.execute.return_value = {
        "id": "file1",
        "name": "notas.txt",
        "mimeType": "text/plain",
    }
    mock_service.files.return_value.get_media.return_value.execute.return_value = b"conteudo teste"

    with patch("thina.integrations.google._build_service", return_value=mock_service):
        result = await read_drive_file("file1")

    assert result["ok"] is True
    assert result["conteudo"] == "conteudo teste"


@pytest.mark.asyncio
async def test_list_calendar_events_mock(google_env: tuple[Path, Path]) -> None:
    mock_service = MagicMock()
    mock_service.events.return_value.list.return_value.execute.return_value = {
        "items": [
            {
                "id": "evt1",
                "summary": "Reuniao",
                "start": {"dateTime": "2026-05-31T15:00:00Z"},
                "end": {"dateTime": "2026-05-31T16:00:00Z"},
            }
        ],
    }

    with patch("thina.integrations.google._build_service", return_value=mock_service):
        result = await list_calendar_events(7, 5)

    assert result["total"] == 1
    assert result["eventos"][0]["summary"] == "Reuniao"


def test_load_credentials_without_token_raises(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    creds = tmp_path / "google_credentials.json"
    creds.write_text('{"installed": {"client_id": "x"}}', encoding="utf-8")
    token = tmp_path / "missing_token.json"
    monkeypatch.setenv("GOOGLE_ENABLED", "true")
    monkeypatch.setenv("GOOGLE_CREDENTIALS_FILE", str(creds))
    monkeypatch.setenv("GOOGLE_TOKEN_FILE", str(token))

    from thina.integrations.google import _load_credentials_sync

    with pytest.raises(GoogleAuthError):
        _load_credentials_sync()
