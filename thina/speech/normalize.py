"""
Normaliza texto da Thina para sintese de voz (Kokoro).

Remove markdown e emojis que o TTS costuma ler em voz alta ("asteriscos", nomes de emoji).
"""

from __future__ import annotations

import re
import unicodedata

# Blocos comuns de emoji / pictogramas (inclui 🎵 e similares)
_RE_EMOJI = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002700-\U000027BF"
    "\U00002600-\U000026FF"
    "\U00002300-\U000023FF"
    "\U00002B50"
    "\U0000FE0F"
    "\U0000200D"
    "\u00A9\u00AE\u2122"
    "]",
    flags=re.UNICODE,
)

_RE_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_RE_BOLD = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_RE_ITALIC_STAR = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", re.DOTALL)
_RE_BOLD_UNDER = re.compile(r"__(.+?)__", re.DOTALL)
_RE_ITALIC_UNDER = re.compile(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)", re.DOTALL)
_RE_INLINE_CODE = re.compile(r"`([^`]+)`")
_RE_HEADING = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_RE_BULLET = re.compile(r"^[\s]*[-*+]\s+", re.MULTILINE)


def preparar_texto_para_voz(texto: str) -> str:
    """Texto limpo para TTS: sem markdown nem emojis."""
    if not texto:
        return texto

    t = texto.strip()
    t = _RE_HEADING.sub("", t)
    t = _RE_BULLET.sub("", t)
    t = _RE_LINK.sub(r"\1", t)
    t = _RE_BOLD.sub(r"\1", t)
    t = _RE_BOLD_UNDER.sub(r"\1", t)
    t = _RE_ITALIC_STAR.sub(r"\1", t)
    t = _RE_ITALIC_UNDER.sub(r"\1", t)
    t = _RE_INLINE_CODE.sub(r"\1", t)
    t = t.replace("**", "").replace("__", "").replace("`", "")
    t = _RE_EMOJI.sub("", t)
    t = "".join(ch for ch in t if unicodedata.category(ch) != "So")
    t = re.sub(r"\s{2,}", " ", t)
    return t.strip()


__all__ = ["preparar_texto_para_voz"]
