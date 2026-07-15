from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest

from src.knowledge_engine import m23_qdrant_first_upsert as subject


def _payload(index: int) -> dict[str, Any]:
    return {
        "section_id": f"pilot/section-{index:03d}",
        "release_id": subject.EXPECTED_RELEASE_ID,
        "release_manifest_sha256": subject.EXPECTED_RELEASE_MANIFEST_SHA256,
        "vector_name": subject.EXPECTED_VECTOR_NAME,
        "vector_dimension": subject.EXPECTED_VECTOR_DIMENSION,
        "canonical_knowledge": False,
        "candidate_release_eligible": False,
        "production_authority": False,
    }


def _points() -> list[dict[str, Any]]:
    vector = [0.0] * subject.EXPECTED_VECTOR_DIMENSION
    return [
        {
            "id": f"00000000-0000-0000-0000-{index:012d}",
            "payload": _payload(index),
            "vector": {subject.EXPECTED_VECTOR_NAME: vector},
        }
        for index in range(subject.EXPECTED_POINT_COUNT)
    ]


def test_validate_empty_preflight_rejects_nonempty_collection() -> None:
    snapshot = {
        "status": "green",
        "points_count": 1,
        "indexed_vectors_count": 0,
        "vector_name": "default",
        "vector_size": 1024,
        "vector_distance": "Cosine",
        "sparse_vectors": None,
    }
    with pytest.raises(subject.GateError, match="write-time preflight failed"):
        subject.validate_empty_preflight(snapshot)


def test_point_fingerprint_is_float32_stable() -> None:
    point = {
        "id": "00000000-0000-0000-0000-000000000001",
        "payload": _payload(1),
        "vector": {"default": [0.1] * subject.EXPECTED_VECTOR_DIMENSION},
    }
    rounded = json.loads(json.dumps(point))
    assert subject.point_fingerprint(point) == subject.point_fingerprint(rounded)


def test_full_authorized_upsert_and_readback(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    stored: list[dict[str, Any]] = []
    expected_points = _points()
    ids_sha = subject.canonical_sha256(sorted(point["id"] for point in expected_points))
    aggregate_sha = subject.aggregate_fingerprint(expected_points)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: object) -> None:
            return

        def _send(self, value: dict[str, Any]) -> None:
            raw = json.dumps(value, separators=(",", ":")).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:
            self._send(
                {
                    "status": "ok",
                    "result": {
                        "status": "green",
                        "points_count": len(stored),
                        "indexed_vectors_count": 0,
                        "config": {
                            "params": {
                                "vectors": {"default": {"size": 1024, "distance": "Cosine"}},
                                "sparse_vectors": None,
                            }
                        },
                    },
                }
            )

        def do_PUT(self) -> None:
            length = int(self.headers["Content-Length"])
            body = json.loads(self.rfile.read(length))
            stored[:] = body["points"]
            self._send(
                {
                    "status": "ok",
                    "result": {"status": "completed", "operation_id": 7},
                }
            )

        def do_POST(self) -> None:
            length = int(self.headers["Content-Length"])
            body = json.loads(self.rfile.read(length))
            ids = set(body["ids"])
            self._send(
                {
                    "status": "ok",
                    "result": [point for point in stored if point["id"] in ids],
                }
            )

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setenv("QDRANT_URL", f"http://127.0.0.1:{server.server_port}")
        monkeypatch.setenv("QDRANT_API_KEY", "not-a-real-secret")
        monkeypatch.setattr(
            subject,
            "validate_points_artifact",
            lambda _path: (
                {"points": expected_points},
                b"synthetic-test-artifact",
                ids_sha,
                aggregate_sha,
            ),
        )
        points_path = tmp_path / "qdrant-points.json"
        points_path.write_text("{}")
        receipt_path = tmp_path / "receipt.json"
        args = subject.argparse.Namespace(
            points=str(points_path),
            receipt=str(receipt_path),
            timeout=5,
        )

        assert subject.run(args) == 0
        receipt = json.loads(receipt_path.read_text())
        assert receipt["status"] == "pass"
        assert receipt["readback"]["point_count"] == subject.EXPECTED_POINT_COUNT
        assert receipt["readback"]["all_payloads_and_vectors_match"] is True
        assert receipt["network_calls"] == 7
        assert receipt["credential_material_recorded"] is False
        assert receipt["service_url_recorded"] is False
        assert receipt["production_mutation_dispatched"] is False
    finally:
        server.shutdown()
        thread.join(timeout=5)
