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
    assert payload["workers_dev"] is True
    assert payload["placement"] == {"hostname": "qdrant.example.test"}
    assert payload["ai"] == {"binding": "AI"}
    assert "QDRANT_API_KEY" not in output.read_text(encoding="utf-8")
    assert identity["generated_config_committed"] is False


def test_atomic_wrangler_secrets_file_is_ephemeral_and_bounded(
    tmp_path: Path,
) -> None:
    output = tmp_path / "wrangler-secrets.json"
    metadata = subject.write_wrangler_secrets_file(
        output,
        qdrant_url="https://qdrant.example.test",
        qdrant_api_key="q" * 32,
        operator_token="t" * 64,
    )
    assert metadata == {
        "atomic_secrets_file_committed": False,
        "atomic_secrets_uploaded_with_deploy": True,
        "secret_binding_names": [
            "M23_R3_8_OPERATOR_TOKEN",
            "QDRANT_API_KEY",
            "QDRANT_URL",
        ],
        "secret_count": 3,
        "secret_values_persisted": False,
    }
    assert output.stat().st_mode & 0o777 == 0o600
    assert json.loads(output.read_text(encoding="utf-8")) == {
        "M23_R3_8_OPERATOR_TOKEN": "t" * 64,
        "QDRANT_API_KEY": "q" * 32,
        "QDRANT_URL": "https://qdrant.example.test",
    }
    assert "q" * 32 not in json.dumps(metadata)
    assert "t" * 64 not in json.dumps(metadata)


def test_atomic_deploy_command_uses_single_secrets_file(tmp_path: Path) -> None:
    config = tmp_path / "wrangler.jsonc"
    secrets_file = tmp_path / "wrangler-secrets.json"
    command = subject.wrangler_deploy_command(
        ["npx", "--yes", "wrangler@4.111.0"],
        config=config,
        secrets_file=secrets_file,
    )
    assert command == [
        "npx",
        "--yes",
        "wrangler@4.111.0",
        "deploy",
        "--config",
        str(config),
        "--secrets-file",
        str(secrets_file),
        "--keep-vars",
    ]
    assert "secret" not in command
    assert "put" not in command


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


def test_remote_failure_code_preserves_latency_repair_code() -> None:
    class LatencyLikeError(RuntimeError):
        code = "worker_status"

    class UnsafeLatencyLikeError(RuntimeError):
        code = "secret shaped text"

    assert (
        subject.remote_failure_code(subject.RemoteOperatorError("worker_not_ready"))
        == "worker_not_ready"
    )
    assert (
        subject.remote_failure_code(LatencyLikeError("do not persist this message"))
        == "latency_repair_worker_status"
    )
    assert subject.remote_failure_code(UnsafeLatencyLikeError("x")) == (
        "bounded_unexpected_failure"
    )
    assert subject.remote_failure_code(RuntimeError("opaque")) == (
        "bounded_unexpected_failure"
    )


def test_worker_readiness_requires_authorized_remote_schema_probe() -> None:
    payload = {"status": "error", "code": "request-schema-drift"}
    assert subject.worker_ready_response(400, payload, "remote")
    assert not subject.worker_ready_response(400, payload, "local")
    assert not subject.worker_ready_response(400, payload, "absent")
    assert not subject.worker_ready_response(400, payload, None)
    assert not subject.worker_ready_response(
        405, {"status": "error", "code": "method-not-allowed"}, "remote"
    )
    assert not subject.worker_ready_response(
        500,
        {"status": "error", "code": "operator-secret-missing"},
        "remote",
    )
    assert not subject.worker_ready_response(
        401, {"status": "error", "code": "unauthorized"}, "remote"
    )


def test_readiness_timeline_splits_service_app_and_placement() -> None:
    ready = subject.readiness_timeline_entry(
        attempt=7,
        elapsed_ms=131,
        status_code=400,
        payload={"status": "error", "code": "request-schema-drift"},
        placement="local",
    )
    assert ready == {
        "attempt": 7,
        "elapsed_ms": 131,
        "http_status_class": "4xx",
        "body_code": "request-schema-drift",
        "service_available": True,
        "application_ready": True,
        "placement_class": "local",
    }
    network = subject.readiness_timeline_entry(
        attempt=8,
        elapsed_ms=-5,
        status_code=None,
        payload={"code": "https://example.invalid/not-persisted"},
        placement="remote-SJC",
    )
    assert network == {
        "attempt": 8,
        "elapsed_ms": 0,
        "http_status_class": "network_error",
        "body_code": None,
        "service_available": False,
        "application_ready": False,
        "placement_class": "unknown",
    }
    assert subject.readiness_summary(
        [ready, network],
        consecutive_successes=1,
    ) == {
        "attempt_count": 2,
        "service_available": True,
        "application_ready": True,
        "placement_classes": ["local"],
        "consecutive_successes": 1,
        "required_consecutive_successes": 2,
    }


def test_source_has_no_fixed_worker_absence_probe() -> None:
    text = Path("scripts/m23_7_r3_8_remote_operator.py").read_text(encoding="utf-8")
    assert "versions list" not in text
    assert "derive_worker_name" in text
    assert "worker_retained" in text
    assert "R2_BUCKET" in text
    assert "READINESS_CONSECUTIVE_SUCCESSES = 2" in text
    assert "PLACEMENT_READINESS_ATTEMPTS = 120" in text
    assert "PLACEMENT_READINESS_RETRY_SECONDS = 5" in text
    assert "PLACEMENT_RESPONSE_HEADER" in text
    assert "LIVE_OBSERVATION_ATTEMPTS = 9" in text
    assert "readiness_timeline" in text
    assert "service_available" in text
    assert "application_ready" in text
    assert '"worker_http_404"' in text
    assert '"worker_http_500_operator_secret_missing"' in text
    assert '"worker_http_502_qdrant_batch_unavailable"' in text
    assert '"worker_http_502_qdrant_query_batch_unavailable"' in text
    assert '"worker_http_502_qdrant_single_query_unavailable"' in text
    assert '"worker_placement_not_remote"' in text
    execute_text = text.split("def execute", 1)[1].split("def parse_args", 1)[0]
    assert "--secrets-file" in text
    assert "wrangler_deploy_command" in execute_text
    assert '"secret", "put"' not in execute_text
    assert "delete" not in text.split("def execute", 1)[1].split("def parse_args", 1)[0]
