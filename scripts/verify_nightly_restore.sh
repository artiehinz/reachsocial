#!/usr/bin/env bash
# Verify the latest encrypted nightly backup without touching production state.
#
# This script is intentionally root-only: the Restic password file and the
# production backup repository are root-protected. It restores into a fresh
# NVMe directory, starts isolated no-network containers, verifies database and
# application compatibility, then removes every temporary container and file.
set -Eeuo pipefail

readonly volume_root="/mnt/reachsocial_data_tor1_01"
readonly repository="$volume_root/backups/agent-enhancer"
readonly password_file="$volume_root/operations/restic-password"
readonly reachsocial_container="reachsocial-app-1"
readonly postgres_container="agent-enhancer-postgres-1"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this verifier as root; it needs the protected Restic password file." >&2
  exit 1
fi

for command in restic docker python3; do
  command -v "$command" >/dev/null || {
    echo "Required command is unavailable: $command" >&2
    exit 1
  }
done
for path in "$repository" "$password_file"; do
  [[ -e "$path" ]] || {
    echo "Required backup path is unavailable: $path" >&2
    exit 1
  }
done
# Use the exact locally installed image backing the live database, so the
# restore tools match its PostgreSQL major version without pulling an image.
postgres_image="$(docker inspect --format '{{.Image}}' "$postgres_container")"
readonly postgres_image
docker image inspect "$postgres_image" >/dev/null || {
  echo "Required local image is unavailable: $postgres_image" >&2
  exit 1
}

umask 077
restore_root="$(mktemp -d "$volume_root/restore-verification.XXXXXX")"
runtime_data="$restore_root/reachsocial-runtime"
aeu_restore_data="$restore_root/agent-enhancer-runtime"
suffix="${RANDOM}${RANDOM}"
restore_app="reachsocial-restore-${suffix}"
restore_postgres="reachsocial-restore-postgres-${suffix}"

cleanup() {
  docker rm --force "$restore_app" "$restore_postgres" >/dev/null 2>&1 || true
  rm -rf -- "$restore_root"
}
trap cleanup EXIT

export RESTIC_REPOSITORY="$repository"
export RESTIC_PASSWORD_FILE="$password_file"
restic restore latest --host reachsocial-production --path "$volume_root/backup-staging/current" --target "$restore_root"

reachsocial_db="$(find "$restore_root" -type f -name reachsocial.db -print -quit)"
aeu_dump="$(find "$restore_root" -type f -name agent-enhancer.pgdump -print -quit)"
[[ -n "$reachsocial_db" && -n "$aeu_dump" ]] || {
  echo "Latest backup did not contain both application database artifacts." >&2
  exit 1
}

python3 - "$reachsocial_db" <<'PY'
import sqlite3
import sys

database = sys.argv[1]
with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        raise SystemExit(f"ReachSocial SQLite integrity check failed: {integrity}")
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    required = {"oauth_states", "payment_receipts", "idempotency_records"}
    missing = sorted(required - tables)
    if missing:
        raise SystemExit(f"ReachSocial restore is missing required tables: {', '.join(missing)}")
    receipts = connection.execute("SELECT count(*) FROM payment_receipts").fetchone()[0]
    mcp_requests = connection.execute(
        "SELECT count(*) FROM oauth_states WHERE kind = 'mcp_request'"
    ).fetchone()[0]
    if receipts < 1:
        raise SystemExit("ReachSocial restore has no historical payment receipts")
print(f"ReachSocial SQLite verified: receipts={receipts} mcp_requests={mcp_requests}")
PY

install -d -m 0700 "$runtime_data"
install -m 0600 "$reachsocial_db" "$runtime_data/reachsocial.db"
chown -R 10001:10001 "$runtime_data"
reachsocial_image="$(docker inspect --format '{{.Image}}' "$reachsocial_container")"
docker run --detach --rm --name "$restore_app" --network none --read-only \
  --tmpfs /tmp:size=64m,mode=1777 \
  --env APP_ENV=restore-verification \
  --env PUBLIC_BASE_URL=http://restore.local \
  --env DATABASE_URL=sqlite:////data/reachsocial.db \
  --env X402_ENABLED=false \
  --env MCP_ENABLED=true \
  --env OAUTH_ENABLED=true \
  --env MCP_PAYMENT_APPROVAL_ENABLED=true \
  --env OAUTH_VALIDATION_WALLETS=0x1111111111111111111111111111111111111111 \
  --env EXTERNAL_BACKUP_ENABLED=false \
  --volume "$runtime_data:/data" \
  --pull never "$reachsocial_image" >/dev/null

ready=false
for _ in $(seq 1 30); do
  if docker exec "$restore_app" python -c \
    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)" \
    >/dev/null 2>&1; then
    ready=true
    break
  fi
  sleep 1
done
[[ "$ready" == true ]] || {
  echo "Isolated ReachSocial application did not become healthy." >&2
  exit 1
}
docker exec "$restore_app" python -c 'from urllib.error import HTTPError
from urllib.request import Request, urlopen

base = "http://127.0.0.1:8000"
for path in [
    "/healthz",
    "/.well-known/oauth-authorization-server",
    "/.well-known/oauth-protected-resource/mcp/",
]:
    with urlopen(base + path, timeout=10) as response:
        assert response.status == 200, (path, response.status)
request = Request(
    base + "/mcp/",
    data=b'"'"'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}'"'"',
    headers={"Content-Type": "application/json"},
    method="POST",
)
try:
    urlopen(request, timeout=10)
    raise AssertionError("anonymous MCP initialization unexpectedly succeeded")
except HTTPError as error:
    assert error.code == 401, error.code
    assert "resource_metadata=" in error.headers.get("WWW-Authenticate", "")'

install -d -m 0755 "$aeu_restore_data"
install -m 0444 "$aeu_dump" "$aeu_restore_data/agent-enhancer.pgdump"
docker run --detach --rm --name "$restore_postgres" --network none \
  --env POSTGRES_HOST_AUTH_METHOD=trust \
  --env POSTGRES_USER=restore_verify \
  --env POSTGRES_DB=agent_enhancer_restore \
  --volume "$aeu_restore_data:/restore:ro" \
  --pull never "$postgres_image" >/dev/null
postgres_ready=false
for _ in $(seq 1 30); do
  # The initialization server listens only on a Unix socket. TCP proves the
  # final server is ready, without racing its initialization-server shutdown.
  if docker exec "$restore_postgres" psql -h 127.0.0.1 -U restore_verify -d agent_enhancer_restore -Atc \
    'SELECT 1' 2>/dev/null | grep -qx '1'; then
    postgres_ready=true
    break
  fi
  sleep 1
done
[[ "$postgres_ready" == true ]] || {
  echo "Isolated Agent Enhancer PostgreSQL did not become ready." >&2
  exit 1
}
docker exec "$restore_postgres" pg_restore \
  --no-owner --no-privileges --exit-on-error \
  --username=restore_verify --dbname=agent_enhancer_restore \
  /restore/agent-enhancer.pgdump
aeu_table_count="$(docker exec "$restore_postgres" psql -U restore_verify -d agent_enhancer_restore -Atc \
  "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")"
[[ "$aeu_table_count" =~ ^[1-9][0-9]*$ ]] || {
  echo "Isolated Agent Enhancer restore has no public tables." >&2
  exit 1
}

printf 'Nightly restore verification passed: ReachSocial app/OAuth/MCP and AEU database (%s public tables).\n' \
  "$aeu_table_count"
