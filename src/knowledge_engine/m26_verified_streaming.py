from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import AsyncIterator, Callable, Mapping
from pathlib import Path
from typing import Any

VERIFIED_STREAM_SCHEMA = "knowledge-engine-m26-verified-stream/v1"
VERIFIED_STREAM_PATH = "/api/m26/query/stream"
VERIFIED_STREAM_QUEUE_MAX = 128


def sse_frame(event_type: str, payload: Mapping[str, Any]) -> str:
    body = {
        "schema_version": VERIFIED_STREAM_SCHEMA,
        "event": event_type,
        **dict(payload),
    }
    return (
        f"event: {event_type}\n"
        f"data: {json.dumps(body, ensure_ascii=False, separators=(',', ':'))}\n\n"
    )


def runtime_progress_event(
    event: Mapping[str, Any],
) -> tuple[str, dict[str, Any]] | None:
    event_type = str(event.get("type", ""))
    stage = str(event.get("stage", ""))
    canonical_runtime = (
        dict(event.get("canonical_runtime", {}))
        if isinstance(event.get("canonical_runtime"), Mapping)
        else {}
    )
    if event_type == "stage.started" and stage == "retrieval":
        return "retrieval_started", {"canonical_runtime": canonical_runtime}
    if event_type == "stage.completed" and stage == "retrieval":
        return (
            "evidence_candidates_ready",
            {
                "selected_evidence_count": int(event.get("selected_evidence_count", 0) or 0),
                "latency_ms": int(event.get("latency_ms", 0) or 0),
                "canonical_runtime": canonical_runtime,
            },
        )
    return None


def verified_material_events(
    dto: Mapping[str, Any],
) -> list[tuple[str, dict[str, Any]]]:
    safe_abstention = bool(dto.get("safe_abstention", True))
    status_value = str(dto.get("status", ""))
    if safe_abstention or status_value != "owner_only_cited_answer":
        return [("safe_abstention_done", {"response": dict(dto)})]

    integrity = dto.get("integrity")
    integrity_map = dict(integrity) if isinstance(integrity, Mapping) else {}
    citations = dto.get("citations")
    citation_rows = (
        [dict(item) for item in citations if isinstance(item, Mapping)]
        if isinstance(citations, list)
        else []
    )
    answer_text = str(dto.get("answer_text", "")).strip()

    if (
        int(integrity_map.get("unsupported_accepted_claims", 1) or 0) != 0
        or integrity_map.get("material_claim_support_verified") is not True
        or integrity_map.get("citation_locator_valid") is not True
        or not citation_rows
        or not answer_text
    ):
        return [
            (
                "error",
                {
                    "code": "M26_VERIFIED_STREAM_FINAL_NOT_STREAMABLE",
                    "message": (
                        "authoritative final state did not satisfy verified "
                        "streaming invariants"
                    ),
                },
            )
        ]

    citations_by_claim: dict[str, list[dict[str, Any]]] = {}
    for citation in citation_rows:
        claim_id = str(citation.get("claim_id", "")).strip()
        if claim_id:
            citations_by_claim.setdefault(claim_id, []).append(citation)

    events: list[tuple[str, dict[str, Any]]] = []
    claims = dto.get("answer_claims")
    if isinstance(claims, list):
        for claim in claims:
            if not isinstance(claim, Mapping):
                continue
            claim_id = str(claim.get("claim_id", "")).strip()
            surface_text = str(claim.get("surface_text", "")).strip()
            claim_citations = citations_by_claim.get(claim_id, [])
            if not claim_id or not surface_text or not claim_citations:
                continue
            events.append(
                (
                    "verified_claim_ready",
                    {
                        "claim_id": claim_id,
                        "text": surface_text,
                        "citations": claim_citations,
                    },
                )
            )

    events.append(
        (
            "cited_segment_ready",
            {
                "text": answer_text,
                "citations": citation_rows,
            },
        )
    )
    events.append(("final_answer_done", {"response": dict(dto)}))
    return events


async def verified_query_event_stream(
    *,
    request: Any,
    root: Path,
    gate_path: Path,
    question: str,
    question_sha256: str,
    owner_subject_hash: str,
    require_remote_dense: bool,
    authoritative_runtime: str,
    run_query: Callable[..., dict[str, Any]],
) -> AsyncIterator[str]:
    loop = asyncio.get_running_loop()
    event_queue: asyncio.Queue[Mapping[str, Any]] = asyncio.Queue(
        maxsize=VERIFIED_STREAM_QUEUE_MAX
    )
    disconnected = threading.Event()

    def enqueue_runtime_event(event: Mapping[str, Any]) -> None:
        if disconnected.is_set():
            return

        def enqueue() -> None:
            if disconnected.is_set():
                return
            try:
                event_queue.put_nowait(dict(event))
            except asyncio.QueueFull:
                # Progress events are observational. Dropping one under client
                # backpressure must never fork or block the authoritative runtime.
                return

        loop.call_soon_threadsafe(enqueue)

    yield sse_frame(
        "request_started",
        {
            "question_sha256": question_sha256,
            "authoritative_runtime": authoritative_runtime,
        },
    )

    worker = asyncio.create_task(
        asyncio.to_thread(
            run_query,
            root=root,
            gate_path=gate_path,
            request_payload={"question": question},
            owner_subject_hash=owner_subject_hash,
            require_remote_dense=require_remote_dense,
            event_sink=enqueue_runtime_event,
        )
    )

    try:
        while True:
            if await request.is_disconnected():
                disconnected.set()
                worker.cancel()
                return

            while True:
                try:
                    runtime_event = event_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                mapped = runtime_progress_event(runtime_event)
                if mapped is not None:
                    yield sse_frame(mapped[0], mapped[1])

            if worker.done():
                break
            await asyncio.sleep(0.01)

        dto = await worker

        while True:
            try:
                runtime_event = event_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            mapped = runtime_progress_event(runtime_event)
            if mapped is not None:
                yield sse_frame(mapped[0], mapped[1])

        for event_type, payload in verified_material_events(dto):
            yield sse_frame(event_type, payload)
    except asyncio.CancelledError:
        disconnected.set()
        worker.cancel()
        raise
    except Exception as exc:
        reason_code = str(getattr(exc, "reason_code", "") or "M26_ASK_RUNTIME_FAILED")
        yield sse_frame("error", {"code": reason_code})
    finally:
        disconnected.set()
