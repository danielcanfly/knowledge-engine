#!/usr/bin/env bash
set -euo pipefail

fail() {
  echo "AQ_PRODUCTION_CLOSURE_FAILURE=$1" >&2
  exit 1
}

echo "AQ_STAGE=host_lock_wait"
lock_file="/tmp/knowledge-engine-production-oracle.lock"
exec 9>"$lock_file"
flock -x 9
echo "AQ_STAGE=host_lock_acquired"

if [ ! -d "$DEPLOY_PATH/.git" ]; then
  git clone https://github.com/danielcanfly/knowledge-engine.git "$DEPLOY_PATH"
fi

exact_head_deploy_script="${AQ_EXACT_HEAD_DEPLOY_SCRIPT:-/tmp/m26-aq-exact-head-deploy.sh}"
[ -s "$exact_head_deploy_script" ] || fail "exact_head_deploy_script_missing"

echo "AQ_STAGE=deploy_start"
deploy_output="$(
  KNOWLEDGE_ENGINE_DEPLOY_LOCK_HELD=1 \
    DEPLOY_PATH="$DEPLOY_PATH" \
    RELEASE_SHA="$RELEASE_SHA" \
    bash "$exact_head_deploy_script" </dev/null
)"
printf '%s\n' "$deploy_output"
echo "AQ_STAGE=deploy_complete"

receipt_head="$(printf '%s\n' "$deploy_output" | awk -F= '$1 == "DEPLOYMENT_HEAD_SHA" {print $2}' | tail -n 1)"
receipt_runtime_sha="$(printf '%s\n' "$deploy_output" | awk -F= '$1 == "DEPLOYMENT_RUNTIME_SHA" {print $2}' | tail -n 1)"
receipt_image_id="$(printf '%s\n' "$deploy_output" | awk -F= '$1 == "DEPLOYMENT_IMAGE_ID" {print $2}' | tail -n 1)"

[ "$receipt_head" = "$EXPECTED_DEPLOY_SHA" ] || fail "deploy_head_sha_mismatch"
[ "$receipt_runtime_sha" = "$EXPECTED_DEPLOY_SHA" ] || fail "deploy_runtime_sha_mismatch"
[ -n "$receipt_image_id" ] || fail "deploy_image_receipt_missing"
echo "AQ_STAGE=deployment_receipt_validated"
echo "AQ_DEPLOY_HEAD_SHA=$receipt_head"
echo "AQ_DEPLOY_RUNTIME_SHA=$receipt_runtime_sha"
echo "AQ_DEPLOY_IMAGE_RECEIPT_PRESENT=true"

cd "$DEPLOY_PATH"
checkout_head="$(git rev-parse HEAD)"
if [ "$checkout_head" != "$EXPECTED_DEPLOY_SHA" ]; then
  echo "AQ_SHARED_CHECKOUT_HEAD_MISMATCH=true"
  echo "AQ_SHARED_CHECKOUT_HEAD_ACTUAL=$checkout_head"
  fail "shared_checkout_changed_inside_host_lock"
fi
echo "AQ_SHARED_CHECKOUT_HEAD_MATCH=true"

container_ids="$(docker compose ps -q knowledge-engine || true)"
container_count="$(printf '%s\n' "$container_ids" | sed '/^$/d' | wc -l | tr -d ' ')"
echo "AQ_COMPOSE_RUNNING_CONTAINER_COUNT=$container_count"
if [ "$container_count" != "1" ]; then
  docker compose ps || true
  fail "compose_container_count_not_one"
fi
container_id="$(printf '%s\n' "$container_ids" | sed '/^$/d' | head -n 1)"
[ -n "$container_id" ] || fail "compose_container_missing"

container_image_id="$(docker inspect --format '{{.Image}}' "$container_id")"
process_cmd="$(docker inspect --format '{{json .Config.Cmd}}' "$container_id")"
[ -n "$container_image_id" ] || fail "container_image_id_missing"
echo "AQ_STAGE=container_discovered"
echo "AQ_CONTAINER_ID_PRESENT=true"
echo "AQ_CONTAINER_IMAGE_ID_PRESENT=true"

container_env() {
  docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$container_id" \
    | awk -F= -v key="$1" '$1 == key {print substr($0, index($0, "=") + 1)}' \
    | tail -n 1
}

