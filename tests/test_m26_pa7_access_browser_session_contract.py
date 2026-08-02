from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "m26_pa7_access_browser_session_contract.py"
)
SPEC = importlib.util.spec_from_file_location(
    "m26_pa7_access_browser_session_contract",
    MODULE_PATH,
)
assert SPEC and SPEC.loader
access_contract = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = access_contract
SPEC.loader.exec_module(access_contract)

ACCOUNT_ID = "a" * 32
HOSTNAME = "m24-internal.danielcanfly.com"
ROOT_APP_ID = "root-access-app-id"
ROOT_AUD = "root-access-audience"
READ_TOKEN = "read-token-hidden"
WRITE_TOKEN = "write-token-hidden"


class FakeRequester:
    def __init__(self, apps: list[dict[str, Any]]) -> None:
        self.apps = apps
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        data: bytes | None,
        timeout: float,
    ) -> tuple[int | None, dict[str, Any] | None, str | None]:
        del timeout
        token = headers["Authorization"].removeprefix("Bearer ")
        self.calls.append(
            {
                "method": method,
                "url": url,
                "token": token,
                "payload": json.loads(data.decode("utf-8")) if data else None,
            }
        )
        if method == "GET" and url.endswith("/access/apps?per_page=100&page=1"):
            return (
                200,
                {
                    "success": True,
                    "result": self.apps,
                    "result_info": {"page": 1, "total_pages": 1},
                },
                None,
            )
        if method == "GET" and f"/access/apps/{ROOT_APP_ID}" in url:
            return 200, {"success": True, "result": dict(self.apps[0])}, None
        if method == "PUT" and f"/access/apps/{ROOT_APP_ID}" in url:
            payload = json.loads(data.decode("utf-8")) if data else {}
            for app in self.apps:
                if app.get("id") == ROOT_APP_ID:
                    app.update(
                        {
                            "same_site_cookie_attribute": payload[
                                "same_site_cookie_attribute"
                            ],
                            "path_cookie_attribute": payload["path_cookie_attribute"],
                        }
                    )
            return 200, {"success": True, "result": payload}, None
        raise AssertionError(f"unexpected request: {method} {url}")


def root_app(
    *,
    same_site: str = "lax",
    path_cookie: bool = False,
) -> dict[str, Any]:
    return {
        "id": ROOT_APP_ID,
        "aud": ROOT_AUD,
        "name": "M26 internal",
        "domain": HOSTNAME,
        "type": "self_hosted",
        "session_duration": "24h",
        "same_site_cookie_attribute": same_site,
        "path_cookie_attribute": path_cookie,
        "allowed_idps": ["idp-hidden"],
    }


def evidence_text_does_not_leak_raw_identity(path: Path) -> None:
    rendered = path.read_text(encoding="utf-8")
    assert HOSTNAME not in rendered
    assert ROOT_APP_ID not in rendered
    assert ROOT_AUD not in rendered
    assert READ_TOKEN not in rendered
    assert WRITE_TOKEN not in rendered


def test_contract_passes_for_single_lax_root_app_without_path_cookie(tmp_path: Path) -> None:
    output = tmp_path / "access-contract.json"
    evidence = access_contract.inspect_contract(
        account_id=ACCOUNT_ID,
        access_token=READ_TOKEN,
        target_hostname=HOSTNAME,
        evidence_output=output,
        requester=FakeRequester([root_app()]),
    )

    assert evidence["status"] == "pass"
    assert evidence["root_cause_classification"] == "access_browser_session_contract_pass"
    assert evidence["target_root_app_count"] == 1
    assert evidence["target_path_match_counts"] == {"/ask": 1, "/full-graph": 1}
    assert evidence["path_specific_overlap_counts"] == {"/ask": 0, "/full-graph": 0}
    assert evidence["target_root_app"]["same_site_cookie_attribute"] == "lax"
    assert evidence["target_root_app"]["path_cookie_attribute"] is False
    assert evidence["raw_domains_recorded"] is False
    assert evidence["raw_cookie_values_recorded"] is False
    assert evidence["raw_login_urls_recorded"] is False
    assert evidence["raw_tokens_recorded"] is False
    assert len(evidence["evidence_sha256"]) == 64
    evidence_text_does_not_leak_raw_identity(output)


