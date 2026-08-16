from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from knowledge_engine.m26_multilingual_semantic_spine import CanonicalSemanticContext
from knowledge_engine.m26_multilingual_verified_claim_spine import (
    build_canonical_verified_claim_spine,
    project_verified_claim_spine,
)


@dataclass(frozen=True)
class RequirementFixture:
    requirement_id: str
    instruction: str = "fixture instruction"
    evidence_terms: tuple[str, ...] = ("fixture",)
    visible_patterns: tuple[str, ...] = (r"\bfixture\b",)
    exact_phrase: str = ""


class RecordingClosureRunner:
    def __init__(
        self,
        verification: dict[str, Any] | None = None,
        closure: dict[str, Any] | None = None,
        *,
        fail: bool = False,
    ) -> None:
        self.verification = verification or verified_answer()
        self.closure = closure or closure_result()
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("fixture closure failure")
        return self.verification, self.closure


def context(*, requested_answer_language: str = "zh-TW") -> CanonicalSemanticContext:
    requirements = (
        RequirementFixture("entity_router"),
        RequirementFixture("semantic_boundary"),
    )
    original_question = (
        "How does the router preserve API-42?"
        if requested_answer_language == "en"
        else "Router 如何保留 API-42？"
    )
    return CanonicalSemanticContext(
        original_question=original_question,
        semantic_question_en="How does the router preserve API-42?",
        closure_question_en="How does the router preserve API-42?",
        requested_answer_language=requested_answer_language,
        detected_input_language="mixed" if requested_answer_language != "en" else "en",
        semantic_question_source="canonical_en"
        if requested_answer_language != "en"
        else "original",
        intent_class="direct_grounded_knowledge",
        semantic_requirements=requirements,
        semantic_requirement_summaries=(),
        semantic_requirement_ids=tuple(item.requirement_id for item in requirements),
        question_contract={"required_facets": [{"facet_id": "direct_answer"}]},
        question_contract_facet_ids=("direct_answer",),
        semantic_contract_schema="fixture-semantic-schema/v1",
        semantic_contract_fingerprint="fixture-fingerprint",
        canonicalization_status_reference="ok",
    )


def evidence_fixture() -> list[dict[str, Any]]:
    return [
        {"evidence_id": "ev-router", "text": "The router preserves API-42 state."}
    ]


def endpoint_proof_fixture() -> dict[str, Any]:
    return {"required": False, "matched": False, "proof_id": "endpoint-fixture"}


def verified_claim(
    *,
    claim_id: str = "claim-router",
    surface_text: str = "The router preserves API-42 state.",
) -> dict[str, Any]:
    return {
        "claim_id": claim_id,
        "claim_role": "direct",
        "claim_type": "EVIDENCE_FACT",
        "surface_text": surface_text,
        "support_refs": [
            {
                "evidence_id": "ev-router",
                "locator_id": "loc-router",
                "exact_quote": "The router preserves API-42 state.",
                "uncertainty": "low",
            }
        ],
    }


def citation() -> dict[str, Any]:
    return {
        "evidence_id": "ev-router",
        "locator_id": "loc-router",
        "source_id": "source-router",
    }


def verified_answer(**overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "status": "owner_only_cited_answer",
        "terminal_status": "answer",
        "answer_text": "The router preserves API-42 state.",
        "answer_source": "provider_verified_runtime_bound_semantic_closure",
        "safe_abstention": False,
        "reason_codes": [],
        "repair_attempted": False,
        "unsupported_accepted_claims": 0,
        "citation_locator_valid": True,
        "material_claim_support_verified": True,
        "semantic_contract_fingerprint": "fixture-fingerprint",
        "answer_claims": [verified_claim()],
        "citations": [citation()],
        "multi_evidence_verification": {
            "semantic_review": {
                "claim_judgments": [
                    {"claim_id": "claim-router", "evidence_ids": ["ev-router"]}
                ]
            }
        },
    }
    value.update(overrides)
    return value


