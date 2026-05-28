"""Testes de carregamento de contexto do usuario."""

from __future__ import annotations

from pathlib import Path

import pytest

from config import Settings
from services import thina_context


def test_list_context_paths_ordem(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    public = tmp_path / "public.md"
    public.write_text("publico", encoding="utf-8")
    legacy = tmp_path / "legacy.md"
    legacy.write_text("legado", encoding="utf-8")
    private = tmp_path / "private"
    private.mkdir()
    (private / "b.md").write_text("b", encoding="utf-8")
    (private / "a.md").write_text("a", encoding="utf-8")

    monkeypatch.setenv("THINA_USER_CONTEXT_FILE", str(public))
    monkeypatch.setenv("THINA_USER_PRIVATE_FILE", str(legacy))
    monkeypatch.setenv("THINA_PRIVATE_DIR", str(private))

    paths = thina_context.list_context_paths()
    assert paths[0] == Settings().thina_user_context_path
    assert legacy in paths
    private_files = [p.name for p in paths if p.parent == private]
    assert private_files == ["a.md", "b.md"]


def test_load_user_context_combina_arquivos(test_env: None) -> None:
    texto = thina_context.load_user_context(force_reload=True)
    assert "assistente de teste" in texto
    assert "Rotina de teste" in texto


def test_cache_reutiliza_sem_alterar_arquivo(test_env: None) -> None:
    first = thina_context.load_user_context(force_reload=True)
    second = thina_context.load_user_context()
    assert first == second
    assert thina_context._cache is not None


def test_augment_system_instruction_sem_contexto(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("THINA_USER_CONTEXT_FILE", str(tmp_path / "vazio.md"))
    monkeypatch.setenv("THINA_USER_PRIVATE_FILE", str(tmp_path / "x.md"))
    monkeypatch.setenv("THINA_PRIVATE_DIR", str(tmp_path / "private"))
    thina_context._cache = None
    assert thina_context.augment_system_instruction("Base.") == "Base."
