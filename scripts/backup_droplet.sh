#!/usr/bin/env bash
set -euo pipefail

readonly volume_root="/mnt/reachsocial_data_tor1_01"
readonly staging="$volume_root/backup-staging/current"
readonly repository="$volume_root/backups/agent-enhancer"
readonly password_file="$volume_root/operations/restic-password"
readonly reachsocial_path="$volume_root/apps/reachsocial"
readonly aeu_path="$volume_root/apps/agent-enhancer"

umask 077
install -d -m 0700 "$staging" "$volume_root/backup-logs"
find "$staging" -mindepth 1 -depth -delete

docker exec -i reachsocial-app-1 python - <<'PY'
import sqlite3
from pathlib import Path

source = Path("/data/reachsocial.db")
target = Path("/tmp/reachsocial-backup.db")
with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
    src.backup(dst)
target.chmod(0o600)
PY
docker cp reachsocial-app-1:/tmp/reachsocial-backup.db "$staging/reachsocial.db"
docker exec reachsocial-app-1 python -c \
  'from pathlib import Path; Path("/tmp/reachsocial-backup.db").unlink()'
docker exec agent-enhancer-postgres-1 \
  pg_dump --username agent_enhancer --dbname agent_enhancer --format=custom \
  > "$staging/agent-enhancer.pgdump"

install -d -m 0700 "$staging/config/reachsocial" "$staging/config/agent-enhancer"
cp -a \
  "$reachsocial_path/.env" \
  "$reachsocial_path/docker-compose.yml" \
  "$reachsocial_path/deploy/caddy/Caddyfile" \
  "$staging/config/reachsocial/"
cp -a \
  "$aeu_path/.env.production" \
  "$aeu_path/compose.production.yaml" \
  "$staging/config/agent-enhancer/"

export RESTIC_REPOSITORY="$repository"
export RESTIC_PASSWORD_FILE="$password_file"
restic backup "$staging" --host reachsocial-production
restic forget --host reachsocial-production \
  --keep-daily 7 --keep-weekly 4 --keep-monthly 6 --prune
restic check
