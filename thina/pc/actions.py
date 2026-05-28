"""
Abertura de aplicativos e sites no PC onde o thina-server roda.

Somente entradas em maps/pc_apps.json (lista branca). Ative com PC_COMMANDS_ENABLED=true.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from thina.core.config import BASE_DIR, get_settings

logger = logging.getLogger(__name__)

_ALIAS_INDEX: dict[str, str] | None = None
_APPS_DATA: dict[str, dict[str, Any]] | None = None

# Lixo comum do Vosk antes do comando real
_STT_FILLER_PREFIXES = (
    "o que você ",
    "o que voce ",
    "o que é ",
    "o que e ",
    "você pode ",
    "voce pode ",
    "pode ",
    "eu quero ",
    "quero que ",
    "por favor ",
    "me ",
)

_OPEN_VERBS = (
    "abrir",
    "abre",
    "abra",
    "abro",
    "inicia",
    "iniciar",
    "iniciou",
    "executa",
    "executar",
    "liga o",
    "liga a",
    "ligar",
)


def _normalize_key(texto: str) -> str:
    return " ".join(texto.strip().lower().split())


def _load_apps_file() -> dict[str, dict[str, Any]]:
    settings = get_settings()
    path = Path(settings.pc_apps_map_file)
    if not path.is_absolute():
        path = BASE_DIR / path
    if not path.is_file():
        raise FileNotFoundError(f"Mapa de apps do PC nao encontrado: {path}")

    with path.open(encoding="utf-8") as f:
        data: dict[str, Any] = json.load(f)

    if not isinstance(data, dict):
        raise ValueError("pc_apps.json deve ser um objeto JSON.")

    apps: dict[str, dict[str, Any]] = {}
    for key, entry in data.items():
        if not isinstance(entry, dict):
            raise ValueError(f"Entrada invalida em pc_apps.json: {key}")
        apps[_normalize_key(key)] = entry
    return apps


def _build_alias_index(apps: dict[str, dict[str, Any]]) -> dict[str, str]:
    index: dict[str, str] = {}
    for app_id, entry in apps.items():
        index[app_id] = app_id
        aliases = entry.get("aliases") or []
        if isinstance(aliases, list):
            for alias in aliases:
                if isinstance(alias, str) and alias.strip():
                    index[_normalize_key(alias)] = app_id
    return index


def _get_apps_catalog() -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    global _APPS_DATA, _ALIAS_INDEX
    if _APPS_DATA is None or _ALIAS_INDEX is None:
        _APPS_DATA = _load_apps_file()
        _ALIAS_INDEX = _build_alias_index(_APPS_DATA)
    return _APPS_DATA, _ALIAS_INDEX


def reload_pc_apps_catalog() -> None:
    """Recarrega o JSON de apps (util apos editar maps/pc_apps.json)."""
    global _APPS_DATA, _ALIAS_INDEX
    _APPS_DATA = None
    _ALIAS_INDEX = None


def _limpar_texto_stt(texto: str) -> str:
    t = _normalize_key(texto)
    changed = True
    while changed:
        changed = False
        for prefix in _STT_FILLER_PREFIXES:
            if t.startswith(prefix):
                t = t[len(prefix) :].strip()
                changed = True
    return t


def _tem_verbo_abrir(texto: str) -> bool:
    return any(verb in texto for verb in _OPEN_VERBS)


def detectar_abertura_app(texto: str) -> str | None:
    """
    Detecta pedido para abrir app da lista branca (ex.: 'abra a calculadora').

    Retorna o alias encontrado ou None.
    """
    t = _limpar_texto_stt(texto)
    if not _tem_verbo_abrir(t):
        return None

    try:
        _, index = _get_apps_catalog()
    except (FileNotFoundError, ValueError, json.JSONDecodeError):
        return None

    for alias in sorted(index.keys(), key=len, reverse=True):
        if alias in t:
            return alias
    return None


def listar_apps_permitidos() -> list[str]:
    apps, _ = _get_apps_catalog()
    labels: list[str] = []
    for app_id, entry in sorted(apps.items()):
        name = str(entry.get("friendly_name") or app_id)
        labels.append(name)
    return labels


def _resolve_app_id(nome: str) -> str | None:
    key = _normalize_key(nome)
    _, index = _get_apps_catalog()
    return index.get(key)


def _launch_windows(entry: dict[str, Any]) -> None:
    cmd = entry.get("windows_cmd")
    path = entry.get("windows_path")

    if isinstance(cmd, list) and cmd:
        subprocess.Popen(
            [str(part) for part in cmd],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            close_fds=True,
        )
        return

    if isinstance(path, str) and path.strip():
        exe = Path(path.strip())
        if not exe.is_file():
            raise FileNotFoundError(f"Executavel nao encontrado: {exe}")
        args = entry.get("windows_args") or []
        if not isinstance(args, list):
            args = []
        subprocess.Popen(
            [str(exe), *[str(a) for a in args]],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            close_fds=True,
        )
        return

    raise ValueError("Entrada sem windows_cmd nem windows_path valido.")


def _launch_sync(app_id: str) -> dict[str, Any]:
    if sys.platform != "win32":
        return {
            "ok": False,
            "erro": "Comandos de PC so estao implementados para Windows nesta versao.",
        }

    apps, _ = _get_apps_catalog()
    entry = apps.get(app_id)
    if not entry:
        return {"ok": False, "erro": f"Aplicativo desconhecido: {app_id}"}

    friendly = str(entry.get("friendly_name") or app_id)
    try:
        _launch_windows(entry)
    except FileNotFoundError as exc:
        logger.warning("Falha ao abrir %s: %s", app_id, exc)
        return {"ok": False, "erro": str(exc), "app": friendly}
    except Exception as exc:
        logger.exception("Erro ao abrir aplicativo %s", app_id)
        return {"ok": False, "erro": str(exc), "app": friendly}

    logger.info("Aplicativo aberto: %s (%s)", friendly, app_id)
    return {"ok": True, "app": friendly, "app_id": app_id}


def _validate_url(url: str) -> str | None:
    raw = url.strip()
    if not raw:
        return None
    if not re.match(r"^https?://", raw, re.IGNORECASE):
        raw = f"https://{raw}"
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    return raw


def _open_url_sync(url: str, navegador: str | None) -> dict[str, Any]:
    if sys.platform != "win32":
        return {
            "ok": False,
            "erro": "Abrir sites so esta implementado para Windows nesta versao.",
        }

    safe_url = _validate_url(url)
    if not safe_url:
        return {"ok": False, "erro": "URL invalida. Use http ou https."}

    if navegador:
        app_id = _resolve_app_id(navegador)
        if not app_id:
            return {
                "ok": False,
                "erro": f"Navegador '{navegador}' nao esta na lista permitida.",
            }
        apps, _ = _get_apps_catalog()
        entry = apps[app_id]
        path = entry.get("windows_path")
        cmd = entry.get("windows_cmd")
        if isinstance(path, str) and Path(path.strip()).is_file():
            subprocess.Popen(
                [path.strip(), safe_url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                close_fds=True,
            )
        elif isinstance(cmd, list) and "chrome" in str(cmd).lower():
            subprocess.Popen(
                ["cmd", "/c", "start", "", "chrome", safe_url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                close_fds=True,
            )
        else:
            subprocess.Popen(
                ["cmd", "/c", "start", "", safe_url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                close_fds=True,
            )
    else:
        subprocess.Popen(
            ["cmd", "/c", "start", "", safe_url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            close_fds=True,
        )

    logger.info("Site aberto: %s", safe_url)
    return {"ok": True, "url": safe_url}


async def abrir_aplicativo(nome: str) -> dict[str, Any]:
    settings = get_settings()
    if not settings.pc_commands_enabled:
        return {
            "ok": False,
            "erro": "Comandos do PC desativados. Defina PC_COMMANDS_ENABLED=true no .env.",
        }

    app_id = _resolve_app_id(nome)
    if not app_id:
        try:
            disponiveis = listar_apps_permitidos()
        except FileNotFoundError as exc:
            return {"ok": False, "erro": str(exc)}
        return {
            "ok": False,
            "erro": f"Aplicativo '{nome}' nao esta na lista permitida.",
            "disponiveis": disponiveis,
        }

    return await asyncio.to_thread(_launch_sync, app_id)


async def abrir_site(url: str, navegador: str | None = None) -> dict[str, Any]:
    settings = get_settings()
    if not settings.pc_commands_enabled:
        return {
            "ok": False,
            "erro": "Comandos do PC desativados. Defina PC_COMMANDS_ENABLED=true no .env.",
        }

    return await asyncio.to_thread(_open_url_sync, url, navegador)


def _resposta_voz_abertura(result: dict[str, Any]) -> str:
    if result.get("ok"):
        app = result.get("app") or result.get("app_id") or "aplicativo"
        return f"Pronto, abri o {app}."
    erro = str(result.get("erro", "nao foi possivel abrir"))
    return f"Desculpe, nao consegui abrir: {erro}"


async def try_pc_fastpath(texto: str) -> str | None:
    """
    Abre app direto sem passar pelo LLM quando o pedido e claro.

    Evita o modelo confundir 'calculadora' com conta matematica.
    """
    alias = detectar_abertura_app(texto)
    if not alias:
        return None

    settings = get_settings()
    if not settings.pc_commands_enabled:
        logger.warning("Pedido de PC detectado (%s) mas PC_COMMANDS_ENABLED=false", alias)
        return (
            "Para abrir programas no computador, ative PC_COMMANDS_ENABLED=true "
            "no arquivo .env do servidor Thina e reinicie o servico."
        )

    logger.info("Fast-path PC: abrindo '%s' (texto STT: %s)", alias, texto[:80])
    result = await abrir_aplicativo(alias)
    return _resposta_voz_abertura(result)
