#!/usr/bin/env bash
set -euo pipefail

: "${DEPLOY_PATH:?set DEPLOY_PATH}"
: "${DOCR_REGISTRY:?set DOCR_REGISTRY}"
: "${IMAGE_TAG:?set IMAGE_TAG}"

cd "$DEPLOY_PATH"
previous_image="$(sed -n 's/^REACHSOCIAL_IMAGE=//p' .env | tail -n 1)"
new_image="$DOCR_REGISTRY/reachsocial:$IMAGE_TAG"

wait_for_app() {
  local attempts=90
  local container_id
  while (( attempts > 0 )); do
    container_id="$(docker compose ps -q app)"
    if [[ -n "$container_id" ]] \
      && [[ "$(docker inspect --format '{{.State.Health.Status}}' "$container_id" 2>/dev/null || true)" == "healthy" ]] \
      && docker compose exec -T app python -c \
        "import urllib.request; urllib.request.urlopen('http://localhost:8000/readyz', timeout=5)"; then
      return 0
    fi
    sleep 1
    attempts=$((attempts - 1))
  done
  return 1
}

set_image() {
  local image="$1"
  sed -i "s|^REACHSOCIAL_IMAGE=.*|REACHSOCIAL_IMAGE=$image|" .env
}

rollback() {
  echo "::error::ReachSocial deployment failed; restoring $previous_image"
  if [[ -n "$previous_image" ]]; then
    set_image "$previous_image"
    docker compose up -d --no-build
    wait_for_app || echo "::error::ReachSocial rollback health check failed"
  fi
  exit 1
}

docker pull "$new_image"
set_image "$new_image"
docker compose up -d --no-build || rollback
wait_for_app || rollback
docker compose ps
