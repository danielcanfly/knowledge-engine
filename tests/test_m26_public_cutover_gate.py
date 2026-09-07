from __future__ import annotations

import pytest
from scripts.m26_public_cutover_gate import _parse_sse, _validate_answer, _validate_health


def test_cutover_gate_requires_exact_health_contract_and_identity() -> None:
    _validate_health(
        {"ok": True, "status": "ok", "backend": {"build_sha": "successor"}},
        "successor",
    )
    with pytest.raises(ValueError, match="boolean ok=true"):
        _validate_health(
            {"ok": "true", "status": "ok", "backend": {"build_sha": "successor"}},
            "successor",
        )
    with pytest.raises(ValueError, match="build SHA mismatch"):
        _validate_health(
            {"ok": True, "status": "ok", "backend": {"build_sha": "predecessor"}},
            "successor",
        )


def test_cutover_gate_requires_completed_answer_with_sources_and_identity() -> None:
    events = [
        {"type": "request.accepted", "runtime": {"build_sha": "successor"}},
        {"type": "answer.completed", "answer": "Grounded answer.", "sources": [{"id": "1"}]},
    ]
    _validate_answer(events, "successor")
    with pytest.raises(ValueError, match="no sources"):
        _validate_answer([events[0], {**events[1], "sources": []}], "successor")
    with pytest.raises(ValueError, match="build SHA mismatch"):
        _validate_answer(events, "different")


def test_parse_sse_preserves_runtime_and_terminal_events() -> None:
    body = (
        b"event: request.accepted\n"
        b'data: {"type":"request.accepted","runtime":{"build_sha":"s"}}\n\n'
        b"event: answer.completed\n"
        b'data: {"type":"answer.completed","answer":"a","sources":[{}]}\n\n'
    )
    assert [event["type"] for event in _parse_sse(body)] == [
        "request.accepted",
        "answer.completed",
    ]
