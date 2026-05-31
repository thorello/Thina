"""
Aplicacao FastAPI do servidor Thina.

Fluxo POST /v1/conversar:
  Home Assistant (texto STT + area_id)
    -> LLM + MCP (casa)
    -> Kokoro TTS (WAV)
    -> media_player.play_media no ReSpeaker do comodo
"""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from thina.api.google_setup import render_google_setup_page
from thina.api.schemas import (
    ConversarRequest,
    ConversarResponse,
    TtsSettingsResponse,
    TtsSettingsUpdate,
)
from thina.core.config import AUDIO_DIR, BASE_DIR, get_settings, setup_logging
from thina.core.tts_settings import (
    get_effective_tts_settings,
    save_tts_overrides,
    voice_label,
)
from thina.core.conversation import append_turn, clear_session, get_historico
from thina.integrations.google import (
    GoogleAuthError,
    GoogleNotConfiguredError,
    begin_web_oauth,
    complete_web_oauth,
    google_status,
    needs_reauth,
    token_path,
)
from thina.integrations.homeassistant import (
    HAAuthError,
    HAConnectionError,
    HAError,
    get_ha_client,
)
from thina.integrations.kokoro import (
    KokoroConnectionError,
    KokoroError,
    KokoroResponseError,
    listar_vozes,
    sintetizar,
)
from thina.llm.gemini_mcp import processar_mensagem

logger = logging.getLogger(__name__)

_areas_map: dict[str, str] = {}


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

UI_DIST = BASE_DIR / "ui" / "dist"

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/v1/areas")
async def list_areas() -> dict[str, list[str]]:
    """Lista area_id validos (maps/areas.json) para a interface web."""
    return {"areas": sorted(_areas_map.keys())}


@app.get("/")
async def root():
    """Redireciona para o painel web quando o build da UI existir."""
    if UI_DIST.is_dir() and (UI_DIST / "index.html").is_file():
        return RedirectResponse(url="/ui/", status_code=302)
    return {
        "service": "thina",
        "docs": "/docs",
        "ui": "Execute npm run build em ui/ e reinicie o servidor.",
    }


@app.get("/v1/google/status")
async def google_integration_status() -> dict:
    """Estado da integracao Google (Gmail, Drive, Calendar)."""
    return google_status()


@app.get("/v1/google/setup", response_class=HTMLResponse)
async def google_setup_page(
    ok: int | None = Query(default=None),
    error: str | None = Query(default=None),
) -> HTMLResponse:
    """Pagina amigavel para conectar a conta Google (sem linha de comando)."""
    result = "ok" if ok else None
    return HTMLResponse(render_google_setup_page(result=result, error=error))


@app.get("/v1/google/connect")
async def google_connect(force: bool = Query(default=False)) -> RedirectResponse:
    """Redireciona o navegador para autorizacao Google."""
    status = google_status()
    if not status["enabled"]:
        return RedirectResponse(
            url="/v1/google/setup?error=Integracao+Google+desativada",
            status_code=302,
        )
    if not status["configured"]:
        return RedirectResponse(
            url="/v1/google/setup?error=Credenciais+OAuth+nao+configuradas",
            status_code=302,
        )
    if force or needs_reauth():
        token_path().unlink(missing_ok=True)
    try:
        url = begin_web_oauth()
    except (GoogleNotConfiguredError, GoogleAuthError) as exc:
        msg = str(exc).replace(" ", "+")
        return RedirectResponse(url=f"/v1/google/setup?error={msg}", status_code=302)
    return RedirectResponse(url=url, status_code=302)


@app.get("/v1/google/oauth/callback")
async def google_oauth_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> RedirectResponse:
    """Callback OAuth apos o usuario autorizar no Google."""
    if error:
        return RedirectResponse(
            url=f"/v1/google/setup?error={error.replace(' ', '+')}",
            status_code=302,
        )
    if not code or not state:
        return RedirectResponse(
            url="/v1/google/setup?error=Resposta+incompleta+do+Google",
            status_code=302,
        )
    try:
        complete_web_oauth(state=state, code=code)
    except GoogleAuthError as exc:
        msg = str(exc).replace(" ", "+")
        return RedirectResponse(url=f"/v1/google/setup?error={msg}", status_code=302)
    return RedirectResponse(url="/v1/google/setup?ok=1", status_code=302)


