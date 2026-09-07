from __future__ import annotations

import pytest
from scripts.m26_public_cutover_gate import (
    SMOKE_QUESTIONS,
    _parse_sse,
    _validate_health,
    _validate_transport,
    _validate_usability,
)


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


def test_transport_accepts_completed_or_abstained_terminal_with_identity() -> None:
    events = [
        {"type": "request.accepted", "runtime": {"build_sha": "successor"}},
        {"type": "answer.completed", "answer": "Grounded answer.", "sources": [{"id": "1"}]},
    ]
    assert _validate_transport(events, "successor")["type"] == "answer.completed"
    abstained = [events[0], {"type": "answer.abstained", "code": "INSUFFICIENT_SUPPORT"}]
    assert _validate_transport(abstained, "successor")["type"] == "answer.abstained"
    with pytest.raises(ValueError, match="build SHA mismatch"):
        _validate_transport(events, "different")
    with pytest.raises(ValueError, match="exactly one valid terminal"):
        _validate_transport([events[0], {"type": "answer.failed"}], "successor")
    with pytest.raises(ValueError, match="events after"):
        _validate_transport([*events, {"type": "stage.completed"}], "successor")


def test_usability_requires_full_fixed_set_and_one_sourced_answer() -> None:
    completed = {"type": "answer.completed", "answer": "Grounded.", "sources": [{}]}
    abstained = {"type": "answer.abstained", "code": "INSUFFICIENT_SUPPORT"}
    assert len(SMOKE_QUESTIONS) == 3
    _validate_usability([abstained, completed, abstained])
    with pytest.raises(ValueError, match="full fixed smoke set"):
        _validate_usability([completed, abstained])
    with pytest.raises(ValueError, match="no completed answer with sources"):
        _validate_usability([abstained, abstained, abstained])
    with pytest.raises(ValueError, match="no completed answer with sources"):
        _validate_usability(
            [abstained, {**completed, "sources": []}, {**completed, "answer": ""}]
        )
    with pytest.raises(ValueError, match="no completed answer with sources"):
        _validate_usability([abstained, abstained, {**completed, "sources": "not-a-list"}])


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
