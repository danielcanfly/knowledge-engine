#!/usr/bin/env bash
set -euo pipefail

: "${ORACLE_VM_HOST:?ORACLE_VM_HOST is required}"
: "${ORACLE_VM_USER:?ORACLE_VM_USER is required}"
: "${ORACLE_VM_SSH_PRIVATE_KEY:?ORACLE_VM_SSH_PRIVATE_KEY is required}"

install -m 700 -d "$HOME/.ssh"
printf '%s\n' "$ORACLE_VM_SSH_PRIVATE_KEY" > "$HOME/.ssh/id_oracle"
chmod 600 "$HOME/.ssh/id_oracle"
ssh-keyscan -H "$ORACLE_VM_HOST" >> "$HOME/.ssh/known_hosts"
cat > "$HOME/.ssh/config" <<EOF
Host oracle-knowledge
  HostName $ORACLE_VM_HOST
  User $ORACLE_VM_USER
  IdentityFile $HOME/.ssh/id_oracle
  IdentitiesOnly yes
EOF
chmod 600 "$HOME/.ssh/config"
