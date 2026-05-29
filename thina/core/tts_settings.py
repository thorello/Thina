"""
Configuração de voz TTS (Kokoro) com overrides persistidos em data/tts_settings.json.

Valores do .env servem como padrão; alterações pela UI sobrescrevem até reiniciar
ou gravar novamente (o arquivo persiste entre reinícios).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from thina.core.config import BASE_DIR, get_settings

logger = logging.getLogger(__name__)

TTS_SETTINGS_FILE = BASE_DIR / "data" / "tts_settings.json"

FALLBACK_VOICES = [
    "thina_mix",
    "pf_dora",
    "af_bella",
    "if_sara",
    "af_heart",
    "am_adam",
    "am_michael",
    "bf_emma",
    "bf_isabella",
    "bm_george",
    "bm_lewis",
    "jf_alpha",
    "jf_gongitsune",
    "jf_nezumi",
    "jf_tebukuro",
    "jm_kumo",
    "zf_xiaobei",
    "zf_xiaoni",
    "zf_xiaoxiao",
    "zf_xiaoyi",
    "zm_yunjian",
    "zm_yunxi",
    "zm_yunxia",
    "zm_yunyang",
]


@dataclass(frozen=True)
class EffectiveTtsSettings:
    voice: str
    mix_voice: str | None
    mix_amount: float
    speed: float
    sentiment: str


def _normalize_mix_voice(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def load_tts_overrides() -> dict[str, object]:
    """Carrega overrides do JSON; retorna {} se ausente ou inválido."""
    if not TTS_SETTINGS_FILE.is_file():
        return {}
    try:
        raw = json.loads(TTS_SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Não foi possível ler %s: %s", TTS_SETTINGS_FILE, exc)
        return {}
    if not isinstance(raw, dict):
        return {}
    return raw


def get_effective_tts_settings() -> EffectiveTtsSettings:
    """Mescla .env com overrides persistidos."""
    settings = get_settings()
    overrides = load_tts_overrides()

    voice = str(overrides.get("voice", settings.kokoro_voice)).strip() or settings.kokoro_voice

    if "mix_voice" in overrides:
        mix_voice_raw = overrides["mix_voice"]
        mix_voice = _normalize_mix_voice(
            str(mix_voice_raw) if mix_voice_raw is not None else None
        )
    else:
        mix_voice = settings.kokoro_mix_voice

    if "mix_amount" in overrides:
        mix_amount = float(overrides["mix_amount"])
    else:
        mix_amount = float(settings.kokoro_mix_amount)

    if "speed" in overrides:
        speed = float(overrides["speed"])
    else:
        speed = float(settings.kokoro_speed)

    sentiment = str(overrides.get("sentiment", settings.kokoro_sentiment)).strip()
    if not sentiment:
        sentiment = settings.kokoro_sentiment

    mix_amount = max(0.0, min(1.0, mix_amount))
    speed = max(0.5, min(2.0, speed))

    return EffectiveTtsSettings(
        voice=voice,
        mix_voice=mix_voice,
        mix_amount=mix_amount,
        speed=speed,
        sentiment=sentiment,
    )


def save_tts_overrides(
    *,
    voice: str,
    mix_voice: str | None,
    mix_amount: float,
    speed: float,
) -> EffectiveTtsSettings:
    """Persiste overrides e retorna configuração efetiva."""
    voice = voice.strip()
    if not voice:
        raise ValueError("Voz principal não pode ser vazia.")

    mix_voice = _normalize_mix_voice(mix_voice)
    mix_amount = max(0.0, min(1.0, float(mix_amount)))
    speed = max(0.5, min(2.0, float(speed)))

    if mix_amount <= 0:
        mix_voice = None

    payload = {
        "voice": voice,
        "mix_voice": mix_voice,
        "mix_amount": mix_amount,
        "speed": speed,
    }

    TTS_SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    TTS_SETTINGS_FILE.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    logger.info(
        "TTS atualizado: %s%s speed=%.2f",
        voice,
        f" + {mix_amount:.0%} {mix_voice}" if mix_voice and mix_amount > 0 else "",
        speed,
    )
    return get_effective_tts_settings()


def voice_label(settings: EffectiveTtsSettings) -> str:
    """Rótulo legível para health/UI."""
    if settings.mix_voice and settings.mix_amount > 0:
        return f"{settings.voice}+{settings.mix_amount:.0%}_{settings.mix_voice}"
    return settings.voice
