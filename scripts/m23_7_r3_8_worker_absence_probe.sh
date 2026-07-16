#!/usr/bin/env bash

M23_R3_8_MAX_ABSENCE_OUTPUT_BYTES=65536
M23_R3_8_PYTHON_BIN="${M23_R3_8_PYTHON_BIN:-python}"

m23_r3_8_absence_probe_error() {
  printf 'R3.8 Worker absence probe ERROR: %s\n' "$*" >&2
  return 1
}

m23_r3_8_probe_worker_absence() {
  local worker_name="${1:-}"
  local wrangler_config="${2:-}"

  if [[ ! "$worker_name" =~ ^[a-z0-9][a-z0-9-]{0,62}$ ]]; then
    m23_r3_8_absence_probe_error \
      "Worker name must be one bounded lowercase token"
    return 1
  fi
  if [[ -z "$wrangler_config" || ! -f "$wrangler_config" ]]; then
    m23_r3_8_absence_probe_error "Wrangler config is missing"
    return 1
  fi
  if [[ ${#M23_R3_8_WRANGLER_CMD[@]} -eq 0 ]]; then
    m23_r3_8_absence_probe_error "Wrangler command array is unresolved"
    return 1
  fi
  if ! command -v "$M23_R3_8_PYTHON_BIN" >/dev/null 2>&1; then
    m23_r3_8_absence_probe_error "Python validator is unavailable"
    return 1
  fi

  local probe_output=""
  local probe_status=0
  if probe_output="$(
    "${M23_R3_8_WRANGLER_CMD[@]}" \
      versions list \
      --name "$worker_name" \
      --config "$wrangler_config" \
      --json \
      2>&1
  )"; then
    probe_status=0
  else
    probe_status=$?
  fi

  if [[ ${#probe_output} -gt $M23_R3_8_MAX_ABSENCE_OUTPUT_BYTES ]]; then
    m23_r3_8_absence_probe_error "Wrangler probe output exceeded the bounded limit"
    return 1
  fi

  if [[ $probe_status -eq 0 ]]; then
    local version_count=""
    if ! version_count="$(
      printf '%s' "$probe_output" | "$M23_R3_8_PYTHON_BIN" -c '
import json
import sys

try:
    value = json.load(sys.stdin)
except Exception:
    raise SystemExit(2)
if not isinstance(value, list):
    raise SystemExit(3)
if not all(isinstance(item, dict) for item in value):
    raise SystemExit(4)
print(len(value))
'
    )"; then
      m23_r3_8_absence_probe_error \
        "successful Wrangler probe returned malformed JSON"
      return 1
    fi
    if [[ ! "$version_count" =~ ^[0-9]+$ ]]; then
      m23_r3_8_absence_probe_error "Wrangler probe count was invalid"
      return 1
    fi
    if [[ $version_count -lt 1 ]]; then
      m23_r3_8_absence_probe_error \
        "successful Wrangler probe returned zero versions; existence is ambiguous"
      return 1
    fi
    printf 'present\n'
    return 0
  fi

  local absence_classification=""
  if absence_classification="$(
    printf '%s' "$probe_output" | "$M23_R3_8_PYTHON_BIN" -c '
import re
import sys

text = sys.stdin.read()
if re.search(r"(?<!\d)403(?!\d)", text):
    raise SystemExit(2)
if re.search(r"\b(?:forbidden|unauthori[sz]ed|authentication)\b", text, re.I):
    raise SystemExit(3)
codes = re.findall(r"(?<!\d)1\d{4}(?!\d)", text)
if len(codes) != 1 or codes[0] not in {"10007", "10090"}:
    raise SystemExit(4)
print("absent")
'
  )"; then
    if [[ "$absence_classification" == "absent" ]]; then
      printf 'absent\n'
      return 0
    fi
  fi

  m23_r3_8_absence_probe_error \
    "Wrangler could not prove Worker absence; exit=$probe_status"
  return 1
}
