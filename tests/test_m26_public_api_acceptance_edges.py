from __future__ import annotations

import asyncio
import json
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from knowledge_engine import m26_public_api
from knowledge_engine.m26_public_api import Admission, PublicQuotaLedger, create_app

ROOT = Path(__file__).resolve().parents[1]
GATE_PATH = ROOT / "pilot/m26/m26-pa-7-resolved-production-gate.json"


class RequestStub:
    def __init__(self, disconnected: bool = False) -> None:
        self.disconnected = disconnected

    async def is_disconnected(self) -> bool:
        return self.disconnected


class Clock:
    def __init__(self, values: list[float]) -> None:
        self.values = list(values)
        self.last = values[-1]

    def monotonic(self) -> float:
        if self.values:
            self.last = self.values.pop(0)
        return self.last


def _admission(ip_key: str = "ip-test") -> Admission:
    return Admission(
        request_id="req_edge_acceptance",
        ip_key=ip_key,
        quota_day="2026-08-16",
        fallback_day="2026-08-16",
        accepted_at="2026-08-16T00:00:00.000Z",
    )


def _event_from_sse(chunk: str) -> dict[str, Any] | None:
    for line in chunk.splitlines():
        if line.startswith("data: "):
            return json.loads(line.removeprefix("data: "))
    return None


def _events(response: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for block in response.text.strip().split("\n\n"):
        event = _event_from_sse(block)
        if event is not None:
            result.append(event)
    return result


def _minimal_dto() -> dict[str, Any]:
    return {
        "status": "owner_only_cited_answer",
        "safe_abstention": False,
        "answer_text": "Verified answer.",
        "citations": [],
        "sources": [],
        "answer_claims": [],
        "provider_routing": {
            "closure_provider_initial": "cloudflare",
            "closure_provider_final": "cloudflare",
            "fallback_used": False,
            "fallback_reason": "NONE",
            "provider_attempts": [],
        },
    }


def _configured_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_run: Any,
) -> TestClient:
    monkeypatch.setenv("M26_PUBLIC_IP_HMAC_SECRET", "edge-hmac-secret")
    monkeypatch.setenv("KNOWLEDGE_ENGINE_OWNER_SUBJECT_HASH", "93" * 32)
    monkeypatch.setenv("M26_PUBLIC_ALLOWED_ORIGINS", "https://danielcanfly.com")
    monkeypatch.setattr(m26_public_api, "BURST_PER_MINUTE_LIMIT", 100)
    monkeypatch.setattr(m26_public_api, "run_owner_query_for_web", fake_run)
    return TestClient(
        create_app(
            root=ROOT,
            gate_path=GATE_PATH,
            quota_ledger=PublicQuotaLedger(tmp_path / "quota.sqlite3"),
        )
    )


def test_burst_boundary_returns_locked_public_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(m26_public_api, "PER_IP_DAILY_LIMIT", 100)
    monkeypatch.setattr(m26_public_api, "BURST_PER_MINUTE_LIMIT", 2)
    monkeypatch.setattr(m26_public_api, "GLOBAL_DAILY_LIMIT", 100)
    ledger = PublicQuotaLedger(tmp_path / "quota.sqlite3")
    now = datetime(2026, 8, 16, 3, 10, 12, tzinfo=UTC)

    for _ in range(2):
        assert ledger.admit(ip_key="ip-a", now=now) is None
        ledger.release(ip_key="ip-a")
    problem = ledger.admit(ip_key="ip-a", now=now)

    assert problem is not None
    assert problem.code == "BURST_RATE_LIMIT_EXCEEDED"
    assert problem.retryable is True
    assert problem.retry_after_seconds == 48


def test_global_concurrency_boundary_returns_locked_public_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(m26_public_api, "ACTIVE_PER_IP_LIMIT", 10)
    monkeypatch.setattr(m26_public_api, "GLOBAL_ACTIVE_LIMIT", 3)
    monkeypatch.setattr(m26_public_api, "BURST_PER_MINUTE_LIMIT", 100)
    monkeypatch.setattr(m26_public_api, "GLOBAL_DAILY_LIMIT", 100)
    ledger = PublicQuotaLedger(tmp_path / "quota.sqlite3")
    now = datetime(2026, 8, 16, 3, 11, tzinfo=UTC)

    for ip_key in ("ip-a", "ip-b", "ip-c"):
        assert ledger.admit(ip_key=ip_key, now=now) is None
    problem = ledger.admit(ip_key="ip-d", now=now)

    assert problem is not None
    assert problem.code == "GLOBAL_CONCURRENCY_LIMIT_EXCEEDED"
    assert problem.retry_after_seconds == 1


def test_global_daily_boundary_and_utc_reset_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(m26_public_api, "PER_IP_DAILY_LIMIT", 100)
    monkeypatch.setattr(m26_public_api, "BURST_PER_MINUTE_LIMIT", 100)
    monkeypatch.setattr(m26_public_api, "GLOBAL_DAILY_LIMIT", 2)
    ledger = PublicQuotaLedger(tmp_path / "quota.sqlite3")
    now = datetime(2026, 8, 16, 23, 59, 30, tzinfo=UTC)

    for ip_key in ("ip-a", "ip-b"):
        assert ledger.admit(ip_key=ip_key, now=now) is None
        ledger.release(ip_key=ip_key)
    problem = ledger.admit(ip_key="ip-c", now=now)

    assert problem is not None
    assert problem.code == "GLOBAL_DAILY_LIMIT_REACHED"
    assert problem.reset_at == "2026-08-17T00:00:00Z"

    next_day = now + timedelta(minutes=1)
    assert ledger.admit(ip_key="ip-c", now=next_day) is None
    ledger.release(ip_key="ip-c")


