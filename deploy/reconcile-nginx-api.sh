#!/usr/bin/env bash
set -euo pipefail

: "${DEPLOY_PATH:?DEPLOY_PATH is required}"

source_config="$DEPLOY_PATH/deploy/nginx/api.danielcanfly.com.conf"
target_config="/etc/nginx/sites-enabled/llamaindex-demo"
backup_dir="/etc/nginx/backups"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup="$backup_dir/llamaindex-demo.pre-$stamp"
changed=0
had_target=0
moved_manifest="$backup_dir/api.danielcanfly.com.disabled-$stamp.manifest"
config_search_globs=(
  "/etc/nginx/sites-enabled/*"
  "/etc/nginx/conf.d/*.conf"
)

test -f "$source_config"
grep -Fq 'server_name api.danielcanfly.com;' "$source_config"
if grep -Fq '127.0.0.1:18000' "$source_config"; then
  echo "NGINX_RECONCILE_REFUSED_RETIRED_UPSTREAM" >&2
  exit 1
fi
if grep -Fq 'X-M26-Build-SHA' "$source_config"; then
  echo "NGINX_RECONCILE_REFUSED_STATIC_BUILD_HEADER" >&2
  exit 1
fi

sudo -n install -d -m 0755 "$backup_dir"
: >"/tmp/knowledge-engine-nginx-disabled-$stamp.manifest"

if sudo -n test -f "$target_config"; then
  had_target=1
  if ! sudo -n cmp -s "$source_config" "$target_config"; then
    sudo -n cp -p "$target_config" "$backup"
    sudo -n install -m 0644 "$source_config" "$target_config"
    changed=1
  fi
else
  sudo -n install -m 0644 "$source_config" "$target_config"
  changed=1
fi

# Own the server name, not just one filename. This prevents a stale enabled
# config from winning server selection and sending non-exact routes to retired
# upstreams such as :18000.
for pattern in "${config_search_globs[@]}"; do
  for candidate in $pattern; do
    [[ -e "$candidate" ]] || continue
    [[ "$candidate" == "$target_config" ]] && continue
    if sudo -n test -f "$candidate" && sudo -n grep -Fq 'server_name api.danielcanfly.com' "$candidate"; then
      safe_name="$(printf '%s' "$candidate" | sed 's#[^A-Za-z0-9._-]#_#g')"
      disabled="$backup_dir/$safe_name.disabled-$stamp"
      sudo -n mv "$candidate" "$disabled"
      printf '%s\t%s\n' "$candidate" "$disabled" >>"/tmp/knowledge-engine-nginx-disabled-$stamp.manifest"
      changed=1
    fi
  done
done
sudo -n install -m 0600 "/tmp/knowledge-engine-nginx-disabled-$stamp.manifest" "$moved_manifest"
rm -f "/tmp/knowledge-engine-nginx-disabled-$stamp.manifest"

restore_disabled_duplicates() {
  if sudo -n test -f "$moved_manifest"; then
    while IFS=$'\t' read -r original disabled; do
      [[ -n "${original:-}" && -n "${disabled:-}" ]] || continue
      if sudo -n test -e "$disabled"; then
        sudo -n mv "$disabled" "$original"
      fi
    done < <(sudo -n cat "$moved_manifest")
  fi
}

rollback() {
  if [[ "$changed" != "1" ]]; then
    return
  fi
  if [[ "$had_target" == "1" ]] && sudo -n test -f "$backup"; then
    sudo -n cp -p "$backup" "$target_config"
  else
    sudo -n rm -f "$target_config"
  fi
  restore_disabled_duplicates
  sudo -n nginx -t >/dev/null 2>&1 || true
  sudo -n systemctl reload nginx >/dev/null 2>&1 || true
}
trap rollback ERR

sudo -n nginx -t
if [[ "$changed" == "1" ]]; then
  sudo -n systemctl reload nginx
fi

sudo -n cmp -s "$source_config" "$target_config" || {
  echo "NGINX_RECONCILE_TARGET_MISMATCH" >&2
  false
}

