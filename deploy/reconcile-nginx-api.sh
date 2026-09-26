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

test -f "$source_config"
grep -q 'server_name api.danielcanfly.com;' "$source_config"
if grep -q '127\.0\.0\.1:18000' "$source_config"; then
  echo "NGINX_RECONCILE_REFUSED_RETIRED_UPSTREAM" >&2
  exit 1
fi
if grep -q 'X-M26-Build-SHA' "$source_config"; then
  echo "NGINX_RECONCILE_REFUSED_STATIC_BUILD_HEADER" >&2
  exit 1
fi

sudo -n install -d -m 0755 "$backup_dir"
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

rollback() {
  if [[ "$changed" != "1" ]]; then
    return
  fi
  if [[ "$had_target" == "1" ]] && sudo -n test -f "$backup"; then
    sudo -n cp -p "$backup" "$target_config"
  else
    sudo -n rm -f "$target_config"
  fi
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

effective="$(sudo -n nginx -T 2>&1)"
if grep -q '127\.0\.0\.1:18000' <<<"$effective"; then
  echo "NGINX_RECONCILE_RETIRED_UPSTREAM_STILL_EFFECTIVE" >&2
  false
fi
if grep -q 'X-M26-Build-SHA' <<<"$effective"; then
  echo "NGINX_RECONCILE_STATIC_BUILD_HEADER_STILL_EFFECTIVE" >&2
  false
fi

for path in /v1/answers/health /v1/health; do
  code="$(curl -ksS --resolve api.danielcanfly.com:443:127.0.0.1 \
    -o /dev/null --max-time 10 -w '%{http_code}' \
    "https://api.danielcanfly.com$path")"
  test "$code" = "200" || {
    echo "NGINX_RECONCILE_HEALTH_FAILED path=$path status=$code" >&2
    false
  }
done

root_code="$(curl -ksS --resolve api.danielcanfly.com:443:127.0.0.1 \
  -o /dev/null --max-time 10 -w '%{http_code}' https://api.danielcanfly.com/)"
test "$root_code" = "404" || {
  echo "NGINX_RECONCILE_ROOT_FAIL_CLOSED_MISMATCH status=$root_code" >&2
  false
}

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
