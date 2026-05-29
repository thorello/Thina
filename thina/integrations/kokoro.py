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

from thina.core.config import AUDIO_DIR, get_settings
from thina.core.tts_settings import FALLBACK_VOICES, get_effective_tts_settings
from thina.speech.normalize import preparar_texto_para_voz

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


async def listar_vozes() -> list[str]:
    """Lista vozes disponíveis no Kokoro; fallback estático se indisponível."""
    settings = get_settings()
    url = f"{settings.kokoro_server_url}/voices"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)
    except httpx.RequestError as exc:
        logger.debug("Kokoro /voices indisponível: %s", exc)
        return list(FALLBACK_VOICES)

    if response.status_code >= 400:
        logger.debug("Kokoro /voices retornou %s", response.status_code)
        return list(FALLBACK_VOICES)

    try:
        data = response.json()
    except ValueError:
        return list(FALLBACK_VOICES)

    voices = data.get("voices", [])
    if not isinstance(voices, list) or not voices:
        return list(FALLBACK_VOICES)

    result = [str(v).strip() for v in voices if str(v).strip()]
    return sorted(set(result)) if result else list(FALLBACK_VOICES)


async def sintetizar(texto: str) -> AudioResult:
    """
    Envia o texto final para o Kokoro e grava o WAV em data/audio/.

    Retorna caminho local e URL publica (THINA_PUBLIC_URL/v1/audio/{id}.wav).
    """
    settings = get_settings()
    tts = get_effective_tts_settings()
    settings.ensure_audio_dir()

    texto = preparar_texto_para_voz(texto)
    if not texto:
        raise KokoroResponseError("Texto vazio apos preparacao para voz.")

    audio_id = uuid.uuid4().hex
    local_path = AUDIO_DIR / f"{audio_id}.wav"

    payload: dict[str, object] = {
        "text": texto,
        "voice": tts.voice,
        "speed": tts.speed,
        "sentiment": tts.sentiment,
        "mix_amount": tts.mix_amount,
    }
    mix_voice = (tts.mix_voice or "").strip()
    mix_amount = float(tts.mix_amount)
    if mix_amount > 0:
        if not mix_voice:
            logger.warning(
                "mix_amount=%.2f mas mix_voice vazio; Kokoro ignora a mistura.",
                mix_amount,
            )
        else:
            payload["mix_voice"] = mix_voice

    url = f"{settings.kokoro_server_url}/generate"
    if mix_voice and mix_amount > 0:
        logger.info(
            "Sintetizando voz via Kokoro (%d caracteres): %s + %.0f%% %s",
            len(texto),
            tts.voice,
            mix_amount * 100,
            mix_voice,
        )
    else:
        logger.info("Sintetizando voz via Kokoro (%d caracteres): %s", len(texto), tts.voice)

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
