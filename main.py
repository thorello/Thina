"""
Servidor central Thina — ponto de entrada FastAPI.

Fluxo POST /v1/conversar:
  Home Assistant (texto STT + area_id)
    -> Gemini + MCP (casa)
    -> Kokoro TTS (WAV)
    -> media_player.play_media no ReSpeaker do comodo
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from config import AUDIO_DIR, get_settings, setup_logging
from services.gemini_mcp import processar_mensagem
from services.ha_client import (
    HAAuthError,
    HAConnectionError,
    HAError,
    get_ha_client,
)
from services.tts_kokoro import (
    KokoroConnectionError,
    KokoroError,
    KokoroResponseError,
    sintetizar,
)

logger = logging.getLogger(__name__)

# Mapa area_id -> media_player carregado no startup
_areas_map: dict[str, str] = {}


class ConversarRequest(BaseModel):
    """Corpo da requisicao enviada pelo Home Assistant apos STT."""

    texto: str = Field(..., min_length=1, description="Texto transcrito pelo Whisper")
    area_id: str = Field(..., min_length=1, description="Identificador do comodo de origem")
    session_id: str | None = Field(None, description="Reservado para historico multi-turno")


class ConversarResponse(BaseModel):
    resposta: str
    audio_url: str
    area_id: str
    media_player: str


def _cleanup_old_audio() -> None:
    """Remove WAV temporarios mais antigos que audio_retention_hours."""
    settings = get_settings()
    if not AUDIO_DIR.exists():
        return

    max_age = settings.audio_retention_hours * 3600
    now = time.time()
    removed = 0

    for path in AUDIO_DIR.glob("*.wav"):
        try:
            if now - path.stat().st_mtime > max_age:
                path.unlink(missing_ok=True)
                removed += 1
        except OSError as exc:
            logger.warning("Falha ao remover %s: %s", path.name, exc)

    if removed:
        logger.debug("Limpeza de audio: %d arquivo(s) removido(s)", removed)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: carrega mapa de areas, garante pastas e aquece cliente HA."""
    global _areas_map
    setup_logging()
    settings = get_settings()
    settings.ensure_audio_dir()

    llm_model = (
        settings.deepseek_model
        if settings.llm_provider == "deepseek"
        else settings.gemini_model
    )
    logger.info(
        "LLM ativo: provider=%s | model=%s | chave_ok=%s",
        settings.llm_provider,
        llm_model,
        settings.llm_api_key_configured(),
    )

    try:
        _areas_map = settings.load_areas_map()
        logger.info("Mapa de areas carregado: %s", list(_areas_map.keys()))
    except (FileNotFoundError, ValueError) as exc:
        logger.error("Erro ao carregar mapa de areas: %s", exc)
        raise

    _cleanup_old_audio()
    yield

    ha = get_ha_client()
    await ha.close()
    logger.info("Servidor Thina encerrado.")


app = FastAPI(
    title="Thina — Assistente de Voz Residencial",
    description="Servidor central: Gemini MCP + Kokoro TTS + Home Assistant",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health() -> dict[str, str]:
    settings = get_settings()
    llm_model = (
        settings.deepseek_model
        if settings.llm_provider == "deepseek"
        else settings.gemini_model
    )
    return {
        "status": "ok",
        "service": "thina",
        "llm_provider": settings.llm_provider,
        "llm_model": llm_model,
    }


@app.get("/v1/audio/{audio_id}.wav")
async def servir_audio(audio_id: str) -> FileResponse:
    """
    Expoe o WAV gerado pelo Kokoro para o Home Assistant baixar via play_media.

    O audio_id e o UUID sem extensao usado no nome do arquivo em data/audio/.
    """
    if not audio_id.replace("-", "").isalnum():
        raise HTTPException(status_code=400, detail="audio_id invalido")

    path = AUDIO_DIR / f"{audio_id}.wav"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Audio nao encontrado")

    return FileResponse(path, media_type="audio/wav", filename=f"{audio_id}.wav")


@app.post("/v1/conversar", response_model=ConversarResponse)
async def conversar(body: ConversarRequest, request: Request) -> ConversarResponse:
    """
    Endpoint principal: recebe texto do HA, processa com Thina e devolve audio no satelite.

    1. Resolve area_id -> media_player
    2. Gemini + MCP processa intencao e acoes na casa
    3. Kokoro sintetiza a resposta em WAV
    4. HA reproduz no ReSpeaker do comodo
    """
    settings = get_settings()

    try:
        media_player = settings.resolve_media_player(body.area_id, _areas_map)
    except KeyError:
        raise HTTPException(
            status_code=400,
            detail=f"area_id desconhecido: '{body.area_id}'. "
            f"Areas validas: {list(_areas_map.keys())}",
        ) from None

    logger.info(
        "Conversa | area=%s | player=%s | texto=%s",
        body.area_id,
        media_player,
        body.texto[:80] + ("..." if len(body.texto) > 80 else ""),
    )

    # --- Etapa 2: Gemini + MCP ---
    try:
        resposta_texto = await processar_mensagem(body.texto, body.area_id)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Falha no LLM/MCP")
        detail = str(exc).strip() or "Falha ao processar mensagem com o assistente."
        raise HTTPException(status_code=503, detail=detail) from exc

    # --- Etapa 3: Kokoro TTS ---
    try:
        audio = await sintetizar(resposta_texto)
    except KokoroConnectionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except KokoroResponseError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except KokoroError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    # --- Etapa 4: Reproduzir no ReSpeaker via HA ---
    ha = get_ha_client()
    try:
        await ha.play_media(media_player, audio.public_url)
    except HAConnectionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except HAAuthError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except HAError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    _cleanup_old_audio()

    return ConversarResponse(
        resposta=resposta_texto,
        audio_url=audio.public_url,
        area_id=body.area_id,
        media_player=media_player,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Erro nao tratado em %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Erro interno do servidor."},
    )


def main() -> None:
    settings = get_settings()
    setup_logging()
    uvicorn.run(
        "main:app",
        host=settings.thina_host,
        port=settings.thina_port,
        reload=False,
    )


if __name__ == "__main__":
    main()