@pytest.mark.parametrize(
    ("same_site", "reason"),
    [
        ("strict", "same_site_strict_confirmed_redirect_loop_risk"),
        ("", "same_site_cookie_attribute_not_machine_readable_or_not_allowed"),
    ],
)
def test_contract_blocks_unsafe_samesite(tmp_path: Path, same_site: str, reason: str) -> None:
    output = tmp_path / "access-contract.json"

    with pytest.raises(access_contract.AccessContractFailure, match=reason):
        access_contract.inspect_contract(
            account_id=ACCOUNT_ID,
            access_token=READ_TOKEN,
            target_hostname=HOSTNAME,
            evidence_output=output,
            requester=FakeRequester([root_app(same_site=same_site)]),
        )

    evidence = json.loads(output.read_text(encoding="utf-8"))
    assert evidence["status"] == "blocked"
    assert evidence["root_cause_classification"] == reason
    evidence_text_does_not_leak_raw_identity(output)


def test_contract_blocks_path_cookie_for_cross_path_owner_session(tmp_path: Path) -> None:
    output = tmp_path / "access-contract.json"

    with pytest.raises(
        access_contract.AccessContractFailure,
        match="path_cookie_attribute_must_be_disabled_for_ask_full_graph_session",
    ):
        access_contract.inspect_contract(
            account_id=ACCOUNT_ID,
            access_token=READ_TOKEN,
            target_hostname=HOSTNAME,
            evidence_output=output,
            requester=FakeRequester([root_app(path_cookie=True)]),
        )

    evidence = json.loads(output.read_text(encoding="utf-8"))
    assert evidence["root_cause_classification"] == (
        "path_cookie_attribute_must_be_disabled_for_ask_full_graph_session"
    )


def test_contract_blocks_path_specific_full_graph_overlap(tmp_path: Path) -> None:
    output = tmp_path / "access-contract.json"
    path_app = {
        **root_app(),
        "id": "full-graph-path-app",
        "aud": "full-graph-path-aud",
        "domain": f"{HOSTNAME}/full-graph",
    }

    with pytest.raises(
        access_contract.AccessContractFailure,
        match="path_specific_access_application_overlap",
    ):
        access_contract.inspect_contract(
            account_id=ACCOUNT_ID,
            access_token=READ_TOKEN,
            target_hostname=HOSTNAME,
            evidence_output=output,
            requester=FakeRequester([root_app(), path_app]),
        )

    evidence = json.loads(output.read_text(encoding="utf-8"))
    assert evidence["target_path_match_counts"] == {"/ask": 1, "/full-graph": 2}
    assert evidence["path_specific_overlap_counts"] == {"/ask": 0, "/full-graph": 1}
    assert "full-graph-path-app" not in output.read_text(encoding="utf-8")


def test_repair_updates_strict_root_app_to_lax_without_raw_evidence(tmp_path: Path) -> None:
    requester = FakeRequester([root_app(same_site="strict", path_cookie=True)])
    after = access_contract.repair_contract(
        account_id=ACCOUNT_ID,
        read_token=READ_TOKEN,
        write_token=WRITE_TOKEN,
        target_hostname=HOSTNAME,
        before_output=tmp_path / "before.json",
        repair_output=tmp_path / "repair.json",
        after_output=tmp_path / "after.json",
        requester=requester,
    )

    put_calls = [call for call in requester.calls if call["method"] == "PUT"]
    assert len(put_calls) == 1
    assert put_calls[0]["token"] == WRITE_TOKEN
    assert put_calls[0]["payload"]["same_site_cookie_attribute"] == "lax"
    assert put_calls[0]["payload"]["path_cookie_attribute"] is False
    assert "aud" not in put_calls[0]["payload"]
    assert after["status"] == "pass"

    repair = json.loads((tmp_path / "repair.json").read_text(encoding="utf-8"))
    assert repair["status"] == "access_browser_session_contract_repaired"
    assert repair["mutations"] == 1
    assert repair["mutation_kind"] == "cloudflare_access_application_update"
    assert repair["before_same_site_cookie_attribute"] == "strict"
    assert repair["after_same_site_cookie_attribute"] == "lax"
    assert repair["before_path_cookie_attribute"] is True
    assert repair["after_path_cookie_attribute"] is False

    for name in ("before.json", "repair.json", "after.json"):
        evidence_text_does_not_leak_raw_identity(tmp_path / name)
