"""Testes de configuracao e mapa de areas."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from thina.core.config import Settings


def test_strip_trailing_slash_on_urls() -> None:
    s = Settings(
        home_assistant_url="http://ha.local:8123/",
        kokoro_server_url="http://kokoro/",
        thina_public_url="http://thina/",
    )
    assert s.home_assistant_url == "http://ha.local:8123"
    assert s.kokoro_server_url == "http://kokoro"
    assert s.thina_public_url == "http://thina"


@pytest.mark.parametrize("provider", ["gemini", "deepseek", "GEMINI"])
def test_llm_provider_normalizado(provider: str) -> None:
    s = Settings(llm_provider=provider)
    assert s.llm_provider in ("gemini", "deepseek")


def test_llm_provider_invalido() -> None:
    with pytest.raises(ValidationError):
        Settings(llm_provider="openai")


def test_kokoro_mix_voice_vazio_vira_none() -> None:
    s = Settings(kokoro_mix_voice="   ")
    assert s.kokoro_mix_voice is None


def test_load_areas_map_ok(areas_map_file: Path) -> None:
    s = Settings(areas_map_file=str(areas_map_file))
    data = s.load_areas_map()
    assert data["sala"] == "media_player.respeaker_sala"


def test_load_areas_map_arquivo_inexistente(tmp_path: Path) -> None:
    s = Settings(areas_map_file=str(tmp_path / "missing.json"))
    with pytest.raises(FileNotFoundError):
        s.load_areas_map()


def test_load_areas_map_entidade_invalida(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"sala": "light.lampada"}), encoding="utf-8")
    s = Settings(areas_map_file=str(path))
    with pytest.raises(ValueError, match="media_player"):
        s.load_areas_map()


def test_resolve_media_player(areas_map_file: Path) -> None:
    s = Settings(areas_map_file=str(areas_map_file))
    areas = s.load_areas_map()
    assert s.resolve_media_player("sala", areas) == "media_player.respeaker_sala"


def test_resolve_media_player_desconhecido(areas_map_file: Path) -> None:
    s = Settings(areas_map_file=str(areas_map_file))
    areas = s.load_areas_map()
    with pytest.raises(KeyError):
        s.resolve_media_player("banheiro", areas)


def test_llm_api_key_configured_deepseek() -> None:
    s = Settings(llm_provider="deepseek", deepseek_api_key="abc")
    assert s.llm_api_key_configured() is True


def test_llm_api_key_configured_gemini() -> None:
    s = Settings(llm_provider="gemini", gemini_api_key="xyz")
    assert s.llm_api_key_configured() is True


def test_ensure_audio_dir_cria_pasta(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import thina.core.config as config_mod

    audio_dir = tmp_path / "audio"
    monkeypatch.setattr(config_mod, "AUDIO_DIR", audio_dir)
    Settings().ensure_audio_dir()
    assert audio_dir.is_dir()
