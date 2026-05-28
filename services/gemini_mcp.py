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
from google.genai import errors as genai_errors
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
THINA_CHAT_INSTRUCTION = """Voce e a Thina, assistente de voz residencial inteligente em portugues do Brasil.

Personalidade:
- Cordial, objetiva e natural, como uma assistente de casa de confianca.
- Respostas curtas e faladas (ideal para serem lidas em voz alta), em uma ou duas frases.

Conhecimento geral (sem ferramentas neste modo):
- Responda perguntas de geografia, ciencia, receitas, noticias e clima com seu conhecimento.
- Previsao do tempo: use a cidade padrao do contexto se o usuario nao disser outra; responda de forma util e breve.
- Nao mencione Home Assistant, MCP, ferramentas, entidades nem aplicativos externos, a menos que o usuario peca controle de um aparelho da casa.

Comandos de casa:
- Se o usuario pedir ligar/desligar luzes, sensores ou automacoes, diga em uma frase que pode ajudar quando o pedido for um comando claro de casa (ex.: "liga a luz da sala").

Regras:
- O usuario fala a partir de um comodo especifico (area_id); considere isso no contexto.
- Se houver cidade/local padrao no contexto, use-a em previsao do tempo e clima sem pedir a cidade de novo.
"""

THINA_SYSTEM_INSTRUCTION = """Voce e a Thina, assistente de voz residencial inteligente em portugues do Brasil.

Personalidade:
- Cordial, objetiva e natural, como uma assistente de casa de confianca.
- Respostas curtas e faladas (ideal para serem lidas em voz alta).
- Confirme antes de acoes que afetem seguranca (portas, alarmes, aquecedores a gas).
- Nunca invente estados de dispositivos: use sempre as ferramentas MCP para ler sensores ou controlar a casa.

Conhecimento e pesquisa:
- Para perguntas gerais (geografia, ciencia, receitas, noticias, clima na cidade, etc.), use a ferramenta Google Search e responda com base nos resultados.
- Nao recuse perguntas de conhecimento geral: pesquise quando precisar de fatos atuais ou precisos e responda em uma ou duas frases.
- Para acoes na casa (luzes, sensores, automacoes), use as ferramentas MCP do Home Assistant, nao a pesquisa na web.
- Para abrir programas no PC (Chrome, Spotify, Calculadora do Windows, etc.) ou sites na web, use abrir_aplicativo e abrir_site — apenas apps da lista permitida.
- Para pausar, retomar, pular ou voltar musica no Spotify do PC, use controlar_spotify (pausar, tocar, proxima, anterior).
- "Abrir a calculadora" / "abre a calculadora" significa o aplicativo Calculadora do Windows, NAO fazer contas matematicas.

Regras:
- O usuario fala a partir de um comodo especifico (area_id); considere isso no contexto.
- Se houver cidade/local padrao no contexto, use-a em previsao do tempo e clima sem pedir a cidade de novo.
- Se nao souber uma entidade exata, use listar_entidades ou pergunte de forma breve.
- Apos executar acoes na casa, resuma o que foi feito em uma frase amigavel.
- Se uma ferramenta falhar, explique o problema de forma simples, sem jargao tecnico.
"""

_WEATHER_PHRASES = (
    "previsao do tempo",
    "previsão do tempo",
    "como esta o tempo",
    "como está o tempo",
    "tempo hoje",
    "tempo amanha",
    "tempo amanhã",
    "vai chover",
    "esta chovendo",
    "está chovendo",
    "clima hoje",
    "clima em",
    "clima na",
    "clima no",
    "temperatura hoje",
    "temperatura amanha",
    "temperatura amanhã",
    "temperatura em",
    "temperatura na",
    "graus em",
    "graus na",
)


def _is_weather_question(texto: str) -> bool:
    """Perguntas de clima/previsao (modo chat, sem MCP)."""
    t = texto.lower()
    return any(p in t for p in _WEATHER_PHRASES)

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


@mcp.tool
async def abrir_aplicativo(nome: str) -> str:
    """
    Abre um aplicativo permitido no PC onde o servidor Thina esta rodando.

    Args:
        nome: Nome ou alias do app (ex: chrome, spotify, calculadora).
    """
    from services.pc_actions import abrir_aplicativo as _abrir

    result = await _abrir(nome)
    return _json_result(result)


