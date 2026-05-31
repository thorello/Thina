"""Fixtures compartilhadas para testes do thina-server."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

import pytest

import thina.core.conversation as conversation_store
import thina.context.user as thina_context
import thina.pc.actions as pc_actions


@pytest.fixture(autouse=True)
def _reset_conversation_sessions() -> Iterator[None]:
    conversation_store._sessions.clear()
    yield
    conversation_store._sessions.clear()


@pytest.fixture(autouse=True)
def _reset_user_context_cache() -> Iterator[None]:
    thina_context._cache = None
    yield
    thina_context._cache = None


@pytest.fixture(autouse=True)
def _reset_pc_apps_catalog() -> Iterator[None]:
    pc_actions.reload_pc_apps_catalog()
    yield
    pc_actions.reload_pc_apps_catalog()


@pytest.fixture(autouse=True)
def _reset_tts_settings_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    import thina.core.tts_settings as tts_store

    tts_file = tmp_path / "tts_settings.json"
    monkeypatch.setattr(tts_store, "TTS_SETTINGS_FILE", tts_file)
    yield


@pytest.fixture
def areas_map_file(tmp_path: Path) -> Path:
    path = tmp_path / "areas.json"
    path.write_text(
        json.dumps(
            {
                "sala": "media_player.respeaker_sala",
                "quarto": "media_player.respeaker_quarto",
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def pc_apps_file(tmp_path: Path) -> Path:
    path = tmp_path / "pc_apps.json"
    path.write_text(
        json.dumps(
            {
                "calculadora": {
                    "friendly_name": "Calculadora",
                    "aliases": ["calc"],
                    "windows_cmd": ["calc.exe"],
                },
                "notepad": {
                    "friendly_name": "Bloco de Notas",
                    "aliases": ["bloco de notas"],
                    "windows_cmd": ["notepad.exe"],
                },
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def test_env(
    monkeypatch: pytest.MonkeyPatch,
    areas_map_file: Path,
    pc_apps_file: Path,
    tmp_path: Path,
) -> None:
    """Variaveis minimas para Settings e mapas em diretorio temporario."""
    monkeypatch.setenv("AREAS_MAP_FILE", str(areas_map_file))
    monkeypatch.setenv("PC_APPS_MAP_FILE", str(pc_apps_file))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek-key")
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("THINA_PUBLIC_URL", "http://test-thina.local:8080")
    monkeypatch.setenv("PC_COMMANDS_ENABLED", "true")

    user_md = tmp_path / "thina_user.md"
    user_md.write_text("# Thina\nVoce e a assistente de teste.", encoding="utf-8")
    monkeypatch.setenv("THINA_USER_CONTEXT_FILE", str(user_md))

    private_dir = tmp_path / "private"
    private_dir.mkdir()
    (private_dir / "rotina.md").write_text("Rotina de teste.", encoding="utf-8")
    monkeypatch.setenv("THINA_PRIVATE_DIR", str(private_dir))
    monkeypatch.setenv(
        "THINA_USER_PRIVATE_FILE",
        str(tmp_path / "inexistente.private.md"),
    )

    # Isola do .env do desenvolvedor (ex.: GOOGLE_ENABLED=true)
    monkeypatch.setenv("GOOGLE_ENABLED", "false")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "")
    monkeypatch.setenv("GOOGLE_CREDENTIALS_FILE", str(tmp_path / "google_credentials.json"))
    monkeypatch.setenv("GOOGLE_TOKEN_FILE", str(tmp_path / "google_token.json"))


@pytest.fixture
def client(test_env: None) -> Iterator:
    from fastapi.testclient import TestClient

    import main

    with TestClient(main.app) as test_client:
        yield test_client
