from __future__ import annotations

import json
from pathlib import Path

from knowledge_engine.m17_operator_tools import (
    build_batch_status_report,
    build_checklist_report,
    build_doctor_report,
    build_production_status_report,
    compare_release_manifests,
    fetch_artifact,
    finalize_report,
    generate_handoff,
    generate_incident_bundle,
    summarize_ledger_export,
    validate_tool_registry,
    verify_evidence_file,
    verify_report,
)
from knowledge_engine.storage import FileObjectStore, sha256_bytes

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "docs/operations/m17/tool-registry.json"
RUNBOOK_REGISTRY = ROOT / "docs/operations/m17/runbook-registry.json"


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return path


def _evidence(path: Path, *, status: str = "passed") -> Path:
    payload = finalize_report(
        {
            "schema_version": "test-evidence/v1",
            "status": status,
            "value": "bounded",
        }
    )
    return _write_json(path, payload)


def test_repository_registry_and_checklist_pass() -> None:
    report = validate_tool_registry(ROOT, REGISTRY)
    assert report["status"] == "passed"
    assert report["tool_count"] == 10
    assert verify_report(report)

    checklist = build_checklist_report(RUNBOOK_REGISTRY)
    assert checklist["status"] == "passed"
    assert checklist["stage_count"] == 18
    assert verify_report(checklist)


