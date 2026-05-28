"""Testes de deteccao e politica de comandos no PC."""

from __future__ import annotations

import pytest

from thina.core.config import Settings
from thina.pc import actions as pc_actions


@pytest.mark.parametrize(
    "texto",
    [
        "abra a calculadora",
        "por favor abre o calc",
        "inicia o bloco de notas",
    ],
)
def test_detectar_abertura_app(texto: str, test_env: None) -> None:
    alias = pc_actions.detectar_abertura_app(texto)
    assert alias is not None


@pytest.mark.parametrize(
    "texto",
    [
        "quanto e dois mais dois",
        "feche a calculadora",
        "calculadora",
    ],
)
def test_detectar_abertura_app_negativo(texto: str, test_env: None) -> None:
    assert pc_actions.detectar_abertura_app(texto) is None


@pytest.mark.asyncio
async def test_abrir_aplicativo_desabilitado(
    test_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PC_COMMANDS_ENABLED", "false")
    result = await pc_actions.abrir_aplicativo("calculadora")
    assert result["ok"] is False
    assert "desativados" in result["erro"].lower()


@pytest.mark.asyncio
async def test_abrir_aplicativo_nao_listado(test_env: None) -> None:
    result = await pc_actions.abrir_aplicativo("photoshop")
    assert result["ok"] is False
    assert "disponiveis" in result


@pytest.mark.asyncio
async def test_try_pc_fastpath_retorna_mensagem_quando_desabilitado(
    test_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PC_COMMANDS_ENABLED", "false")
    msg = await pc_actions.try_pc_fastpath("abra a calculadora")
    assert msg is not None
    assert "PC_COMMANDS_ENABLED" in msg


def test_listar_apps_permitidos(test_env: None) -> None:
    apps = pc_actions.listar_apps_permitidos()
    assert "Calculadora" in apps
    assert "Bloco de Notas" in apps
