"""
Orquestrador DeepSeek (API OpenAI-compatible) + MCP para acoes na casa.

Para perguntas gerais usa chat simples; para comandos da casa conecta ao subprocess
MCP (mesmo modulo FastMCP do gemini_mcp) e executa tool calls em loop.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import Any

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from thina.core.config import BASE_DIR, get_settings
from thina.llm.gemini_mcp import (
    get_thina_chat_instruction,
    get_thina_system_instruction,
    _build_user_prompt,
    _needs_home_tools,
    _needs_mcp_tools,
    _needs_pc_tools,
)
from thina.integrations.homeassistant import HAAuthError, HAConnectionError

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 10

def _deepseek_mcp_instruction() -> str:
    """Instrucao MCP do DeepSeek (ajustes + contexto do usuario)."""
    base = get_thina_system_instruction()
    return base.replace(
        "- Para perguntas gerais (geografia, ciência, receitas, notícias, clima na cidade, etc.), "
        "use a ferramenta Google Search e responda com base nos resultados.\n"
        "- Não recuse perguntas de conhecimento geral: pesquise quando precisar de fatos atuais ou precisos "
        "e responda em uma ou duas frases.\n"
        "- Para ações na casa (luzes, sensores, automações), use as ferramentas MCP do Home Assistant, "
        "não a pesquisa na web.\n",
        "- Para ações na casa (luzes, sensores, automações), use sempre as ferramentas MCP do Home Assistant.\n"
        "- Previsão do tempo: se existir entidade weather no HA, use ler_sensor; senão responda com conhecimento geral.\n",
    )


def _messages_for_request(
    texto: str,
    area_id: str,
    historico: list[dict[str, str]] | None,
    *,
    usar_mcp: bool,
) -> list[dict[str, Any]]:
    system = _deepseek_mcp_instruction() if usar_mcp else get_thina_chat_instruction()
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
    ]
    if historico:
        for turn in historico:
            role = turn.get("role", "user")
            content = turn.get("content", "")
            if role in ("user", "assistant", "system") and content:
                messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": _build_user_prompt(texto, area_id)})
    return messages


def _mcp_tools_to_openai(tools_result: Any) -> list[dict[str, Any]]:
    openai_tools: list[dict[str, Any]] = []
    for tool in tools_result.tools:
        schema = tool.inputSchema if isinstance(tool.inputSchema, dict) else {}
        openai_tools.append(
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": schema or {"type": "object", "properties": {}},
                },
            }
        )
    return openai_tools


def _tool_result_text(result: Any) -> str:
    if result is None:
        return ""
    content = getattr(result, "content", None)
    if not content:
        return str(result)
    parts: list[str] = []
    for block in content:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
    return "\n".join(parts).strip() or str(result)


async def _deepseek_request(
    client: httpx.AsyncClient,
    settings: Any,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    url = f"{settings.deepseek_base_url.rstrip('/')}/chat/completions"
    payload: dict[str, Any] = {
        "model": settings.deepseek_model,
        "messages": messages,
        "temperature": 0.7,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    response = await client.post(
        url,
        headers={
            "Authorization": f"Bearer {settings.deepseek_api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
    )
    if response.is_error:
        detail = response.text[:500]
        raise RuntimeError(f"DeepSeek HTTP {response.status_code}: {detail}")
    return response.json()


def _extract_assistant_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    return "Desculpe, não consegui formular uma resposta agora."


async def _chat_simple(
    settings: Any,
    messages: list[dict[str, Any]],
) -> str:
    timeout = httpx.Timeout(settings.deepseek_timeout)
    async with httpx.AsyncClient(timeout=timeout) as client:
        data = await _deepseek_request(client, settings, messages)
    message = data["choices"][0]["message"]
    return _extract_assistant_text(message)


async def _chat_com_mcp(
    settings: Any,
    messages: list[dict[str, Any]],
) -> str:
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", settings.mcp_server_module],
        cwd=str(BASE_DIR),
        env=None,
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = _mcp_tools_to_openai(await session.list_tools())

            timeout = httpx.Timeout(settings.deepseek_timeout)
            async with httpx.AsyncClient(timeout=timeout) as client:
                for round_idx in range(MAX_TOOL_ROUNDS):
                    data = await _deepseek_request(
                        client, settings, messages, tools=tools
                    )
                    choice = data["choices"][0]
                    message = choice["message"]
                    tool_calls = message.get("tool_calls")

                    if not tool_calls:
                        return _extract_assistant_text(message)

                    messages.append(message)

                    for tool_call in tool_calls:
                        fn = tool_call.get("function") or {}
                        name = fn.get("name", "")
                        raw_args = fn.get("arguments") or "{}"
                        try:
                            args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                        except json.JSONDecodeError:
                            args = {}

                        logger.info("DeepSeek tool call: %s", name)
                        try:
                            result = await session.call_tool(name, arguments=args)
                            content = _tool_result_text(result)
                        except Exception as exc:
                            logger.exception("Falha ao executar tool MCP %s", name)
                            content = json.dumps(
                                {"ok": False, "erro": str(exc)},
                                ensure_ascii=False,
                            )

                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call["id"],
                                "content": content,
                            }
                        )

                    logger.debug("DeepSeek MCP round %d concluida", round_idx + 1)

    raise RuntimeError("Limite de chamadas de ferramentas DeepSeek/MCP atingido.")


async def processar_mensagem_deepseek(
    texto: str,
    area_id: str,
    historico: list[dict[str, str]] | None = None,
) -> str:
    """Processa mensagem com DeepSeek (+ MCP quando for comando da casa)."""
    settings = get_settings()

    if not settings.deepseek_api_key:
        raise ValueError("DEEPSEEK_API_KEY nao configurada.")

    usar_mcp = _needs_mcp_tools(texto)
    messages = _messages_for_request(texto, area_id, historico, usar_mcp=usar_mcp)
    if usar_mcp:
        if _needs_pc_tools(texto) and _needs_home_tools(texto):
            modo = "MCP (casa + PC)"
        elif _needs_pc_tools(texto):
            modo = "MCP (PC)"
        else:
            modo = "MCP (casa)"
    else:
        modo = "chat"
    logger.info(
        "Processando com DeepSeek (%s) | modo=%s | texto=%s",
        settings.deepseek_model,
        modo,
        texto[:60] + ("..." if len(texto) > 60 else ""),
    )

    try:
        if usar_mcp:
            resposta = await _chat_com_mcp(settings, messages)
        else:
            resposta = await _chat_simple(settings, messages)
    except asyncio.TimeoutError as exc:
        raise TimeoutError("Timeout ao aguardar resposta do DeepSeek.") from exc
    except httpx.TimeoutException as exc:
        raise TimeoutError("Timeout ao aguardar resposta do DeepSeek.") from exc
    except (HAConnectionError, HAAuthError) as exc:
        raise RuntimeError(f"Home Assistant inacessivel durante MCP: {exc}") from exc

    logger.info("Resposta Thina (%d caracteres)", len(resposta))
    return resposta
