"""Pagina web simples para conectar Gmail, Drive e Calendar (OAuth)."""

from __future__ import annotations

from html import escape

from thina.integrations.google import (
    GoogleAuthError,
    GoogleNotConfiguredError,
    google_status,
    is_google_authorized,
    needs_reauth,
)


def _status_badge(status: dict) -> tuple[str, str, str]:
    if not status["enabled"]:
        return (
            "Desativado",
            "A integracao Google esta desligada. Ative GOOGLE_ENABLED=true no .env.",
            "warn",
        )
    if not status["configured"]:
        return (
            "Falta configuracao",
            "Quem instalou a Thina precisa colocar as credenciais OAuth uma vez "
            "(veja docs/integracao-google.md — secao Instalador).",
            "warn",
        )
    if status["authorized"] and not status["needs_reauth"]:
        return (
            "Conectado",
            "Sua conta Google esta autorizada. A Thina pode usar Gmail, Drive e Agenda.",
            "ok",
        )
    if status["needs_reauth"]:
        return (
            "Reconectar",
            "As permissoes mudaram. Clique abaixo para autorizar de novo.",
            "warn",
        )
    return (
        "Aguardando voce",
        "Clique no botao para abrir o Google e permitir o acesso.",
        "action",
    )


def render_google_setup_page(*, result: str | None = None, error: str | None = None) -> str:
    status = google_status()
    title, hint, level = _status_badge(status)
    show_connect = status["enabled"] and status["configured"] and (
        not is_google_authorized() or needs_reauth()
    )

    result_html = ""
    if result == "ok":
        result_html = (
            '<p class="banner ok">Conta Google conectada com sucesso! '
            "Ja pode pedir: <em>Thina, tenho email novo?</em></p>"
        )
    elif error:
        result_html = f'<p class="banner err">{escape(error)}</p>'

    connect_btn = ""
    if show_connect:
        connect_btn = (
            '<a class="btn" href="/v1/google/connect">Conectar conta Google</a>'
        )
    elif status["authorized"] and not status["needs_reauth"]:
        connect_btn = (
            '<a class="btn secondary" href="/v1/google/connect?force=1">'
            "Reconectar outra conta</a>"
        )

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Thina — Conectar Google</title>
  <style>
    :root {{
      font-family: system-ui, -apple-system, Segoe UI, sans-serif;
      color: #e8eaed;
      background: #0f1117;
    }}
    body {{
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      padding: 1.5rem;
    }}
    .card {{
      max-width: 32rem;
      width: 100%;
      background: #171a22;
      border: 1px solid #2a3140;
      border-radius: 16px;
      padding: 2rem;
      box-shadow: 0 12px 40px rgba(0,0,0,.35);
    }}
    h1 {{ margin: 0 0 .25rem; font-size: 1.5rem; }}
    .sub {{ color: #9aa3b2; margin: 0 0 1.5rem; }}
    .status {{
      display: inline-block;
      padding: .35rem .75rem;
      border-radius: 999px;
      font-size: .85rem;
      font-weight: 600;
      margin-bottom: 1rem;
    }}
    .status.ok {{ background: #163d2a; color: #7ddea0; }}
    .status.warn {{ background: #3d3016; color: #f0c674; }}
    .status.action {{ background: #1a2f4d; color: #8ab4ff; }}
    .hint {{ color: #c4cad4; line-height: 1.5; margin: 0 0 1.5rem; }}
    .btn {{
      display: inline-block;
      background: #4285f4;
      color: #fff;
      text-decoration: none;
      font-weight: 600;
      padding: .85rem 1.25rem;
      border-radius: 10px;
    }}
    .btn.secondary {{ background: #2a3140; color: #c4cad4; }}
    .btn:hover {{ filter: brightness(1.08); }}
    .banner {{
      padding: .85rem 1rem;
      border-radius: 10px;
      margin: 0 0 1rem;
      line-height: 1.45;
    }}
    .banner.ok {{ background: #163d2a; color: #b8f0c8; }}
    .banner.err {{ background: #3d1a1a; color: #ffb4b4; }}
    ul {{ color: #9aa3b2; padding-left: 1.2rem; line-height: 1.6; }}
    .foot {{ margin-top: 1.5rem; font-size: .85rem; color: #6b7280; }}
    .foot a {{ color: #8ab4ff; }}
  </style>
</head>
<body>
  <main class="card">
    <h1>Conectar Google</h1>
    <p class="sub">Gmail, Drive e Agenda para a Thina</p>
    {result_html}
    <span class="status {level}">{escape(title)}</span>
    <p class="hint">{escape(hint)}</p>
    {connect_btn}
    <ul>
      <li>Le e envia emails (Gmail)</li>
      <li>Lista e abre arquivos (Drive)</li>
      <li>Ve e cria eventos (Agenda)</li>
    </ul>
    <p class="foot">
      Depois de conectar, volte ao painel em
      <a href="/ui/">/ui/</a>.
      Revogar acesso:
      <a href="https://myaccount.google.com/permissions" target="_blank" rel="noopener">
        Conta Google
      </a>
    </p>
  </main>
</body>
</html>"""
