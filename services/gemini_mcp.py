"""
Gemini 1.5 Flash + servidor MCP (FastMCP) para acoes na casa.

Este modulo tem duas funcoes:
  1) Servidor MCP (stdio): ferramentas @mcp.tool que falam com o Home Assistant.
  2) Orquestrador: processar_mensagem() liga o Gemini ao subprocess MCP.

Fluxo: texto do usuario -> Gemini -> (auto) tool calls MCP -> HA REST -> texto Thina.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any, Literal

from fastmcp import FastMCP
from google import genai
from google.genai import types
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from config import BASE_DIR, get_settings
from services.ha_client import (
    HAAuthError,
    HAConnectionError,
    HAError,
    HANotFoundError,
    get_ha_client,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Personalidade da Thina (system instruction para o Gemini)
# ---------------------------------------------------------------------------
THINA_SYSTEM_INSTRUCTION = """Voce e a Thina, assistente de voz residencial inteligente em portugues do Brasil.

Personalidade:
- Cordial, objetiva e natural, como uma assistente de casa de confianca.
- Respostas curtas e faladas (ideal para serem lidas em voz alta).
- Confirme antes de acoes que afetem seguranca (portas, alarmes, aquecedores a gas).
- Nunca invente estados de dispositivos: use sempre as ferramentas para ler sensores ou controlar a casa.

