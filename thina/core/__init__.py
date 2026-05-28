"""Configuracao e estado de conversa multi-turno."""

from thina.core.config import AUDIO_DIR, BASE_DIR, Settings, get_settings, setup_logging
from thina.core.conversation import append_turn, clear_session, get_historico

__all__ = [
    "AUDIO_DIR",
    "BASE_DIR",
    "Settings",
    "append_turn",
    "clear_session",
    "get_historico",
    "get_settings",
    "setup_logging",
]
