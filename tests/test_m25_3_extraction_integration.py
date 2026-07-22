from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from knowledge_engine.m25_extraction_common import (
    PROVIDER_RESPONSE_SCHEMA,
    RECORDED_RESPONSE_SET_SCHEMA,
    _digest,
)
from knowledge_engine.m25_extraction_provider import RecordedResponseProvider
from knowledge_engine.m25_extraction_worker import (
    execute_extraction,
    prepare_extraction_request,
)
from knowledge_engine.m25_intake_orchestrator import resume_orchestrator
from m25_2_test_support import _descriptor, _prepare

ROOT = Path(__file__).resolve().parents[1]


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def signed(value: dict[str, Any], field: str) -> dict[str, Any]:
    output = dict(value)
    output[field] = _digest(output)
    return output


def test_m25_2_to_m25_3_recorded_replay_vertical_slice(tmp_path: Path) -> None:
    text = "# Retrieval\n\nBounded retrieval requires human review.\n"
    (tmp_path / "source.md").write_text(text, encoding="utf-8")
    store, bundle = _prepare(tmp_path, [_descriptor("source.md")])
    plan_id = bundle["admission_plan"]["plan_id"]
    intake = resume_orchestrator(
        store,
        plan_id,
        allowed_root=tmp_path,
        run_at="2026-07-23T00:00:00Z",
        max_items=5,
    )
    assert intake["report"]["ready_for_m25_3"] is True

    prompt = load(ROOT / "pilot" / "m25" / "m25-3-prompt-contract.json")
    model = load(ROOT / "pilot" / "m25" / "m25-3-model-policy.json")
    candidate = load(ROOT / "pilot" / "m25" / "m25-3-candidate-policy.json")
    prepared = prepare_extraction_request(
        store,
        plan_id,
        prompt_contract=prompt,
        model_policy=model,
        candidate_policy=candidate,
    )
    derivative_id = prepared["inputs"][0].derivative_id
    excerpt = "Bounded retrieval"
    start = text.index(excerpt)
    proposal = {
        "kind": "concept",
        "label": "Bounded retrieval",
        "language": "en",
        "confidence": 0.93,
        "aliases": [],
        "tags": ["retrieval"],
        "definition": "Retrieval constrained by explicit operational limits.",
        "evidence": [
            {
                "derivative_id": derivative_id,
                "start": start,
                "end": start + len(excerpt),
                "excerpt_sha256": hashlib.sha256(excerpt.encode()).hexdigest(),
            }
        ],
    }
    response = signed(
        {
            "schema_version": PROVIDER_RESPONSE_SCHEMA,
            "request_sha256": prepared["request"]["request_sha256"],
            "provider_id": "recorded-primary",
            "model_id": "fixture-model",
            "model_revision": "fixture-v1",
            "authority": "candidate_only",
            "canonical_knowledge": False,
            "production_authority": False,
            "review_required": True,
            "proposals": [proposal],
        },
        "response_sha256",
    )
    response_set = signed(
        {
            "schema_version": RECORDED_RESPONSE_SET_SCHEMA,
            "responses": [response],
        },
        "response_set_sha256",
    )
    provider = RecordedResponseProvider(
        provider_id="recorded-primary",
        model_id="fixture-model",
        model_revision="fixture-v1",
        response_set=response_set,
    )
    result = execute_extraction(
        store,
        plan_id,
        prompt_contract=prompt,
        model_policy=model,
        candidate_policy=candidate,
        providers={"recorded-primary": provider},
    )
    assert result["candidate_packet"]["candidate_count"] == 1
    assert result["candidate_packet"]["candidates"][0]["authority"] == "candidate_only"
    assert result["receipt"]["replay_deterministic"] is True
    assert result["receipt"]["live_provider_call_performed"] is False
    assert result["receipt"]["credentials_used"] is False
    assert not list((tmp_path / "store").glob("knowledge-source/**"))
