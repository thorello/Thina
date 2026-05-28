"""Integracoes externas (Home Assistant, Kokoro TTS)."""

from thina.integrations.homeassistant import (
    HAAuthError,
    HAConnectionError,
    HAError,
    HANotFoundError,
    HomeAssistantClient,
    get_ha_client,
)
from thina.integrations.kokoro import (
    AudioResult,
    KokoroConnectionError,
    KokoroError,
    KokoroResponseError,
    sintetizar,
)

__all__ = [
    "AudioResult",
    "HAAuthError",
    "HAConnectionError",
    "HAError",
    "HANotFoundError",
    "HomeAssistantClient",
    "KokoroConnectionError",
    "KokoroError",
    "KokoroResponseError",
    "get_ha_client",
    "sintetizar",
]
