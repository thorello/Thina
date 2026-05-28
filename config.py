"""
Configuracao global do servidor Thina.

Carrega variaveis de ambiente via pydantic-settings e o mapa area_id -> media_player.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Diretorio raiz do projeto (onde esta este arquivo)
BASE_DIR = Path(__file__).resolve().parent
AUDIO_DIR = BASE_DIR / "data" / "audio"


class Settings(BaseSettings):
    """Variaveis de ambiente e caminhos do servidor."""

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM: gemini | deepseek
    llm_provider: str = "deepseek"

    # Gemini
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    gemini_google_search: bool = True

    # DeepSeek (API compativel com OpenAI)
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-v4-flash"
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_timeout: float = 90.0

    # Home Assistant
    home_assistant_url: str = "http://homeassistant.local:8123"
    home_assistant_token: str = ""

    # Kokoro TTS (thina_mix = media igual de pf_dora + if_sara em assets/voices)
    kokoro_server_url: str = "http://localhost:8000"
    kokoro_voice: str = "thina_mix"
    kokoro_mix_voice: str | None = None
    kokoro_mix_amount: float = 0.0
    kokoro_speed: float = 1.0
    kokoro_sentiment: str = "neutral"

    # Thina
    thina_host: str = "0.0.0.0"
    thina_port: int = 8080
    thina_public_url: str = "http://127.0.0.1:8080"
    thina_default_city: str = ""

    # Comandos no PC local (lista branca em maps/pc_apps.json)
    pc_commands_enabled: bool = False
    pc_apps_map_file: str = "maps/pc_apps.json"

    # Mapas e MCP
    areas_map_file: str = "maps/areas.json"
    mcp_server_module: str = "services.gemini_mcp"

    # Timeouts (segundos)
    ha_timeout: float = 30.0
    kokoro_timeout: float = 60.0
    gemini_timeout: float = 90.0

    audio_retention_hours: int = 24
    log_level: str = "INFO"

    @field_validator("home_assistant_url", "kokoro_server_url", "thina_public_url")
    @classmethod
    def strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")

    @field_validator("llm_provider")
    @classmethod
    def normalize_llm_provider(cls, v: str) -> str:
        normalized = v.strip().lower()
        if normalized not in ("gemini", "deepseek"):
            raise ValueError("LLM_PROVIDER deve ser 'gemini' ou 'deepseek'.")
        return normalized

    @field_validator("kokoro_mix_voice", mode="before")
    @classmethod
    def empty_mix_voice(cls, v: object) -> str | None:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        return str(v)

    @property
    def areas_map_path(self) -> Path:
        path = Path(self.areas_map_file)
        if not path.is_absolute():
            path = BASE_DIR / path
        return path

    def load_areas_map(self) -> dict[str, str]:
        """Carrega JSON area_id -> entity_id do media_player."""
        path = self.areas_map_path
        if not path.exists():
            raise FileNotFoundError(f"Mapa de areas nao encontrado: {path}")

        with path.open(encoding="utf-8") as f:
            data: dict[str, Any] = json.load(f)

        for area_id, entity_id in data.items():
            if not isinstance(entity_id, str) or not entity_id.startswith("media_player."):
                raise ValueError(
                    f"Entidade invalida para area '{area_id}': "
                    f"deve comecar com 'media_player.'"
                )

        return data

    def resolve_media_player(self, area_id: str, areas_map: dict[str, str]) -> str:
        """Retorna entity_id do media_player para o area_id informado."""
        entity = areas_map.get(area_id)
        if not entity:
            raise KeyError(area_id)
        return entity

    def ensure_audio_dir(self) -> None:
        """Garante que o diretorio de audios temporarios existe."""
        AUDIO_DIR.mkdir(parents=True, exist_ok=True)

    def llm_api_key_configured(self) -> bool:
        """True se a chave do provedor LLM ativo estiver definida."""
        if self.llm_provider == "deepseek":
            return bool(self.deepseek_api_key.strip())
        return bool(self.gemini_api_key.strip())


def get_settings() -> Settings:
    """Recarrega o .env a cada chamada (alteracoes sem reiniciar o processo)."""
    return Settings()


def setup_logging() -> None:
    """Configura logging no terminal sem expor segredos."""
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
