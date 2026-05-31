"""Testes dos endpoints de setup Google (pagina web + OAuth)."""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient


def test_google_status_desabilitado(client: TestClient) -> None:
    response = client.get("/v1/google/status")
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is False
    assert body["configured"] is False
    assert "setup_url" in body


def test_google_setup_page_html(client: TestClient) -> None:
    response = client.get("/v1/google/setup")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Conectar Google" in response.text


def test_google_connect_redireciona_quando_desabilitado(client: TestClient) -> None:
    response = client.get("/v1/google/connect", follow_redirects=False)
    assert response.status_code == 302
    assert "/v1/google/setup" in response.headers["location"]


def test_google_connect_inicia_oauth_quando_configurado(
    client: TestClient,
    monkeypatch,
    tmp_path,
) -> None:
    creds = tmp_path / "google_credentials.json"
    creds.write_text(
        '{"installed":{"client_id":"cid","client_secret":"sec","redirect_uris":["http://localhost"]}}',
        encoding="utf-8",
    )
    monkeypatch.setenv("GOOGLE_ENABLED", "true")
    monkeypatch.setenv("GOOGLE_CREDENTIALS_FILE", str(creds))
    monkeypatch.setenv("GOOGLE_TOKEN_FILE", str(tmp_path / "google_token.json"))

    with patch(
        "thina.api.app.begin_web_oauth",
        return_value="https://accounts.google.com/o/oauth2/auth?test=1",
    ):
        response = client.get("/v1/google/connect", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"].startswith("https://accounts.google.com/")


def test_google_oauth_callback_sucesso(
    client: TestClient,
    monkeypatch,
    tmp_path,
) -> None:
    creds = tmp_path / "google_credentials.json"
    creds.write_text(
        '{"installed":{"client_id":"cid","client_secret":"sec","redirect_uris":["http://localhost"]}}',
        encoding="utf-8",
    )
    monkeypatch.setenv("GOOGLE_ENABLED", "true")
    monkeypatch.setenv("GOOGLE_CREDENTIALS_FILE", str(creds))
    monkeypatch.setenv("GOOGLE_TOKEN_FILE", str(tmp_path / "google_token.json"))

    with patch("thina.api.app.complete_web_oauth") as mock_complete:
        response = client.get(
            "/v1/google/oauth/callback?code=abc&state=xyz",
            follow_redirects=False,
        )

    assert response.status_code == 302
    assert response.headers["location"] == "/v1/google/setup?ok=1"
    mock_complete.assert_called_once_with(state="xyz", code="abc")