dump_nginx_reconcile_diagnostics() {
  echo "NGINX_RECONCILE_DIAGNOSTICS_BEGIN" >&2
  echo "direct_8080_answers_health=$(curl -sS -o /dev/null --max-time 5 -w '%{http_code}' http://127.0.0.1:8080/v1/answers/health || true)" >&2
  echo "direct_8080_health=$(curl -sS -o /dev/null --max-time 5 -w '%{http_code}' http://127.0.0.1:8080/v1/health || true)" >&2
  echo "local_nginx_answers_health=$(curl -ksS --resolve api.danielcanfly.com:443:127.0.0.1 -o /dev/null --max-time 5 -w '%{http_code}' https://api.danielcanfly.com/v1/answers/health || true)" >&2
  echo "local_nginx_health=$(curl -ksS --resolve api.danielcanfly.com:443:127.0.0.1 -o /dev/null --max-time 5 -w '%{http_code}' https://api.danielcanfly.com/v1/health || true)" >&2
  echo "local_nginx_root=$(curl -ksS --resolve api.danielcanfly.com:443:127.0.0.1 -o /dev/null --max-time 5 -w '%{http_code}' https://api.danielcanfly.com/ || true)" >&2
  echo "api_server_name_sources:" >&2
  sudo -n nginx -T 2>&1 | awk '
    /^# configuration file / { file=$4 }
    /server_name api[.]danielcanfly[.]com/ { print file ":" $0 }
    /127[.]0[.]0[.]1:18000/ { print file ":" $0 }
    /X-M26-Build-SHA/ { print file ":" $0 }
  ' >&2 || true
  echo "nginx_error_tail:" >&2
  sudo -n tail -n 40 /var/log/nginx/error.log >&2 || true
  echo "NGINX_RECONCILE_DIAGNOSTICS_END" >&2
}

effective="$(sudo -n nginx -T 2>&1)"
if grep -Fq '127.0.0.1:18000' <<<"$effective"; then
  echo "NGINX_RECONCILE_RETIRED_UPSTREAM_STILL_EFFECTIVE" >&2
  dump_nginx_reconcile_diagnostics
  false
fi
if grep -Fq 'X-M26-Build-SHA' <<<"$effective"; then
  echo "NGINX_RECONCILE_STATIC_BUILD_HEADER_STILL_EFFECTIVE" >&2
  dump_nginx_reconcile_diagnostics
  false
fi
server_name_count="$(grep -Fc 'server_name api.danielcanfly.com;' <<<"$effective")"
if [[ "$server_name_count" != "2" ]]; then
  echo "NGINX_RECONCILE_API_SERVER_NAME_COUNT_MISMATCH expected=2 actual=$server_name_count" >&2
  dump_nginx_reconcile_diagnostics
  false
fi

local_ingress_ready=0
for attempt in $(seq 1 30); do
  answers_code="$(curl -ksS --resolve api.danielcanfly.com:443:127.0.0.1 \
    -o /dev/null --max-time 5 -w '%{http_code}' \
    https://api.danielcanfly.com/v1/answers/health || true)"
  health_code="$(curl -ksS --resolve api.danielcanfly.com:443:127.0.0.1 \
    -o /dev/null --max-time 5 -w '%{http_code}' \
    https://api.danielcanfly.com/v1/health || true)"
  root_code="$(curl -ksS --resolve api.danielcanfly.com:443:127.0.0.1 \
    -o /dev/null --max-time 5 -w '%{http_code}' \
    https://api.danielcanfly.com/ || true)"
  if [[ "$answers_code" == "200" && "$health_code" == "200" && "$root_code" == "404" ]]; then
    local_ingress_ready=1
    echo "NGINX_LOCAL_INGRESS_READY attempt=$attempt"
    break
  fi
  sleep 1
done

if [[ "$local_ingress_ready" != "1" ]]; then
  echo "NGINX_RECONCILE_LOCAL_INGRESS_TIMEOUT answers=$answers_code health=$health_code root=$root_code" >&2
  dump_nginx_reconcile_diagnostics
  false
fi

trap - ERR
sudo -n find "$backup_dir" -maxdepth 1 -type f -name 'llamaindex-demo.pre-*' -print0 \
  | sudo -n xargs -0 -r ls -1t 2>/dev/null \
  | tail -n +11 \
  | sudo -n xargs -r rm -f

echo "NGINX_API_RECONCILE=PASS"
echo "NGINX_API_CHANGED=$changed"
if [[ "$changed" == "1" && "$had_target" == "1" ]]; then
  echo "NGINX_API_BACKUP=$backup"
else
  echo "NGINX_API_BACKUP=none"
fi
echo "NGINX_API_DISABLED_DUPLICATES_MANIFEST=$moved_manifest"