runtime_sha="$(container_env M26_QUERY_BUILD_SHA)"
export M26_QUERY_BACKEND_TOKEN="$(container_env M26_QUERY_BACKEND_TOKEN)"
export KNOWLEDGE_ENGINE_OWNER_SUBJECT_HASH="$(container_env KNOWLEDGE_ENGINE_OWNER_SUBJECT_HASH)"
routed_origin="https://${ROUTED_BACKEND_HOSTNAME}"

runtime_sha_present=false
backend_token_present=false
owner_hash_present=false
routed_hostname_present=false
[ -n "$runtime_sha" ] && runtime_sha_present=true
[ -n "$M26_QUERY_BACKEND_TOKEN" ] && backend_token_present=true
[ -n "$KNOWLEDGE_ENGINE_OWNER_SUBJECT_HASH" ] && owner_hash_present=true
[ -n "$ROUTED_BACKEND_HOSTNAME" ] && routed_hostname_present=true
echo "AQ_CONTAINER_RUNTIME_SHA_PRESENT=$runtime_sha_present"
echo "AQ_CONTAINER_BACKEND_TOKEN_PRESENT=$backend_token_present"
echo "AQ_CONTAINER_OWNER_HASH_PRESENT=$owner_hash_present"
echo "AQ_ROUTED_HOSTNAME_PRESENT=$routed_hostname_present"
echo "AQ_ROUTED_ORIGIN_CLASS=named_cloudflare_tunnel_https_origin"

[ "$runtime_sha" = "$EXPECTED_DEPLOY_SHA" ] || fail "container_runtime_sha_mismatch"
[ -n "$M26_QUERY_BACKEND_TOKEN" ] || fail "container_backend_token_missing"
[ -n "$KNOWLEDGE_ENGINE_OWNER_SUBJECT_HASH" ] || fail "container_owner_hash_missing"
[ -n "$ROUTED_BACKEND_HOSTNAME" ] || fail "routed_backend_hostname_missing"
echo "AQ_STAGE=runtime_identity_and_credentials_validated"

evidence_dir="$DEPLOY_PATH/.m26-aq-final-production-closure"
mkdir -p "$evidence_dir"
chmod 700 "$evidence_dir"
identity_path="$evidence_dir/identity-$EXPECTED_DEPLOY_SHA.json"
frozen_path="$evidence_dir/frozen-$EXPECTED_DEPLOY_SHA.json"
blackbox_path="$evidence_dir/blackbox-$EXPECTED_DEPLOY_SHA.json"
targeted_path="$evidence_dir/targeted-$EXPECTED_DEPLOY_SHA.json"
targeted_summary_path="$evidence_dir/targeted-summary-$EXPECTED_DEPLOY_SHA.json"
targeted_csv_path="$evidence_dir/targeted-results-$EXPECTED_DEPLOY_SHA.csv"
targeted_raw_answers_path="$evidence_dir/targeted-raw-answers-$EXPECTED_DEPLOY_SHA.md"
routed_health_path="$evidence_dir/routed-health-$EXPECTED_DEPLOY_SHA.json"
local_health_preflight_path="$evidence_dir/local-health-preflight-$EXPECTED_DEPLOY_SHA.json"
rm -f "$identity_path" "$frozen_path" "$blackbox_path" "$targeted_path" \
  "$targeted_summary_path" "$targeted_csv_path" "$targeted_raw_answers_path" \
  "$routed_health_path" "$local_health_preflight_path"

venv_dir="$evidence_dir/venv"
python3 -m venv "$venv_dir"
. "$venv_dir/bin/activate"
python -m pip install --upgrade pip >/dev/null
python -m pip install -e . >/dev/null
echo "AQ_STAGE=host_python_runtime_ready"

canonical_identity_json="$(PYTHONPATH=src python3 - <<'PY'
import json
from knowledge_engine.m26_aq_semantic_contract import (
    CANONICAL_RUNTIME_ENTRYPOINT,
    semantic_contract_fingerprint,
)
print(json.dumps({
    "entrypoint": CANONICAL_RUNTIME_ENTRYPOINT,
    "semantic_contract_fingerprint": semantic_contract_fingerprint(),
}, sort_keys=True))
PY
)"
export AQ_CANONICAL_IDENTITY_JSON="$canonical_identity_json"

