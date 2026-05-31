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

from thina.core.config import BASE_DIR, get_settings
from thina.integrations.homeassistant import (
    HAAuthError,
    HAConnectionError,
    HAError,
    HANotFoundError,
    get_ha_client,
)
from thina.speech.normalize import preparar_texto_para_voz

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Personalidade da Thina (system instruction para o Gemini)
# ---------------------------------------------------------------------------
_VOZ_FORMATO = """
Formato (a resposta será lida em voz alta por TTS):
- Português brasileiro correto, com acentuação e cedilha (você, não, está, também, etc.).
- Apenas texto corrido, sem markdown: sem asteriscos, underscores, backticks ou listas com marcadores.
- Sem emojis, emoticons nem símbolos decorativos.
- Não descreva formatação; fale como numa conversa normal.
"""

_OBJETIVIDADE = """
Objetividade (prioridade máxima):
- Responda somente ao que foi pedido; uma ou duas frases, no máximo.
- Não acrescente detalhes, contexto, dicas, alternativas, avisos preventivos nem sugestões do tipo "se quiser posso...".
- Não antecipe perguntas seguintes: o usuário pedirá na mesma conversa se precisar de mais.
- Em tarefas (casa, PC, pesquisa): execute e confirme em uma frase curta; sem explicar passos nem listar o que mais dá para fazer.
- Pergunte algo só quando for indispensável para concluir o pedido (ex.: entidade ambígua); uma pergunta curta, sem rodeios.
"""

THINA_CHAT_INSTRUCTION_BASE = """Você é a Thina, assistente de voz residencial inteligente em português do Brasil.

Personalidade:
- Cordial, objetiva e natural, como uma assistente de casa de confiança.
- Respostas curtas e faladas (ideal para serem lidas em voz alta), em uma ou duas frases.
""" + _OBJETIVIDADE + _VOZ_FORMATO + """

Conhecimento geral (sem ferramentas neste modo):
- Responda perguntas de geografia, ciência, receitas, notícias e clima com seu conhecimento.
- Previsão do tempo: use a cidade padrão do contexto se o usuário não disser outra; responda de forma útil e breve.
- Não mencione Home Assistant, MCP, ferramentas, entidades nem aplicativos externos, a menos que o usuário peça controle de um aparelho da casa.

Comandos de casa:
- Se o usuário pedir ligar/desligar luzes, sensores ou automações, diga em uma frase que pode ajudar quando o pedido for um comando claro de casa (ex.: "liga a luz da sala").

Regras:
- O usuário fala a partir de um cômodo específico (area_id); considere isso no contexto.
- Se houver cidade/local padrão no contexto, use-a em previsão do tempo e clima sem pedir a cidade de novo.
"""

THINA_SYSTEM_INSTRUCTION_BASE = """Você é a Thina, assistente de voz residencial inteligente em português do Brasil.

Personalidade:
- Cordial, objetiva e natural, como uma assistente de casa de confiança.
- Respostas curtas e faladas (ideal para serem lidas em voz alta).
- Confirme antes de ações que afetem segurança (portas, alarmes, aquecedores a gás).
- Nunca invente estados de dispositivos: use sempre as ferramentas MCP para ler sensores ou controlar a casa.
""" + _OBJETIVIDADE + _VOZ_FORMATO + """

Conhecimento e pesquisa:
- Para perguntas gerais (geografia, ciência, receitas, notícias, clima na cidade, etc.), use a ferramenta Google Search e responda com base nos resultados.
- Não recuse perguntas de conhecimento geral: pesquise quando precisar de fatos atuais ou precisos e responda em uma ou duas frases.
- Para ações na casa (luzes, sensores, automações), use as ferramentas MCP do Home Assistant, não a pesquisa na web.
- Para abrir programas no PC (Chrome, Spotify, Calculadora do Windows, etc.) ou sites na web, use abrir_aplicativo e abrir_site — apenas apps da lista permitida.
- Para pausar, retomar, pular ou voltar música no Spotify do PC, use controlar_spotify (pausar, tocar, proxima, anterior).
- "Abrir a calculadora" / "abre a calculadora" significa o aplicativo Calculadora do Windows, NÃO fazer contas matemáticas.
- Para emails do Gmail, arquivos do Google Drive e eventos do Google Calendar da conta do usuário, use as ferramentas Google MCP.
- Leitura: listar_emails_gmail, ler_email_gmail, listar_arquivos_drive, ler_arquivo_drive, listar_eventos_agenda.
- Ações: abrir_arquivo_drive (abre no navegador), criar_evento_agenda (inicio/fim em ISO, ex: 2026-06-01T16:00:00), enviar_email_gmail, marcar_email_lido.
- Antes de enviar email ou criar evento, confirme titulo, destinatario ou horario se o pedido for ambiguo.
- Resuma emails e documentos em voz: cite remetente, assunto e o essencial; não leia listas longas nem URLs inteiras.

Regras:
- O usuário fala a partir de um cômodo específico (area_id); considere isso no contexto.
- Se houver cidade/local padrão no contexto, use-a em previsão do tempo e clima sem pedir a cidade de novo.
- Se não souber uma entidade exata, use listar_entidades ou faça uma pergunta curta indispensável.
- Após executar ações na casa ou no PC, confirme em uma única frase o que foi feito, sem extras.
- Se uma ferramenta falhar, diga o problema em uma frase simples, sem jargão nem sugestões adicionais.
"""


