#!/usr/bin/env bash
# Conecta Gmail, Drive e Agenda — fluxo guiado para quem nao e tecnico.
# Uso: ./scripts/setup_google.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

ENV_FILE="$ROOT/.env"
CREDS_FILE="$ROOT/data/google_credentials.json"
PORT=8080

title() {
  echo ""
  echo "=== $1 ==="
  echo ""
}

ensure_google_enabled() {
  if [[ ! -f "$ENV_FILE" ]]; then
    echo "Arquivo .env nao encontrado. Rode ./install.sh primeiro."
    exit 1
  fi
  if grep -qE '^GOOGLE_ENABLED[[:space:]]*=[[:space:]]*true[[:space:]]*$' "$ENV_FILE"; then
    return
  fi
  if grep -qE '^GOOGLE_ENABLED[[:space:]]*=' "$ENV_FILE"; then
    sed -i.bak 's/^GOOGLE_ENABLED[[:space:]]=.*/GOOGLE_ENABLED=true/' "$ENV_FILE"
    rm -f "$ENV_FILE.bak"
  else
    echo "" >> "$ENV_FILE"
    echo "GOOGLE_ENABLED=true" >> "$ENV_FILE"
  fi
  echo "GOOGLE_ENABLED=true definido no .env"
}

ensure_data_files() {
  mkdir -p "$ROOT/data"
  if [[ ! -f "$ROOT/data/google_token.json" ]]; then
    echo "{}" > "$ROOT/data/google_token.json"
  fi
}

thina_running() {
  curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1
}

title "Thina — conectar Google"

if [[ -f "$ENV_FILE" ]]; then
  line="$(grep -E '^[[:space:]]*THINA_PORT[[:space:]]*=' "$ENV_FILE" | head -1 || true)"
  if [[ -n "$line" ]]; then
    PORT="${line#*=}"
    PORT="$(echo "$PORT" | tr -d ' \"')"
  fi
fi

ensure_data_files
ensure_google_enabled

has_creds_file=false
has_env_creds=false
if [[ -f "$CREDS_FILE" ]] && [[ "$(wc -c < "$CREDS_FILE" | tr -d ' ')" -gt 10 ]]; then
  has_creds_file=true
fi
if grep -qE '^GOOGLE_CLIENT_ID[[:space:]]*=\S+' "$ENV_FILE" 2>/dev/null \
   && grep -qE '^GOOGLE_CLIENT_SECRET[[:space:]]*=\S+' "$ENV_FILE" 2>/dev/null; then
  has_env_creds=true
fi

if [[ "$has_creds_file" != true && "$has_env_creds" != true ]]; then
  echo "Credenciais OAuth ainda nao foram colocadas."
  echo ""
  echo "Quem INSTALA a Thina precisa fazer isto UMA vez:"
  echo "  1. Criar app OAuth no Google Cloud (tipo Desktop)"
  echo "  2. GOOGLE_CLIENT_ID + GOOGLE_CLIENT_SECRET no .env"
  echo "     OU JSON em data/google_credentials.json"
  echo ""
  echo "Guia: docs/integracao-google.md (secao Instalador)"
  read -r -p "Caminho do JSON baixado (Enter para pular): " json_path
  if [[ -n "${json_path:-}" && -f "$json_path" ]]; then
    cp "$json_path" "$CREDS_FILE"
    has_creds_file=true
    echo "JSON copiado."
  fi
  if [[ "$has_creds_file" != true && "$has_env_creds" != true ]]; then
    echo "Sem credenciais — nao e possivel conectar a conta ainda."
    exit 1
  fi
fi

SETUP_URL="http://127.0.0.1:${PORT}/v1/google/setup"

if ! thina_running; then
  echo "A Thina nao esta rodando. Subindo stack Docker..."
  if [[ -x "$ROOT/start-docker.sh" ]]; then
    "$ROOT/start-docker.sh"
    sleep 8
  else
    echo "Rode ./start-docker.sh e execute este script de novo."
    exit 1
  fi
fi

if ! thina_running; then
  echo "Thina ainda offline. Verifique: docker compose ps"
  exit 1
fi

echo "Abrindo pagina para conectar sua conta Google..."
echo "  $SETUP_URL"
echo ""
echo "Clique em 'Conectar conta Google' e autorize no navegador."
echo ""

if command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$SETUP_URL" >/dev/null 2>&1 || true
elif command -v open >/dev/null 2>&1; then
  open "$SETUP_URL"
fi

echo 'Pronto! Depois de autorizar, teste: "Thina, tenho email novo no Gmail?"'
