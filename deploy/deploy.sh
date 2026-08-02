#!/usr/bin/env bash
set -euo pipefail

: "${DEPLOY_PATH:?DEPLOY_PATH is required}"
: "${RELEASE_SHA:?RELEASE_SHA is required}"

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

container_env_value() {
  local container_id="$1"
  local key="$2"
  docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$container_id" \
    | awk -F= -v key="$key" '$1 == key {print substr($0, index($0, "=") + 1)}' \
    | tail -n 1
}

maybe_collect_aq_final_closure() {
  local actual_sha="$1"
  local container_build_sha="$2"

  if [[ -z "${EXPECTED_DEPLOY_SHA:-}" || -z "${ROUTED_BACKEND_HOSTNAME:-}" ]]; then
    return 0
  fi
  if [[ "$EXPECTED_DEPLOY_SHA" != "$RELEASE_SHA" ]]; then
    echo "AQ_EXPECTED_DEPLOY_SHA_MISMATCH expected_env=$EXPECTED_DEPLOY_SHA release=$RELEASE_SHA" >&2
    return 1
  fi

  local container_id
  container_id="$(docker compose ps -q knowledge-engine)"
  test -n "$container_id"
  local image_id
  image_id="$(docker inspect --format '{{.Image}}' "$container_id")"
  local process_cmd
  process_cmd="$(docker inspect --format '{{json .Config.Cmd}}' "$container_id")"

  local runtime_sha
  runtime_sha="$(container_env_value "$container_id" M26_QUERY_BUILD_SHA)"
  export M26_QUERY_BACKEND_TOKEN="$(container_env_value "$container_id" M26_QUERY_BACKEND_TOKEN)"
  export KNOWLEDGE_ENGINE_OWNER_SUBJECT_HASH="$(container_env_value "$container_id" KNOWLEDGE_ENGINE_OWNER_SUBJECT_HASH)"

  local runtime_sha_present=false
  local backend_token_present=false
  local owner_hash_present=false
  local routed_hostname_present=false
  [[ -n "$runtime_sha" ]] && runtime_sha_present=true
  [[ -n "$M26_QUERY_BACKEND_TOKEN" ]] && backend_token_present=true
  [[ -n "$KNOWLEDGE_ENGINE_OWNER_SUBJECT_HASH" ]] && owner_hash_present=true
  [[ -n "$ROUTED_BACKEND_HOSTNAME" ]] && routed_hostname_present=true
  echo "AQ_CONTAINER_RUNTIME_SHA_PRESENT=$runtime_sha_present"
  echo "AQ_CONTAINER_BACKEND_TOKEN_PRESENT=$backend_token_present"
  echo "AQ_CONTAINER_OWNER_HASH_PRESENT=$owner_hash_present"
  echo "AQ_ROUTED_HOSTNAME_PRESENT=$routed_hostname_present"
  echo "AQ_ROUTED_ORIGIN_CLASS=named_cloudflare_tunnel_https_origin"

  test "$actual_sha" = "$EXPECTED_DEPLOY_SHA"
  test "$container_build_sha" = "$EXPECTED_DEPLOY_SHA"
  test "$runtime_sha" = "$EXPECTED_DEPLOY_SHA"
  test -n "$M26_QUERY_BACKEND_TOKEN"
  test -n "$KNOWLEDGE_ENGINE_OWNER_SUBJECT_HASH"
  test -n "$ROUTED_BACKEND_HOSTNAME"

  local evidence_dir="$DEPLOY_PATH/.m26-aq-final-production-closure"
  mkdir -p "$evidence_dir"
  chmod 700 "$evidence_dir"
  local identity_path="$evidence_dir/identity-$EXPECTED_DEPLOY_SHA.json"
  local frozen_path="$evidence_dir/frozen-$EXPECTED_DEPLOY_SHA.json"
  local blackbox_path="$evidence_dir/blackbox-$EXPECTED_DEPLOY_SHA.json"
  local routed_health_path="$evidence_dir/routed-health-$EXPECTED_DEPLOY_SHA.json"
  rm -f "$identity_path" "$frozen_path" "$blackbox_path" "$routed_health_path"

  PYTHONPATH=src python3 scripts/m26_aq_final_closure.py collect \
    --questions pilot/m26/m26-aq-final-r3-questions.json \
    --output "$frozen_path" \
    --expected-sha "$EXPECTED_DEPLOY_SHA"

  PYTHONPATH=src python3 scripts/m26_aq_final_closure.py validate \
    --input "$frozen_path" \
    --gate pilot/m26/m26-pa-7-resolved-production-gate.json \
    --expected-sha "$EXPECTED_DEPLOY_SHA"

  PYTHONPATH=src python3 scripts/m26_aq_final_closure.py collect \
    --questions pilot/m26/m26-aq-gpt-e-black-box-questions.json \
    --output "$blackbox_path" \
    --expected-sha "$EXPECTED_DEPLOY_SHA"

  PYTHONPATH=src python3 scripts/m26_aq_generalized_closure.py \
    --input "$blackbox_path" \
    --expected-sha "$EXPECTED_DEPLOY_SHA" \
    --minimum 10

  local routed_origin="https://${ROUTED_BACKEND_HOSTNAME}"
  local routed_code
  routed_code="$(curl --silent --show-error \
    -H "authorization: Bearer $M26_QUERY_BACKEND_TOKEN" \
    -H "x-m26-owner-subject-hash: $KNOWLEDGE_ENGINE_OWNER_SUBJECT_HASH" \
    -o "$routed_health_path" \
    -w '%{http_code}' \
    "${routed_origin%/}/api/m26/health")"
  if [[ "$routed_code" != "200" ]]; then
    echo "AQ_ROUTED_HEALTH_HTTP=$routed_code"
    return 1
  fi

  EXPECTED_DEPLOY_SHA="$EXPECTED_DEPLOY_SHA" \
  GIT_SHA="$actual_sha" \
  CONTAINER_ID="$container_id" \
  IMAGE_ID="$image_id" \
  RUNTIME_SHA="$runtime_sha" \
  PROCESS_CMD="$process_cmd" \
  FROZEN_PATH="$frozen_path" \
  ROUTED_HEALTH_PATH="$routed_health_path" \
  IDENTITY_PATH="$identity_path" \
  python3 - <<'PY'
import json
import os
from pathlib import Path

expected = os.environ["EXPECTED_DEPLOY_SHA"]
frozen = json.loads(Path(os.environ["FROZEN_PATH"]).read_text(encoding="utf-8"))
local_health = frozen.get("health", {}) if isinstance(frozen, dict) else {}
routed_health = json.loads(Path(os.environ["ROUTED_HEALTH_PATH"]).read_text(encoding="utf-8"))
routed_canonical = routed_health.get("canonical_runtime", {}) if isinstance(routed_health, dict) else {}
entrypoint = local_health.get("entrypoint")
expected_entrypoint = "knowledge_engine.m26_pa7_semantic_closure_runtime.run_owner_arbitrary_query"
if local_health.get("build_sha") != expected:
    raise SystemExit("local health SHA mismatch")
if routed_canonical.get("build_sha") != expected:
    raise SystemExit("routed health SHA mismatch")
if entrypoint != expected_entrypoint:
    raise SystemExit("local health entrypoint mismatch")
if routed_canonical.get("entrypoint") != expected_entrypoint:
    raise SystemExit("routed health entrypoint mismatch")
if routed_health.get("status") != "ok":
    raise SystemExit("routed health status mismatch")

evidence = {
    "schema_version": "m26-aq-production-identity/v2",
    "expected_deploy_sha": expected,
    "git_head_sha": os.environ["GIT_SHA"],
    "container_id": os.environ["CONTAINER_ID"],
    "image_id": os.environ["IMAGE_ID"],
    "container_runtime_sha": os.environ["RUNTIME_SHA"],
    "local_health_sha": local_health.get("build_sha"),
    "routed_health_sha": routed_canonical.get("build_sha"),
    "routed_health_status": routed_health.get("status"),
    "routed_route_class": "named_cloudflare_tunnel_https_origin",
    "entrypoint": entrypoint,
    "process_cmd": os.environ["PROCESS_CMD"],
    "frozen_population_rows": len(frozen.get("rows", [])),
    "raw_routed_origin_recorded": False,
    "raw_secret_recorded": False,
}
Path(os.environ["IDENTITY_PATH"]).write_text(
    json.dumps(evidence, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY

  test -s "$identity_path"
  test -s "$frozen_path"
  test -s "$blackbox_path"
  test -s "$routed_health_path"
  echo "AQ_ATOMIC_DEPLOY_AND_LIVE_CLOSURE_PASSED"
}

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

  # Keep the one-shot probe non-interactive as an additional local safeguard.
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
      maybe_collect_aq_final_closure "$actual_sha" "$container_build_sha"
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
