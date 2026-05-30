"""
Controle de reproducao do Spotify (ou player de midia ativo) no PC Windows.

Usa teclas globais de midia (play/pause, proxima, anterior) — funciona com o app
Spotify em segundo plano quando ele e a sessao de midia ativa do Windows.
Requer PC_COMMANDS_ENABLED=true (mesmo flag dos apps do PC).
"""

from __future__ import annotations

import asyncio
import ctypes
import logging
import sys
from typing import Any, Literal

from thina.core.config import get_settings
from thina.pc.actions import _limpar_texto_stt

logger = logging.getLogger(__name__)

SpotifyAcao = Literal["pausar", "tocar", "proxima", "anterior"]

# Virtual-key codes (winuser.h)
_VK_MEDIA_PLAY_PAUSE = 0xB3
_VK_MEDIA_NEXT_TRACK = 0xB0
_VK_MEDIA_PREV_TRACK = 0xB1
_KEYEVENTF_KEYUP = 0x0002

_ACAO_VK: dict[SpotifyAcao, int] = {
    "pausar": _VK_MEDIA_PLAY_PAUSE,
    "tocar": _VK_MEDIA_PLAY_PAUSE,
    "proxima": _VK_MEDIA_NEXT_TRACK,
    "anterior": _VK_MEDIA_PREV_TRACK,
}

_MUSIC_CONTEXT = (
    "spotify",
    "musica",
    "música",
    "faixa",
    "som ",
    " som",
    "playlist",
)

_PAUSE_PHRASES = (
    "pausa ",
    "pausa o",
    "pausa a",
    "pausar",
    "pause ",
    "parar a musica",
    "parar a música",
    "parar o spotify",
    "para a musica",
    "para a música",
    "para o spotify",
    "para de tocar",
    "interrompe",
    "interromper",
)

_PLAY_PHRASES = (
    "continua",
    "continuar",
    "retoma",
    "retomar",
    "despausa",
    "despausar",
    "toca ",
    "toca a",
    "toca o",
    "tocar ",
    "play ",
    "da play",
    "dá play",
    "volta a tocar",
)

_NEXT_PHRASES = (
    "proxima musica",
    "próxima música",
    "proxima faixa",
    "próxima faixa",
    "musica seguinte",
    "música seguinte",
    "pula ",
    "pular ",
    "pula a",
    "pula essa",
    "pula essa musica",
    "pula essa música",
    "passa ",
    "passa para",
    "passa pra",
    "avanca",
    "avança",
    "skip",
    "next ",
)

_PREV_PHRASES = (
    "musica anterior",
    "música anterior",
    "faixa anterior",
    "volta a musica",
    "volta a música",
    "musica de volta",
    "música de volta",
    "anterior ",
    "previous",
)


def _tem_contexto_musica(texto: str) -> bool:
    return any(ctx in texto for ctx in _MUSIC_CONTEXT)


def _match_any(texto: str, phrases: tuple[str, ...]) -> bool:
    return any(p in texto for p in phrases)


def detectar_acao_spotify(texto: str) -> SpotifyAcao | None:
    """
    Detecta comando de midia (pausar, tocar, proxima, anterior) a partir do STT.

    Exige contexto de musica/spotify para evitar falsos positivos.
    """
    t = _limpar_texto_stt(texto)
    if not _tem_contexto_musica(t):
        return None

    # Ordem: play explicito antes de pause (despausa contem "pausa")
    if _match_any(t, _PLAY_PHRASES):
        return "tocar"
    if _match_any(t, _NEXT_PHRASES):
        return "proxima"
    if _match_any(t, _PREV_PHRASES):
        return "anterior"
    if _match_any(t, _PAUSE_PHRASES):
        return "pausar"

    # Atalhos curtos com spotify no texto
    if "spotify" in t:
        if t in ("spotify", "abre spotify"):
            return None
        if any(w in t for w in ("proxima", "próxima", "pula", "skip", "seguinte")):
            return "proxima"
        if "anterior" in t or "volta" in t:
            return "anterior"
        if any(w in t for w in ("pausa", "pause", "parar", "para ")):
            return "pausar"
        if any(w in t for w in ("toca", "play", "continua", "retoma")):
            return "tocar"

    return None


def _send_media_key(vk: int) -> None:
    user32 = ctypes.windll.user32
    user32.keybd_event(vk, 0, 0, 0)
    user32.keybd_event(vk, 0, _KEYEVENTF_KEYUP, 0)


def _controlar_sync(acao: SpotifyAcao) -> dict[str, Any]:
    if sys.platform != "win32":
        return {
            "ok": False,
            "erro": "Controle do Spotify so esta disponivel no Windows.",
        }

    vk = _ACAO_VK.get(acao)
    if vk is None:
        return {"ok": False, "erro": f"Acao invalida: {acao}"}

    try:
        _send_media_key(vk)
    except Exception as exc:
        logger.exception("Falha ao enviar tecla de midia (%s)", acao)
        return {"ok": False, "erro": str(exc), "acao": acao}

    logger.info("Spotify/midia PC: acao=%s (vk=0x%02X)", acao, vk)
    return {"ok": True, "acao": acao}


async def controlar_spotify(acao: SpotifyAcao) -> dict[str, Any]:
    settings = get_settings()
    if not settings.pc_commands_enabled:
        return {
            "ok": False,
            "erro": "Comandos do PC desativados. Defina PC_COMMANDS_ENABLED=true no .env.",
        }

    acao_norm = acao.strip().lower()
    if acao_norm not in _ACAO_VK:
        return {
            "ok": False,
            "erro": f"Acao '{acao}' invalida. Use: pausar, tocar, proxima, anterior.",
        }

    return await asyncio.to_thread(_controlar_sync, acao_norm)  # type: ignore[arg-type]


def _resposta_voz_spotify(result: dict[str, Any]) -> str:
    if not result.get("ok"):
        erro = str(result.get("erro", "não foi possível controlar a música"))
        return f"Desculpe, não consegui controlar o Spotify: {erro}"

    acao = result.get("acao", "")
    mensagens = {
        "pausar": "Pronto, pausei a música.",
        "tocar": "Pronto, continuei a reprodução.",
        "proxima": "Pulei para a próxima faixa.",
        "anterior": "Voltei para a faixa anterior.",
    }
    return mensagens.get(acao, "Pronto, comando de música enviado.")


async def try_spotify_fastpath(texto: str) -> str | None:
    """Executa controle de midia sem LLM quando o pedido e claro."""
    acao = detectar_acao_spotify(texto)
    if not acao:
        return None

    settings = get_settings()
    if not settings.pc_commands_enabled:
        logger.warning("Pedido Spotify detectado (%s) mas PC_COMMANDS_ENABLED=false", acao)
        return (
            "Para controlar o Spotify no computador, ative PC_COMMANDS_ENABLED=true "
            "no arquivo .env do servidor Thina e reinicie o serviço."
        )

    logger.info("Fast-path Spotify: %s (texto STT: %s)", acao, texto[:80])
    result = await controlar_spotify(acao)
    return _resposta_voz_spotify(result)
