#!/usr/bin/env bash
set -euo pipefail

: "${ORACLE_VM_HOST:?ORACLE_VM_HOST is required}"
: "${ORACLE_VM_USER:?ORACLE_VM_USER is required}"
: "${ORACLE_VM_SSH_PRIVATE_KEY:?ORACLE_VM_SSH_PRIVATE_KEY is required}"

log_stage() {
  printf 'ORACLE_SSH_STAGE=%s\n' "$1" >&2
}

umask 077
ssh_dir="$HOME/.ssh"
key_path="$ssh_dir/id_oracle"
known_hosts_path="$ssh_dir/known_hosts"
config_path="$ssh_dir/config"
control_path="$ssh_dir/oracle-%r@%h:%p"
scan_dir="$(mktemp -d)"
trap 'rm -rf "$scan_dir"' EXIT

install -m 700 -d "$ssh_dir"
printf '%s\n' "$ORACLE_VM_SSH_PRIVATE_KEY" > "$key_path"
chmod 600 "$key_path"
touch "$known_hosts_path"
chmod 600 "$known_hosts_path"

keyscan_ready=0
for attempt in 1 2 3 4 5; do
  log_stage "keyscan_attempt_${attempt}"
  scan_file="$scan_dir/keyscan_${attempt}"
  if ssh-keyscan -T 10 -H "$ORACLE_VM_HOST" > "$scan_file" 2>/dev/null && [ -s "$scan_file" ]; then
    cat "$scan_file" >> "$known_hosts_path"
    chmod 600 "$known_hosts_path"
    keyscan_ready=1
    break
  fi
  if [ "$attempt" -lt 5 ]; then
    sleep $((2 ** attempt))
  fi
done

if [ "$keyscan_ready" -ne 1 ]; then
  printf 'ORACLE_SSH_ERROR=host_key_unavailable\n' >&2
  exit 1
fi
log_stage host_key_ready

cat > "$config_path" <<EOF
Host oracle-knowledge
  HostName $ORACLE_VM_HOST
  User $ORACLE_VM_USER
  IdentityFile $key_path
  BatchMode yes
  IdentitiesOnly yes
  ConnectTimeout 15
  ConnectionAttempts 3
  ServerAliveInterval 30
  ServerAliveCountMax 6
  TCPKeepAlive yes
  StrictHostKeyChecking yes
  UserKnownHostsFile $known_hosts_path
  ControlMaster auto
  ControlPersist 10m
  ControlPath $control_path
EOF
chmod 600 "$config_path"

auth_ready=0
for attempt in 1 2 3; do
  log_stage "auth_preflight_attempt_${attempt}"
  if ssh oracle-knowledge true; then
    auth_ready=1
    break
  fi
  if [ "$attempt" -lt 3 ]; then
    sleep $((2 ** attempt))
  fi
done

if [ "$auth_ready" -ne 1 ]; then
  printf 'ORACLE_SSH_ERROR=auth_preflight_failed\n' >&2
  exit 1
fi
log_stage ready