def closure_result(**overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema_version": "m26-aq-semantic-closure/v1",
        "support_proof": [
            {
                "claim_id": "claim-router",
                "evidence_id": "ev-router",
                "locator_id": "loc-router",
            }
        ],
        "endpoint_proof": endpoint_proof_fixture(),
        "semantic_review": {
            "claim_judgments": [
                {"claim_id": "claim-router", "evidence_ids": ["ev-router"]}
            ]
        },
        "semantic_contract": {"fingerprint": "fixture-fingerprint"},
        "broad_deterministic_fallback_used": False,
    }
    value.update(overrides)
    return value


def test_closure_runner_receives_canonical_context_inputs_once() -> None:
    runner = RecordingClosureRunner()
    ctx = context()
    evidence = evidence_fixture()
    endpoint_proof = endpoint_proof_fixture()

    result = build_canonical_verified_claim_spine(
        context=ctx,
        selected_authorized_evidence=evidence,
        provider_client=object(),
        endpoint_proof=endpoint_proof,
        trace_id="trace-phase4",
        closure_runner=runner,
    )

    assert result.status == "verified_full"
    assert len(runner.calls) == 1
    call = runner.calls[0]
    assert call["question"] == ctx.closure_question_en
    assert call["intent_class"] == ctx.intent_class
    assert call["requirements"] is ctx.semantic_requirements
    assert call["evidence"] is evidence
    assert call["endpoint_proof"] is endpoint_proof
    assert call["trace_id"] == "trace-phase4"


def test_authority_failure_is_not_retried_by_track2() -> None:
    runner = RecordingClosureRunner(fail=True)

    result = build_canonical_verified_claim_spine(
        context=context(),
        selected_authorized_evidence=evidence_fixture(),
        provider_client=object(),
        endpoint_proof=endpoint_proof_fixture(),
        trace_id="trace-phase4",
        closure_runner=runner,
    )

    assert result.status == "failed"
    assert result.failure_code == "CANONICAL_CLOSURE_AUTHORITY_FAILED"
    assert len(runner.calls) == 1


def test_verified_full_result_preserves_claim_identity_text_support_and_citations() -> None:
    result = project_verified_claim_spine(
        context=context(),
        verification=verified_answer(),
        closure=closure_result(),
    )

    assert result.status == "verified_full"
    assert result.spine is not None
    claim = result.spine.canonical_claims[0]
    assert claim.claim_id == "claim-router"
    assert claim.surface_text == "The router preserves API-42 state."
    assert claim.support_refs == tuple(verified_claim()["support_refs"])
    assert claim.citations == (citation(),)
    assert claim.publication_eligible is True
    assert result.spine.publication_eligible_claim_count == 1
    assert result.spine.semantic_review == closure_result()["semantic_review"]
    assert result.spine.closure["support_proof"] == closure_result()["support_proof"]


def test_canonical_claims_come_only_from_verified_claim_objects() -> None:
    verification = verified_answer(
        answer_text="This answer text is not converted into a separate claim.",
        answer_claims=[verified_claim(surface_text="Only verified claim text survives.")],
    )

    result = project_verified_claim_spine(
        context=context(),
        verification=verification,
        closure=closure_result(),
    )

    assert result.status == "verified_full"
    assert result.spine is not None
    assert len(result.spine.canonical_claims) == 1
    assert result.spine.canonical_claims[0].surface_text == (
        "Only verified claim text survives."
    )


