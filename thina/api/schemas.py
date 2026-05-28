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


class ConversarResponse(BaseModel):
    resposta: str
    audio_url: str
    area_id: str
    media_player: str
    session_id: str
