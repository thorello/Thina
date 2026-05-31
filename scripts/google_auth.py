#!/usr/bin/env python3
"""
Autoriza a conta Google da Thina (Gmail, Drive, Calendar).

Pre-requisitos:
  1. GOOGLE_ENABLED=true no .env
  2. Credenciais OAuth Desktop em data/google_credentials.json
     (Google Cloud Console -> APIs & Services -> Credentials)

Uso:
  python scripts/google_auth.py
  python scripts/google_auth.py --force   # reautoriza (scopes novos)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from thina.core.config import get_settings, setup_logging
from thina.integrations.google import (
    GoogleNotConfiguredError,
    SCOPES,
    credentials_path,
    is_google_configured,
    needs_reauth,
    run_oauth_flow_sync,
    token_path,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Autoriza conta Google da Thina.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Apaga token antigo e reautoriza (necessario ao mudar permissoes).",
    )
    args = parser.parse_args()

    setup_logging()
    settings = get_settings()

    if not settings.google_enabled:
        print("Integracao Google desabilitada.")
        print("Defina GOOGLE_ENABLED=true no .env")
        return 1

    if not is_google_configured():
        print("Credenciais OAuth ainda nao configuradas.")
        print("Opcao A — JSON em:", credentials_path())
        print("Opcao B — GOOGLE_CLIENT_ID e GOOGLE_CLIENT_SECRET no .env")
        print("")
        print("Crie credencial Desktop app em:")
        print("https://console.cloud.google.com/apis/credentials")
        return 1

    token = token_path()
    if args.force and token.exists():
        token.unlink()
        print("Token antigo removido.")

    if token.exists() and needs_reauth():
        print("Permissoes do token estao desatualizadas. Reautorizando...")
        token.unlink()

    print("Permissoes solicitadas:")
    for scope in SCOPES:
        print(f"  - {scope}")
    print("")
    print("Abrindo navegador para autorizar Gmail, Drive e Calendar...")
    try:
        run_oauth_flow_sync()
    except GoogleNotConfiguredError as exc:
        print(f"Erro: {exc}")
        return 1

    print(f"Autorizacao concluida. Token salvo em: {token_path()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