def get_thina_chat_instruction() -> str:
    """Instrucao de chat (sem MCP), incluindo contexto de maps/thina_user.md."""
    from thina.context.user import augment_system_instruction

    return augment_system_instruction(THINA_CHAT_INSTRUCTION_BASE)


def get_thina_system_instruction() -> str:
    """Instrucao completa (MCP / pesquisa), incluindo contexto de maps/thina_user.md."""
    from thina.context.user import augment_system_instruction

    return augment_system_instruction(THINA_SYSTEM_INSTRUCTION_BASE)


# Compatibilidade com imports antigos (sem contexto do usuario)
THINA_CHAT_INSTRUCTION = THINA_CHAT_INSTRUCTION_BASE
THINA_SYSTEM_INSTRUCTION = THINA_SYSTEM_INSTRUCTION_BASE

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
    from thina.pc.actions import abrir_aplicativo as _abrir

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
    from thina.pc.spotify import controlar_spotify as _controlar

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
    from thina.pc.actions import abrir_site as _abrir_site

    result = await _abrir_site(url, navegador)
    return _json_result(result)


@mcp.tool
async def listar_emails_gmail(
    consulta: str = "",
    max_resultados: int = 10,
) -> str:
    """
    Lista emails recentes do Gmail do usuario.

    Args:
        consulta: Filtro Gmail (ex: is:unread, from:fulano@gmail.com, subject:conta).
        max_resultados: Quantidade maxima de mensagens (1-20).
    """
    from thina.integrations.google import GoogleError, list_gmail_messages

    try:
        limit = max(1, min(max_resultados, 20))
        result = await list_gmail_messages(consulta, limit)
        return _json_result(result)
    except GoogleError as exc:
        return _json_result({"ok": False, "erro": str(exc)})


@mcp.tool
async def ler_email_gmail(id_mensagem: str) -> str:
    """
    Le o conteudo completo de um email do Gmail.

    Args:
        id_mensagem: ID retornado por listar_emails_gmail.
    """
    from thina.integrations.google import GoogleError, get_gmail_message

    try:
        result = await get_gmail_message(id_mensagem.strip())
        return _json_result(result)
    except GoogleError as exc:
        return _json_result({"ok": False, "erro": str(exc)})


@mcp.tool
async def listar_arquivos_drive(
    consulta: str = "",
    max_resultados: int = 15,
) -> str:
    """
    Lista arquivos recentes no Google Drive do usuario.

    Args:
        consulta: Filtro Drive (ex: name contains 'orcamento', mimeType='application/pdf').
        max_resultados: Quantidade maxima (1-30).
    """
    from thina.integrations.google import GoogleError, list_drive_files

    try:
        limit = max(1, min(max_resultados, 30))
        result = await list_drive_files(consulta, limit)
        return _json_result(result)
    except GoogleError as exc:
        return _json_result({"ok": False, "erro": str(exc)})


