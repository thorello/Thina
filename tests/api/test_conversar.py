"""Testes de integracao leve dos endpoints FastAPI (com mocks externos)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from thina.integrations.kokoro import AudioResult


def test_servir_audio_id_invalido(client: TestClient) -> None:
    response = client.get("/v1/audio/id_com_underscore_invalido.wav")
    assert response.status_code == 400


def test_servir_audio_nao_encontrado(client: TestClient) -> None:
    response = client.get("/v1/audio/00000000-0000-4000-8000-000000000001.wav")
    assert response.status_code == 404


def test_conversar_area_desconhecida(client: TestClient) -> None:
    response = client.post(
        "/v1/conversar",
        json={"texto": "ola", "area_id": "banheiro_inexistente"},
    )
    assert response.status_code == 400
    assert "area_id" in response.json()["detail"].lower()


@patch("thina.api.app.processar_mensagem", new_callable=AsyncMock)
@patch("thina.api.app.sintetizar", new_callable=AsyncMock)
@patch("thina.api.app.get_ha_client")
def test_conversar_fluxo_completo(
    mock_get_ha: MagicMock,
    mock_sintetizar: AsyncMock,
    mock_processar: AsyncMock,
    client: TestClient,
    tmp_path: Path,
) -> None:
    mock_processar.return_value = "Resposta da Thina."
    mock_sintetizar.return_value = AudioResult(
        audio_id="audio-test-1",
        local_path=tmp_path / "audio-test-1.wav",
        public_url="http://test-thina.local:8080/v1/audio/audio-test-1.wav",
    )
    ha = MagicMock()
    ha.play_media = AsyncMock()
    mock_get_ha.return_value = ha

    response = client.post(
        "/v1/conversar",
        json={
            "texto": "ligue a luz da sala",
            "area_id": "sala",
            "session_id": "test-session-1",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["resposta"] == "Resposta da Thina."
    assert body["area_id"] == "sala"
    assert body["media_player"] == "media_player.respeaker_sala"
    assert body["session_id"] == "test-session-1"
    assert "audio-test-1.wav" in body["audio_url"]

    mock_processar.assert_awaited_once()
    mock_sintetizar.assert_awaited_once_with("Resposta da Thina.")
    ha.play_media.assert_awaited_once()


@patch("thina.api.app.processar_mensagem", new_callable=AsyncMock)
@patch("thina.api.app.sintetizar", new_callable=AsyncMock)
@patch("thina.api.app.get_ha_client")
def test_conversar_sem_reproduzir_ha(
    mock_get_ha: MagicMock,
    mock_sintetizar: AsyncMock,
    mock_processar: AsyncMock,
    client: TestClient,
    tmp_path: Path,
) -> None:
    mock_processar.return_value = "Brasilia."
    mock_sintetizar.return_value = AudioResult(
        audio_id="audio-test-2",
        local_path=tmp_path / "audio-test-2.wav",
        public_url="http://test-thina.local:8080/v1/audio/audio-test-2.wav",
    )
    ha = MagicMock()
    ha.play_media = AsyncMock()
    mock_get_ha.return_value = ha

    response = client.post(
        "/v1/conversar",
        json={
            "texto": "qual a capital do brasil?",
            "area_id": "sala",
            "reproduzir_ha": False,
        },
    )

    assert response.status_code == 200
    assert response.json()["resposta"] == "Brasilia."
    ha.play_media.assert_not_awaited()
    mock_get_ha.assert_not_called()


@patch("thina.api.app.processar_mensagem", new_callable=AsyncMock)
@patch("thina.api.app.sintetizar", new_callable=AsyncMock)
@patch("thina.api.app.get_ha_client")
def test_conversar_ha_falha_retorna_502_com_reproduzir_ha(
    mock_get_ha: MagicMock,
    mock_sintetizar: AsyncMock,
    mock_processar: AsyncMock,
    client: TestClient,
    tmp_path: Path,
) -> None:
    from thina.integrations.homeassistant import HAConnectionError

    mock_processar.return_value = "Resposta ok."
    mock_sintetizar.return_value = AudioResult(
        audio_id="audio-ha-fail",
        local_path=tmp_path / "audio-ha-fail.wav",
        public_url="http://test-thina.local:8080/v1/audio/audio-ha-fail.wav",
    )
    ha = MagicMock()
    ha.play_media = AsyncMock(
        side_effect=HAConnectionError("Nao foi possivel ligar ao Home Assistant: falha")
    )
    mock_get_ha.return_value = ha

    response = client.post(
        "/v1/conversar",
        json={
            "texto": "ola",
            "area_id": "sala",
            "reproduzir_ha": True,
        },
    )

    assert response.status_code == 502
    assert "Home Assistant" in response.json()["detail"]
    ha.play_media.assert_awaited_once()


@patch("thina.api.app.processar_mensagem", new_callable=AsyncMock)
@patch("thina.api.app.sintetizar", new_callable=AsyncMock)
@patch("thina.api.app.get_ha_client")
def test_conversar_reproduzir_ha_padrao_chama_play_media(
    mock_get_ha: MagicMock,
    mock_sintetizar: AsyncMock,
    mock_processar: AsyncMock,
    client: TestClient,
    tmp_path: Path,
) -> None:
    mock_processar.return_value = "Sim."
    mock_sintetizar.return_value = AudioResult(
        audio_id="audio-default-ha",
        local_path=tmp_path / "audio-default-ha.wav",
        public_url="http://test/x.wav",
    )
    ha = MagicMock()
    ha.play_media = AsyncMock()
    mock_get_ha.return_value = ha

    response = client.post(
        "/v1/conversar",
        json={"texto": "ola", "area_id": "sala"},
    )

    assert response.status_code == 200
    mock_get_ha.assert_called_once()
    ha.play_media.assert_awaited_once()


@patch("thina.api.app.processar_mensagem", new_callable=AsyncMock)
def test_conversar_llm_indisponivel(
    mock_processar: AsyncMock, client: TestClient
) -> None:
    mock_processar.side_effect = ValueError("Chave API ausente.")

    response = client.post(
        "/v1/conversar",
        json={"texto": "ola", "area_id": "sala"},
    )

    assert response.status_code == 503
    assert "Chave API" in response.json()["detail"]


@patch("thina.api.app.processar_mensagem", new_callable=AsyncMock)
@patch("thina.api.app.sintetizar", new_callable=AsyncMock)
def test_conversar_kokoro_falha(
    mock_sintetizar: AsyncMock,
    mock_processar: AsyncMock,
    client: TestClient,
) -> None:
    from thina.integrations.kokoro import KokoroConnectionError

    mock_processar.return_value = "ok"
    mock_sintetizar.side_effect = KokoroConnectionError("Kokoro offline.")

    response = client.post(
        "/v1/conversar",
        json={"texto": "ola", "area_id": "quarto"},
    )

    assert response.status_code == 502
    assert "Kokoro" in response.json()["detail"]


@patch("thina.api.app.processar_mensagem", new_callable=AsyncMock)
@patch("thina.api.app.clear_session", new_callable=AsyncMock)
def test_conversar_nova_sessao_limpa_historico(
    mock_clear: AsyncMock,
    mock_processar: AsyncMock,
    client: TestClient,
) -> None:
    mock_processar.return_value = "ok"

    with patch("thina.api.app.sintetizar", new_callable=AsyncMock) as mock_tts, patch(
        "thina.api.app.get_ha_client"
    ) as mock_ha:
        mock_tts.return_value = AudioResult(
            audio_id="x",
            local_path=Path("x.wav"),
            public_url="http://test/x.wav",
        )
        ha = MagicMock()
        ha.play_media = AsyncMock()
        mock_ha.return_value = ha

        response = client.post(
            "/v1/conversar",
            json={
                "texto": "tina",
                "area_id": "sala",
                "session_id": "sid-nova",
                "nova_sessao": True,
            },
        )

    assert response.status_code == 200
    mock_clear.assert_awaited_once_with("sid-nova")
