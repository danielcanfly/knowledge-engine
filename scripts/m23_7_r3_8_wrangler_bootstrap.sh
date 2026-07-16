#!/usr/bin/env bash

M23_R3_8_WRANGLER_VERSION="4.111.0"
M23_R3_8_WRANGLER_PACKAGE="wrangler@${M23_R3_8_WRANGLER_VERSION}"
declare -a M23_R3_8_WRANGLER_CMD=()
M23_R3_8_WRANGLER_SOURCE=""

m23_r3_8_wrangler_error() {
  printf 'R3.8 Wrangler bootstrap ERROR: %s\n' "$*" >&2
  return 1
}

m23_r3_8_resolve_wrangler() {
  M23_R3_8_WRANGLER_CMD=()
  M23_R3_8_WRANGLER_SOURCE=""

  local override="${WRANGLER_BIN:-}"
  if [[ -n "$override" ]]; then
    if [[ ! "$override" =~ ^[A-Za-z0-9_./-]+$ ]]; then
      m23_r3_8_wrangler_error \
        "WRANGLER_BIN must be one executable token without shell syntax"
      return 1
    fi
    if ! command -v "$override" >/dev/null 2>&1; then
      m23_r3_8_wrangler_error "WRANGLER_BIN is not executable: $override"
      return 1
    fi
    M23_R3_8_WRANGLER_CMD=("$override")
    M23_R3_8_WRANGLER_SOURCE="explicit"
  elif command -v wrangler >/dev/null 2>&1; then
    M23_R3_8_WRANGLER_CMD=("$(command -v wrangler)")
    M23_R3_8_WRANGLER_SOURCE="global"
  elif command -v npx >/dev/null 2>&1; then
    M23_R3_8_WRANGLER_CMD=(
      "$(command -v npx)"
      "--yes"
      "$M23_R3_8_WRANGLER_PACKAGE"
    )
    M23_R3_8_WRANGLER_SOURCE="npx-pinned"
  else
    m23_r3_8_wrangler_error \
      "neither wrangler nor npx is available; install Node.js/npm or Wrangler"
    return 1
  fi

  local version_output=""
  if ! version_output="$("${M23_R3_8_WRANGLER_CMD[@]}" --version 2>&1)"; then
    m23_r3_8_wrangler_error \
      "resolved Wrangler command failed its version probe"
    return 1
  fi

  local actual_version=""
  if [[ "$version_output" =~ wrangler[[:space:]]+([0-9]+\.[0-9]+\.[0-9]+) ]]; then
    actual_version="${BASH_REMATCH[1]}"
  else
    m23_r3_8_wrangler_error \
      "cannot parse Wrangler version from the resolved command"
    return 1
  fi

  if [[ "$actual_version" != "$M23_R3_8_WRANGLER_VERSION" ]]; then
    m23_r3_8_wrangler_error \
      "Wrangler version drifted: expected=$M23_R3_8_WRANGLER_VERSION actual=$actual_version"
    return 1
  fi

  printf 'R3.8 Wrangler bootstrap source=%s version=%s\n' \
    "$M23_R3_8_WRANGLER_SOURCE" \
    "$actual_version"
}