@mcp.tool
async def ler_arquivo_drive(id_arquivo: str) -> str:
    """
    Le o texto de um arquivo do Google Drive (Docs exportados como texto, arquivos .txt/.json etc.).

    Args:
        id_arquivo: ID retornado por listar_arquivos_drive.
    """
    from thina.integrations.google import GoogleError, read_drive_file

    try:
        result = await read_drive_file(id_arquivo.strip())
        return _json_result(result)
    except GoogleError as exc:
        return _json_result({"ok": False, "erro": str(exc)})


@mcp.tool
async def listar_eventos_agenda(
    dias: int = 7,
    max_resultados: int = 10,
) -> str:
    """
    Lista proximos eventos do Google Calendar (agenda principal).

    Args:
        dias: Janela de dias a partir de hoje (1-30).
        max_resultados: Quantidade maxima de eventos (1-20).
    """
    from thina.integrations.google import GoogleError, list_calendar_events

    try:
        window = max(1, min(dias, 30))
        limit = max(1, min(max_resultados, 20))
        result = await list_calendar_events(window, limit)
        return _json_result(result)
    except GoogleError as exc:
        return _json_result({"ok": False, "erro": str(exc)})


@mcp.tool
async def abrir_arquivo_drive(
    id_arquivo: str,
    navegador: str | None = None,
) -> str:
    """
    Abre um arquivo do Google Drive no navegador do PC.

    Args:
        id_arquivo: ID retornado por listar_arquivos_drive.
        navegador: Opcional — chrome, edge ou firefox.
    """
    from thina.integrations.google import GoogleError, get_drive_file_link
    from thina.pc.actions import abrir_site as _abrir_site

    try:
        link = await get_drive_file_link(id_arquivo.strip())
        if not link.get("ok", True):
            return _json_result(link)
        open_result = await _abrir_site(link["webViewLink"], navegador)
        return _json_result({"ok": True, "arquivo": link, "navegador": open_result})
    except GoogleError as exc:
        return _json_result({"ok": False, "erro": str(exc)})


@mcp.tool
async def criar_evento_agenda(
    titulo: str,
    inicio: str,
    fim: str,
    local: str = "",
    descricao: str = "",
) -> str:
    """
    Cria um evento no Google Calendar (agenda principal).

    Args:
        titulo: Nome do evento.
        inicio: Data/hora ISO (ex: 2026-06-01T16:00:00).
        fim: Data/hora ISO de termino.
        local: Endereco ou sala (opcional).
        descricao: Detalhes adicionais (opcional).
    """
    from thina.integrations.google import GoogleError, create_calendar_event

    try:
        result = await create_calendar_event(titulo, inicio, fim, local, descricao)
        return _json_result(result)
    except GoogleError as exc:
        return _json_result({"ok": False, "erro": str(exc)})


@mcp.tool
async def enviar_email_gmail(
    para: str,
    assunto: str,
    corpo: str,
) -> str:
    """
    Envia um email pelo Gmail do usuario.

    Args:
        para: Endereco do destinatario.
        assunto: Assunto do email.
        corpo: Texto da mensagem (sem HTML).
    """
    from thina.integrations.google import GoogleError, send_gmail_message

    try:
        result = await send_gmail_message(para, assunto, corpo)
        return _json_result(result)
    except GoogleError as exc:
        return _json_result({"ok": False, "erro": str(exc)})


@mcp.tool
async def marcar_email_lido(id_mensagem: str) -> str:
    """
    Marca um email do Gmail como lido.

    Args:
        id_mensagem: ID retornado por listar_emails_gmail.
    """
    from thina.integrations.google import GoogleError, mark_gmail_read

    try:
        result = await mark_gmail_read(id_mensagem.strip())
        return _json_result(result)
    except GoogleError as exc:
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

