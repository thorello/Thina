"""Testes do endpoint /health (inclui estado do Home Assistant)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient


def test_health_campos_base(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "thina"
    assert "llm_provider" in body
    assert "areas" in body
    assert "ha_url" in body
    assert "ha_ok" in body


@patch("thina.api.app.get_ha_client")
def test_health_ha_ok_quando_token_e_ha_responde(
    mock_get_ha: MagicMock,
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setenv("HOME_ASSISTANT_TOKEN", "test-ha-token")
    ha = MagicMock()
    ha.get_states = AsyncMock(return_value=[])
    mock_get_ha.return_value = ha

    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["ha_ok"] is True
    ha.get_states.assert_awaited_once()


@patch("thina.api.app.get_ha_client")
def test_health_ha_offline_quando_ha_falha(
    mock_get_ha: MagicMock,
    client: TestClient,
    monkeypatch,
) -> None:
    from thina.integrations.homeassistant import HAConnectionError

    monkeypatch.setenv("HOME_ASSISTANT_TOKEN", "test-ha-token")
    ha = MagicMock()
    ha.get_states = AsyncMock(side_effect=HAConnectionError("offline"))
    mock_get_ha.return_value = ha

    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["ha_ok"] is False


def test_health_ha_ok_false_sem_token(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("HOME_ASSISTANT_TOKEN", "")
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["ha_ok"] is False
