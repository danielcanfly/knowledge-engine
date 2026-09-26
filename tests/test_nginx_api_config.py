from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "deploy" / "nginx" / "api.danielcanfly.com.conf"
RECONCILE = ROOT / "deploy" / "reconcile-nginx-api.sh"
DEPLOY = ROOT / "deploy" / "deploy.sh"


def test_api_nginx_has_no_retired_upstream_or_stale_build_header() -> None:
    text = CONFIG.read_text()
    assert "127.0.0.1:18000" not in text
    assert "X-M26-Build-SHA" not in text
    assert "location ^~ /v1/" in text
    assert "proxy_pass http://127.0.0.1:8080;" in text
    assert "location / {" in text
    assert "return 404;" in text


def test_deploy_reconciles_nginx_with_validation_and_rollback() -> None:
    reconcile = RECONCILE.read_text()
    deploy = DEPLOY.read_text()
    assert "sudo -n nginx -t" in reconcile
    assert "systemctl reload nginx" in reconcile
    assert "trap rollback ERR" in reconcile
    assert "/v1/answers/health /v1/health" in reconcile
    assert "tail -n +11" in reconcile
    assert "deploy/reconcile-nginx-api.sh" in deploy
