#!/usr/bin/env bash
set -euo pipefail

: "${DEPLOY_PATH:?DEPLOY_PATH is required}"
: "${RELEASE_SHA:?RELEASE_SHA is required}"

CANONICAL_M26_QDRANT_COLLECTION="m25_blog_m25blog_5250f8422f4f_f5f01d82c7a1_fe499db2e043_fe499db2e043"

# Production deployment is sometimes invoked from `ssh ... bash -s`. Isolate the
# entire deploy subprocess from that caller's stdin so no Docker/BuildKit child
# can consume the remaining remote acceptance program.
if [[ "${KNOWLEDGE_ENGINE_DEPLOY_STDIN_ISOLATED:-0}" != "1" ]]; then
  export KNOWLEDGE_ENGINE_DEPLOY_STDIN_ISOLATED=1
  exec bash "$0" </dev/null
fi

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
  # The shared production checkout is a deployment cache, not an authoring
  # workspace. Under the production host lock, discard tracked residue from a
  # prior diagnostic/repair before selecting the immutable release SHA. This
  # preserves untracked/ignored server configuration such as .env while making
  # exact-head deployment deterministic.
  git reset --hard HEAD
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
  BASE_ENV="$DEPLOY_PATH/.env" \
  RUNTIME_ENV="$runtime_env" \
  RELEASE_SHA="$RELEASE_SHA" \
  CANONICAL_M26_QDRANT_COLLECTION="$CANONICAL_M26_QDRANT_COLLECTION" \
  python3 - <<'PY'
import os
from pathlib import Path

base = Path(os.environ["BASE_ENV"])
runtime = Path(os.environ["RUNTIME_ENV"])
release_sha = os.environ["RELEASE_SHA"]
canonical_collection = os.environ["CANONICAL_M26_QDRANT_COLLECTION"]
lines = base.read_text(encoding="utf-8").splitlines()
out = []
for line in lines:
    stripped = line.lstrip()
    if stripped.startswith("M26_QUERY_BUILD_SHA=") or stripped.startswith(
        "export M26_QUERY_BUILD_SHA="
    ):
        continue
    if stripped.startswith("M26_PA7_DENSE_COLLECTION=") or stripped.startswith(
        "export M26_PA7_DENSE_COLLECTION="
    ):
        continue
    out.append(line)
out.append(f"M26_QUERY_BUILD_SHA={release_sha}")
out.append(f"M26_PA7_DENSE_COLLECTION={canonical_collection}")
runtime.write_text("\n".join(out) + "\n", encoding="utf-8")
os.chmod(runtime, 0o600)
PY

  export M26_RUNTIME_ENV_FILE="$runtime_env"

  docker compose build --pull
  docker compose down --remove-orphans || true
  docker compose rm -f -s -v knowledge-engine >/dev/null 2>&1 || true
  docker compose config >/dev/null

  # Keep the one-shot probe non-interactive as an additional local safeguard.
  docker compose run --rm --no-deps knowledge-engine \
    python -c 'from knowledge_engine.config import Settings; Settings.from_env(); print("CONFIG_OK")' \
    </dev/null

  docker compose up -d --remove-orphans

  for attempt in $(seq 1 90); do
    # Deployment only needs HTTP liveness plus immutable runtime identity; the
    # owner-only closure workflow performs the heavier semantic health/readiness
    # checks immediately afterwards.
    if curl --fail --silent --max-time 5 http://127.0.0.1:8080/openapi.json >/dev/null; then
      container_build_sha="$(docker compose exec -T knowledge-engine sh -c 'printf %s "$M26_QUERY_BUILD_SHA"')"
      if [[ "$container_build_sha" != "$RELEASE_SHA" ]]; then
        echo "DEPLOYMENT_RUNTIME_SHA_MISMATCH expected=$RELEASE_SHA actual=$container_build_sha" >&2
        docker compose logs --tail=200 knowledge-engine >&2
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

  echo "DEPLOYMENT_HTTP_LIVENESS_TIMEOUT release_sha=$RELEASE_SHA" >&2
  docker compose logs --tail=200 knowledge-engine >&2
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
