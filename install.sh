#!/usr/bin/env bash
# Instalacao inicial: Kokoro (submodulo/clone) + .env + venvs opcionais.
# Uso: ./install.sh
#      ./install.sh --docker-only
#      ./install.sh --native-only

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
KOKORO_DIR="$ROOT/kokoro"
KOKORO_URL="https://github.com/thorello/kokoro.git"
DOCKER_ONLY=false
NATIVE_ONLY=false

for arg in "$@"; do
  case "$arg" in
    --docker-only) DOCKER_ONLY=true ;;
    --native-only) NATIVE_ONLY=true ;;
  esac
done

step() { echo -e "\n>> $1"; }

ensure_kokoro() {
  if [[ -f "$KOKORO_DIR/src/app.py" ]]; then
    echo "  Kokoro OK em kokoro/"
    return
  fi
  step "Obtendo Kokoro TTS"
  cd "$ROOT"
  if [[ -f .gitmodules ]]; then
    git submodule update --init --recursive || true
  fi
  if [[ -f "$KOKORO_DIR/src/app.py" ]]; then
    echo "  Kokoro via submodulo"
    return
  fi
  rm -rf "$KOKORO_DIR"
  git clone --depth 1 "$KOKORO_URL" "$KOKORO_DIR"
  echo "  Kokoro clonado em kokoro/"
}

ensure_env() {
  if [[ -f "$ROOT/.env" ]]; then
    echo "  .env ja existe"
    return
  fi
  cp "$ROOT/.env.example" "$ROOT/.env"
  echo "  .env criado — edite chaves LLM e HOME_ASSISTANT_TOKEN"
}

ensure_data() {
  mkdir -p "$ROOT/data/audio" "$ROOT/data/run" "$ROOT/data/homeassistant"
  if [[ ! -f "$ROOT/data/tts_settings.json" ]]; then
    echo "{}" > "$ROOT/data/tts_settings.json"
  fi
  if [[ ! -d "$ROOT/maps/private" && -d "$ROOT/maps/private.example" ]]; then
    cp -R "$ROOT/maps/private.example" "$ROOT/maps/private"
  fi
}

install_native() {
  step "Ambiente Python nativo"
  if ! command -v python3 >/dev/null 2>&1; then
    echo "  AVISO: python3 nao encontrado"
    return
  fi
  if [[ ! -d "$ROOT/.venv" ]]; then
    python3 -m venv "$ROOT/.venv"
    "$ROOT/.venv/bin/pip" install -r "$ROOT/requirements.txt"
  fi
  if [[ ! -d "$KOKORO_DIR/.venv" ]]; then
    python3 -m venv "$KOKORO_DIR/.venv"
    "$KOKORO_DIR/.venv/bin/pip" install -r "$KOKORO_DIR/requirements.txt"
  fi
  if [[ -d "$ROOT/ui" && ! -d "$ROOT/ui/node_modules" ]] && command -v npm >/dev/null 2>&1; then
    npm install --prefix "$ROOT/ui" --no-fund --no-audit
  fi
}

echo ""
echo "=== Instalacao Thina Server ==="
echo "Raiz: $ROOT"

ensure_kokoro
ensure_env
ensure_data

if [[ "$DOCKER_ONLY" != true ]]; then
  install_native
fi

echo ""
echo "=== Instalacao concluida ==="
if [[ "$NATIVE_ONLY" != true ]]; then
  echo "  Docker:  docker compose up -d --build"
fi
if [[ "$DOCKER_ONLY" != true ]]; then
  echo "  Nativo:  ./scripts/start-services.sh (se existir) ou python main.py"
fi
