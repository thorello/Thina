"""
Historico multi-turno em memoria (por session_id).

Usado pelo POST /v1/conversar: o cliente mantem o mesmo session_id ate dizer
'Tina' de novo (nova_sessao=True).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from config import get_settings

_lock = asyncio.Lock()


@dataclass
class _SessionState:
    turns: list[dict[str, str]] = field(default_factory=list)
    updated_at: float = field(default_factory=time.time)


_sessions: dict[str, _SessionState] = {}


def _prune_expired() -> None:
    ttl = get_settings().conversation_ttl_seconds
    if ttl <= 0:
        return
    now = time.time()
    expired = [sid for sid, st in _sessions.items() if now - st.updated_at > ttl]
    for sid in expired:
        _sessions.pop(sid, None)


def _trim_turns(turns: list[dict[str, str]]) -> list[dict[str, str]]:
    max_turns = get_settings().conversation_max_turns
    if max_turns <= 0:
        return turns
    # Cada turno do usuario + resposta = 2 entradas
    max_entries = max_turns * 2
    if len(turns) <= max_entries:
        return turns
    return turns[-max_entries:]


async def get_historico(session_id: str) -> list[dict[str, str]]:
    """Copia do historico da sessao (vazio se expirada ou inexistente)."""
    async with _lock:
        _prune_expired()
        state = _sessions.get(session_id)
        if not state:
            return []
        return list(state.turns)


async def clear_session(session_id: str) -> None:
    async with _lock:
        _sessions.pop(session_id, None)


async def append_turn(session_id: str, texto_usuario: str, resposta: str) -> None:
    async with _lock:
        _prune_expired()
        state = _sessions.setdefault(session_id, _SessionState())
        state.turns.append({"role": "user", "content": texto_usuario})
        state.turns.append({"role": "assistant", "content": resposta})
        state.turns = _trim_turns(state.turns)
        state.updated_at = time.time()
