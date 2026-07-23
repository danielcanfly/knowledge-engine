from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "m25_9_cloudflare_preflight_probe.py"
)
SPEC = importlib.util.spec_from_file_location("m25_9_cloudflare_preflight_probe", MODULE_PATH)
assert SPEC and SPEC.loader
probe = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = probe
SPEC.loader.exec_module(probe)

ACCOUNT_ID = "a" * 32
PROJECT = "llm-wiki-m24-internal"
HOSTNAME = "m24-internal.danielcanfly.com"


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
        assert headers["Authorization"].startswith("Bearer ")
        token = headers["Authorization"].removeprefix("Bearer ")
        endpoint = endpoint_from_url(url)
        self.calls.append((token, endpoint))
        outcome = self.outcomes[(token, endpoint)].pop(0)
        body = json.dumps(outcome.get("payload", {})).encode()
        return probe.HttpResponse(
            status=outcome.get("status"),
            content_type="application/json",
            body=body,
            network_error=outcome.get("network_error"),
        )


def endpoint_from_url(url: str) -> str:
    if url.endswith("/user/tokens/verify"):
        return "user_token_verify"
    if url.endswith("/tokens/verify"):
        return "account_token_verify"
    if "/pages/projects?" in url:
        return "pages_projects"
    if "/deployments?" in url:
        return "pages_deployments"
    if "/access/apps?" in url:
        return "access_apps"
    if url.endswith("/access/organizations"):
        return "access_organization"
    raise AssertionError(url)


def success_payload(endpoint: str) -> dict[str, Any]:
    if endpoint.endswith("token_verify"):
        return {"success": True, "result": {"status": "active", "id": "redacted"}}
    if endpoint == "pages_projects":
        return {"success": True, "result": [{"name": PROJECT}, {"name": "other"}]}
    if endpoint == "pages_deployments":
        return {"success": True, "result": [{"id": "deployment-1"}]}
    if endpoint == "access_apps":
        return {"success": True, "result": [{"id": "hidden", "aud": "hidden"}]}
    if endpoint == "access_organization":
        return {"success": True, "result": {"auth_domain": "hidden.cloudflareaccess.com"}}
    raise AssertionError(endpoint)


def all_success(token: str) -> dict[tuple[str, str], list[dict[str, Any]]]:
    endpoints = (
        "user_token_verify",
        "account_token_verify",
        "pages_projects",
        "pages_deployments",
        "access_apps",
        "access_organization",
    )
    return {
        (token, endpoint): [{"status": 200, "payload": success_payload(endpoint)}]
        for endpoint in endpoints
    }


def all_failure(token: str, status: int, code: int) -> dict[tuple[str, str], list[dict[str, Any]]]:
    endpoints = (
        "user_token_verify",
        "account_token_verify",
        "pages_projects",
        "pages_deployments",
        "access_apps",
        "access_organization",
    )
    return {
        (token, endpoint): [
            {"status": status, "payload": {"success": False, "errors": [{"code": code}]}}
        ]
        for endpoint in endpoints
    }


def test_generic_success_classifies_dedicated_failure_without_secret_leak() -> None:
    outcomes = {}
    outcomes.update(all_failure("pages-token", 403, 9109))
    outcomes.update(all_failure("access-token", 403, 9109))
    outcomes.update(all_success("generic-token"))
    evidence = probe.run_diagnostic(
        account_id=ACCOUNT_ID,
        project=PROJECT,
        internal_hostname=HOSTNAME,
        credentials={
            "pages_dedicated": "pages-token",
            "access_dedicated": "access-token",
            "generic_cloudflare": "generic-token",
        },
        requester=FakeRequester(outcomes),
        max_attempts=1,
    )
    assert evidence["mutations"] == 0
    assert evidence["recommended_credential_topology"] == "verified_generic_temporary"
    assert evidence["root_cause_classification"] == (
        "dedicated_credential_failure_or_scope_mismatch_generic_passes"
    )
    rendered = json.dumps(evidence)
    assert "pages-token" not in rendered
    assert "access-token" not in rendered
    assert "generic-token" not in rendered
    assert "hidden.cloudflareaccess.com" not in rendered
    assert '"aud":' not in rendered


def test_separate_dedicated_tokens_pass_with_least_privilege_topology() -> None:
    outcomes = {}
    outcomes.update(all_success("pages-token"))
    outcomes.update(all_success("access-token"))
    evidence = probe.run_diagnostic(
        account_id=ACCOUNT_ID,
        project=PROJECT,
        internal_hostname=HOSTNAME,
        credentials={
            "pages_dedicated": "pages-token",
            "access_dedicated": "access-token",
            "generic_cloudflare": "",
        },
        requester=FakeRequester(outcomes),
        max_attempts=1,
    )
    assert evidence["recommended_credential_topology"] == "explicit_dedicated_tokens"
    assert evidence["root_cause_classification"] == (
        "dedicated_pages_and_access_credentials_pass"
    )
    assert evidence["credential_summaries"]["pages_dedicated"][
        "previous_pages_deployment_captured"
    ]


def test_retry_records_each_attempt_for_retryable_status() -> None:
    outcomes = all_success("generic-token")
    outcomes[("generic-token", "pages_deployments")] = [
        {"status": 503, "payload": {"success": False, "errors": [{"code": 1001}]}},
        {"status": 200, "payload": success_payload("pages_deployments")},
    ]
    evidence = probe.run_diagnostic(
        account_id=ACCOUNT_ID,
        project=PROJECT,
        internal_hostname=HOSTNAME,
        credentials={
            "pages_dedicated": "",
            "access_dedicated": "",
            "generic_cloudflare": "generic-token",
        },
        requester=FakeRequester(outcomes),
        max_attempts=2,
    )
    attempts = [
        item["attempt"]
        for item in evidence["probes"]
        if item["credential_label"] == "generic_cloudflare"
        and item["endpoint"] == "pages_deployments"
    ]
    assert attempts == [1, 2]
    assert evidence["credential_summaries"]["generic_cloudflare"]["pages_deployments_read"]


def test_all_missing_is_bounded_and_diagnostic_complete() -> None:
    evidence = probe.run_diagnostic(
        account_id=ACCOUNT_ID,
        project=PROJECT,
        internal_hostname=HOSTNAME,
        credentials={
            "pages_dedicated": "",
            "access_dedicated": "",
            "generic_cloudflare": "",
        },
        requester=FakeRequester({}),
        max_attempts=1,
    )
    assert evidence["status"] == "diagnostic_complete"
    assert evidence["root_cause_classification"] == "all_effective_cloudflare_secrets_missing"
    assert evidence["probes"] == []
