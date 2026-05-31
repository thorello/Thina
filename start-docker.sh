#!/usr/bin/env bash
# Sobe HA + Kokoro + thina-server via Docker Compose.
# Uso: ./start-docker.sh
#      ./start-docker.sh --build

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
LIB="$ROOT/scripts/lib/docker-stack.sh"

if [[ ! -f "$LIB" ]]; then
  echo "Nao encontrado: $LIB" >&2
  exit 1
fi

# shellcheck source=scripts/lib/docker-stack.sh
source "$LIB"

KOKORO_APP="$ROOT/kokoro/src/app.py"
if [[ ! -f "$KOKORO_APP" ]]; then
  echo "Kokoro nao encontrado. Executando install.sh --docker-only..."
  "$ROOT/install.sh" --docker-only
fi

BUILD=false
for arg in "$@"; do
  case "$arg" in
    --build) BUILD=true ;;
  esac
done

if [[ "$BUILD" != true ]] && docker_stack_images_missing; then
  echo "Imagens Docker ainda nao existem — build automatico na primeira execucao."
  BUILD=true
fi

if [[ "$BUILD" == true ]]; then
  start_docker_stack --build
else
  start_docker_stack
fi