local_health_code="$(curl --silent --show-error \
  -H "authorization: Bearer $M26_QUERY_BACKEND_TOKEN" \
  -H "x-m26-owner-subject-hash: $KNOWLEDGE_ENGINE_OWNER_SUBJECT_HASH" \
  -o "$local_health_preflight_path" \
  -w '%{http_code}' \
  http://127.0.0.1:8080/api/m26/health)"
echo "AQ_LOCAL_PREFLIGHT_HEALTH_HTTP=$local_health_code"
[ "$local_health_code" = "200" ] || fail "local_health_preflight_http_not_200"
EXPECTED_DEPLOY_SHA="$EXPECTED_DEPLOY_SHA" \
LOCAL_HEALTH_PREFLIGHT_PATH="$local_health_preflight_path" \
python3 - <<'PY'
import json
import os
from pathlib import Path

expected = os.environ["EXPECTED_DEPLOY_SHA"]
expected_identity = json.loads(os.environ["AQ_CANONICAL_IDENTITY_JSON"])
health = json.loads(Path(os.environ["LOCAL_HEALTH_PREFLIGHT_PATH"]).read_text(encoding="utf-8"))
canonical = health.get("canonical_runtime", {}) if isinstance(health, dict) else {}
if health.get("status") != "ok":
    raise SystemExit("local health status mismatch")
if canonical.get("build_sha") != expected:
    raise SystemExit("local health SHA mismatch before query")
if canonical.get("entrypoint") != expected_identity["entrypoint"]:
    raise SystemExit("local health entrypoint mismatch before query")
if canonical.get("semantic_contract_fingerprint") != expected_identity["semantic_contract_fingerprint"]:
    raise SystemExit("local health fingerprint mismatch before query")
PY
echo "AQ_STAGE=local_health_identity_preflight_passed"

collect_once() {
  local label="$1"
  local questions_path="$2"
  local output_path="$3"
  echo "AQ_COLLECT_POPULATION_START=$label"
  echo "AQ_COLLECT_POPULATION_ATTEMPT=1"
  rm -f "$output_path"
  PYTHONPATH=src python3 scripts/m26_aq_final_closure.py collect \
    --questions "$questions_path" \
    --output "$output_path" \
    --expected-sha "$EXPECTED_DEPLOY_SHA"
  echo "AQ_COLLECT_POPULATION_RESULT=success"
}

collect_once frozen pilot/m26/m26-aq-final-r3-questions.json "$frozen_path"
echo "AQ_STAGE=frozen_population_collected"

PYTHONPATH=src python3 scripts/m26_aq_final_closure.py validate \
  --input "$frozen_path" \
  --gate pilot/m26/m26-pa-7-resolved-production-gate.json \
  --expected-sha "$EXPECTED_DEPLOY_SHA"
echo "AQ_STAGE=frozen_population_validated"

collect_once blackbox pilot/m26/m26-aq-gpt-e-black-box-questions.json "$blackbox_path"
echo "AQ_STAGE=blackbox_population_collected"

PYTHONPATH=src python3 scripts/m26_aq_generalized_closure.py \
  --input "$blackbox_path" \
  --expected-sha "$EXPECTED_DEPLOY_SHA" \
  --minimum 20
echo "AQ_STAGE=blackbox_population_validated"

targeted_questions="pilot/m26/m26-aq-universal-answerability-targeted-questions.json"
[ -s "$targeted_questions" ] || fail "targeted_questions_missing"
collect_once targeted "$targeted_questions" "$targeted_path"
echo "AQ_STAGE=targeted_population_collected"

PYTHONPATH=src python3 scripts/m26_aq_targeted_answerability_closure.py \
  --input "$targeted_path" \
  --questions "$targeted_questions" \
  --expected-sha "$EXPECTED_DEPLOY_SHA" \
  --summary "$targeted_summary_path" \
  --csv "$targeted_csv_path" \
  --raw-answers "$targeted_raw_answers_path"
echo "AQ_STAGE=targeted_population_validated"

