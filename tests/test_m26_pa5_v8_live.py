from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from knowledge_engine.m26_pa5_v8_live import calibration_ids, run_population

ROOT = Path(__file__).resolve().parents[1]


class FakeProviderClient:
    def __init__(self) -> None:
        self.calls = 0
        self.cost = Decimal("0")

    def call(self, payload: dict[str, Any], call_class: str) -> dict[str, Any]:
        self.calls += 1
        self.cost += Decimal("0.00001")
        user = json.loads(payload["messages"][0]["content"])
        if call_class == "independent_review":
            value = {"verdict": "pass", "reason_codes": []}
        else:
            evidence = user["candidate_evidence"]
            mandatory = user["mandatory_abstention_reason"]
            if mandatory:
                value = {
                    "status": "abstain",
                    "selected_span_ids": [],
                    "selected_evidence_ids": [],
                    "relation": None,
                    "abstention_reason": mandatory,
                }
            else:
                value = {
                    "status": "select",
                    "selected_span_ids": [item["span_id"] for item in evidence],
                    "selected_evidence_ids": [item["evidence_id"] for item in evidence],
                    "relation": (
                        user["allowed_relations"][0]
                        if user["allowed_relations"]
                        else None
                    ),
                    "abstention_reason": None,
                }
        return {
            "text": json.dumps(value, sort_keys=True),
            "usage": {
                "input_tokens": 10,
                "output_tokens": 5,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            },
            "cost_usd": "0.00001",
            "latency_ms": 10,
            "response_id": f"fake-{self.calls}",
            "call_class": call_class,
            "network_attempt": 1,
        }


def test_calibration_controller_passes_complete_sample_with_runtime_owned_evidence() -> None:
    question_ids, sample_sha256 = calibration_ids(ROOT)
    client = FakeProviderClient()
    receipt = run_population(
        root=ROOT,
        question_ids=question_ids,
        max_calls=160,
        max_cost=Decimal("5.00"),
        thresholds={
            "count": 35,
            "safe_min": 0.90,
            "grounded_min": 0.90,
            "over_abstention_max": 0.10,
            "disagreement_max": 0.10,
        },
        mode="calibration-test",
        client=client,
    )
    assert sample_sha256
    assert receipt["status"] == "passed"
    assert receipt["metrics"]["complete_accounting"] == 35
    assert receipt["metrics"]["answerable_grounded_quality_pass_rate"] == 1.0
    assert receipt["metrics"]["mandatory_abstention_correctness"] == 1.0
    assert receipt["metrics"]["citation_locator_validity"] == 1.0
    assert receipt["metrics"]["unresolved_disagreements"] == 0
    assert client.calls == 70


def test_live_receipt_persists_only_bounded_identifiers_and_metrics() -> None:
    question_ids, _ = calibration_ids(ROOT)
    receipt = run_population(
        root=ROOT,
        question_ids=question_ids,
        max_calls=160,
        max_cost=Decimal("5.00"),
        thresholds={
            "count": 35,
            "safe_min": 0.90,
            "grounded_min": 0.90,
            "over_abstention_max": 0.10,
            "disagreement_max": 0.10,
        },
        mode="calibration-test",
        client=FakeProviderClient(),
    )
    serialized = json.dumps(receipt, sort_keys=True)
    assert '"question"' not in serialized
    assert '"span_text"' not in serialized
    assert '"candidate_evidence"' not in serialized
    assert receipt["raw_query_persisted"] is False
    assert receipt["raw_evidence_persisted"] is False
    assert receipt["full_provider_response_persisted"] is False