_GOOGLE_KEYWORDS = (
    "gmail",
    "e-mail",
    "email",
    "emails",
    "correio",
    "caixa de entrada",
    "mensagem nova",
    "mensagens novas",
    "google drive",
    "no drive",
    "do drive",
    "meu drive",
    "arquivo no google",
    "documento no google",
    "google calendar",
    "google agenda",
    "minha agenda",
    "na agenda",
    "compromisso",
    "compromissos",
    "reuniao",
    "reunião",
    "evento amanha",
    "evento amanhã",
    "eventos amanha",
    "eventos amanhã",
    "criar evento",
    "cria evento",
    "agendar",
    "agenda ",
    "marcar na agenda",
    "marca na agenda",
    "abrir arquivo",
    "abre o arquivo",
    "abre arquivo",
    "enviar email",
    "envia email",
    "mandar email",
    "manda email",
    "marcar como lido",
    "marca como lido",
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


def _needs_google_tools(texto: str) -> bool:
    """True se o pedido provavelmente exige Gmail, Drive ou Calendar."""
    if not get_settings().google_enabled:
        return False
    if _is_weather_question(texto):
        return False
    t = texto.lower()
    return any(k in t for k in _GOOGLE_KEYWORDS)


def _needs_mcp_tools(texto: str) -> bool:
    """Casa (HA), PC (apps/sites) ou Google — subprocess MCP."""
    return _needs_home_tools(texto) or _needs_pc_tools(texto) or _needs_google_tools(texto)


def _mcp_mode_label(texto: str) -> str:
    """Rotulo de log para o modo MCP ativo."""
    parts: list[str] = []
    if _needs_home_tools(texto):
        parts.append("casa")
    if _needs_pc_tools(texto):
        parts.append("PC")
    if _needs_google_tools(texto):
        parts.append("Google")
    if not parts:
        return "MCP"
    return "MCP (" + " + ".join(parts) + ")"


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
    parts = [f"Cômodo atual (area_id): {area_id}"]
    city = settings.thina_default_city.strip()
    if city:
        parts.append(f"Cidade/local padrão: {city}")
    parts.append(f"Mensagem do usuário: {texto}")
    if _is_weather_question(texto):
        city_hint = city or "a cidade informada pelo usuário"
        parts.append(
            "Instrução: responda previsão ou clima em 1 ou 2 frases curtas para voz. "
            f"Use {city_hint} se o pedido não citar outra cidade. "
            "Não mencione Home Assistant, MCP, ferramentas nem apps."
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

    return "Desculpe, não consegui formular uma resposta agora."


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
                system_instruction=get_thina_system_instruction(),
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
                        system_instruction=get_thina_system_instruction(),
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
    from thina.pc.actions import try_pc_fastpath
    from thina.pc.spotify import try_spotify_fastpath

    fast = await try_spotify_fastpath(texto)
    if fast is not None:
        out = preparar_texto_para_voz(fast)
        logger.info("Resposta Thina fast-path Spotify (%d caracteres)", len(out))
        return out

    fast = await try_pc_fastpath(texto)
    if fast is not None:
        out = preparar_texto_para_voz(fast)
        logger.info("Resposta Thina fast-path PC (%d caracteres)", len(out))
        return out

    settings = get_settings()

    if settings.llm_provider == "deepseek":
        from thina.llm.deepseek import processar_mensagem_deepseek

        return await processar_mensagem_deepseek(texto, area_id, historico)

    if not settings.gemini_api_key:
        raise ValueError("GEMINI_API_KEY nao configurada.")

    contents = _build_contents(texto, area_id, historico)
    client = genai.Client(api_key=settings.gemini_api_key)
    _patch_gemini_mcp_schema_filter()

    usar_mcp = _needs_mcp_tools(texto)
    usar_pesquisa = settings.gemini_google_search and not usar_mcp
    modo = _mcp_mode_label(texto) if usar_mcp else "Google Search"
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

    resposta = preparar_texto_para_voz(resposta)
    logger.info("Resposta Thina (%d caracteres)", len(resposta))
    return resposta


# ---------------------------------------------------------------------------
# Entrada do subprocess MCP (python -m thina.llm.gemini_mcp)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    mcp.run()