routed_code="$(curl --silent --show-error \
  -H "authorization: Bearer $M26_QUERY_BACKEND_TOKEN" \
  -H "x-m26-owner-subject-hash: $KNOWLEDGE_ENGINE_OWNER_SUBJECT_HASH" \
  -o "$routed_health_path" \
  -w '%{http_code}' \
  "${routed_origin%/}/api/m26/health")"
if [ "$routed_code" != "200" ]; then
  echo "AQ_ROUTED_HEALTH_HTTP=$routed_code"
  fail "routed_health_http_not_200"
fi
echo "AQ_STAGE=routed_health_collected"

EXPECTED_DEPLOY_SHA="$EXPECTED_DEPLOY_SHA" \
GIT_SHA="$receipt_head" \
CONTAINER_ID="$container_id" \
DEPLOY_IMAGE_ID="$receipt_image_id" \
CONTAINER_IMAGE_ID="$container_image_id" \
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
expected_identity = json.loads(os.environ["AQ_CANONICAL_IDENTITY_JSON"])
frozen = json.loads(Path(os.environ["FROZEN_PATH"]).read_text(encoding="utf-8"))
local_health = frozen.get("health", {}) if isinstance(frozen, dict) else {}
routed_health = json.loads(Path(os.environ["ROUTED_HEALTH_PATH"]).read_text(encoding="utf-8"))
routed_canonical = routed_health.get("canonical_runtime", {}) if isinstance(routed_health, dict) else {}
entrypoint = local_health.get("entrypoint")
fingerprint = local_health.get("semantic_contract_fingerprint")
if local_health.get("build_sha") != expected:
    raise SystemExit("local health SHA mismatch")
if routed_canonical.get("build_sha") != expected:
    raise SystemExit("routed health SHA mismatch")
if entrypoint != expected_identity["entrypoint"]:
    raise SystemExit("local health entrypoint mismatch")
if routed_canonical.get("entrypoint") != expected_identity["entrypoint"]:
    raise SystemExit("routed health entrypoint mismatch")
if fingerprint != expected_identity["semantic_contract_fingerprint"]:
    raise SystemExit("local health fingerprint mismatch")
if routed_canonical.get("semantic_contract_fingerprint") != expected_identity["semantic_contract_fingerprint"]:
    raise SystemExit("routed health fingerprint mismatch")
if routed_health.get("status") != "ok":
    raise SystemExit("routed health status mismatch")

evidence = {
    "schema_version": "m26-aq-production-identity/v4",
    "expected_deploy_sha": expected,
    "git_head_sha": os.environ["GIT_SHA"],
    "container_id": os.environ["CONTAINER_ID"],
    "deployment_image_id": os.environ["DEPLOY_IMAGE_ID"],
    "container_image_id": os.environ["CONTAINER_IMAGE_ID"],
    "container_runtime_sha": os.environ["RUNTIME_SHA"],
    "local_health_sha": local_health.get("build_sha"),
    "routed_health_sha": routed_canonical.get("build_sha"),
    "routed_health_status": routed_health.get("status"),
    "routed_route_class": "named_cloudflare_tunnel_https_origin",
    "entrypoint": entrypoint,
    "semantic_contract_fingerprint": fingerprint,
    "routed_semantic_contract_fingerprint": routed_canonical.get("semantic_contract_fingerprint"),
    "process_cmd": os.environ["PROCESS_CMD"],
    "frozen_population_rows": len(frozen.get("rows", [])),
    "raw_routed_origin_recorded": False,
    "raw_secret_recorded": False,
}
Path(os.environ["IDENTITY_PATH"]).write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
echo "AQ_STAGE=production_identity_written"

[ -s "$identity_path" ] || fail "identity_evidence_missing"
[ -s "$frozen_path" ] || fail "frozen_evidence_missing"
[ -s "$blackbox_path" ] || fail "blackbox_evidence_missing"
[ -s "$targeted_path" ] || fail "targeted_evidence_missing"
[ -s "$targeted_summary_path" ] || fail "targeted_summary_missing"
[ -s "$targeted_csv_path" ] || fail "targeted_csv_missing"
[ -s "$targeted_raw_answers_path" ] || fail "targeted_raw_answers_missing"
[ -s "$routed_health_path" ] || fail "routed_health_evidence_missing"
echo "AQ_ATOMIC_DEPLOY_AND_LIVE_CLOSURE_PASSED"
