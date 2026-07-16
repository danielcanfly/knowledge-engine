#!/usr/bin/env bash

M23_R3_8_WRANGLER_VERSION="4.111.0"
M23_R3_8_WRANGLER_PACKAGE="wrangler@${M23_R3_8_WRANGLER_VERSION}"
M23_R3_8_MAX_VERSION_OUTPUT_BYTES=4096
declare -a M23_R3_8_WRANGLER_CMD=()
M23_R3_8_WRANGLER_SOURCE=""

m23_r3_8_wrangler_error() {
  printf 'R3.8 Wrangler bootstrap ERROR: %s\n' "$*" >&2
  return 1
}

m23_r3_8_parse_wrangler_version() {
  local version_output="$1"
  if [[ ${#version_output} -gt $M23_R3_8_MAX_VERSION_OUTPUT_BYTES ]]; then
    m23_r3_8_wrangler_error "Wrangler version output exceeded the bounded limit"
    return 1
  fi

  local line=""
  local ansi_sequence=""
  local actual_version=""
  local version_line_count=0
  local escape_character=$'\033'
  local ansi_pattern="${escape_character}\\[[0-9;]*[[:alpha:]]"
  local version_pattern='^[^[:alnum:]]*(wrangler[[:space:]]+)?([0-9]+\.[0-9]+\.[0-9]+)[[:space:]]*$'

  while IFS= read -r line || [[ -n "$line" ]]; do
    while [[ "$line" =~ $ansi_pattern ]]; do
      ansi_sequence="${BASH_REMATCH[0]}"
      line="${line/"$ansi_sequence"/}"
    done

    if [[ "$line" =~ $version_pattern ]]; then
      version_line_count=$((version_line_count + 1))
      actual_version="${BASH_REMATCH[2]}"
    fi
  done <<< "$version_output"

  if [[ $version_line_count -ne 1 ]]; then
    m23_r3_8_wrangler_error \
      "expected exactly one bounded Wrangler version line; found=$version_line_count"
    return 1
  fi

  printf '%s\n' "$actual_version"
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
  if ! actual_version="$(m23_r3_8_parse_wrangler_version "$version_output")"; then
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
