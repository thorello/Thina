#!/usr/bin/env bash
# Reinicia a stack Docker (para + sobe com rebuild).
# Uso: ./restart-docker.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
LIB="$ROOT/scripts/lib/docker-stack.sh"

if [[ ! -f "$LIB" ]]; then
  echo "Nao encontrado: $LIB" >&2
  exit 1
fi

# shellcheck source=scripts/lib/docker-stack.sh
source "$LIB"
restart_docker_stack
