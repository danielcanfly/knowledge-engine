from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import httpx
import pytest

from knowledge_engine import m23_7_r3_8_latency_repair as latency
import scripts
from scripts import m23_7_r3_8_remote_entrypoint_placement_v2 as entrypoint
from scripts import m23_7_r3_8_remote_operator as base
from scripts import m23_7_r3_8_remote_operator_placement_v2 as subject


def test_readiness_accepts_only_present_sanitized_placement_classes() -> None:
    payload = {"status": "error", "code": "request-schema-drift"}
    assert subject.worker_ready_response(400, payload, "local")
    assert subject.worker_ready_response(400, payload, "remote")
    assert not subject.worker_ready_response(400, payload, "absent")
    assert not subject.worker_ready_response(400, payload, None)
    assert not subject.worker_ready_response(401, payload, "local")
    assert not subject.worker_ready_response(
        400,
        {"status": "error", "code": "other"},
        "remote",
    )


@pytest.mark.parametrize("placement", ["local", "remote"])
def test_formal_invoker_accepts_enabled_placement_classes(
    placement: str,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"status": "ok"},
            headers={latency.PLACEMENT_RESPONSE_HEADER: placement},
        )

    invoker = subject.PlacementAwareHttpWorkerInvoker(
        "https://worker.example.test/observe",
        "a" * 32,
    )
    invoker._http.close()
    invoker._http = httpx.Client(transport=httpx.MockTransport(handler))
    payload, _elapsed = invoker.invoke(
        {"schema_version": "test"},
        clock_ns=lambda: 1,
    )
    assert payload == {"status": "ok"}
    assert invoker.placement_response_class == placement


@pytest.mark.parametrize("placement", [None, "absent", "unknown"])
def test_formal_invoker_rejects_unproven_placement(
    placement: str | None,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        headers = (
            {}
            if placement is None
            else {latency.PLACEMENT_RESPONSE_HEADER: placement}
        )
        return httpx.Response(200, json={"status": "ok"}, headers=headers)

    invoker = subject.PlacementAwareHttpWorkerInvoker(
        "https://worker.example.test/observe",
        "a" * 32,
    )
    invoker._http.close()
    invoker._http = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(latency.LatencyRepairError) as exc:
        invoker.invoke({"schema_version": "test"}, clock_ns=lambda: 1)
    assert exc.value.code == "worker_placement_unproven"


@pytest.mark.parametrize(
    ("placement", "remote"),
    [("local", False), ("remote", True)],
)
def test_receipt_records_actual_class_without_location(
    placement: str,
    remote: bool,
) -> None:
    receipt = {
        "status": "pass_placed_worker_latency_repair",
        "remote_operator": {
            "placement_remote_readiness_verified": True,
            "placement_response_class": "remote",
            "placement_location_persisted": False,
        },
        "receipt_sha256": "0" * 64,
    }
    value = subject.normalise_receipt(receipt, placement)
    operator = value["remote_operator"]
    assert operator["placement_header_verified"] is True
    assert operator["placement_local_or_remote_readiness_verified"] is True
    assert operator["placement_remote_readiness_verified"] is remote
    assert operator["placement_response_class"] == placement
    assert operator["placement_routing_was_remote"] is remote
    assert operator["placement_targeted_hostname_configured"] is True
    assert operator["placement_location_persisted"] is False
    assert operator["placement_contract_sha256"] == subject.PLACEMENT_CONTRACT_SHA256
    digest = value.pop("receipt_sha256")
    assert latency.canonical_sha256(value) == digest
    encoded = json.dumps(value)
    for forbidden in ("local-", "remote-", "QDRANT_URL", "workers.dev"):
        assert forbidden not in encoded


def _entry_args(output_dir: Path) -> list[str]:
    return [
        "--expected-head",
        "a" * 40,
        "--run-id",
        "12345",
        "--run-attempt",
        "1",
        "--confirmation",
        "RUN_R3_8_REMOTE_ONCE",
        "--evidence-key",
        "diagnostic/m23-7/r3-8/evidence.zip",
        "--output-dir",
        str(output_dir),
    ]


def test_v2_entrypoint_routes_to_v2_operator(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fake = types.SimpleNamespace(execute=lambda args: 0)
    monkeypatch.setitem(
        sys.modules,
        "scripts.m23_7_r3_8_remote_operator_placement_v2",
        fake,
    )
    monkeypatch.setattr(
        scripts,
        "m23_7_r3_8_remote_operator_placement_v2",
        fake,
        raising=False,
    )
    monkeypatch.setattr(
        entrypoint.subprocess,
        "check_output",
        lambda *args, **kwargs: "a" * 40 + "\n",
    )
    assert entrypoint.main(_entry_args(tmp_path)) == 0
    entry = json.loads(
        (tmp_path / "remote-entry.json").read_text(encoding="utf-8")
    )
    digest = entry.pop("entry_sha256")
    assert entrypoint.canonical_sha256(entry) == digest
    assert entry["placement_location_persisted"] is False
    assert entry["service_hostname_persisted"] is False


def test_adapter_restores_canonical_runtime_after_execution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    original_ready = base.worker_ready_response
    original_invoker = latency.HttpWorkerInvoker
    original_write = base._write_json
    original_codes = base.LIVE_OBSERVATION_RETRY_CODES

    monkeypatch.setattr(base, "execute", lambda args: 23)
    args = types.SimpleNamespace(output_dir=str(tmp_path))
    assert subject.execute(args) == 23

    assert base.worker_ready_response is original_ready
    assert latency.HttpWorkerInvoker is original_invoker
    assert base._write_json is original_write
    assert original_codes == base.LIVE_OBSERVATION_RETRY_CODES


def test_source_preserves_mutation_and_privacy_boundaries() -> None:
    operator_text = Path(
        "scripts/m23_7_r3_8_remote_operator_placement_v2.py"
    ).read_text(encoding="utf-8")
    entry_text = Path(
        "scripts/m23_7_r3_8_remote_entrypoint_placement_v2.py"
    ).read_text(encoding="utf-8")
    assert "ALLOWED_PLACEMENT_CLASSES" in operator_text
    assert '{"local", "remote"}' in operator_text
    assert "worker_placement_unproven" in operator_text
    assert "placement_location_persisted" in operator_text
    for forbidden in (
        "wrangler delete",
        "qdrant_write",
        "R2_SECRET_ACCESS_KEY =",
        "cf-placement:",
    ):
        assert forbidden not in operator_text + entry_text
