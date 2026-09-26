#!/usr/bin/env bash
set -euo pipefail

: "${DEPLOY_PATH:?DEPLOY_PATH is required}"

source_config="$DEPLOY_PATH/deploy/nginx/api.danielcanfly.com.conf"
target_config="/etc/nginx/sites-enabled/llamaindex-demo"
backup_dir="/etc/nginx/backups"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup="$backup_dir/llamaindex-demo.pre-$stamp"

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
  sudo -n cp -p "$target_config" "$backup"
fi
sudo -n install -m 0644 "$source_config" "$target_config"

rollback() {
  if sudo -n test -f "$backup"; then
    sudo -n cp -p "$backup" "$target_config"
    sudo -n nginx -t >/dev/null 2>&1 || true
    sudo -n systemctl reload nginx >/dev/null 2>&1 || true
  fi
}
trap rollback ERR

sudo -n nginx -t
sudo -n systemctl reload nginx

effective="$(sudo -n nginx -T 2>&1)"
if grep -q '127\.0\.0\.1:18000' <<<"$effective"; then
  echo "NGINX_RECONCILE_RETIRED_UPSTREAM_STILL_EFFECTIVE" >&2
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
sudo -n find "$backup_dir" -maxdepth 1 -type f -name 'llamaindex-demo.pre-*' -print0   | sudo -n xargs -0 ls -1t 2>/dev/null   | tail -n +11   | sudo -n xargs -r rm -f
echo "NGINX_API_RECONCILE=PASS"
echo "NGINX_API_BACKUP=$backup"
