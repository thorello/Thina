"""Modelos Pydantic da API HTTP."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ConversarRequest(BaseModel):
    """Corpo da requisicao enviada pelo Home Assistant apos STT."""

    texto: str = Field(..., min_length=1, description="Texto transcrito pelo Whisper")
    area_id: str = Field(..., min_length=1, description="Identificador do comodo de origem")
    session_id: str | None = Field(
        None,
        description="Identificador da conversa; reutilize ate nova_sessao ou timeout",
    )
    nova_sessao: bool = Field(
        False,
        description="True ao dizer 'Tina' de novo: limpa historico e inicia conversa nova",
    )
    reproduzir_ha: bool = Field(
        True,
        description="False no painel web: devolve texto/audio sem media_player.play_media no HA",
    )


class ConversarResponse(BaseModel):
    resposta: str
    audio_url: str
    area_id: str
    media_player: str
    session_id: str


class TtsSettingsResponse(BaseModel):
    voice: str
    mix_voice: str | None
    mix_amount: float
    speed: float
    sentiment: str
    voices: list[str]


class TtsSettingsUpdate(BaseModel):
    voice: str = Field(..., min_length=1, description="Voz principal Kokoro")
    mix_voice: str | None = Field(None, description="Segunda voz para mistura")
    mix_amount: float = Field(0.0, ge=0.0, le=1.0, description="Proporção da 2ª voz (0–1)")
    speed: float = Field(1.0, ge=0.5, le=2.0, description="Velocidade da fala")
