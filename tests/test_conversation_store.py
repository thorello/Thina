"""Testes do historico multi-turno em memoria."""

from __future__ import annotations

import pytest

from services import conversation_store


@pytest.mark.asyncio
async def test_historico_vazio_para_sessao_nova() -> None:
    assert await conversation_store.get_historico("sessao-1") == []


@pytest.mark.asyncio
async def test_append_e_get_historico() -> None:
    sid = "sessao-abc"
    await conversation_store.append_turn(sid, "ola", "oi, como posso ajudar?")
    historico = await conversation_store.get_historico(sid)
    assert len(historico) == 2
    assert historico[0] == {"role": "user", "content": "ola"}
    assert historico[1]["role"] == "assistant"


@pytest.mark.asyncio
async def test_clear_session() -> None:
    sid = "sessao-clear"
    await conversation_store.append_turn(sid, "a", "b")
    await conversation_store.clear_session(sid)
    assert await conversation_store.get_historico(sid) == []


@pytest.mark.asyncio
async def test_trim_turns_respeita_limite(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONVERSATION_MAX_TURNS", "2")
    sid = "sessao-trim"
    for i in range(4):
        await conversation_store.append_turn(sid, f"pergunta {i}", f"resposta {i}")

    historico = await conversation_store.get_historico(sid)
    assert len(historico) == 4  # 2 turnos * 2 mensagens
    assert historico[0]["content"] == "pergunta 2"
    assert historico[-1]["content"] == "resposta 3"


@pytest.mark.asyncio
async def test_sessao_expira_por_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONVERSATION_TTL_SECONDS", "1")
    sid = "sessao-ttl"
    await conversation_store.append_turn(sid, "x", "y")

    state = conversation_store._sessions[sid]
    state.updated_at -= 10

    assert await conversation_store.get_historico(sid) == []
