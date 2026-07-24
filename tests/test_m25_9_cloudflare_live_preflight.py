from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "m25_9_cloudflare_live_preflight.py"
)
SPEC = importlib.util.spec_from_file_location("m25_9_cloudflare_live_preflight", MODULE_PATH)
assert SPEC and SPEC.loader
preflight = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = preflight
SPEC.loader.exec_module(preflight)

ACCOUNT_ID = "a" * 32
PROJECT = "llm-wiki-m24-internal"
HOSTNAME = "m24-internal.danielcanfly.com"
ZONE = "danielcanfly.com"
TOKENS = {
    "pages-token": "pages_dedicated",
    "workers-token": "workers_dedicated",
    "access-token": "access_dedicated",
}


class FakeRequester:
    def __init__(self, outcomes: dict[tuple[str, str], list[dict[str, Any]]]) -> None:
        self.outcomes = outcomes
        self.calls: list[tuple[str, str]] = []

    def __call__(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        timeout: float,
    ) -> Any:
        assert method == "GET"
        token = headers["Authorization"].removeprefix("Bearer ")
        endpoint = endpoint_from_url(url)
        self.calls.append((token, endpoint))
        outcome = self.outcomes[(token, endpoint)].pop(0)
        return preflight.HttpResponse(
            status=outcome.get("status"),
            content_type="application/json",
            body=json.dumps(outcome.get("payload", {})).encode(),
            network_error=outcome.get("network_error"),
        )


def endpoint_from_url(url: str) -> str:
    if url.endswith("/user/tokens/verify"):
        return "user_token_verify"
    if url.endswith(f"/pages/projects/{PROJECT}"):
        return "pages_project"
    if "/deployments?" in url:
        return "pages_deployments"
    if url.endswith("/workers/scripts"):
        return "workers_scripts"
    if "/zones?" in url:
        return "zones"
    if url.endswith("/workers/routes"):
        return "workers_routes"
    if "/access/apps?" in url:
        return "access_apps"
    if url.endswith("/access/organizations"):
        return "access_organization"
    raise AssertionError(url)


def payload_for(endpoint: str) -> dict[str, Any]:
    if endpoint == "user_token_verify":
        return {"success": True, "result": {"status": "active", "id": "hidden"}}
    if endpoint == "pages_project":
        return {"success": True, "result": {"name": PROJECT}}
    if endpoint == "pages_deployments":
        return {"success": True, "result": [{"id": "pages-deployment-1"}]}
    if endpoint == "workers_scripts":
        return {"success": True, "result": [{"id": "existing-worker"}]}
    if endpoint == "zones":
        return {"success": True, "result": [{"id": "zone-id-hidden", "name": ZONE}]}
    if endpoint == "workers_routes":
        return {"success": True, "result": []}
    if endpoint == "access_apps":
        return {
            "success": True,
            "result": [{"domain": HOSTNAME, "aud": "access-audience-hidden"}],
        }
    if endpoint == "access_organization":
        return {
            "success": True,
            "result": {"auth_domain": "team-hidden.cloudflareaccess.com"},
        }
    raise AssertionError(endpoint)


def successful_outcomes() -> dict[tuple[str, str], list[dict[str, Any]]]:
    mapping: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for token in TOKENS:
        mapping[(token, "user_token_verify")] = [
            {"status": 200, "payload": payload_for("user_token_verify")}
        ]
    for endpoint in ("pages_project", "pages_deployments"):
        mapping[("pages-token", endpoint)] = [
            {"status": 200, "payload": payload_for(endpoint)}
        ]
    for endpoint in ("workers_scripts", "zones", "workers_routes"):
        mapping[("workers-token", endpoint)] = [
            {"status": 200, "payload": payload_for(endpoint)}
        ]
    for endpoint in ("access_apps", "access_organization"):
        mapping[("access-token", endpoint)] = [
            {"status": 200, "payload": payload_for(endpoint)}
        ]
    return mapping


def run_success(tmp_path: Path, requester: FakeRequester) -> dict[str, Any]:
    return preflight.run_preflight(
        account_id=ACCOUNT_ID,
        pages_project=PROJECT,
        internal_hostname=HOSTNAME,
        zone_name=ZONE,
        pages_token="pages-token",
        workers_token="workers-token",
        access_token="access-token",
        evidence_output=tmp_path / "evidence.json",
        runtime_env_output=tmp_path / "runtime.env",
        requester=requester,
        max_attempts=2,
    )


