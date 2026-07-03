#!/usr/bin/env bash
set -euo pipefail

: "${ORACLE_VM_DEPLOY_PATH:?ORACLE_VM_DEPLOY_PATH is required}"
: "${EXPECTED_RELEASE_ID:?EXPECTED_RELEASE_ID is required}"

EVIDENCE_DIR="${EVIDENCE_DIR:-evidence}"
mkdir -p "$EVIDENCE_DIR"

ssh oracle-knowledge \
  "cd '$ORACLE_VM_DEPLOY_PATH' && docker compose restart knowledge-engine"

for attempt in $(seq 1 30); do
  if ssh oracle-knowledge \
    "curl --fail --silent http://127.0.0.1:8080/v1/health" \
    > "$EVIDENCE_DIR/oracle-health.json"; then
    if python - "$EVIDENCE_DIR/oracle-health.json" "$EXPECTED_RELEASE_ID" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
expected = {
    "status": "healthy",
    "channel": "production",
    "release_id": sys.argv[2],
}
raise SystemExit(0 if all(payload.get(k) == v for k, v in expected.items()) else 1)
PY
    then
      exit 0
    fi
  fi
  test "$attempt" -lt 30 || {
    cat "$EVIDENCE_DIR/oracle-health.json" 2>/dev/null || true
    exit 1
  }
  sleep 2
done
