from __future__ import annotations

from pathlib import Path

from scripts import m23_7_r3_8_remote_recovery_probe as subject


def _classify(
    payload: object,
    *,
    key: str = "items",
    fields: tuple[str, ...] = ("id",),
    status: int = 200,
):
    return subject.classify_control_plane_response(
        status,
        payload,
        collection_key=key,
        identity_fields=fields,
    )


def test_not_found_responses_reconcile_to_absent() -> None:
    versions = _classify(
        {"success": False, "errors": [{"code": 10090}]},
        status=404,
    )
    deployments = _classify(
        {"success": False, "errors": [{"code": 10007}]},
        key="deployments",
        status=404,
    )
    assert versions["state"] == "absent"
    assert deployments["state"] == "absent"
    assert subject.reconcile_worker_state(versions, deployments) == "worker_absent"


def test_official_nonempty_collections_reconcile_to_present() -> None:
    versions = _classify(
        {
            "success": True,
            "errors": [],
            "result": {"items": [{"id": "v2"}, {"id": "v1"}]},
        }
    )
    deployments = _classify(
        {
            "success": True,
            "errors": [],
            "result": {"deployments": [{"id": "d1"}]},
        },
        key="deployments",
    )
    assert versions["state"] == "present"
    assert versions["identities"] == ["v1", "v2"]
    assert versions["collection_key"] == "items"
    assert deployments["state"] == "present"
    assert deployments["identities"] == ["d1"]
    assert subject.reconcile_worker_state(versions, deployments) == "worker_present"


def test_official_empty_collections_reconcile_to_absent() -> None:
    versions = _classify(
        {"success": True, "errors": [], "result": {"items": []}}
    )
    deployments = _classify(
        {
            "success": True,
            "errors": [],
            "result": {"deployments": []},
        },
        key="deployments",
    )
    assert versions["state"] == "absent"
    assert deployments["state"] == "absent"
    assert subject.reconcile_worker_state(versions, deployments) == "worker_absent"


def test_wrong_or_legacy_collection_shapes_fail_closed() -> None:
    for payload in (
        {"success": True, "errors": [], "result": [{"id": "v1"}]},
        {"success": True, "errors": [], "result": {"deployments": []}},
        {"success": True, "errors": [], "result": {"items": [], "extra": []}},
        {"success": True, "errors": [], "result": {"items": {}}},
    ):
        assert _classify(payload)["state"] == "indeterminate"


def test_malformed_or_duplicate_identities_fail_closed() -> None:
    for collection in (
        [{}],
        [{"id": ""}],
        [{"id": "v1"}, {"id": "v1"}],
        ["v1"],
    ):
        result = _classify(
            {"success": True, "errors": [], "result": {"items": collection}}
        )
        assert result["state"] == "indeterminate"
        assert result["identities"] == []


def test_auth_mixed_errors_and_bad_success_fail_closed() -> None:
    for status, payload in (
        (403, {"success": False, "errors": [{"code": 10000}]}),
        (404, {"success": False, "errors": [{"code": 10007}, {"code": 10000}]}),
        (200, {"success": True, "errors": [{"code": 10000}], "result": {"items": []}}),
        (200, {"success": False, "errors": [], "result": {"items": []}}),
    ):
        assert _classify(payload, status=status)["state"] == "indeterminate"


def test_mixed_absent_and_present_is_inconsistent() -> None:
    absent = _classify(
        {"success": True, "errors": [], "result": {"items": []}}
    )
    present = _classify(
        {
            "success": True,
            "errors": [],
            "result": {"deployments": [{"id": "d1"}]},
        },
        key="deployments",
    )
    assert (
        subject.reconcile_worker_state(absent, present)
        == "worker_state_inconsistent"
    )


def test_probe_source_has_only_read_methods_and_schema_v2_identity() -> None:
    source = Path(
        "scripts/m23_7_r3_8_remote_recovery_probe.py"
    ).read_text(encoding="utf-8")
    assert source.count("client.get(") == 2
    assert "client.post(" not in source
    assert "client.put(" not in source
    assert "client.patch(" not in source
    assert "client.delete(" not in source
    assert subject.AUTHORIZED_RUNS == {
        "29506217284": {
            "engine_sha": "090db324939a4272b90d212fa462674b371b2e6d",
            "worker_name": "knowledge-engine-r3-8-29506217284",
        },
        "29546336917": {
            "engine_sha": "b6c60752741b7079d93b25ddbe16a6582f9db966",
            "worker_name": "knowledge-engine-r3-8-29546336917",
        },
        "29548837457": {
            "engine_sha": "47e16b4981698fb304af48377b93210e841c72e2",
            "worker_name": "knowledge-engine-r3-8-29548837457",
        },
        "29550965495": {
            "engine_sha": "e36559665429514789a6a0122d3b7ac8ff4d5765",
            "worker_name": "knowledge-engine-r3-8-29550965495",
        },
        "29553221650": {
            "engine_sha": "b7ff3c05e8eb2e2c7fcc56c206dd2da678256674",
            "worker_name": "knowledge-engine-r3-8-29553221650",
        },
        "29557251118": {
            "engine_sha": "4729ee2264fdd3650770a9be227606e995973725",
            "worker_name": "knowledge-engine-r3-8-29557251118",
        },
        "29558980092": {
            "engine_sha": "3aca4b793a841858bd0682fe61cc0febe8b649cd",
            "worker_name": "knowledge-engine-r3-8-29558980092",
        },
        "29561411876": {
            "engine_sha": "cb7ecefa8f5a4ac31bdfb71d891b60f3aa51555d",
            "worker_name": "knowledge-engine-r3-8-29561411876",
        },
        "29564569280": {
            "engine_sha": "8cc41a192104d2361d7cf3b388f5fedb6bd1cf56",
            "worker_name": "knowledge-engine-r3-8-29564569280",
        },
        "29568576968": {
            "engine_sha": "11970fc0624f86e30499297dc8154edbb6210163",
            "worker_name": "knowledge-engine-r3-8-29568576968",
        },
        "29568662778": {
            "engine_sha": "11970fc0624f86e30499297dc8154edbb6210163",
            "worker_name": "knowledge-engine-r3-8-29568662778",
        },
    }
    assert subject.CONFIRMATION_SUFFIX == "_SCHEMA_V2"
    assert subject.SCHEMA_VERSION.endswith("/v2")
