from __future__ import annotations

import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest

from knowledge_engine import m23_7_r3_6_candidate_reingestion as subject


def _points() -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for index in range(subject.EXPECTED_POINT_COUNT):
        vector = [0.0] * subject.EXPECTED_VECTOR_DIMENSION
        vector[index] = 1.0
        points.append(
            {
                "id": f"00000000-0000-0000-0000-{index:012d}",
                "vector": {"default": vector},
                "payload": {
                    "payload_schema_version": subject.EXPECTED_PAYLOAD_SCHEMA,
                    "section_id": f"pilot/section-{index:03d}",
                    "section_title": f"Section {index}",
                    "language": "en",
                    "canonical_knowledge": False,
                    "candidate_release_eligible": False,
                    "production_authority": False,
                },
            }
        )
    return points


def _manifest(points: list[dict[str, Any]]) -> dict[str, Any]:
    ids = sorted(point["id"] for point in points)
    return {
        "points": points,
        "ids_sha256": subject.canonical_sha256(ids),
        "aggregate_fingerprint_sha256": subject.aggregate_fingerprint(points),
        "manifest_sha256": "a" * 64,
    }


def test_contract_derives_new_collection_and_preserves_boundaries() -> None:
    contract = subject.canonical_contract()
    assert contract["implementation_issue"] == 508
    assert contract["collection"]["name"] == subject.EXPECTED_COLLECTION
    assert subject.R3_5_CANDIDATE_ARTIFACT_SHA256[:12] in subject.EXPECTED_COLLECTION
    assert subject.EXPECTED_COLLECTION != subject.HISTORICAL_PILOT_COLLECTION
    assert contract["collection"]["must_be_absent_before_create"] is True
    assert contract["collection"]["reuse_existing_collection"] is False
    assert contract["authority"]["historical_pilot_mutation_authorized"] is False
    assert contract["authority"]["production_collection_mutation_authorized"] is False
    assert contract["authority"]["live_acceptance_authorized"] is False
    assert contract["authority"]["retrieval_quality_blocker_cleared"] is False


def test_build_candidate_points_binds_v2_payload_and_candidate_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence.zip"
    evidence.write_bytes(b"synthetic-frozen-evidence")
    monkeypatch.setattr(
        subject,
        "EXPECTED_EVIDENCE_SHA256",
        hashlib.sha256(evidence.read_bytes()).hexdigest(),
    )
    raw_points = _points()
    monkeypatch.setattr(
        subject,
        "build_calibration_candidate",
        lambda _path: {
            "candidate_artifact_sha256": subject.R3_5_CANDIDATE_ARTIFACT_SHA256,
            "points": raw_points,
        },
    )
    manifest = subject.build_candidate_points(evidence)
    assert manifest["point_count"] == 107
    assert len({point["id"] for point in manifest["points"]}) == 107
    for point in manifest["points"]:
        payload = point["payload"]
        assert payload["payload_schema_version"] == subject.EXPECTED_PAYLOAD_SCHEMA
        assert payload["source_membership"] == "r3-6-candidate-live-acceptance-only"
        assert payload["candidate_collection"] == subject.EXPECTED_COLLECTION
        assert payload["candidate_artifact_sha256"] == subject.R3_5_CANDIDATE_ARTIFACT_SHA256
        assert payload["canonical_knowledge"] is False
        assert payload["candidate_release_eligible"] is False
        assert payload["production_authority"] is False


