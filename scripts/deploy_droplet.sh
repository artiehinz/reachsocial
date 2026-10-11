#!/usr/bin/env bash
set -euo pipefail

: "${DEPLOY_PATH:?set DEPLOY_PATH}"
: "${DOCR_REGISTRY:?set DOCR_REGISTRY}"
: "${IMAGE_TAG:?set IMAGE_TAG}"

cd "$DEPLOY_PATH"
previous_image="$(sed -n 's/^REACHSOCIAL_IMAGE=//p' .env | tail -n 1)"
new_image="$DOCR_REGISTRY/reachsocial:$IMAGE_TAG"

app_is_ready_or_safely_paused() {
  docker compose exec -T app python - <<'PY'
import json
import urllib.error
import urllib.request

url = "http://localhost:8000/readyz"
try:
    with urllib.request.urlopen(url, timeout=5):
        raise SystemExit(0)
except urllib.error.HTTPError as error:
    if error.code != 503:
        raise
    try:
        payload = json.load(error)
    except (TypeError, ValueError):
        raise SystemExit(1) from None
    raise SystemExit(0 if payload.get("status") == "payments_paused" else 1)
PY
}

wait_for_app() {
  local attempts=90
  local container_id
  while (( attempts > 0 )); do
    container_id="$(docker compose ps -q app)"
    if [[ -n "$container_id" ]] \
      && [[ "$(docker inspect --format '{{.State.Health.Status}}' "$container_id" 2>/dev/null || true)" == "healthy" ]] \
      && app_is_ready_or_safely_paused; then
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
