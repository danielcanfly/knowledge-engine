from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts import m23_7_r3_8_remote_operator as subject


def test_worker_name_is_unique_and_bounded() -> None:
    assert subject.derive_worker_name("29499115739", 1) == (
        "knowledge-engine-r3-8-29499115739"
    )
    with pytest.raises(subject.RemoteOperatorError, match="rerun_attempt_forbidden"):
        subject.derive_worker_name("29499115739", 2)
    with pytest.raises(subject.RemoteOperatorError, match="invalid_run_id"):
        subject.derive_worker_name("run-1", 1)


def test_evidence_key_is_exactly_bounded() -> None:
    assert subject.validate_evidence_key(subject.DEFAULT_EVIDENCE_KEY) == (
        subject.DEFAULT_EVIDENCE_KEY
    )
    for invalid in (
        "diagnostic/m23-7/r3-8/other.zip",
        "../M23.5_Cloudflare_BGE_M3_20260714T164215Z.zip",
        "/diagnostic/m23-7/r3-8/M23.5_Cloudflare_BGE_M3_20260714T164215Z.zip",
    ):
        with pytest.raises(subject.RemoteOperatorError):
            subject.validate_evidence_key(invalid)


def test_exact_head_requires_full_identity() -> None:
    head = "a" * 40
    assert subject.validate_expected_head(head, head) == head
    with pytest.raises(subject.RemoteOperatorError):
        subject.validate_expected_head("a" * 39, "a" * 39)
    with pytest.raises(subject.RemoteOperatorError):
        subject.validate_expected_head("a" * 40, "b" * 40)


def test_wrangler_config_uses_unique_name_and_no_secret(tmp_path: Path) -> None:
    output = tmp_path / "wrangler.jsonc"
    identity = subject.generate_wrangler_config(
        "https://qdrant.example.test", subject.derive_worker_name("12345", 1), output
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["name"] == "knowledge-engine-r3-8-12345"
    assert payload["placement"] == {"hostname": "qdrant.example.test"}
    assert payload["ai"] == {"binding": "AI"}
    assert "QDRANT_API_KEY" not in output.read_text(encoding="utf-8")
    assert identity["generated_config_committed"] is False


def _deploy_record(worker: str, **updates: object) -> dict[str, object]:
    record: dict[str, object] = {
        "type": "deploy",
        "version": 1,
        "worker_name": worker,
        "worker_name_overridden": False,
        "version_id": "version-123",
        "targets": [f"https://{worker}.nattynites.workers.dev"],
    }
    record.update(updates)
    return record


def test_deploy_identity_is_strict(tmp_path: Path) -> None:
    worker = subject.derive_worker_name("12345", 1)
    output = tmp_path / "deploy.jsonl"
    output.write_text(
        json.dumps({"type": "wrangler-session", "version": 1})
        + "\n"
        + json.dumps(_deploy_record(worker))
        + "\n",
        encoding="utf-8",
    )
    identity = subject.parse_deploy_identity(output, worker)
    assert identity == {
        "worker_version_id": "version-123",
        "worker_origin": f"https://{worker}.nattynites.workers.dev",
    }


@pytest.mark.parametrize(
    "record",
    (
        lambda worker: _deploy_record(worker, worker_name="other"),
        lambda worker: _deploy_record(worker, worker_name_overridden=True),
        lambda worker: _deploy_record(worker, targets=[]),
        lambda worker: _deploy_record(
            worker, targets=[f"https://{worker}.nattynites.workers.dev/path"]
        ),
        lambda worker: _deploy_record(worker, targets=["https://example.com"]),
    ),
)
def test_deploy_identity_rejects_drift(tmp_path: Path, record: object) -> None:
    worker = subject.derive_worker_name("12345", 1)
    output = tmp_path / "deploy.jsonl"
    output.write_text(json.dumps(record(worker)) + "\n", encoding="utf-8")
    with pytest.raises(subject.RemoteOperatorError):
        subject.parse_deploy_identity(output, worker)


def test_wrangler_error_classification_is_bounded() -> None:
    assert subject.classify_wrangler_error("code: 10007") == "worker_not_found"
    assert subject.classify_wrangler_error("code: 10090") == "worker_not_found"
    assert subject.classify_wrangler_error("403 Forbidden code: 10007") == (
        "authentication_or_authorization"
    )
    assert subject.classify_wrangler_error("code: 10007 code: 10090") == (
        "cloudflare_error_code"
    )
    assert subject.classify_wrangler_error("opaque error") == "wrangler_failure"


def test_source_has_no_fixed_worker_absence_probe() -> None:
    text = Path("scripts/m23_7_r3_8_remote_operator.py").read_text(encoding="utf-8")
    assert "versions list" not in text
    assert "derive_worker_name" in text
    assert "worker_retained" in text
    assert "R2_BUCKET" in text
    assert "delete" not in text.split("def execute", 1)[1].split("def parse_args", 1)[0]
