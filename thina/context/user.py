"""
Contexto permanente do usuario para a Thina.

- maps/thina_user.md — personalidade (pode ir no Git)
- maps/thina_user.private.md — legado; ainda carregado se existir
- maps/private/*.md — pasta gitignored com contexto privado (casa, rotina, PC, etc.)
"""

from __future__ import annotations

import logging
from pathlib import Path

from thina.core.config import BASE_DIR, get_settings

logger = logging.getLogger(__name__)

_cache: tuple[tuple[float, ...], str] | None = None


def _resolve_path(relative_or_absolute: str) -> Path:
    path = Path(relative_or_absolute)
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


def user_context_path() -> Path:
    """Caminho do markdown publico (personalidade / preferencias)."""
    return get_settings().thina_user_context_path


def user_private_context_path() -> Path:
    """Arquivo privado legado (maps/thina_user.private.md)."""
    return get_settings().thina_user_private_path


def private_context_dir() -> Path:
    """Pasta com varios .md privados (maps/private)."""
    return get_settings().thina_private_dir_path


def list_context_paths() -> list[Path]:
    """
    Ordem de leitura: publico, legado (se existir), depois maps/private/*.md por nome.
    """
    settings = get_settings()
    paths: list[Path] = [settings.thina_user_context_path]

    legacy = settings.thina_user_private_path
    if legacy.is_file():
        paths.append(legacy)

    private_dir = settings.thina_private_dir_path
    if private_dir.is_dir():
        for path in sorted(private_dir.glob("*.md")):
            if path.is_file() and path not in paths:
                paths.append(path)

    return paths


def _read_markdown(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8").strip()


def _files_signature(paths: list[Path]) -> tuple[float, ...]:
    sig: list[float] = []
    for path in paths:
        if path.is_file():
            sig.append(path.stat().st_mtime)
        else:
            sig.append(0.0)
    return tuple(sig)


def load_user_context(*, force_reload: bool = False) -> str:
    """Le e combina todos os arquivos de contexto configurados."""
    global _cache
    paths = list_context_paths()
    signature = _files_signature(paths)

    if not force_reload and _cache is not None and _cache[0] == signature:
        return _cache[1]

    parts: list[str] = []
    loaded_names: list[str] = []
    for path in paths:
        text = _read_markdown(path)
        if text:
            parts.append(text)
            loaded_names.append(path.name)

    combined = "\n\n".join(parts)
    _cache = (signature, combined)
    if combined:
        logger.debug(
            "Contexto do usuario carregado (%d caracteres de %s)",
            len(combined),
            ", ".join(loaded_names),
        )
    return combined


def augment_system_instruction(base: str) -> str:
    """Anexa o contexto do usuario a instrucao base da Thina."""
    extra = load_user_context()
    if not extra:
        return base
    return (
        f"{base.rstrip()}\n\n"
        "Contexto permanente do usuario (sempre considere em todas as respostas):\n"
        f"{extra}"
    )