@mcp.tool
async def controlar_spotify(
    acao: Literal["pausar", "tocar", "proxima", "anterior"],
) -> str:
    """
    Controla reproducao no Spotify (ou player de midia ativo) no PC do servidor.

    Args:
        acao: pausar (ou retomar se ja pausado), tocar, proxima faixa, faixa anterior.
    """
    from services.spotify_pc import controlar_spotify as _controlar

    result = await _controlar(acao)
    return _json_result(result)


@mcp.tool
async def abrir_site(url: str, navegador: str | None = None) -> str:
    """
    Abre uma pagina web no navegador (http/https).

    Args:
        url: Endereco completo ou dominio (ex: https://google.com).
        navegador: Opcional — chrome, edge ou firefox se estiver na lista permitida.
    """
    from services.pc_actions import abrir_site as _abrir_site

    result = await _abrir_site(url, navegador)
    return _json_result(result)


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


# Palavras que indicam comando/leitura na casa (MCP). Demais mensagens vao para Google Search.
_HOME_KEYWORDS = (
    "ligar",
    "desligar",
    "liga ",
    "desliga ",
    "acender",
    "apagar",
    "acende",
    "apaga",
    "luz",
    "luzes",
    "lampada",
    "lâmpada",
    "interruptor",
    "tomada",
    "temperatura",
    "ar condicionado",
    "aquecedor",
    "porta",
    "alarme",
    "trancar",
    "destrancar",
    "sensor",
    "entidade",
    "listar",
    "media_player",
    "volume",
    "televis",
    "cortina",
    "persiana",
    "estado do",
    "esta ligad",
    "está ligad",
    "automatiz",
)

_PC_KEYWORDS = (
    "abrir ",
    "abre ",
    "abra ",
    "abra a ",
    "abra o ",
    "abrir o ",
    "abre o ",
    "abre a ",
    "inicia ",
    "iniciar ",
    "iniciar o ",
    "executa ",
    "executar ",
    "liga o ",
    "liga a ",
    "chrome",
    "navegador",
    "firefox",
    "edge",
    "spotify",
    "musica",
    "música",
    "faixa",
    "playlist",
    "pausa ",
    "pausar",
    "pause ",
    "pula ",
    "pular ",
    "proxima",
    "próxima",
    "anterior ",
    "skip",
    "discord",
    "notepad",
    "bloco de notas",
    "calculadora",
    "explorador",
    "vscode",
    "visual studio code",
    "cursor",
    "aplicativo",
    "programa ",
    "no computador",
    "no pc",
    "site ",
    "pagina ",
    "página ",
    "google.com",
    "youtube",
    "http://",
    "https://",
)


def _needs_home_tools(texto: str) -> bool:
    """True se o pedido provavelmente exige ferramentas do Home Assistant."""
    if _is_weather_question(texto):
        return False
    t = texto.lower()
    return any(k in t for k in _HOME_KEYWORDS)


def _needs_pc_tools(texto: str) -> bool:
    """True se o pedido provavelmente exige abrir app ou site no PC."""
    if _is_weather_question(texto):
        return False
    t = texto.lower()
    return any(k in t for k in _PC_KEYWORDS)


def _needs_mcp_tools(texto: str) -> bool:
    """Casa (HA) ou PC (apps/sites) — ambos usam o subprocess MCP."""
    return _needs_home_tools(texto) or _needs_pc_tools(texto)


def _build_contents(
    texto: str,
    area_id: str,
    historico: list[dict[str, str]] | None,
) -> list[Any]:
    user_prompt = _build_user_prompt(texto, area_id)
    contents: list[Any] = []
    if historico:
        for turn in historico:
            role = turn.get("role", "user")
            if role == "assistant":
                role = "model"
            content = turn.get("content", "")
            contents.append(
                types.Content(
                    role=role,
                    parts=[types.Part(text=content)],
                )
            )
    contents.append(types.Content(role="user", parts=[types.Part(text=user_prompt)]))
    return contents