def _server(*, existing: bool = False, corrupt_readback: bool = False):
    state: dict[str, Any] = {
        "created": existing,
        "points": _points() if existing else [],
        "deleted_paths": [],
        "write_paths": [],
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: object) -> None:
            return

        def _json(self, status_code: int, value: dict[str, Any]) -> None:
            raw = json.dumps(value, separators=(",", ":")).encode()
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:
            if not state["created"]:
                self._json(404, {"status": {"error": "not found"}})
                return
            self._json(
                200,
                {
                    "status": "ok",
                    "result": {
                        "status": "green",
                        "points_count": len(state["points"]),
                        "indexed_vectors_count": len(state["points"]),
                        "config": {
                            "params": {
                                "vectors": {
                                    "default": {
                                        "size": subject.EXPECTED_VECTOR_DIMENSION,
                                        "distance": subject.EXPECTED_DISTANCE,
                                    }
                                },
                                "sparse_vectors": None,
                            }
                        },
                    },
                },
            )

        def do_PUT(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length)) if length else {}
            state["write_paths"].append(self.path)
            if self.path.endswith(subject._escaped_collection()):
                state["created"] = True
                state["points"] = []
                self._json(200, {"status": "ok", "result": True})
                return
            state["points"] = body["points"]
            self._json(
                200,
                {"status": "ok", "result": {"status": "completed", "operation_id": 1}},
            )

        def do_POST(self) -> None:
            length = int(self.headers["Content-Length"])
            body = json.loads(self.rfile.read(length))
            requested = set(body["ids"])
            rows = [point for point in state["points"] if point["id"] in requested]
            if corrupt_readback and rows:
                rows = json.loads(json.dumps(rows))
                rows[0]["payload"]["section_title"] = "corrupted"
            self._json(200, {"status": "ok", "result": rows})

        def do_DELETE(self) -> None:
            state["deleted_paths"].append(self.path)
            state["created"] = False
            state["points"] = []
            self._json(200, {"status": "ok", "result": True})

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return state, server, thread


def _run_with_server(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    existing: bool = False,
    corrupt_readback: bool = False,
):
    points = _points()
    monkeypatch.setattr(subject, "build_candidate_points", lambda _path: _manifest(points))
    evidence = tmp_path / "evidence.zip"
    evidence.write_bytes(b"evidence")
    receipt = tmp_path / "receipt.json"
    state, server, thread = _server(existing=existing, corrupt_readback=corrupt_readback)
    monkeypatch.setenv("QDRANT_URL", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setenv("QDRANT_API_KEY", "test-secret")
    try:
        exit_code = subject.execute(evidence, receipt, timeout=5)
        value = json.loads(receipt.read_text())
        return exit_code, value, state
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_successful_create_upsert_and_full_readback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    exit_code, receipt, state = _run_with_server(monkeypatch, tmp_path)
    assert exit_code == 0
    assert receipt["status"] == "pass_candidate_reingestion"
    assert receipt["point_count"] == 107
    assert receipt["collection_absent_before_create"] is True
    assert receipt["strong_ordering_upsert_complete"] is True
    assert receipt["full_readback_complete"] is True
    assert receipt["readback_mismatch_count"] == 0
    assert receipt["network_calls"] == 9
    assert receipt["rollback_dispatched"] is False
    assert receipt["authority"]["retrieval_quality_blocker_cleared"] is False
    assert state["deleted_paths"] == []
    assert any("wait=true&ordering=strong" in path for path in state["write_paths"])


def test_existing_collection_is_refused_without_mutation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    exit_code, receipt, state = _run_with_server(monkeypatch, tmp_path, existing=True)
    assert exit_code == 30
    assert receipt["status"] == "rejected_candidate_reingestion_no_mutation"
    assert receipt["failure_code"] == "collection_exists"
    assert receipt["collection_created"] is False
    assert receipt["rollback_dispatched"] is False
    assert state["write_paths"] == []
    assert state["deleted_paths"] == []


def test_post_create_mismatch_rolls_back_only_new_candidate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    exit_code, receipt, state = _run_with_server(
        monkeypatch,
        tmp_path,
        corrupt_readback=True,
    )
    assert exit_code == 30
    assert receipt["status"] == "rejected_candidate_reingestion_rolled_back"
    assert receipt["failure_code"] == "readback_fingerprint"
    assert receipt["rollback_dispatched"] is True
    assert receipt["rollback_complete"] is True
    assert state["deleted_paths"] == [f"/collections/{subject._escaped_collection()}"]
    assert subject.HISTORICAL_PILOT_COLLECTION not in state["deleted_paths"][0]


def test_receipt_is_privacy_safe(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _exit_code, receipt, _state = _run_with_server(monkeypatch, tmp_path)
    text = json.dumps(receipt, sort_keys=True)
    assert "test-secret" not in text
    assert "127.0.0.1" not in text
    assert "http://" not in text
    assert all(value is False for value in receipt["privacy"].values())
