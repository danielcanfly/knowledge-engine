#!/usr/bin/env bash
set -euo pipefail

: "${DEPLOY_PATH:?DEPLOY_PATH is required}"
: "${RELEASE_SHA:?RELEASE_SHA is required}"

DEPLOY_LOCK_FILE="${KNOWLEDGE_ENGINE_DEPLOY_LOCK_FILE:-/tmp/knowledge-engine-production-oracle.lock}"
runtime_env=""

cleanup() {
  if [[ -n "$runtime_env" && -f "$runtime_env" ]]; then
    rm -f "$runtime_env"
  fi
}
trap cleanup EXIT

deploy_locked() {
  cd "$DEPLOY_PATH"

  git fetch --prune origin
  git checkout --detach "$RELEASE_SHA"
  actual_sha="$(git rev-parse HEAD)"
  if [[ "$actual_sha" != "$RELEASE_SHA" ]]; then
    echo "DEPLOYMENT_HEAD_MISMATCH expected=$RELEASE_SHA actual=$actual_sha" >&2
    return 1
  fi

  if [[ ! -f .env ]]; then
    echo "missing server-side .env" >&2
    return 1
  fi

  runtime_env="$(mktemp "$DEPLOY_PATH/.env.runtime.${RELEASE_SHA}.XXXXXX")"
  BASE_ENV="$DEPLOY_PATH/.env" RUNTIME_ENV="$runtime_env" RELEASE_SHA="$RELEASE_SHA" python3 - <<'PY'
import os
from pathlib import Path

base = Path(os.environ["BASE_ENV"])
runtime = Path(os.environ["RUNTIME_ENV"])
release_sha = os.environ["RELEASE_SHA"]
lines = base.read_text(encoding="utf-8").splitlines()
out = []
for line in lines:
    stripped = line.lstrip()
    if stripped.startswith("M26_QUERY_BUILD_SHA=") or stripped.startswith("export M26_QUERY_BUILD_SHA="):
        continue
    out.append(line)
out.append(f"M26_QUERY_BUILD_SHA={release_sha}")
runtime.write_text("\n".join(out) + "\n", encoding="utf-8")
os.chmod(runtime, 0o600)
PY

  export M26_RUNTIME_ENV_FILE="$runtime_env"

  docker compose build --pull
  docker compose down --remove-orphans || true
  docker compose rm -f -s -v knowledge-engine >/dev/null 2>&1 || true
  docker compose config >/dev/null

  # Never let the one-shot config probe inherit a caller's stdin. Production
  # closure executes this script inside `ssh ... bash -s`; redirecting stdin
  # prevents compose from consuming the remaining remote acceptance program.
  docker compose run --rm --no-deps knowledge-engine \
    python -c 'from knowledge_engine.config import Settings; Settings.from_env(); print("CONFIG_OK")' \
    </dev/null

  docker compose up -d --remove-orphans

  for attempt in $(seq 1 30); do
    if curl --fail --silent http://127.0.0.1:8080/v1/health >/dev/null; then
      container_build_sha="$(docker compose exec -T knowledge-engine sh -c 'printf %s "$M26_QUERY_BUILD_SHA"')"
      if [[ "$container_build_sha" != "$RELEASE_SHA" ]]; then
        echo "DEPLOYMENT_RUNTIME_SHA_MISMATCH expected=$RELEASE_SHA actual=$container_build_sha" >&2
        docker compose logs --tail=200 knowledge-engine
        return 1
      fi
      image_id="$(docker compose images -q knowledge-engine | head -n 1)"
      echo "DEPLOYMENT_HEAD_SHA=$actual_sha"
      echo "DEPLOYMENT_RUNTIME_SHA=$container_build_sha"
      echo "DEPLOYMENT_IMAGE_ID=$image_id"
      echo "DEPLOYMENT_HEALTH_PASSED"
      return 0
    fi
    sleep 2
  done

  docker compose logs --tail=200 knowledge-engine
  return 1
}

if [[ "${KNOWLEDGE_ENGINE_DEPLOY_LOCK_HELD:-0}" == "1" ]]; then
  deploy_locked
else
  command -v flock >/dev/null 2>&1 || {
    echo "flock is required for production deployment serialization" >&2
    exit 1
  }
  exec 9>"$DEPLOY_LOCK_FILE"
  flock -x 9
  deploy_locked
fi
