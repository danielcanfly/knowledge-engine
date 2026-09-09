#!/usr/bin/env bash
set -euo pipefail

: "${DEPLOY_PATH:?DEPLOY_PATH is required}"
: "${ROLLBACK_SHA:?ROLLBACK_SHA is required}"
: "${ROLLBACK_IMAGE_ID:?ROLLBACK_IMAGE_ID is required}"
: "${ROLLBACK_ENV_FILE:?ROLLBACK_ENV_FILE is required}"
: "${ROLLBACK_ENV_SHA256:?ROLLBACK_ENV_SHA256 is required}"

if [[ ! "$ROLLBACK_SHA" =~ ^[0-9a-f]{40}$ ]]; then
  echo "ROLLBACK_SHA must be an exact 40-character lowercase commit SHA" >&2
  exit 2
fi
if [[ ! "$ROLLBACK_IMAGE_ID" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  echo "ROLLBACK_IMAGE_ID must be an exact sha256 image ID" >&2
  exit 2
fi
if [[ ! "$ROLLBACK_ENV_SHA256" =~ ^[0-9a-f]{64}$ ]]; then
  echo "ROLLBACK_ENV_SHA256 must be an exact lowercase SHA256" >&2
  exit 2
fi
deploy_root="$(cd "$DEPLOY_PATH" && pwd -P)"
rollback_env_dir="$(cd "$(dirname "$ROLLBACK_ENV_FILE")" && pwd -P)"
rollback_env_name="$(basename "$ROLLBACK_ENV_FILE")"
if [[ "$rollback_env_dir" != "$deploy_root" || ! "$rollback_env_name" =~ ^\.env\.pre-deploy-[0-9]{8}T[0-9]{6}Z$ ]]; then
  echo "ROLLBACK_ENV_FILE must be a canonical pre-deploy backup inside DEPLOY_PATH" >&2
  exit 2
fi

rollback_locked() {
  cd "$DEPLOY_PATH"
  test -f "$ROLLBACK_ENV_FILE" || {
    echo "rollback environment backup is missing" >&2
    return 1
  }
  observed_env_sha256="$(sha256sum "$ROLLBACK_ENV_FILE" | cut -d' ' -f1)"
  if [[ "$observed_env_sha256" != "$ROLLBACK_ENV_SHA256" ]]; then
    echo "ROLLBACK_ENV_SHA256_MISMATCH expected=$ROLLBACK_ENV_SHA256 actual=$observed_env_sha256" >&2
    return 1
  fi

  rollback_tag="knowledge-engine-rollback:$ROLLBACK_SHA"
  tagged_id="$(docker image inspect "$rollback_tag" --format '{{.Id}}' 2>/dev/null || true)"
  if [[ "$tagged_id" != "$ROLLBACK_IMAGE_ID" ]]; then
    echo "ROLLBACK_IMAGE_ID_MISMATCH expected=$ROLLBACK_IMAGE_ID actual=$tagged_id" >&2
    return 1
  fi

  git fetch --prune origin
  git checkout --detach "$ROLLBACK_SHA"
  actual_sha="$(git rev-parse HEAD)"
  if [[ "$actual_sha" != "$ROLLBACK_SHA" ]]; then
    echo "ROLLBACK_HEAD_MISMATCH expected=$ROLLBACK_SHA actual=$actual_sha" >&2
    return 1
  fi

  cp -p "$ROLLBACK_ENV_FILE" .env.rollback-next
  chmod 600 .env.rollback-next
  mv .env.rollback-next .env
  export M26_RUNTIME_IMAGE="$rollback_tag"
  unset M26_RUNTIME_ENV_FILE
  docker compose config >/dev/null
  docker compose up -d --no-build --remove-orphans

  for _attempt in $(seq 1 30); do
    health_probe="$(mktemp)"
    if curl --fail --silent --show-error --max-time 5 \
      http://127.0.0.1:8080/v1/answers/health >"$health_probe"; then
      health_ok="$(python3 -c 'import json,sys; p=json.load(open(sys.argv[1])); print(str(p.get("ok")).lower())' "$health_probe")"
      health_sha="$(python3 -c 'import json,sys; p=json.load(open(sys.argv[1])); print((p.get("backend") or p.get("runtime") or {}).get("build_sha", ""))' "$health_probe")"
      rm -f "$health_probe"
      container_id="$(docker compose ps -q knowledge-engine)"
      running_image_id="$(docker inspect --format '{{.Image}}' "$container_id")"
      if [[ "$health_ok" == "true" && "$health_sha" == "$ROLLBACK_SHA" && "$running_image_id" == "$ROLLBACK_IMAGE_ID" ]]; then
        echo "ROLLBACK_HEAD_SHA=$actual_sha"
        echo "ROLLBACK_RUNTIME_SHA=$health_sha"
        echo "ROLLBACK_IMAGE_ID=$running_image_id"
        echo "ROLLBACK_EXACT_IMAGE_PASSED"
        return 0
      fi
      echo "ROLLBACK_IDENTITY_MISMATCH expected_sha=$ROLLBACK_SHA actual_sha=$health_sha expected_image=$ROLLBACK_IMAGE_ID actual_image=$running_image_id" >&2
      return 1
    fi
    rm -f "$health_probe"
    sleep 2
  done
  echo "ROLLBACK_HTTP_LIVENESS_TIMEOUT" >&2
  return 1
}

command -v flock >/dev/null 2>&1 || {
  echo "flock is required for production rollback serialization" >&2
  exit 1
}
rollback_lock="${KNOWLEDGE_ENGINE_DEPLOY_LOCK_FILE:-/tmp/knowledge-engine-production-oracle.lock}"
exec 9>"$rollback_lock"
flock -x 9
rollback_locked
