#!/usr/bin/env bash
set -euo pipefail

: "${DEPLOY_PATH:?DEPLOY_PATH is required}"
: "${ROLLBACK_SHA:?ROLLBACK_SHA is required}"

cd "$DEPLOY_PATH"
git fetch --prune origin
git checkout --detach "$ROLLBACK_SHA"
docker compose build
docker compose up -d --remove-orphans
curl --fail --retry 20 --retry-delay 2 http://127.0.0.1:8080/v1/health
