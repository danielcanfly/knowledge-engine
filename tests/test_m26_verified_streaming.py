from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from knowledge_engine import m26_ask_api
from knowledge_engine.m26_verified_streaming import (
    VERIFIED_STREAM_PATH,
    VERIFIED_STREAM_QUEUE_MAX,
    verified_material_events,
    verified_query_event_stream,
)

ROOT = Path(__file__).resolve().parents[1]
GATE_PATH = ROOT / "pilot/m26/m26-pa-7-resolved-production-gate.json"
OWNER_SUBJECT_HASH = "93c8aaae82e498dc2e6bfdcaa48b8823fe21a5ceef44ca2cf9cf35cf6350e05b"
TEST_BACKEND_TOKEN = "test-backend-token"


class _NeverDisconnected:
    async def is_disconnected(self) -> bool:
        return False


class _DisconnectAfterFirstPoll:
    def __init__(self) -> None:
        self.calls = 0

    async def is_disconnected(self) -> bool:
        self.calls += 1
        return self.calls >= 2


def _headers() -> dict[str, str]:
    return {
        "authorization": f"Bearer {TEST_BACKEND_TOKEN}",
        "x-m26-owner-subject-hash": OWNER_SUBJECT_HASH,
    }


def _dto(*, safe: bool = False, verified: bool = True) -> dict[str, Any]:
    if safe:
        return {
            "schema_version": "knowledge-engine-m26-pa7-ask-web-response/v1",
            "status": "owner_only_safe_abstention",
            "terminal_status": "safe_abstention",
            "trace_id": "trace-safe",
            "question_sha256": "aa" * 32,
            "answer_text": "",
            "answer_source": "safe_abstention",
            "safe_abstention": True,
            "reason_codes": ["LOW_RETRIEVAL_SUPPORT"],
            "citations": [],
            "sources": [],
            "answer_claims": [],
            "integrity": {
                "unsupported_accepted_claims": 0,
                "material_claim_support_verified": True,
                "citation_locator_valid": True,
            },
        }
    return {
        "schema_version": "knowledge-engine-m26-pa7-ask-web-response/v1",
        "status": "owner_only_cited_answer",
        "terminal_status": "answered",
        "trace_id": "trace-answer",
        "question_sha256": "bb" * 32,
        "answer_text": "Verified claim text [c1].",
        "answer_source": "provider_verified_runtime_bound_semantic_closure",
        "safe_abstention": False,
        "reason_codes": [],
        "citations": [
            {
                "citation_id": "c1",
                "claim_id": "claim_1",
                "locator_id": "loc_1",
                "source_identity": "source_1",
            }
        ],
        "sources": [],
        "answer_claims": [
            {
                "claim_id": "claim_1",
                "surface_text": "Verified claim text.",
                "citation_ids": ["c1"],
            }
        ],
        "integrity": {
            "unsupported_accepted_claims": 0 if verified else 1,
            "material_claim_support_verified": verified,
            "citation_locator_valid": verified,
        },
    }


def _parse_frame(frame: str) -> tuple[str, dict[str, Any]]:
    lines = [line for line in frame.splitlines() if line]
    event = lines[0].split(": ", 1)[1]
    payload = json.loads(lines[1].split(": ", 1)[1])
    return event, payload


def test_stream_uses_one_authoritative_execution_and_preserves_final_parity() -> None:
    async def scenario() -> None:
        calls = 0
        final = _dto()

        def run_query(**kwargs: Any) -> dict[str, Any]:
            nonlocal calls
            calls += 1
            sink = kwargs["event_sink"]
            sink(
                {
                    "type": "stage.started",
                    "stage": "retrieval",
                    "canonical_runtime": {"entrypoint": "canonical"},
                }
            )
            time.sleep(0.02)
            sink(
                {
                    "type": "stage.completed",
                    "stage": "retrieval",
                    "selected_evidence_count": 1,
                    "latency_ms": 20,
                    "canonical_runtime": {"entrypoint": "canonical"},
                }
            )
            return final

        frames = [
            frame
            async for frame in verified_query_event_stream(
                request=_NeverDisconnected(),
                root=ROOT,
                gate_path=GATE_PATH,
                question="What is verified streaming?",
                question_sha256="cc" * 32,
                owner_subject_hash=OWNER_SUBJECT_HASH,
                require_remote_dense=False,
                authoritative_runtime="canonical",
                run_query=run_query,
            )
        ]
        events = [_parse_frame(frame) for frame in frames]
        names = [name for name, _ in events]

        assert calls == 1
        assert names[0] == "request_started"
        assert "retrieval_started" in names
        assert "evidence_candidates_ready" in names
        assert names[-3:] == [
            "verified_claim_ready",
            "cited_segment_ready",
            "final_answer_done",
        ]
        final_payload = events[-1][1]
        assert final_payload["response"] == final
        assert (
            final_payload["response"]["answer_text"]
            == events[-2][1]["text"]
        )
    asyncio.run(scenario())