@app.get("/health")
async def health() -> dict[str, str | list[str] | bool]:
    settings = get_settings()
    llm_model = (
        settings.deepseek_model
        if settings.llm_provider == "deepseek"
        else settings.gemini_model
    )
    tts = get_effective_tts_settings()

    ha_ok = False
    if settings.home_assistant_token:
        try:
            ha = get_ha_client()
            await ha.get_states()
            ha_ok = True
        except Exception as exc:
            logger.debug("Health: HA indisponivel: %s", exc)

    return {
        "status": "ok",
        "service": "thina",
        "llm_provider": settings.llm_provider,
        "llm_model": llm_model,
        "kokoro_voice": voice_label(tts),
        "kokoro_speed": str(tts.speed),
        "kokoro_mix_voice": tts.mix_voice or "",
        "kokoro_mix_amount": str(tts.mix_amount),
        "kokoro_sentiment": tts.sentiment,
        "areas": sorted(_areas_map.keys()),
        "ha_ok": ha_ok,
        "ha_url": settings.home_assistant_url,
    }


@app.get("/v1/tts/settings", response_model=TtsSettingsResponse)
async def get_tts_settings() -> TtsSettingsResponse:
    """Configuração efetiva de voz (env + overrides da UI) e lista de vozes Kokoro."""
    tts = get_effective_tts_settings()
    voices = await listar_vozes()
    for name in (tts.voice, tts.mix_voice):
        if name and name not in voices:
            voices.append(name)
    voices.sort()
    return TtsSettingsResponse(
        voice=tts.voice,
        mix_voice=tts.mix_voice,
        mix_amount=tts.mix_amount,
        speed=tts.speed,
        sentiment=tts.sentiment,
        voices=voices,
    )


@app.put("/v1/tts/settings", response_model=TtsSettingsResponse)
async def update_tts_settings(body: TtsSettingsUpdate) -> TtsSettingsResponse:
    """Atualiza voz, mistura e velocidade (persistido em data/tts_settings.json)."""
    try:
        tts = save_tts_overrides(
            voice=body.voice,
            mix_voice=body.mix_voice,
            mix_amount=body.mix_amount,
            speed=body.speed,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    voices = await listar_vozes()
    for name in (tts.voice, tts.mix_voice):
        if name and name not in voices:
            voices.append(name)
    voices.sort()
    return TtsSettingsResponse(
        voice=tts.voice,
        mix_voice=tts.mix_voice,
        mix_amount=tts.mix_amount,
        speed=tts.speed,
        sentiment=tts.sentiment,
        voices=voices,
    )


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
    2. LLM + MCP processa intencao e acoes na casa
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

    session_id = body.session_id or str(uuid.uuid4())
    if body.nova_sessao:
        await clear_session(session_id)
    historico = await get_historico(session_id)

    logger.info(
        "Conversa | area=%s | player=%s | session=%s | turnos=%d | nova=%s | texto=%s",
        body.area_id,
        media_player,
        session_id[:8],
        len(historico) // 2,
        body.nova_sessao,
        body.texto[:80] + ("..." if len(body.texto) > 80 else ""),
    )

    try:
        resposta_texto = await processar_mensagem(
            body.texto, body.area_id, historico=historico or None
        )
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

    try:
        audio = await sintetizar(resposta_texto)
    except KokoroConnectionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except KokoroResponseError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except KokoroError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if body.reproduzir_ha:
        ha = get_ha_client()
        try:
            await ha.play_media(media_player, audio.public_url)
        except HAConnectionError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except HAAuthError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except HAError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    else:
        logger.info(
            "reproduzir_ha=false — audio em %s (sem play_media no %s)",
            audio.public_url,
            media_player,
        )

    await append_turn(session_id, body.texto, resposta_texto)
    _cleanup_old_audio()

    return ConversarResponse(
        resposta=resposta_texto,
        audio_url=audio.public_url,
        area_id=body.area_id,
        media_player=media_player,
        session_id=session_id,
    )


if UI_DIST.is_dir() and (UI_DIST / "index.html").is_file():
    app.mount(
        "/ui",
        StaticFiles(directory=str(UI_DIST), html=True),
        name="thina-ui",
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
        "thina.api.app:app",
        host=settings.thina_host,
        port=settings.thina_port,
        reload=False,
    )