def _build_user_prompt(texto: str, area_id: str) -> str:
    settings = get_settings()
    parts = [f"Comodo atual (area_id): {area_id}"]
    city = settings.thina_default_city.strip()
    if city:
        parts.append(f"Cidade/local padrao: {city}")
    parts.append(f"Mensagem do usuario: {texto}")
    if _is_weather_question(texto):
        city_hint = city or "a cidade informada pelo usuario"
        parts.append(
            "Instrucao: responda previsao ou clima em 1 ou 2 frases curtas para voz. "
            f"Use {city_hint} se o pedido nao citar outra cidade. "
            "Nao mencione Home Assistant, MCP, ferramentas nem apps."
        )
    return "\n".join(parts)


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


async def _gerar_com_google_search(
    client: genai.Client,
    settings: Any,
    contents: list[Any],
) -> str:
    """
    Perguntas gerais: so Google Search.

    A API Gemini nao permite google_search e function calling (MCP) no mesmo request.
    """
    response = await asyncio.wait_for(
        client.aio.models.generate_content(
            model=settings.gemini_model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=THINA_SYSTEM_INSTRUCTION,
                temperature=0.7,
                tools=[types.Tool(google_search=types.GoogleSearch())],
            ),
        ),
        timeout=settings.gemini_timeout,
    )
    return _extract_response_text(response)


async def _gerar_com_mcp(
    client: genai.Client,
    settings: Any,
    contents: list[Any],
) -> str:
    """Comandos da casa: subprocess MCP + ferramentas Home Assistant."""
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", settings.mcp_server_module],
        cwd=str(BASE_DIR),
        env=None,
    )

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
    return _extract_response_text(response)


async def processar_mensagem(
    texto: str,
    area_id: str,
    historico: list[dict[str, str]] | None = None,
) -> str:
    """
    Roteia para DeepSeek ou Gemini conforme LLM_PROVIDER.

    Gemini: Google Search (geral) ou MCP (casa). DeepSeek: chat ou MCP (casa).
    """
    from services.pc_actions import try_pc_fastpath
    from services.spotify_pc import try_spotify_fastpath

    fast = await try_spotify_fastpath(texto)
    if fast is not None:
        logger.info("Resposta Thina fast-path Spotify (%d caracteres)", len(fast))
        return fast

    fast = await try_pc_fastpath(texto)
    if fast is not None:
        logger.info("Resposta Thina fast-path PC (%d caracteres)", len(fast))
        return fast

    settings = get_settings()

    if settings.llm_provider == "deepseek":
        from services.deepseek_llm import processar_mensagem_deepseek

        return await processar_mensagem_deepseek(texto, area_id, historico)

    if not settings.gemini_api_key:
        raise ValueError("GEMINI_API_KEY nao configurada.")

    contents = _build_contents(texto, area_id, historico)
    client = genai.Client(api_key=settings.gemini_api_key)
    _patch_gemini_mcp_schema_filter()

    usar_mcp = _needs_mcp_tools(texto)
    usar_pesquisa = settings.gemini_google_search and not usar_mcp
    if usar_mcp:
        if _needs_pc_tools(texto) and _needs_home_tools(texto):
            modo = "MCP (casa + PC)"
        elif _needs_pc_tools(texto):
            modo = "MCP (PC)"
        else:
            modo = "MCP (casa)"
    else:
        modo = "Google Search"
    logger.info(
        "Processando com Gemini (%s) | modo=%s | texto=%s",
        settings.gemini_model,
        modo,
        texto[:60] + ("..." if len(texto) > 60 else ""),
    )

    try:
        if usar_pesquisa:
            resposta = await _gerar_com_google_search(client, settings, contents)
        else:
            resposta = await _gerar_com_mcp(client, settings, contents)
    except asyncio.TimeoutError as exc:
        raise TimeoutError("Timeout ao aguardar resposta do Gemini.") from exc
    except genai_errors.ClientError as exc:
        logger.exception("Erro da API Gemini")
        raise RuntimeError(f"Gemini: {exc}") from exc
    except (HAConnectionError, HAAuthError) as exc:
        raise RuntimeError(f"Home Assistant inacessivel durante MCP: {exc}") from exc

    logger.info("Resposta Thina (%d caracteres)", len(resposta))
    return resposta


# ---------------------------------------------------------------------------
# Entrada do subprocess MCP (python -m services.gemini_mcp)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    mcp.run()
