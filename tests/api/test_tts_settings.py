"""Testes dos endpoints /v1/tts/settings."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

import thina.core.tts_settings as tts_store


@patch("thina.api.app.listar_vozes", new_callable=AsyncMock)
def test_get_tts_settings_retorna_env_padrao(
    mock_voices: AsyncMock,
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.delenv("KOKORO_VOICE", raising=False)
    monkeypatch.setenv("KOKORO_VOICE", "pf_dora")
    monkeypatch.setenv("KOKORO_MIX_VOICE", "af_bella")
    monkeypatch.setenv("KOKORO_MIX_AMOUNT", "0.3")
    monkeypatch.setenv("KOKORO_SPEED", "1.1")
    mock_voices.return_value = ["af_bella", "pf_dora", "thina_mix"]

    response = client.get("/v1/tts/settings")
    assert response.status_code == 200
    body = response.json()
    assert body["voice"] == "pf_dora"
    assert body["mix_voice"] == "af_bella"
    assert body["mix_amount"] == 0.3
    assert body["speed"] == 1.1
    assert "pf_dora" in body["voices"]


@patch("thina.api.app.listar_vozes", new_callable=AsyncMock)
def test_put_tts_settings_persiste_e_sobrescreve(
    mock_voices: AsyncMock,
    client: TestClient,
) -> None:
    mock_voices.return_value = ["af_bella", "if_sara", "pf_dora"]

    response = client.put(
        "/v1/tts/settings",
        json={
            "voice": "if_sara",
            "mix_voice": "af_bella",
            "mix_amount": 0.5,
            "speed": 1.2,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["voice"] == "if_sara"
    assert body["mix_voice"] == "af_bella"
    assert body["mix_amount"] == 0.5
    assert body["speed"] == 1.2

    saved = json.loads(tts_store.TTS_SETTINGS_FILE.read_text(encoding="utf-8"))
    assert saved["voice"] == "if_sara"
    assert saved["mix_amount"] == 0.5

    get_response = client.get("/v1/tts/settings")
    assert get_response.json()["voice"] == "if_sara"


@patch("thina.api.app.listar_vozes", new_callable=AsyncMock)
def test_put_tts_settings_valida_limites(
    mock_voices: AsyncMock,
    client: TestClient,
) -> None:
    mock_voices.return_value = ["pf_dora"]
    response = client.put(
        "/v1/tts/settings",
        json={
            "voice": "pf_dora",
            "mix_voice": None,
            "mix_amount": 2.5,
            "speed": 3.0,
        },
    )
    assert response.status_code == 422