def test_first_stream_event_precedes_completion() -> None:
    async def scenario() -> None:
        finished = False

        def run_query(**_: Any) -> dict[str, Any]:
            nonlocal finished
            time.sleep(0.08)
            finished = True
            return _dto()

        stream = verified_query_event_stream(
            request=_NeverDisconnected(),
            root=ROOT,
            gate_path=GATE_PATH,
            question="stream early",
            question_sha256="dd" * 32,
            owner_subject_hash=OWNER_SUBJECT_HASH,
            require_remote_dense=False,
            authoritative_runtime="canonical",
            run_query=run_query,
        )
        first = await stream.__anext__()
        assert _parse_frame(first)[0] == "request_started"
        assert finished is False
        await stream.aclose()
    asyncio.run(scenario())

def test_unverified_material_claim_is_never_streamed() -> None:
    events = verified_material_events(_dto(verified=False))
    assert [name for name, _ in events] == ["error"]
    encoded = json.dumps(events)
    assert "Verified claim text" not in encoded


def test_safe_abstention_emits_no_material_answer_segment() -> None:
    events = verified_material_events(_dto(safe=True))
    assert [name for name, _ in events] == ["safe_abstention_done"]
    assert "cited_segment_ready" not in [name for name, _ in events]
    assert "verified_claim_ready" not in [name for name, _ in events]


def test_disconnect_stops_transport_without_final_material() -> None:
    async def scenario() -> None:
        def run_query(**kwargs: Any) -> dict[str, Any]:
            sink = kwargs["event_sink"]
            sink({"type": "stage.started", "stage": "retrieval"})
            time.sleep(0.15)
            return _dto()

        frames = [
            frame
            async for frame in verified_query_event_stream(
                request=_DisconnectAfterFirstPoll(),
                root=ROOT,
                gate_path=GATE_PATH,
                question="disconnect",
                question_sha256="ee" * 32,
                owner_subject_hash=OWNER_SUBJECT_HASH,
                require_remote_dense=False,
                authoritative_runtime="canonical",
                run_query=run_query,
            )
        ]
        names = [_parse_frame(frame)[0] for frame in frames]
        assert names == ["request_started"]
        assert "final_answer_done" not in names
        assert "cited_segment_ready" not in names
    asyncio.run(scenario())

def test_stream_queue_is_bounded() -> None:
    assert VERIFIED_STREAM_QUEUE_MAX == 128


def test_stream_endpoint_is_owner_only_and_returns_sse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KNOWLEDGE_ENGINE_OWNER_SUBJECT_HASH", OWNER_SUBJECT_HASH)
    monkeypatch.setenv("M26_QUERY_BACKEND_TOKEN", TEST_BACKEND_TOKEN)
    monkeypatch.setattr(m26_ask_api, "_preload_query_runtime", lambda: None)

    def run_query(**kwargs: Any) -> dict[str, Any]:
        sink = kwargs["event_sink"]
        sink({"type": "stage.started", "stage": "retrieval"})
        sink(
            {
                "type": "stage.completed",
                "stage": "retrieval",
                "selected_evidence_count": 1,
                "latency_ms": 1,
            }
        )
        return _dto()

    monkeypatch.setattr(m26_ask_api, "run_owner_query_for_web", run_query)
    app = m26_ask_api.create_app(
        root=ROOT,
        gate_path=GATE_PATH,
        require_remote_dense=False,
    )
    client = TestClient(app)

    denied = client.post(VERIFIED_STREAM_PATH, json={"question": "test"})
    assert denied.status_code == 403

    admitted = client.post(
        VERIFIED_STREAM_PATH,
        json={"question": "test"},
        headers=_headers(),
    )
    assert admitted.status_code == 200
    assert admitted.headers["content-type"].startswith("text/event-stream")
    assert "event: request_started" in admitted.text
    assert "event: final_answer_done" in admitted.text
