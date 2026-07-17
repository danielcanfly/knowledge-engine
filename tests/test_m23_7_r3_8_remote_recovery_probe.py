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
        "29572790495": {
            "engine_sha": "53c4b7a230ce73cf49980d605ca905b8a73f50e4",
            "worker_name": "knowledge-engine-r3-8-29572790495",
        },
        "29574526665": {
            "engine_sha": "7b9143bd2762f5ccfb642e1de094ffce4db626d2",
            "worker_name": "knowledge-engine-r3-8-29574526665",
        },
        "29576200306": {
            "engine_sha": "b0ecfd8709da6531bd43059fec2916301cf819ac",
            "worker_name": "knowledge-engine-r3-8-29576200306",
        },
        "29578234650": {
            "engine_sha": "0e4e746b7d4e611b8e983d646b95ae4f2803fb2a",
            "worker_name": "knowledge-engine-r3-8-29578234650",
        },
        "29579965754": {
            "engine_sha": "ecbd56aa2631aaabed8b27049585bd13c7ca78ac",
            "worker_name": "knowledge-engine-r3-8-29579965754",
        },
        "29582316388": {
            "engine_sha": "46b432a17bc03befb18fe7ab6537e5645f94a1bd",
            "worker_name": "knowledge-engine-r3-8-29582316388",
        },
        "29584764087": {
            "engine_sha": "986899961f7667581017279c4935d9125125199b",
            "worker_name": "knowledge-engine-r3-8-29584764087",
        },
        "29587264678": {
            "engine_sha": "9c7933fcaec85d01e05959b26d7b3fde81d261b4",
            "worker_name": "knowledge-engine-r3-8-29587264678",
        },
        "29589719171": {
            "engine_sha": "c30b02634fc232f2b59f357739087359d5dbe36b",
            "worker_name": "knowledge-engine-r3-8-29589719171",
        },
        "29592583765": {
            "engine_sha": "e7e10cf1cbd7e2ea5f8562dbde2cba791564f8a2",
            "worker_name": "knowledge-engine-r3-8-29592583765",
        },
        "29595625175": {
            "engine_sha": "c555ac8322bc4558157f643c2931410d3eb2e680",
            "worker_name": "knowledge-engine-r3-8-29595625175",
        },
        "29597922646": {
            "engine_sha": "e9336e525a472387076a39c547d082acaf60b6cc",
            "worker_name": "knowledge-engine-r3-8-29597922646",
        },
        "29600412694": {
            "engine_sha": "55ee393543b68eb55c18f0177b7d7969f0936956",
            "worker_name": "knowledge-engine-r3-8-29600412694",
        },
        "29602737093": {
            "engine_sha": "627615a9dcf69e22f9c139827df404207b1ac061",
            "worker_name": "knowledge-engine-r3-8-29602737093",
        },
        "29604923286": {
            "engine_sha": "3be9999b4ce0d721a29b92e9dbbfa17870ddc6e2",
            "worker_name": "knowledge-engine-r3-8-29604923286",
        },
        "29607698618": {
            "engine_sha": "63184eb576dc756d9bfff6701a3f6907be0cab00",
            "worker_name": "knowledge-engine-r3-8-29607698618",
        },
        "29610393567": {
            "engine_sha": "fd00b915c8a9e906ec96fe3f55c859ee3565afd2",
            "worker_name": "knowledge-engine-r3-8-29610393567",
        },
    }
    assert subject.CONFIRMATION_SUFFIX == "_SCHEMA_V2"
    assert subject.SCHEMA_VERSION.endswith("/v2")
