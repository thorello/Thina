#!/usr/bin/env bash
# Funcoes Docker Compose para a stack Thina (HA + Kokoro + thina-server).
# Uso: source scripts/lib/docker-stack.sh
#      start_docker_stack [--build]
#      stop_docker_stack
#      restart_docker_stack
#      show_docker_stack_status

set -euo pipefail

DOCKER_STACK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DOCKER_STACK_COMPOSE="$DOCKER_STACK_ROOT/docker-compose.yml"

_get_compose_cmd() {
  if docker compose version >/dev/null 2>&1; then
    echo "docker compose"
  elif command -v docker-compose >/dev/null 2>&1; then
    echo "docker-compose"
  else
    echo "docker compose"
  fi
}

_invoke_compose() {
  local compose_cmd
  compose_cmd=$(_get_compose_cmd)
  if [[ ! -f "$DOCKER_STACK_COMPOSE" ]]; then
    echo "Compose nao encontrado: $DOCKER_STACK_COMPOSE" >&2
    return 1
  fi
  (
    cd "$DOCKER_STACK_ROOT"
    # shellcheck disable=SC2086
    $compose_cmd "$@"
  )
}

start_docker_stack() {
  local build=false
  for arg in "$@"; do
    case "$arg" in
      --build) build=true ;;
    esac
  done

  echo ""
  echo "=== Subindo stack Docker (HA + Kokoro + Thina) ==="
  echo "Raiz: $DOCKER_STACK_ROOT"

  local args=(up -d)
  if [[ "$build" == true ]]; then
    args+=(--build)
  fi

  _invoke_compose "${args[@]}"

  echo ""
  echo "=== Stack Docker iniciada ==="
  echo "  HA:     http://127.0.0.1:8123"
  echo "  Kokoro: http://127.0.0.1:8000/voices"
  echo "  Thina:  http://127.0.0.1:8080/health"
  echo "  UI:     http://127.0.0.1:8080/ui/"
  echo "  Docs:   http://127.0.0.1:8080/docs"
  echo ""
}

stop_docker_stack() {
  echo ""
  echo "=== Parando stack Docker ==="
  _invoke_compose down
  echo "=== Stack Docker parada ==="
  echo ""
}

show_docker_stack_status() {
  echo ""
  echo "=== Estado Docker Compose ==="
  _invoke_compose ps
  echo ""
}

restart_docker_stack() {
  stop_docker_stack
  start_docker_stack --build
}

docker_stack_images_missing() {
  local images has_thina=false has_kokoro=false repo
  images=$(docker images --format '{{.Repository}}' 2>/dev/null || true)
  while IFS= read -r repo; do
    repo="${repo//$'\r'/}"
    [[ -z "$repo" ]] && continue
    [[ "$repo" == "thina-thina" ]] && has_thina=true
    [[ "$repo" == "thina-kokoro" ]] && has_kokoro=true
  done <<< "$images"
  [[ "$has_thina" != true || "$has_kokoro" != true ]]
}
