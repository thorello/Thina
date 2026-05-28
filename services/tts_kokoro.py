"""
Integracao com o servidor Kokoro TTS (repositorio separado).

Fluxo: texto da Thina -> POST /generate no Kokoro -> WAV em disco -> URL publica para o HA.
"""

from __future__ import annotations

import base64
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path

import httpx

from config import AUDIO_DIR, get_settings

logger = logging.getLogger(__name__)


class KokoroError(Exception):
    """Erro base na sintese de voz."""


class KokoroConnectionError(KokoroError):
    """Kokoro indisponivel ou timeout."""


class KokoroResponseError(KokoroError):
    """Resposta invalida do servidor Kokoro."""


@dataclass
class AudioResult:
    """Resultado da sintese: arquivo local e URL para o Home Assistant."""

    audio_id: str
    local_path: Path
    public_url: str


async def sintetizar(texto: str) -> AudioResult:
    """
    Envia o texto final para o Kokoro e grava o WAV em data/audio/.

    Retorna caminho local e URL publica (THINA_PUBLIC_URL/v1/audio/{id}.wav).
    """
    settings = get_settings()
    settings.ensure_audio_dir()

    audio_id = uuid.uuid4().hex
    local_path = AUDIO_DIR / f"{audio_id}.wav"

    payload: dict[str, object] = {
        "text": texto,
        "voice": settings.kokoro_voice,
        "speed": settings.kokoro_speed,
        "sentiment": settings.kokoro_sentiment,
        "mix_amount": settings.kokoro_mix_amount,
    }
    mix_voice = (settings.kokoro_mix_voice or "").strip()
    mix_amount = float(settings.kokoro_mix_amount)
    if mix_amount > 0:
        if not mix_voice:
            logger.warning(
                "KOKORO_MIX_AMOUNT=%.2f mas KOKORO_MIX_VOICE vazio; Kokoro ignora a mistura.",
                mix_amount,
            )
        else:
            payload["mix_voice"] = mix_voice

    url = f"{settings.kokoro_server_url}/generate"
    if mix_voice and mix_amount > 0:
        logger.info(
            "Sintetizando voz via Kokoro (%d caracteres): %s + %.0f%% %s",
            len(texto),
            settings.kokoro_voice,
            mix_amount * 100,
            mix_voice,
        )
    else:
        logger.info("Sintetizando voz via Kokoro (%d caracteres): %s", len(texto), settings.kokoro_voice)

    try:
        async with httpx.AsyncClient(timeout=settings.kokoro_timeout) as client:
            response = await client.post(url, json=payload)
    except httpx.TimeoutException as exc:
        raise KokoroConnectionError(
            "Timeout ao contactar o servidor Kokoro. Verifique KOKORO_SERVER_URL."
        ) from exc
    except httpx.RequestError as exc:
        raise KokoroConnectionError(
            f"Nao foi possivel ligar ao Kokoro: {exc}"
        ) from exc

    if response.status_code == 503:
        raise KokoroConnectionError("Kokoro retornou 503: modelo nao carregado.")

    if response.status_code >= 400:
        raise KokoroResponseError(
            f"Kokoro retornou {response.status_code}: {response.text[:300]}"
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise KokoroResponseError("Resposta do Kokoro nao e JSON valido.") from exc

    if "error" in data:
        raise KokoroResponseError(f"Kokoro: {data['error']}")

    audio_b64 = data.get("audio")
    if not audio_b64:
        raise KokoroResponseError("Campo 'audio' ausente na resposta do Kokoro.")

    try:
        wav_bytes = base64.b64decode(audio_b64)
    except (ValueError, TypeError) as exc:
        raise KokoroResponseError("Audio base64 invalido no retorno do Kokoro.") from exc

    local_path.write_bytes(wav_bytes)
    public_url = f"{settings.thina_public_url}/v1/audio/{audio_id}.wav"

    logger.info("Audio gerado: %s (%d bytes)", local_path.name, len(wav_bytes))
    return AudioResult(audio_id=audio_id, local_path=local_path, public_url=public_url)
