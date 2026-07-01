#!/usr/bin/env bash
set -euo pipefail

: "${DEPLOY_PATH:?DEPLOY_PATH is required}"
: "${RELEASE_SHA:?RELEASE_SHA is required}"

cd "$DEPLOY_PATH"
git fetch --prune origin
git checkout --detach "$RELEASE_SHA"
docker compose build --pull

docker compose run --rm --no-deps knowledge-engine \
  python -c 'from knowledge_engine.config import Settings; Settings.from_env(); print("CONFIG_OK")'

docker compose up -d --remove-orphans

for attempt in $(seq 1 30); do
  if curl --fail --silent http://127.0.0.1:8080/v1/health >/dev/null; then
    echo "DEPLOYMENT_HEALTH_PASSED"
    exit 0
  fi
  sleep 2
done

docker compose logs --tail=200 knowledge-engine
exit 1
