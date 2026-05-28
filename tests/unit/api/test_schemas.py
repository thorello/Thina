"""Testes dos modelos Pydantic da API."""

from __future__ import annotations

from thina.api.schemas import ConversarRequest


def test_conversar_request_reproduzir_ha_padrao_true() -> None:
    req = ConversarRequest(texto="ola", area_id="sala")
    assert req.reproduzir_ha is True
    assert req.nova_sessao is False
    assert req.session_id is None


def test_conversar_request_reproduzir_ha_false_painel_web() -> None:
    req = ConversarRequest(
        texto="qual a capital?",
        area_id="sala",
        reproduzir_ha=False,
    )
    assert req.reproduzir_ha is False
