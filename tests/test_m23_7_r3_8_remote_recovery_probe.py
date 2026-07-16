from __future__ import annotations

from scripts import m23_7_r3_8_remote_recovery_probe as subject


def test_absent_responses_reconcile_to_absent() -> None:
    payload = {"success": False, "errors": [{"code": 10090}]}
    versions = subject.classify_control_plane_response(
        404, payload, identity_fields=("id",)
    )
    deployments = subject.classify_control_plane_response(
        404, {"success": False, "errors": [{"code": 10007}]}, identity_fields=("id",)
    )
    assert versions["state"] == "absent"
    assert deployments["state"] == "absent"
    assert subject.reconcile_worker_state(versions, deployments) == "worker_absent"


def test_present_responses_bind_sorted_unique_identities() -> None:
    versions = subject.classify_control_plane_response(
        200,
        {"success": True, "result": [{"id": "v2"}, {"id": "v1"}, {"id": "v2"}]},
        identity_fields=("id", "version_id"),
    )
    deployments = subject.classify_control_plane_response(
        200,
        {"success": True, "result": [{"deployment_id": "d1"}]},
        identity_fields=("id", "deployment_id"),
    )
    assert versions["identities"] == ["v1", "v2"]
    assert versions["identity_count"] == 2
    assert deployments["identities"] == ["d1"]
    assert subject.reconcile_worker_state(versions, deployments) == "worker_present"


def test_ambiguous_or_auth_responses_fail_closed() -> None:
    auth = subject.classify_control_plane_response(
        403,
        {"success": False, "errors": [{"code": 10000}]},
        identity_fields=("id",),
    )
    malformed = subject.classify_control_plane_response(
        200,
        {"success": True, "result": {}},
        identity_fields=("id",),
    )
    assert auth["state"] == "indeterminate"
    assert malformed["state"] == "indeterminate"
    assert subject.reconcile_worker_state(auth, malformed) == "worker_state_indeterminate"


def test_mixed_absent_and_present_is_inconsistent() -> None:
    absent = {
        "state": "absent",
        "http_status": 404,
        "error_codes": [10090],
        "identity_count": 0,
        "identities": [],
    }
    present = {
        "state": "present",
        "http_status": 200,
        "error_codes": [],
        "identity_count": 1,
        "identities": ["v1"],
    }
    assert subject.reconcile_worker_state(absent, present) == "worker_state_inconsistent"


def test_probe_source_has_no_mutating_cloudflare_methods() -> None:
    source = open(
        "scripts/m23_7_r3_8_remote_recovery_probe.py", encoding="utf-8"
    ).read()
    assert "client.get(" in source
    assert "client.post(" not in source
    assert "client.put(" not in source
    assert "client.patch(" not in source
    assert "client.delete(" not in source
    assert subject.AFFECTED_RUN_ID == "29506217284"
    assert subject.AFFECTED_WORKER == "knowledge-engine-r3-8-29506217284"