def test_explicit_dedicated_topology_passes_without_token_leak(tmp_path: Path) -> None:
    evidence = run_success(tmp_path, FakeRequester(successful_outcomes()))
    assert evidence["status"] == "pass"
    assert evidence["mutations"] == 0
    assert evidence["selected_credential_topology"] == "explicit_dedicated_tokens"
    env_text = (tmp_path / "runtime.env").read_text()
    assert "PREVIOUS_PAGES_DEPLOYMENT_ID=pages-deployment-1" in env_text
    assert "ACCESS_AUD=access-audience-hidden" in env_text
    rendered = (tmp_path / "evidence.json").read_text()
    for token in TOKENS:
        assert token not in rendered
    assert "access-audience-hidden" not in rendered
    assert "team-hidden.cloudflareaccess.com" not in rendered
    assert "zone-id-hidden" not in rendered


def test_missing_dedicated_token_blocks_before_network(tmp_path: Path) -> None:
    evidence_path = tmp_path / "evidence.json"
    try:
        preflight.run_preflight(
            account_id=ACCOUNT_ID,
            pages_project=PROJECT,
            internal_hostname=HOSTNAME,
            zone_name=ZONE,
            pages_token="",
            workers_token="workers-token",
            access_token="access-token",
            evidence_output=evidence_path,
            runtime_env_output=None,
            requester=FakeRequester({}),
            max_attempts=1,
        )
    except preflight.PreflightFailure:
        pass
    else:
        raise AssertionError("missing credential should block")
    evidence = json.loads(evidence_path.read_text())
    assert evidence["root_cause_classification"] == "required_dedicated_credentials_missing"
    assert evidence["missing_credential_labels"] == ["pages_dedicated"]
    assert evidence["probes"] == []


def test_pages_403_retains_status_and_cloudflare_code(tmp_path: Path) -> None:
    outcomes = successful_outcomes()
    outcomes[("pages-token", "pages_project")] = [
        {
            "status": 403,
            "payload": {"success": False, "errors": [{"code": 10000}]},
        }
    ]
    evidence_path = tmp_path / "evidence.json"
    try:
        run_success(tmp_path, FakeRequester(outcomes))
    except preflight.PreflightFailure:
        pass
    else:
        raise AssertionError("403 should block")
    evidence = json.loads(evidence_path.read_text())
    record = [item for item in evidence["probes"] if item["endpoint"] == "pages_project"][-1]
    assert record["http_status"] == 403
    assert record["cloudflare_error_code"] == 10000
    assert record["cloudflare_error_category"] == "permission_or_resource_scope_failure"


def test_retryable_pages_failure_is_bounded_then_passes(tmp_path: Path) -> None:
    outcomes = successful_outcomes()
    outcomes[("pages-token", "pages_deployments")] = [
        {
            "status": 503,
            "payload": {"success": False, "errors": [{"code": 1001}]},
        },
        {"status": 200, "payload": payload_for("pages_deployments")},
    ]
    evidence = run_success(tmp_path, FakeRequester(outcomes))
    attempts = [
        item["attempt"]
        for item in evidence["probes"]
        if item["endpoint"] == "pages_deployments"
    ]
    assert attempts == [1, 2]


def test_pages_latest_writes_only_new_deployment_runtime_value(tmp_path: Path) -> None:
    outcomes = {
        ("pages-token", "pages_deployments"): [
            {"status": 200, "payload": payload_for("pages_deployments")}
        ]
    }
    evidence = preflight.run_pages_latest(
        account_id=ACCOUNT_ID,
        pages_project=PROJECT,
        pages_token="pages-token",
        evidence_output=tmp_path / "pages-latest.json",
        runtime_env_output=tmp_path / "pages-latest.env",
        requester=FakeRequester(outcomes),
        max_attempts=1,
    )
    assert evidence["status"] == "pass"
    assert (tmp_path / "pages-latest.env").read_text() == (
        "NEW_PAGES_DEPLOYMENT_ID=pages-deployment-1\n"
    )
    assert "pages-deployment-1" not in (tmp_path / "pages-latest.json").read_text()