def test_verified_partial_keeps_only_retained_claims_and_preserves_drop_metadata() -> None:
    verification = verified_answer(
        answer_source="provider_verified_runtime_bound_partial_semantic_closure",
        answer_claims=[
            verified_claim(
                claim_id="claim-kept",
                surface_text="The retained claim is verified.",
            )
        ],
        multi_evidence_verification={
            "partial_answer": True,
            "dropped_claim_count": 1,
            "dropped_claim_ids": ["claim-dropped"],
            "semantic_review": {"status": "partial"},
        },
    )
    result = project_verified_claim_spine(
        context=context(),
        verification=verification,
        closure=closure_result(partial_answer=True),
    )

    assert result.status == "verified_partial"
    assert result.spine is not None
    assert [claim.claim_id for claim in result.spine.canonical_claims] == ["claim-kept"]
    assert "claim-dropped" not in [
        claim.claim_id for claim in result.spine.canonical_claims
    ]
    assert result.spine.dropped_claim_ids == ("claim-dropped",)
    assert result.spine.dropped_claim_count == 1


def test_safe_abstention_has_zero_claims_and_preserves_reasons() -> None:
    verification = verified_answer(
        status="owner_only_safe_abstention",
        terminal_status="safe_abstention",
        answer_source="safe_abstention",
        safe_abstention=True,
        reason_codes=["M26-PA7-ME-029"],
        answer_text="This abstention text must not become a claim.",
        answer_claims=[],
    )
    result = project_verified_claim_spine(
        context=context(),
        verification=verification,
        closure=closure_result(failures=["M26-PA7-ME-029"]),
    )

    assert result.status == "abstained"
    assert result.spine is not None
    assert result.spine.canonical_claims == ()
    assert result.spine.publication_eligible_claim_count == 0
    assert result.spine.reason_codes == ("M26-PA7-ME-029",)


def test_unsupported_accepted_claims_fail_closed() -> None:
    result = project_verified_claim_spine(
        context=context(),
        verification=verified_answer(unsupported_accepted_claims=1),
        closure=closure_result(),
    )

    assert result.status == "failed"
    assert result.failure_code == "VERIFIED_CLAIM_SPINE_UNSUPPORTED_ACCEPTED_CLAIM"
    assert result.spine is None


def test_invalid_citation_locator_fails_closed() -> None:
    result = project_verified_claim_spine(
        context=context(),
        verification=verified_answer(citation_locator_valid=False),
        closure=closure_result(),
    )

    assert result.status == "failed"
    assert result.failure_code == "VERIFIED_CLAIM_SPINE_INVALID_CITATION_LOCATOR"


def test_unverified_material_support_fails_closed() -> None:
    result = project_verified_claim_spine(
        context=context(),
        verification=verified_answer(material_claim_support_verified=False),
        closure=closure_result(),
    )

    assert result.status == "failed"
    assert result.failure_code == "VERIFIED_CLAIM_SPINE_MATERIAL_SUPPORT_UNVERIFIED"


def test_semantic_contract_fingerprint_mismatch_fails_closed() -> None:
    result = project_verified_claim_spine(
        context=context(),
        verification=verified_answer(semantic_contract_fingerprint="different"),
        closure=closure_result(),
    )

    assert result.status == "failed"
    assert result.failure_code == "SEMANTIC_CONTRACT_IDENTITY_MISMATCH"


def test_missing_semantic_contract_fingerprint_fails_closed() -> None:
    verification = verified_answer(semantic_contract_fingerprint="")

    result = project_verified_claim_spine(
        context=context(),
        verification=verification,
        closure=closure_result(semantic_contract={}),
    )

    assert result.status == "failed"
    assert result.failure_code == "SEMANTIC_CONTRACT_IDENTITY_MISSING"


def test_missing_claim_support_mapping_fails_closed() -> None:
    claim = verified_claim()
    claim["support_refs"] = []

    result = project_verified_claim_spine(
        context=context(),
        verification=verified_answer(answer_claims=[claim]),
        closure=closure_result(),
    )

    assert result.status == "failed"
    assert result.failure_code == "VERIFIED_CLAIM_SPINE_SUPPORT_MAPPING_MISSING"