def test_doctor_redacts_environment_values(tmp_path: Path) -> None:
    for relative in (
        "pyproject.toml",
        "docs/architecture/README.md",
        "docs/operations/README.md",
        "docs/operations/m17/runbook-registry.json",
        "docs/troubleshooting/m17/failure-registry.json",
        "docs/operations/m17/tool-registry.json",
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("test", encoding="utf-8")
    secret = "do-not-serialize-this-value"
    report = build_doctor_report(
        tmp_path,
        {
            "OBJECT_STORE_BACKEND": "r2",
            "R2_ENDPOINT_URL": "present",
            "R2_BUCKET": "present",
            "R2_ACCESS_KEY_ID": secret,
            "R2_SECRET_ACCESS_KEY": secret,
        },
    )
    assert report["status"] == "passed"
    assert secret not in json.dumps(report)


def test_batch_status_and_evidence_tamper_detection(tmp_path: Path) -> None:
    batch = _write_json(
        tmp_path / "batch.json",
        {
            "batch_id": "batch-1",
            "state": "candidate_accepted",
            "engine_sha": "a" * 40,
            "source_sha": "b" * 40,
        },
    )
    status = build_batch_status_report(batch)
    assert status["status"] == "passed"

    evidence = _evidence(tmp_path / "evidence.json")
    verified = verify_evidence_file(evidence)
    assert verified["status"] == "passed"
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    payload["value"] = "tampered"
    _write_json(evidence, payload)
    assert verify_evidence_file(evidence)["status"] == "blocked"


def test_production_status_and_bounded_fetch(tmp_path: Path) -> None:
    store = FileObjectStore(tmp_path / "store")
    release_id = "release-test-0001"
    artifact_key = f"releases/{release_id}/lexical.json"
    artifact = b"{}"
    store.put(
        artifact_key,
        artifact,
        content_type="application/json",
        sha256=sha256_bytes(artifact),
    )
    manifest = {
        "release_id": release_id,
        "artifacts": [
            {
                "key": artifact_key,
                "kind": "lexical_index",
                "bytes": len(artifact),
                "sha256": sha256_bytes(artifact),
            }
        ],
    }
    manifest_bytes = json.dumps(manifest, sort_keys=True).encode()
    manifest_key = f"releases/{release_id}/manifest.json"
    store.put(
        manifest_key,
        manifest_bytes,
        content_type="application/json",
        sha256=sha256_bytes(manifest_bytes),
    )
    pointer = {
        "release_id": release_id,
        "manifest_key": manifest_key,
        "manifest_sha256": sha256_bytes(manifest_bytes),
    }
    pointer_bytes = json.dumps(pointer, sort_keys=True).encode()
    store.put(
        "channels/production.json",
        pointer_bytes,
        content_type="application/json",
        sha256=sha256_bytes(pointer_bytes),
    )

    report = build_production_status_report(store, "production")
    assert report["status"] == "passed"
    fetched = fetch_artifact(
        store,
        artifact_key,
        tmp_path / "downloads",
        expected_sha256=sha256_bytes(artifact),
    )
    assert fetched["status"] == "passed"
    assert Path(fetched["output"]).read_bytes() == artifact


def test_release_compare_and_ledger_summary(tmp_path: Path) -> None:
    left = _write_json(
        tmp_path / "left.json",
        {
            "release_id": "release-left",
            "artifacts": [
                {"key": "releases/release-left/a", "kind": "graph", "bytes": 1, "sha256": "a" * 64}
            ],
        },
    )
    right = _write_json(
        tmp_path / "right.json",
        {
            "release_id": "release-right",
            "artifacts": [
                {"key": "releases/release-right/b", "kind": "graph", "bytes": 1, "sha256": "b" * 64}
            ],
        },
    )
    comparison = compare_release_manifests(left, right)
    assert comparison["status"] == "passed"
    assert comparison["identical"] is False

    ledger = _write_json(
        tmp_path / "ledger.json",
        {
            "entries": [
                {"batch_id": "b1", "release_id": "r1", "status": "closed"},
                {"batch_id": "b2", "release_id": "r2", "status": "blocked"},
            ]
        },
    )
    summary = summarize_ledger_export(ledger)
    assert summary["entry_count"] == 2
    assert summary["status_counts"] == {"blocked": 1, "closed": 1}


def test_incident_and_handoff_are_metadata_only(tmp_path: Path) -> None:
    first = _evidence(tmp_path / "first.json")
    second = _evidence(tmp_path / "second.json")
    incident_path = tmp_path / "incident.json"
    incident = generate_incident_bundle(
        [first, second],
        incident_path,
        incident_id="incident-1",
        failure_id="m17.test.failure",
    )
    assert incident["status"] == "passed"
    assert "bounded" not in incident_path.read_text(encoding="utf-8")

    handoff_path = tmp_path / "handoff.json"
    handoff = generate_handoff([first, second], handoff_path, handoff_id="handoff-1")
    assert handoff["status"] == "passed"
    assert "bounded" not in handoff_path.read_text(encoding="utf-8")


def test_registry_rejects_missing_command_and_unsafe_remote_operation(tmp_path: Path) -> None:
    payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    payload["tools"] = payload["tools"][:-1]
    payload["tools"][0]["remote_operations"] = ["put"]

    docs = tmp_path / "docs/operations/m17"
    docs.mkdir(parents=True)
    for relative in payload["owned_documents"]:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("safe", encoding="utf-8")
    source = tmp_path / "src/knowledge_engine/m17_operator_tools.py"
    source.parent.mkdir(parents=True)
    anchors = "\n".join(item["reference"]["anchor"] for item in payload["tools"])
    source.write_text(anchors, encoding="utf-8")
    path = _write_json(docs / "tool-registry.json", payload)

    report = validate_tool_registry(tmp_path, path)
    codes = {item["code"] for item in report["issues"]}
    assert report["status"] == "blocked"
    assert "command_coverage_mismatch" in codes
    assert "remote_authority_invalid" in codes


def test_privacy_unsafe_component_is_rejected(tmp_path: Path) -> None:
    unsafe = _write_json(
        tmp_path / "unsafe.json",
        finalize_report(
            {
                "schema_version": "test/v1",
                "status": "passed",
                "secret_value": "redacted",
            }
        ),
    )
    try:
        generate_incident_bundle(
            [unsafe],
            tmp_path / "incident.json",
            incident_id="incident-2",
            failure_id="m17.test.failure",
        )
    except ValueError as exc:
        assert "privacy-unsafe" in str(exc)
    else:
        raise AssertionError("privacy-unsafe component was accepted")