Regras:
- O usuario fala a partir de um comodo especifico (area_id); considere isso no contexto.
- Se nao souber uma entidade exata, use listar_entidades ou pergunte de forma breve.
- Apos executar acoes, resuma o que foi feito em uma frase amigavel.
- Se uma ferramenta falhar, explique o problema de forma simples, sem jargao tecnico.
"""

mcp = FastMCP("ThinaHome")


def _json_result(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# Ferramentas MCP expostas ao Gemini
# ---------------------------------------------------------------------------
@mcp.tool
async def controlar_dispositivo(
    entity_id: str,
    dominio: str,
    servico: str,
    dados_json: str = "",
) -> str:
    """
    Aciona um servico no Home Assistant (ex: light.turn_on, switch.turn_off).

    Args:
        entity_id: ID da entidade (ex: light.sala).
        dominio: Dominio do servico (ex: light).
        servico: Nome do servico (ex: turn_on).
        dados_json: JSON opcional com campos extras do servico (ex: {"brightness": 255}).
    """
    ha = get_ha_client()
    payload: dict[str, Any] = {}
    if dados_json.strip():
        try:
            parsed = json.loads(dados_json)
            if isinstance(parsed, dict):
                payload = parsed
        except json.JSONDecodeError:
            return _json_result({"ok": False, "erro": "dados_json invalido"})
    payload.setdefault("entity_id", entity_id)
    try:
        result = await ha.call_service(dominio, servico, payload)
        return _json_result({"ok": True, "entity_id": entity_id, "resultado": result})
    except HAError as exc:
        return _json_result({"ok": False, "erro": str(exc)})


@mcp.tool
async def ler_sensor(entity_id: str) -> str:
    """Le o estado atual e atributos de uma entidade do Home Assistant."""
    ha = get_ha_client()
    try:
        state = await ha.get_state(entity_id)
        return _json_result(
            {
                "entity_id": entity_id,
                "state": state.get("state"),
                "attributes": state.get("attributes", {}),
                "last_changed": state.get("last_changed"),
            }
        )
    except HANotFoundError:
        return _json_result({"ok": False, "erro": f"Entidade nao encontrada: {entity_id}"})
    except HAError as exc:
        return _json_result({"ok": False, "erro": str(exc)})


@mcp.tool
async def listar_entidades(
    dominio: str | None = None,
    area: str | None = None,
) -> str:
    """
    Lista entidades do Home Assistant, opcionalmente filtradas por dominio ou area.

    Args:
        dominio: Ex: light, switch, sensor, climate.
        area: Nome da area HA (area_id) para filtrar pelo atributo area_id.
    """
    ha = get_ha_client()
    try:
        states = await ha.get_states()
        entidades: list[dict[str, str]] = []
        for st in states:
            eid = st.get("entity_id", "")
            if dominio and not eid.startswith(f"{dominio}."):
                continue
            attrs = st.get("attributes") or {}
            if area:
                entity_area = attrs.get("area_id") or attrs.get("area")
                if entity_area != area:
                    continue
            entidades.append(
                {
                    "entity_id": eid,
                    "state": str(st.get("state", "")),
                    "friendly_name": str(attrs.get("friendly_name", eid)),
                }
            )
        return _json_result({"total": len(entidades), "entidades": entidades[:50]})
    except HAError as exc:
        return _json_result({"ok": False, "erro": str(exc)})


@mcp.tool
async def ligar_desligar(
    entity_id: str,
    acao: Literal["ligar", "desligar"],
) -> str:
    """Liga ou desliga uma entidade compativel com turn_on/turn_off."""
    ha = get_ha_client()
    try:
        if acao == "ligar":
            result = await ha.turn_on(entity_id)
        else:
            result = await ha.turn_off(entity_id)
        return _json_result({"ok": True, "entity_id": entity_id, "acao": acao, "resultado": result})
    except HAError as exc:
        return _json_result({"ok": False, "erro": str(exc)})


def _patch_gemini_mcp_schema_filter() -> None:
    """
    Corrige incompatibilidade google-genai + FastMCP 3.x:
    schemas com additionalProperties: false (bool) quebram _filter_to_supported_schema.
    """
    import google.genai._mcp_utils as mcp_utils

    if getattr(mcp_utils, "_thina_schema_patch", False):
        return

    original = mcp_utils._filter_to_supported_schema

    def filtered(schema: Any) -> Any:
        if not isinstance(schema, dict):
            return {}
        cleaned = {
            key: value
            for key, value in schema.items()
            if not (key == "additionalProperties" and isinstance(value, bool))
        }
        return original(cleaned)

    mcp_utils._filter_to_supported_schema = filtered
    mcp_utils._thina_schema_patch = True


def _build_user_prompt(texto: str, area_id: str) -> str:
    return (
        f"Comodo atual (area_id): {area_id}\n"
        f"Mensagem do usuario: {texto}"
    )


def _extract_response_text(response: types.GenerateContentResponse) -> str:
    """Extrai texto final da resposta do Gemini."""
    if response.text:
        return response.text.strip()

    if response.candidates:
        parts = response.candidates[0].content.parts if response.candidates[0].content else []
        textos = [p.text for p in parts if getattr(p, "text", None)]
        if textos:
            return "\n".join(textos).strip()

    return "Desculpe, nao consegui formular uma resposta agora."


async def processar_mensagem(
    texto: str,
    area_id: str,
    historico: list[dict[str, str]] | None = None,
) -> str:
    """
    Envia o texto do usuario ao Gemini 1.5 Flash com sessao MCP (ferramentas HA).

    Um subprocess stdio executa este modulo como servidor MCP; o SDK Gemini
    chama as tools automaticamente (automatic function calling).
    """
    settings = get_settings()

    if not settings.gemini_api_key:
        raise ValueError("GEMINI_API_KEY nao configurada.")

    user_prompt = _build_user_prompt(texto, area_id)
    contents: list[Any] = []

    if historico:
        for turn in historico:
            role = turn.get("role", "user")
            content = turn.get("content", "")
            contents.append(
                types.Content(
                    role=role,
                    parts=[types.Part(text=content)],
                )
            )

    contents.append(
        types.Content(role="user", parts=[types.Part(text=user_prompt)])
    )

    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", settings.mcp_server_module],
        cwd=str(BASE_DIR),
        env=None,
    )

    client = genai.Client(api_key=settings.gemini_api_key)
    _patch_gemini_mcp_schema_filter()

    logger.info("Processando mensagem com Gemini (%s) e MCP", settings.gemini_model)

    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                response = await asyncio.wait_for(
                    client.aio.models.generate_content(
                        model=settings.gemini_model,
                        contents=contents,
                        config=types.GenerateContentConfig(
                            system_instruction=THINA_SYSTEM_INSTRUCTION,
                            temperature=0.7,
                            tools=[session],
                        ),
                    ),
                    timeout=settings.gemini_timeout,
                )
    except asyncio.TimeoutError as exc:
        raise TimeoutError(
            "Timeout ao aguardar resposta do Gemini/MCP."
        ) from exc
    except (HAConnectionError, HAAuthError) as exc:
        raise RuntimeError(f"Home Assistant inacessivel durante MCP: {exc}") from exc

    resposta = _extract_response_text(response)
    logger.info("Resposta Thina (%d caracteres)", len(resposta))
    return resposta


# ---------------------------------------------------------------------------
# Entrada do subprocess MCP (python -m services.gemini_mcp)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    mcp.run()
