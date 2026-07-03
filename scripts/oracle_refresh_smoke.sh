#!/usr/bin/env bash
set -euo pipefail

: "${ORACLE_VM_DEPLOY_PATH:?ORACLE_VM_DEPLOY_PATH is required}"
: "${EXPECTED_RELEASE_ID:?EXPECTED_RELEASE_ID is required}"
: "${EXPECTED_MANIFEST_SHA256:?EXPECTED_MANIFEST_SHA256 is required}"
: "${ACCEPTANCE_QUERY:?ACCEPTANCE_QUERY is required}"

EVIDENCE_DIR="${EVIDENCE_DIR:-evidence}"
mkdir -p "$EVIDENCE_DIR"

ssh oracle-knowledge \
  "cd '$ORACLE_VM_DEPLOY_PATH' && docker compose restart knowledge-engine"

for attempt in $(seq 1 30); do
  if ssh oracle-knowledge \
    "curl --fail --silent http://127.0.0.1:8080/v1/health" \
    > "$EVIDENCE_DIR/oracle-health.json"; then
    if python - \
      "$EVIDENCE_DIR/oracle-health.json" \
      "$EXPECTED_RELEASE_ID" \
      "$EXPECTED_MANIFEST_SHA256" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
expected = {
    "status": "healthy",
    "channel": "production",
    "release_id": sys.argv[2],
    "manifest_sha256": sys.argv[3],
}
raise SystemExit(0 if all(payload.get(k) == v for k, v in expected.items()) else 1)
PY
    then
      break
    fi
  fi
  test "$attempt" -lt 30 || {
    cat "$EVIDENCE_DIR/oracle-health.json" 2>/dev/null || true
    exit 1
  }
  sleep 2
done

query_arg=$(printf '%q' "$ACCEPTANCE_QUERY")
ssh oracle-knowledge \
  "cd '$ORACLE_VM_DEPLOY_PATH' && docker compose exec -T knowledge-engine knowledge-engine query --channel production --query $query_arg --audiences public,internal" \
  > "$EVIDENCE_DIR/oracle-internal-query.json"
ssh oracle-knowledge \
  "cd '$ORACLE_VM_DEPLOY_PATH' && docker compose exec -T knowledge-engine knowledge-engine query --channel production --query $query_arg --audiences public" \
  > "$EVIDENCE_DIR/oracle-public-query.json"

python scripts/validate_runtime_evidence.py \
  --health "$EVIDENCE_DIR/oracle-health.json" \
  --internal "$EVIDENCE_DIR/oracle-internal-query.json" \
  --public "$EVIDENCE_DIR/oracle-public-query.json" \
  --expected-release-id "$EXPECTED_RELEASE_ID" \
  --output "$EVIDENCE_DIR/runtime-acceptance.json"

python - \
  "$EVIDENCE_DIR/oracle-internal-query.json" \
  "$EVIDENCE_DIR/oracle-public-query.json" \
  "$EXPECTED_MANIFEST_SHA256" <<'PY'
import json
import sys

for filename in sys.argv[1:3]:
    payload = json.load(open(filename, encoding="utf-8"))
    release = payload.get("release") or {}
    if release.get("manifest_sha256") != sys.argv[3]:
        raise SystemExit(f"runtime query manifest mismatch: {filename}")
PY
