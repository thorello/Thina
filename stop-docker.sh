#!/usr/bin/env bash
# Para a stack Docker (HA + Kokoro + thina-server).
# Uso: ./stop-docker.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
LIB="$ROOT/scripts/lib/docker-stack.sh"

if [[ ! -f "$LIB" ]]; then
  echo "Nao encontrado: $LIB" >&2
  exit 1
fi

# shellcheck source=scripts/lib/docker-stack.sh
source "$LIB"
stop_docker_stack
