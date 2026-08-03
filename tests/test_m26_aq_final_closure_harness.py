from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


def _load_module() -> ModuleType:
    root = Path(__file__).resolve().parents[1]
    script = root / "scripts" / "m26_aq_final_closure.py"
    if not script.exists():
        script = Path("/mnt/data/m26_aq_final_closure.py")
    spec = importlib.util.spec_from_file_location("m26_aq_final_closure", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeResponse:
    def __init__(self, status: int, payload: dict[str, Any]) -> None:
        self.status = status
        self._payload = payload

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def _http_error(module: ModuleType, url: str, status: int) -> Exception:
    return module.urllib.error.HTTPError(
        url,
        status,
        "synthetic transient",
        hdrs=None,
        fp=io.BytesIO(b'{"error":"busy"}'),
    )


def _write_questions(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "questions": [
                    {
                        "case_id": "R3-Q01",
                        "question": "What is the production router role?",
                        "expected": "answer",
                        "critical": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def test_query_post_does_not_use_generic_eight_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    calls: list[tuple[str, float]] = []

    def fake_urlopen(request: Any, timeout: float) -> FakeResponse:
        calls.append((request.get_method(), timeout))
        raise TimeoutError("synthetic hang")

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(module.RequestFailure):
        module._query_post_json(
            "http://example.test/api/m26/query",
            token="token",
            owner_hash="owner",
            payload={"question": "q"},
            case_id="R3-Q01",
        )
    assert module.QUERY_POST_ATTEMPTS == 1
    assert len(calls) == 1
    assert calls[0] == ("POST", module.QUERY_COLLECTOR_REQUEST_TIMEOUT_SECONDS)


def test_transient_get_still_uses_bounded_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    calls = 0

    def fake_urlopen(request: Any, timeout: float) -> FakeResponse:
        nonlocal calls
        calls += 1
        assert request.get_method() == "GET"
        assert timeout == module.GET_REQUEST_TIMEOUT_SECONDS
        if calls == 1:
            raise _http_error(module, request.full_url, 503)
        return FakeResponse(200, {"status": "ok"})

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)
    status, body, _, attempts = module._request_json_get(
        "http://example.test/api/m26/health",
        token="token",
        owner_hash="owner",
    )
    assert status == 200
    assert body["status"] == "ok"
    assert attempts == 2
    assert calls == 2
    assert module.GET_REQUEST_ATTEMPTS > module.QUERY_POST_ATTEMPTS


def test_partial_artifact_survives_query_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    questions = tmp_path / "questions.json"
    output = tmp_path / "closure.json"
    _write_questions(questions)
    monkeypatch.setenv("M26_QUERY_BACKEND_TOKEN", "token-value")
    monkeypatch.setenv("KNOWLEDGE_ENGINE_OWNER_SUBJECT_HASH", "owner-hash-value")

    def fake_urlopen(request: Any, timeout: float) -> FakeResponse:
        if request.get_method() == "GET" and request.full_url.endswith("/health"):
            return FakeResponse(
                200,
                {
                    "status": "ok",
                    "canonical_runtime": {
                        "build_sha": "sha",
                        "entrypoint": "entrypoint",
                    },
                },
            )
        if request.get_method() == "GET" and request.full_url.endswith("/graph"):
            return FakeResponse(
                200,
                {
                    "status": "ok",
                    "graph_scope": "full_current_production_relation_graph",
                    "release_id": module.EXPECTED_RELEASE_ID,
                    "graph_v2_sha256": module.EXPECTED_GRAPH_SHA256,
                    "nodes": [],
                    "edges": [],
                    "authority": {},
                },
            )
        raise TimeoutError("synthetic query timeout")

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(SystemExit):
        module.collect(
            questions_path=questions,
            output=output,
            base_url="http://example.test",
            expected_sha="sha",
        )
    artifact_text = output.read_text(encoding="utf-8")
    artifact = json.loads(artifact_text)
    assert artifact["collection"]["status"] == "failed"
    assert artifact["collection"]["current_case_id"] == "R3-Q01"
    assert artifact["rows"][0]["case_id"] == "R3-Q01"
    assert artifact["rows"][0]["status"] == "collector_failure"
    assert "token-value" not in artifact_text
    assert "owner-hash-value" not in artifact_text


def test_complete_population_is_required_to_pass(tmp_path: Path) -> None:
    module = _load_module()
    artifact = {
        "expected_deploy_sha": "sha",
        "collection": {"status": "failed", "failure": {"reason": "timeout"}},
        "health": {"http_status": 200, "status": "ok", "build_sha": "sha"},
        "graph": {
            "http_status": 200,
            "status": "ok",
            "graph_scope": "full_current_production_relation_graph",
            "release_id": module.EXPECTED_RELEASE_ID,
            "graph_v2_sha256": module.EXPECTED_GRAPH_SHA256,
            "node_count": module.EXPECTED_NODE_COUNT,
            "edge_count": module.EXPECTED_EDGE_COUNT,
        },
        "rows": [],
        "privacy": {
            "raw_backend_token_recorded": False,
            "raw_owner_hash_recorded": False,
            "provider_secret_recorded": False,
        },
    }
    gate = {"production_identities": {"public_traffic_percent": 0}}
    artifact_path = tmp_path / "artifact.json"
    gate_path = tmp_path / "gate.json"
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
    gate_path.write_text(json.dumps(gate), encoding="utf-8")
    with pytest.raises(SystemExit):
        module.validate(
            input_path=artifact_path,
            gate_path=gate_path,
            expected_sha="sha",
        )


def test_timeout_row_is_not_accepted_answer() -> None:
    module = _load_module()
    row = module._query_failure_row(
        {
            "case_id": "R3-Q01",
            "question": "q",
            "expected": "answer",
        },
        http_status=0,
        reason="TimeoutError",
        elapsed_ms=module.QUERY_COLLECTOR_REQUEST_TIMEOUT_SECONDS * 1000,
        attempts=1,
    )
    assert row["status"] == "collector_failure"
    assert row["safe_abstention"] is False
    assert row["answer_text"] == ""
    assert row["collector"]["timeout_converted_to_answer"] is False


def test_slow_query_budget_fails_before_old_global_timeout() -> None:
    module = _load_module()
    module._assert_timeout_hierarchy()
    assert module.QUERY_POST_ATTEMPTS == 1
    assert (
        module.POPULATION_DEADLINE_SECONDS
        + module.QUERY_COLLECTOR_REQUEST_TIMEOUT_SECONDS
        < 60 * 60
    )


def test_failure_row_keeps_case_identity_and_attempt_count() -> None:
    module = _load_module()
    row = module._query_failure_row(
        {"case_id": "R3-Q07", "question": "q", "expected": "answer"},
        http_status=504,
        reason="query_http_not_200",
        elapsed_ms=1234,
        attempts=1,
    )
    assert row["case_id"] == "R3-Q07"
    assert row["collector"]["attempts"] == 1
    assert row["collector"]["elapsed_ms"] == 1234


def test_timeout_policy_is_embedded_for_forensics() -> None:
    module = _load_module()
    artifact = module._new_artifact(expected_sha="sha")
    policy = artifact["collection"]["timeout_policy"]
    assert policy["query_post_attempts"] == 1
    assert policy["get_request_attempts"] == module.GET_REQUEST_ATTEMPTS
    assert policy["collector_request_timeout_seconds"] < policy[
        "population_deadline_seconds"
    ]
