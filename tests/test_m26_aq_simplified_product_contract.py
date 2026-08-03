from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest


def _load_module(*, name: str = "m26_aq_final_closure") -> ModuleType:
    root = Path(__file__).resolve().parents[1]
    script = root / "scripts" / "m26_aq_final_closure.py"
    spec = importlib.util.spec_from_file_location(name, script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_generalized_module() -> ModuleType:
    _load_module(name="m26_aq_final_closure")
    root = Path(__file__).resolve().parents[1]
    script = root / "scripts" / "m26_aq_generalized_closure.py"
    spec = importlib.util.spec_from_file_location("m26_aq_generalized_closure_contract", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _answered_row(module: ModuleType, case_id: str) -> dict[str, object]:
    closure: dict[str, object] = {
        "failures": [],
        "broad_deterministic_fallback_used": False,
    }
    if case_id in {"R3-Q05", "R3-Q09"}:
        closure["endpoint_proof"] = {
            "matched": True,
            "edge_id": module.EXPECTED_GRAPH_EDGE,
            "relation_type": "precedes",
        }
    answer_text = "A grounded supported answer."
    if case_id == "R3-Q09":
        answer_text = (
            "The precedes edge supports ordering or navigation. "
            "It does not prove dependency."
        )
    return {
        "case_id": case_id,
        "question": "synthetic product-contract question",
        "http_status": 200,
        "status": "owner_only_cited_answer",
        "safe_abstention": False,
        "answer_text": answer_text,
        "answer_source": module.ANSWER_SOURCE,
        "citations": [{"citation_id": "c1"}],
        "accounting": {"provider_call_count": 1},
        "integrity": {
            "unsupported_accepted_claims": 0,
            "material_claim_support_verified": True,
            "citation_locator_valid": True,
        },
        "mutations": {},
        "semantic_closure": closure,
        "multi_evidence_verification": {},
        "relationship_summary": {},
        "collector": {
            "deadline_exceeded": False,
            "timeout_converted_to_answer": False,
        },
    }


def _abstention_row(case_id: str) -> dict[str, object]:
    return {
        "case_id": case_id,
        "question": "synthetic abstention question",
        "http_status": 200,
        "status": "owner_only_safe_abstention",
        "safe_abstention": True,
        "answer_text": "",
        "citations": [],
        "accounting": {"provider_call_count": 0},
        "collector": {
            "deadline_exceeded": False,
            "timeout_converted_to_answer": False,
        },
    }


def test_correct_false_premise_answer_need_not_begin_with_no(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module(name="m26_aq_final_closure_contract")
    monkeypatch.setattr(module, "_validate_visible_semantics", lambda row: [])

    rows = []
    for index in range(1, 13):
        case_id = f"R3-Q{index:02d}"
        if case_id in {"R3-Q10", "R3-Q11"}:
            rows.append(_abstention_row(case_id))
        else:
            rows.append(_answered_row(module, case_id))

    artifact = {
        "collection": {"status": "complete", "failure": None},
        "health": {
            "http_status": 200,
            "status": "ok",
            "build_sha": "sha",
            "entrypoint": (
                "knowledge_engine.m26_pa7_semantic_closure_runtime."
                "run_owner_arbitrary_query"
            ),
        },
        "graph": {
            "http_status": 200,
            "status": "ok",
            "graph_scope": "full_current_production_relation_graph",
            "release_id": module.EXPECTED_RELEASE_ID,
            "graph_v2_sha256": module.EXPECTED_GRAPH_SHA256,
            "node_count": module.EXPECTED_NODE_COUNT,
            "edge_count": module.EXPECTED_EDGE_COUNT,
        },
        "rows": rows,
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

    module.validate(
        input_path=artifact_path,
        gate_path=gate_path,
        expected_sha="sha",
    )


def test_blackbox_false_premise_answer_need_not_begin_with_no(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_generalized_module()
    monkeypatch.setattr(module, "_validate_visible_semantics", lambda row: [])
    failures: list[str] = []
    module._validate_answer_row(
        {
            "case_id": "GPT-E-BB09",
            "class": "grounded_but_irrelevant_adversarial",
            "safe_abstention": False,
            "status": "owner_only_cited_answer",
            "answer_source": module.ANSWER_SOURCE,
            "answer_text": (
                "The precedes edge records ordering or navigation. "
                "It does not establish dependency."
            ),
            "citations": [{"citation_id": "c1"}],
            "accounting": {"provider_call_count": 1},
            "integrity": {
                "unsupported_accepted_claims": 0,
                "material_claim_support_verified": True,
                "citation_locator_valid": True,
            },
            "semantic_closure": {
                "failures": [],
                "broad_deterministic_fallback_used": False,
            },
            "multi_evidence_verification": {},
        },
        failures,
    )
    assert failures == []


def test_blackbox_safe_abstention_may_use_one_bounded_provider_call() -> None:
    module = _load_generalized_module()
    failures: list[str] = []
    module._validate_abstention_row(
        {
            "case_id": "GPT-E-BB18",
            "safe_abstention": True,
            "status": "owner_only_safe_abstention",
            "answer_text": "",
            "citations": [],
            "accounting": {"provider_call_count": 1},
        },
        failures,
    )
    assert failures == []


def test_blackbox_abstention_still_rejects_answer_text_or_excess_calls() -> None:
    module = _load_generalized_module()
    failures: list[str] = []
    module._validate_abstention_row(
        {
            "case_id": "GPT-E-BB18",
            "safe_abstention": True,
            "status": "owner_only_safe_abstention",
            "answer_text": "unsupported prose",
            "citations": [],
            "accounting": {"provider_call_count": 3},
        },
        failures,
    )
    assert "GPT-E-BB18:provider_call_count" in failures
    assert "GPT-E-BB18:abstention_has_answer_text" in failures
