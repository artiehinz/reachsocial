#!/usr/bin/env bash
set -euo pipefail

: "${REACHSOCIAL_IMAGE_REPOSITORY:?set the ReachSocial registry repository}"

# Docker lists repository tags newest first. Keep the live image and one rollback image.
mapfile -t image_ids < <(
  docker image ls "$REACHSOCIAL_IMAGE_REPOSITORY" --format '{{.ID}} {{.Tag}}' \
    | awk '$2 != "<none>" && !seen[$1]++ {print $1}'
)

if (( ${#image_ids[@]} > 2 )); then
  docker image rm "${image_ids[@]:2}" || true
fi
