#!/usr/bin/env bash
set -euo pipefail
set +x

deploy_path=${1:?deploy path required}
expected_sha=${2:?expected sha required}
cd "$deploy_path"

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_dir=/var/backups/l3b-backend-recovery
env_backup="$backup_dir/runtime-env.$stamp.bak"
nginx_path="$(readlink -f /etc/nginx/sites-enabled/llamaindex-demo 2>/dev/null || true)"
nginx_backup="$backup_dir/llamaindex-demo.$stamp.bak"
stale_manifest="/tmp/l3b-stale-enabled.$stamp"

test -n "$nginx_path" && test -f "$nginx_path"
test "$(git rev-parse HEAD)" = "$expected_sha"
test "$(docker compose exec -T knowledge-engine sh -c 'printf %s "$M26_QUERY_BUILD_SHA"')" = "$expected_sha"

sudo -n install -d -m 700 "$backup_dir"
sudo -n cp -p .env "$env_backup"
sudo -n cp -p "$nginx_path" "$nginx_backup"
sudo -n find /etc/nginx/sites-enabled -maxdepth 1 -type f \
  -name 'llamaindex-demo.l3b-502-recovery-*.bak' -print >"$stale_manifest"

rollback() {
  set +e
  sudo -n cp -p "$env_backup" .env
  sudo -n cp -p "$nginx_backup" "$nginx_path"
  while IFS= read -r stale_path; do
    test -n "$stale_path" || continue
    stale_name="$(basename "$stale_path")"
    if test -f "$backup_dir/stale-enabled-$stale_name"; then
      sudo -n mv "$backup_dir/stale-enabled-$stale_name" "$stale_path"
    fi
  done <"$stale_manifest"
  sudo -n nginx -t >/dev/null 2>&1 && sudo -n systemctl reload nginx >/dev/null 2>&1
  docker compose up -d --force-recreate --no-build knowledge-engine >/dev/null 2>&1
  echo 'RECOVERY_ROLLBACK=EXECUTED'
}
trap rollback ERR

while IFS= read -r stale_path; do
  test -n "$stale_path" || continue
  stale_name="$(basename "$stale_path")"
  sudo -n mv "$stale_path" "$backup_dir/stale-enabled-$stale_name"
done <"$stale_manifest"

sudo -n sed -i -E \
  's#^(export[[:space:]]+)?M26_CONSOLE_ACCESS_TEAM_DOMAIN=([^:/]+\.cloudflareaccess\.com)$#\1M26_CONSOLE_ACCESS_TEAM_DOMAIN=https://\2#' \
  .env
sudo -n grep -Eq \
  '^(export[[:space:]]+)?M26_CONSOLE_ACCESS_TEAM_DOMAIN=https://[^/]+\.cloudflareaccess\.com$' \
  .env

if ! sudo -n grep -Fq 'L3B_CANONICAL_ADMIN_ORIGIN_SPLIT' "$nginx_path"; then
  sudo -n awk '
  BEGIN { inserted = 0 }
  $0 == "    location / {" && inserted == 0 {
      print "    # L3B_CANONICAL_ADMIN_ORIGIN_SPLIT"
      print "    location ^~ /v1/admin/ {"
      print "        proxy_pass http://127.0.0.1:8080;"
      print "    }"
      print ""
      inserted = 1
  }
  { print }
  END { if (inserted == 0) exit 4 }
  ' "$nginx_path" | sudo -n tee "$backup_dir/llamaindex-demo.$stamp.next" >/dev/null
  sudo -n mv "$backup_dir/llamaindex-demo.$stamp.next" "$nginx_path"
fi

sudo -n grep -F 'location ^~ /v1/admin/' "$nginx_path"
test "$(sudo -n nginx -T 2>/dev/null | grep -cF 'location ^~ /v1/admin/' || true)" -eq 1
sudo -n nginx -t
sudo -n systemctl reload nginx
docker compose up -d --force-recreate --no-build knowledge-engine

health_ready=0
for _attempt in $(seq 1 30); do
  if curl --fail --silent --max-time 5 \
    http://127.0.0.1:8080/v1/answers/health >/tmp/l3b-health.json; then
    if python3 - "$expected_sha" <<'PY'
import json, sys
payload = json.load(open('/tmp/l3b-health.json', encoding='utf-8'))
actual = (payload.get('backend') or payload.get('runtime') or {}).get('build_sha', '')
raise SystemExit(0 if payload.get('ok') is True and actual == sys.argv[1] else 1)
PY
    then
      health_ready=1
      break
    fi
  fi
  sleep 2
done
test "$health_ready" -eq 1

local_app_code="$(curl --silent --output /tmp/l3b-admin.json --write-out '%{http_code}' \
  --max-time 10 http://127.0.0.1:8080/v1/admin/settings || true)"
local_nginx_code="$(curl --insecure --silent --output /tmp/l3b-nginx-admin.json --write-out '%{http_code}' \
  --max-time 10 -H 'Host: api.danielcanfly.com' https://127.0.0.1/v1/admin/settings || true)"
echo "RECOVERY_LOCAL_APP_ADMIN_STATUS=$local_app_code"
echo "RECOVERY_LOCAL_NGINX_ADMIN_STATUS=$local_nginx_code"
test "$local_app_code" = 401
test "$local_nginx_code" = 401
grep -F 'ADMIN_ACCESS_ASSERTION_MISSING' /tmp/l3b-admin.json >/dev/null
grep -F 'ADMIN_ACCESS_ASSERTION_MISSING' /tmp/l3b-nginx-admin.json >/dev/null

echo "RECOVERY_CHECKOUT_HEAD=$(git rev-parse HEAD)"
echo "RECOVERY_RUNTIME_SHA=$(docker compose exec -T knowledge-engine sh -c 'printf %s "$M26_QUERY_BUILD_SHA"')"
echo 'RECOVERY_ENV_TEAM_DOMAIN_NORMALIZED=YES'
echo 'RECOVERY_NGINX_ADMIN_ROUTE=8080'
echo 'RECOVERY_STALE_ENABLED_BACKUPS=REMOVED_FROM_INCLUDE_PATH'
echo 'RECOVERY_BACKEND_RESTART=1'
echo 'RECOVERY_DNS_ACCESS_WRITE=0'
echo 'RECOVERY_DATA_PLANE_MUTATION=0'
echo 'RECOVERY_ROLLBACK=NOT_REQUIRED'
rm -f /tmp/l3b-health.json /tmp/l3b-admin.json /tmp/l3b-nginx-admin.json "$stale_manifest"
trap - ERR
