from __future__ import annotations

from typing import Any

import pytest

from knowledge_engine import m26_aq_semantic_contract as contract
from knowledge_engine import m26_pa7_semantic_closure_runtime as runtime


class _Provider:
    calls = 0


def _abstention() -> dict[str, Any]:
    return {
        "status": "owner_only_safe_abstention",
        "terminal_status": "safe_abstention",
        "answer_text": "",
        "reason_codes": ["TEST"],
        "safe_abstention": True,
    }


def test_no_seed_uses_bounded_b6_recovery_not_legacy_wrapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}

    def fake_runtime(**kwargs: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        observed.update(kwargs)
        return _abstention(), {"failures": ["TEST"]}

    monkeypatch.setattr(runtime, "_synthesize_and_verify", fake_runtime)

    verification, closure = contract._consolidated_semantic_recovery(
        question="question",
        trace_id="trace",
        intent_class="direct_grounded_knowledge",
        evidence=[],
        provider_client=_Provider(),
        requirements=[],
        endpoint_proof={},
    )

    assert observed["max_attempts"] == 2
    assert verification["status"] == "owner_only_safe_abstention"
    assert closure["bp5c_r2_recovery"] is True


def test_fast_seed_review_contract_failure_does_not_fall_through_to_synthesis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = contract.FastRecoverySeed(
        answer_text="supported answer",
        citation_ids=("ev-1",),
        facet_ids=("facet-1",),
        support_refs=({"evidence_id": "ev-1", "exact_quote": "support"},),
    )
    monkeypatch.setattr(contract, "_fast_recovery_seed", lambda **_kwargs: seed)
    monkeypatch.setattr(contract, "_fast_seed_candidate", lambda **_kwargs: {"claims": []})

    error = runtime.NativeSemanticReviewContractError(
        "REVIEW_CONTRACT",
        raw={"text": "bad"},
        review_slots=[],
    )
    monkeypatch.setattr(
        runtime,
        "_call_runtime_bound_semantic_entailment_review",
        lambda **_kwargs: (_ for _ in ()).throw(error),
    )
    monkeypatch.setattr(
        runtime,
        "_synthesize_and_verify",
        lambda **_kwargs: pytest.fail("review contract failure fell through to synthesis"),
    )

    verification, closure = contract._consolidated_semantic_recovery(
        question="question",
        trace_id="trace",
        intent_class="direct_grounded_knowledge",
        evidence=[],
        provider_client=_Provider(),
        requirements=[],
        endpoint_proof={},
        fast_envelope=contract.FastAttemptEnvelope({}, ("alignment",)),
    )

    assert verification["status"] == "owner_only_safe_abstention"
    assert closure["fast_seed_used"] is True


def test_fast_seed_semantic_block_rewrites_only_with_two_slots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = contract.FastRecoverySeed("answer", ("ev-1",), ("facet-1",), ())
    monkeypatch.setattr(contract, "_fast_recovery_seed", lambda **_kwargs: seed)
    monkeypatch.setattr(
        contract,
        "_fast_seed_review",
        lambda **_kwargs: (
            _abstention(),
            {"failures": ["SEMANTIC_REVIEW_BLOCKED:claim:INSUFFICIENT"]},
        ),
    )
    monkeypatch.setattr(contract, "_provider_attempts_remaining", lambda _provider: 2)
    calls: list[int] = []

    def fake_runtime(**kwargs: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        calls.append(kwargs["max_attempts"])
        return _abstention(), {"failures": ["TEST"]}

    monkeypatch.setattr(runtime, "_synthesize_and_verify", fake_runtime)

    _verification, closure = contract._consolidated_semantic_recovery(
        question="question",
        trace_id="trace",
        intent_class="direct_grounded_knowledge",
        evidence=[],
        provider_client=_Provider(),
        requirements=[],
        endpoint_proof={},
        fast_envelope=contract.FastAttemptEnvelope({}, ("alignment",)),
    )

    assert calls == [1]
    assert closure["fast_seed_semantic_rewrite"] is True
