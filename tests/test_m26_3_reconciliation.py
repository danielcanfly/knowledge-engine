from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot" / "m26"


def canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


ACCEPTANCE = load(PILOT / "m26-3-acceptance.json")
REGISTRY = load(PILOT / "m26-3-contract-registry.json")


def test_acceptance_identity_and_remote_contracts() -> None:
    unsigned = dict(ACCEPTANCE)
    claimed = unsigned.pop("self_sha256")
    assert claimed == hashlib.sha256(canonical(unsigned)).hexdigest()
    assert ACCEPTANCE["status"] == "m26_3_context_compiler_accepted"
    assert ACCEPTANCE["predecessor"] == {
        "status": "m26_2_retrieval_envelope_accepted",
        "main_seal_sha": "31d6aa093181cb9efbf48d1da70c70ae9181773b",
    }
    assert ACCEPTANCE["implementation"]["pull_request_number"] == 1066
    assert ACCEPTANCE["implementation"]["final_head_sha"] == (
        "56b00926957e10327be5910538b5b3b34b60b06d"
    )
    assert ACCEPTANCE["implementation"]["merge_sha"] == (
        "693fdc32c5f4f7d30505112be0b866bdb671143e"
    )
    assert ACCEPTANCE["implementation"]["expected_head_merge"] is True
    assert ACCEPTANCE["implementation"]["unresolved_review_thread_count"] == 0


def test_frozen_identities_match_registry() -> None:
    contracts = {entry["path"]: entry["sha256"] for entry in REGISTRY["contracts"]}
    assert ACCEPTANCE["frozen_identities"]["entry_contract_sha256"] == contracts[
        "pilot/m26/m26-3-entry-contract.json"
    ]
    assert ACCEPTANCE["frozen_identities"]["context_policy_sha256"] == contracts[
        "pilot/m26/m26-3-context-policy.json"
    ]
    assert ACCEPTANCE["frozen_identities"]["benchmark_cases_sha256"] == contracts[
        "pilot/m26/m26-3-benchmark-cases.json"
    ]
    assert ACCEPTANCE["frozen_identities"]["context_package_schema_sha256"] == contracts[
        "schemas/m26-context-package-v1.schema.json"
    ]
    assert ACCEPTANCE["frozen_identities"]["evidence_budget_schema_sha256"] == contracts[
        "schemas/m26-evidence-budget-v1.schema.json"
    ]
    assert ACCEPTANCE["frozen_identities"]["contract_registry_self_sha256"] == REGISTRY[
        "self_sha256"
    ]


def test_quality_metrics_and_authority_boundary() -> None:
    benchmark = ACCEPTANCE["benchmark"]
    assert benchmark["case_count"] == 9
    assert benchmark["passed_count"] == 9
    assert benchmark["failed_count"] == 0
    assert benchmark["compiled_context_count"] == 6
    assert benchmark["abstain_required_count"] == 3
    assert benchmark["provider_call_count"] == 0
    assert benchmark["real_corpus_binding_count"] == 0
    assert benchmark["semantic_or_hybrid_use_count"] == 0
    assert benchmark["production_answer_serving_count"] == 0

    boundary = ACCEPTANCE["authority_boundary"]
    assert boundary["synthetic_only"] is True
    assert not any(value for key, value in boundary.items() if key != "synthetic_only")


def test_next_stage_is_synthetic_provider_mock_only() -> None:
    next_stage = ACCEPTANCE["next_stage"]
    assert next_stage["stage_id"] == "M26.4"
    assert next_stage["authorized"] is True
    assert next_stage["provider_mock_replay_permitted"] is True
    assert next_stage["live_provider_calls_permitted"] is False
    assert next_stage["real_corpus_binding_permitted"] is False
    assert next_stage["production_answer_serving_permitted"] is False