def test_fallback_daily_boundary_returns_locked_public_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(m26_public_api, "FALLBACK_DAILY_LIMIT", 2)
    ledger = PublicQuotaLedger(tmp_path / "quota.sqlite3")
    now = datetime(2026, 8, 16, 3, 12, tzinfo=UTC)

    assert ledger.fallback_budget_available(now=now) is None
    ledger.record_fallback(now=now)
    ledger.record_fallback(now=now)
    problem = ledger.fallback_budget_available(now=now)

    assert problem is not None
    assert problem.code == "FALLBACK_DAILY_LIMIT_REACHED"
    assert problem.reset_at == "2026-08-17T00:00:00Z"


def test_90_second_hard_deadline_via_controlled_clock_double(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert m26_public_api.HARD_DEADLINE_SECONDS == 90
    monkeypatch.setattr(m26_public_api, "time", Clock([0.0, 0.0, 91.0]))

    async def never_to_thread(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        await asyncio.Event().wait()

    monkeypatch.setattr(m26_public_api.asyncio, "to_thread", never_to_thread)
    ledger = PublicQuotaLedger(tmp_path / "quota.sqlite3")

    async def run() -> list[dict[str, Any]]:
        stream = m26_public_api._answer_event_stream(  # noqa: SLF001
            request=RequestStub(),
            question="What is safe?",
            admission=_admission(),
            ledger=ledger,
            app_root=ROOT,
            gate_path=GATE_PATH,
        )
        first = _event_from_sse(await anext(stream))
        second = _event_from_sse(await anext(stream))
        await stream.aclose()
        return [event for event in (first, second) if event is not None]

    events = asyncio.run(run())
    assert events[0]["type"] == "request.accepted"
    assert events[1]["type"] == "answer.failed"
    assert events[1]["code"] == "ANSWER_TIMEOUT"
    assert events[1]["retryable"] is True


def test_heartbeat_is_emitted_while_execution_is_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert m26_public_api.HEARTBEAT_SECONDS == 10
    monkeypatch.setattr(m26_public_api, "time", Clock([0.0, 0.0, 0.0, 11.0]))

    async def never_to_thread(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        await asyncio.Event().wait()

    monkeypatch.setattr(m26_public_api.asyncio, "to_thread", never_to_thread)
    ledger = PublicQuotaLedger(tmp_path / "quota.sqlite3")

    async def run() -> tuple[str, str]:
        stream = m26_public_api._answer_event_stream(  # noqa: SLF001
            request=RequestStub(),
            question="What is safe?",
            admission=_admission(),
            ledger=ledger,
            app_root=ROOT,
            gate_path=GATE_PATH,
        )
        accepted = await anext(stream)
        heartbeat = await anext(stream)
        await stream.aclose()
        return accepted, heartbeat

    accepted, heartbeat = asyncio.run(run())
    assert "event: request.accepted" in accepted
    assert heartbeat == ": heartbeat\n\n"


def test_disconnect_yields_exactly_one_cancelled_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def never_to_thread(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        await asyncio.Event().wait()

    monkeypatch.setattr(m26_public_api.asyncio, "to_thread", never_to_thread)
    ledger = PublicQuotaLedger(tmp_path / "quota.sqlite3")

    async def run() -> list[dict[str, Any]]:
        stream = m26_public_api._answer_event_stream(  # noqa: SLF001
            request=RequestStub(disconnected=True),
            question="What is safe?",
            admission=_admission(),
            ledger=ledger,
            app_root=ROOT,
            gate_path=GATE_PATH,
        )
        result: list[dict[str, Any]] = []
        async for chunk in stream:
            event = _event_from_sse(chunk)
            if event is not None:
                result.append(event)
        return result

    events = asyncio.run(run())
    terminals = [event for event in events if event["type"].startswith("answer.")]
    assert [event["type"] for event in terminals] == ["answer.cancelled"]
    assert terminals[0]["code"] == "CLIENT_DISCONNECTED"


def test_late_runtime_event_after_dto_cannot_escape_after_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release_late = threading.Event()
    late_done = threading.Event()

    def fake_run(**kwargs: Any) -> dict[str, Any]:
        sink = kwargs["event_sink"]
        sink({"type": "stage.started", "stage": "retrieval"})

        def late_emit() -> None:
            release_late.wait(timeout=2)
            sink({"type": "stage.completed", "stage": "publication", "status": "late"})
            late_done.set()

        threading.Thread(target=late_emit, daemon=True).start()
        return _minimal_dto()

    with _configured_client(tmp_path, monkeypatch, fake_run) as client:
        response = client.post("/v1/answers", json={"question": "What is safe?"})
    events = _events(response)
    release_late.set()
    assert late_done.wait(timeout=2)

    terminals = [event for event in events if event["type"].startswith("answer.")]
    assert len(terminals) == 1
    assert terminals[0]["type"] == "answer.completed"
    terminal_index = events.index(terminals[0])
    assert terminal_index == len(events) - 1


def test_independent_requests_have_independent_request_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(**kwargs: Any) -> dict[str, Any]:
        del kwargs
        return _minimal_dto()

    with _configured_client(tmp_path, monkeypatch, fake_run) as client:
        first = _events(client.post("/v1/answers", json={"question": "What is safe?"}))
        second = _events(client.post("/v1/answers", json={"question": "What is safe?"}))

    first_id = first[0]["request_id"]
    second_id = second[0]["request_id"]
    assert first_id != second_id
    assert all(event["request_id"] == first_id for event in first)
    assert all(event["request_id"] == second_id for event in second)