def test_missing_citation_for_support_mapping_fails_closed() -> None:
    result = project_verified_claim_spine(
        context=context(),
        verification=verified_answer(citations=[]),
        closure=closure_result(),
    )

    assert result.status == "failed"
    assert result.failure_code == "VERIFIED_CLAIM_SPINE_SUPPORT_MAPPING_MISSING"


def test_missing_claim_id_fails_closed() -> None:
    claim = verified_claim(claim_id="")

    result = project_verified_claim_spine(
        context=context(),
        verification=verified_answer(answer_claims=[claim]),
        closure=closure_result(),
    )

    assert result.status == "failed"
    assert result.failure_code == "VERIFIED_CLAIM_SPINE_CLAIM_ID_MISSING"


def test_non_abstention_without_verified_claims_fails_closed() -> None:
    result = project_verified_claim_spine(
        context=context(),
        verification=verified_answer(answer_claims=[]),
        closure=closure_result(),
    )

    assert result.status == "failed"
    assert result.failure_code == "VERIFIED_CLAIM_SPINE_NO_VERIFIED_CLAIMS"


def test_malformed_verified_claim_schema_fails_closed() -> None:
    result = project_verified_claim_spine(
        context=context(),
        verification=verified_answer(answer_claims=["not-a-claim"]),
        closure=closure_result(),
    )

    assert result.status == "failed"
    assert result.failure_code == "VERIFIED_CLAIM_SPINE_VERIFICATION_SCHEMA_INVALID"


def test_me065_style_result_cannot_become_publication_eligible_claims() -> None:
    verification = verified_answer(
        status="owner_only_safe_abstention",
        terminal_status="safe_abstention",
        answer_source="safe_abstention",
        safe_abstention=True,
        reason_codes=["M26-PA7-ME-065"],
        answer_claims=[],
    )
    result = project_verified_claim_spine(
        context=context(),
        verification=verification,
        closure=closure_result(failures=["M26-PA7-ME-065"]),
    )

    assert result.status == "abstained"
    assert result.spine is not None
    assert result.spine.publication_eligible_claim_count == 0
    assert result.spine.reason_codes == ("M26-PA7-ME-065",)


def test_english_and_multilingual_canonical_contexts_project_same_claim_spine() -> None:
    english = context(requested_answer_language="en")
    multilingual = context(requested_answer_language="zh-TW")
    verification = verified_answer()
    closure = closure_result()

    english_result = project_verified_claim_spine(
        context=english,
        verification=verification,
        closure=closure,
    )
    multilingual_result = project_verified_claim_spine(
        context=multilingual,
        verification=verification,
        closure=closure,
    )

    assert english_result.status == multilingual_result.status
    assert english_result.spine is not None
    assert multilingual_result.spine is not None
    assert english_result.spine.closure_question_en == (
        multilingual_result.spine.closure_question_en
    )
    assert english_result.spine.intent_class == multilingual_result.spine.intent_class
    assert english_result.spine.semantic_contract_fingerprint == (
        multilingual_result.spine.semantic_contract_fingerprint
    )
    assert english_result.spine.canonical_claims == multilingual_result.spine.canonical_claims
    assert english_result.spine.requested_answer_language == "en"
    assert multilingual_result.spine.requested_answer_language == "zh-TW"


def test_product_code_has_no_track2_reviewer_verifier_retry_or_chinese_realization() -> None:
    source = (
        __import__("pathlib")
        .Path(__file__)
        .resolve()
        .parents[1]
        .joinpath("src/knowledge_engine/m26_multilingual_verified_claim_spine.py")
        .read_text(encoding="utf-8")
    )

    for forbidden in ("Q01", "Q03", "Q04", "Q06", "Q08", "差別", "benchmark", "R3"):
        assert forbidden not in source
    assert "derive_semantic_requirements" not in source
    assert "_intent_class" not in source
    assert "_synthesize_and_verify" not in source
    assert "evaluate_visible_semantics" not in source
