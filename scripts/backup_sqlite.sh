#!/usr/bin/env bash
set -euo pipefail

: "${REACHSOCIAL_BACKUP_KEY:?set an encryption key in the protected host environment}"
backup_dir="${REACHSOCIAL_BACKUP_DIR:-/var/lib/reachsocial-backups}"
database_path="${REACHSOCIAL_SQLITE_PATH:-/var/lib/docker/volumes/reachsocial_reachsocial_data/_data/reachsocial.db}"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$backup_dir"
tmp_file="$(mktemp "$backup_dir/reachsocial-${timestamp}.XXXXXX.db")"
trap 'rm -f "$tmp_file"' EXIT
sqlite3 "$database_path" ".backup '$tmp_file'"
gzip -c "$tmp_file" | openssl enc -aes-256-gcm -salt -pbkdf2 -pass env:REACHSOCIAL_BACKUP_KEY > "$backup_dir/reachsocial-${timestamp}.db.gz.enc"
find "$backup_dir" -name 'reachsocial-*.db.gz.enc' -mtime +7 -delete
