from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

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
    citation_ids: list[str] | None = None,
    support_ref_count: int = 1,
    claim_type: str = "EVIDENCE_FACT",
    source_identities: list[str] | None = None,
) -> dict[str, Any]:
    if citation_ids is None:
        citation_ids = [f"{claim_id}_ref_1"]
    if source_identities is None:
        source_identities = ["source-router#section-router"]
    return {
        "claim_id": claim_id,
        "claim_role": "direct",
        "claim_type": claim_type,
        "surface_text": surface_text,
        "facet_ids": ["direct_answer"],
        "support_mode": "exact_quote",
        "support_ref_count": support_ref_count,
        "source_identities": source_identities,
        "citation_ids": citation_ids,
    }


def citation_free_model_explanation(
    *,
    claim_id: str = "claim-generic",
    surface_text: str = "This answer uses the selected evidence to explain the boundary.",
) -> dict[str, Any]:
    return verified_claim(
        claim_id=claim_id,
        surface_text=surface_text,
        citation_ids=[],
        support_ref_count=0,
        claim_type="MODEL_EXPLANATION",
        source_identities=[],
    )


def citation(
    *,
    citation_id: str = "claim-router_ref_1",
    claim_id: str = "claim-router",
    evidence_id: str = "ev-router",
    locator_id: str = "loc-router",
) -> dict[str, Any]:
    return {
        "citation_id": citation_id,
        "claim_id": claim_id,
        "claim_role": "direct",
        "evidence_id": evidence_id,
        "locator_id": locator_id,
        "source_id": "source-router",
        "source_identity": "source-router#section-router",
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
    assert claim.facet_ids == ("direct_answer",)
    assert claim.support_mode == "exact_quote"
    assert claim.support_ref_count == 1
    assert claim.source_identities == ("source-router#section-router",)
    assert claim.citation_ids == ("claim-router_ref_1",)
    assert claim.citations == (citation(),)
    assert claim.support_evidence_refs[0].citation_id == "claim-router_ref_1"
    assert claim.support_evidence_refs[0].evidence_id == "ev-router"
    assert claim.support_evidence_refs[0].locator_id == "loc-router"
    assert claim.publication_eligible is True
    assert result.spine.publication_eligible_claim_count == 1
    assert result.spine.semantic_review == closure_result()["semantic_review"]
    assert result.spine.closure["support_proof"] == closure_result()["support_proof"]


def test_cited_evidence_synthesis_claim_is_retained() -> None:
    synthesis_claim = verified_claim(
        claim_id="claim-synth",
        surface_text="The router and cache are both verified.",
        claim_type="EVIDENCE_SYNTHESIS",
        citation_ids=["claim-synth_ref_1"],
        support_ref_count=1,
    )

    result = project_verified_claim_spine(
        context=context(),
        verification=verified_answer(
            answer_claims=[synthesis_claim],
            citations=[citation(citation_id="claim-synth_ref_1", claim_id="claim-synth")],
        ),
        closure=closure_result(),
    )

    assert result.status == "verified_full"
    assert result.spine is not None
    assert [claim.claim_id for claim in result.spine.canonical_claims] == ["claim-synth"]
    assert result.spine.canonical_claims[0].claim_type == "EVIDENCE_SYNTHESIS"
    assert result.spine.publication_eligible_claim_count == 1


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
        citations=[
            citation(
                citation_id="claim-kept_ref_1",
                claim_id="claim-kept",
                evidence_id="ev-kept",
                locator_id="loc-kept",
            ),
            citation(
                citation_id="claim-dropped_ref_1",
                claim_id="claim-dropped",
                evidence_id="ev-dropped",
                locator_id="loc-dropped",
            ),
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
    assert result.spine.canonical_claims[0].citation_ids == ("claim-kept_ref_1",)
    assert result.spine.canonical_claims[0].support_evidence_refs[0].evidence_id == "ev-kept"
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
    claim.pop("citation_ids")

    result = project_verified_claim_spine(
        context=context(),
        verification=verified_answer(answer_claims=[claim], citations=[]),
        closure=closure_result(),
    )

    assert result.status == "failed"
    assert result.failure_code == "VERIFIED_CLAIM_SPINE_CITATION_MAPPING_MISSING"


def test_missing_citation_for_support_mapping_fails_closed() -> None:
    result = project_verified_claim_spine(
        context=context(),
        verification=verified_answer(citations=[]),
        closure=closure_result(),
    )

    assert result.status == "failed"
    assert result.failure_code == "VERIFIED_CLAIM_SPINE_CITATION_MAPPING_MISSING"


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


def test_claim_empty_citation_ids_with_support_count_fails_closed() -> None:
    claim = verified_claim(citation_ids=[], support_ref_count=1)

    result = project_verified_claim_spine(
        context=context(),
        verification=verified_answer(answer_claims=[claim]),
        closure=closure_result(),
    )

    assert result.status == "failed"
    assert result.failure_code == "VERIFIED_CLAIM_SPINE_CITATION_MAPPING_MISSING"


def test_uncited_evidence_fact_with_zero_support_count_fails_closed() -> None:
    claim = verified_claim(citation_ids=[], support_ref_count=0)

    result = project_verified_claim_spine(
        context=context(),
        verification=verified_answer(answer_claims=[claim], citations=[]),
        closure=closure_result(),
    )

    assert result.status == "failed"
    assert result.failure_code == "VERIFIED_CLAIM_SPINE_CITATION_MAPPING_MISSING"


def test_citation_free_model_explanation_is_conservatively_omitted() -> None:
    claim = citation_free_model_explanation()

    result = project_verified_claim_spine(
        context=context(),
        verification=verified_answer(answer_claims=[claim]),
        closure=closure_result(),
    )

    assert result.status == "abstained"
    assert result.spine is not None
    assert result.spine.canonical_claims == ()
    assert result.spine.publication_eligible_claim_count == 0
    assert result.spine.dropped_claim_ids == ("claim-generic",)
    assert result.spine.dropped_claim_count == 1
    assert (
        result.spine.telemetry["track2_citation_free_model_explanation_omitted_count"]
        == 1
    )
    assert result.spine.telemetry[
        "track2_citation_free_model_explanation_omitted_claim_ids"
    ] == ("claim-generic",)


def test_material_and_generic_claims_keep_material_and_drop_generic() -> None:
    kept = verified_claim(
        claim_id="claim-kept",
        surface_text="The router preserves API-42 state.",
        citation_ids=["claim-kept_ref_1"],
        support_ref_count=1,
    )
    dropped = citation_free_model_explanation(claim_id="claim-drop")

    result = project_verified_claim_spine(
        context=context(),
        verification=verified_answer(
            answer_claims=[kept, dropped],
            citations=[citation(citation_id="claim-kept_ref_1", claim_id="claim-kept")],
        ),
        closure=closure_result(),
    )

    assert result.status == "verified_partial"
    assert result.spine is not None
    assert [claim.claim_id for claim in result.spine.canonical_claims] == ["claim-kept"]
    assert result.spine.publication_eligible_claim_count == 1
    assert result.spine.dropped_claim_ids == ("claim-drop",)
    assert result.spine.dropped_claim_count == 1


def test_multiple_generic_model_explanations_abstain_without_failure() -> None:
    result = project_verified_claim_spine(
        context=context(),
        verification=verified_answer(
            answer_claims=[
                citation_free_model_explanation(claim_id="claim-a"),
                citation_free_model_explanation(claim_id="claim-b"),
            ],
            citations=[],
        ),
        closure=closure_result(),
    )

    assert result.status == "abstained"
    assert result.spine is not None
    assert result.spine.canonical_claims == ()
    assert result.spine.dropped_claim_ids == ("claim-a", "claim-b")
    assert result.spine.dropped_claim_count == 2


def test_existing_partial_drop_metadata_and_new_omission_are_merged() -> None:
    kept = verified_claim(
        claim_id="claim-kept",
        surface_text="The router preserves API-42 state.",
        citation_ids=["claim-kept_ref_1"],
        support_ref_count=1,
    )
    dropped = citation_free_model_explanation(claim_id="claim-omitted")
    verification = verified_answer(
        answer_claims=[kept, dropped],
        citations=[citation(citation_id="claim-kept_ref_1", claim_id="claim-kept")],
        multi_evidence_verification={
            "partial_answer": True,
            "dropped_claim_count": 1,
            "dropped_claim_ids": ["claim-existing-drop"],
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
    assert result.spine.dropped_claim_ids == ("claim-existing-drop", "claim-omitted")
    assert result.spine.dropped_claim_count == 2
    assert (
        result.spine.telemetry["track2_citation_free_model_explanation_omitted_claim_ids"]
        == ("claim-omitted",)
    )


@pytest.mark.parametrize(
    "claim",
    [
        verified_claim(
            claim_id="claim-bad-1",
            claim_type="MODEL_EXPLANATION",
            citation_ids=["claim-bad-1_ref_1"],
            support_ref_count=1,
            source_identities=[],
        ),
        verified_claim(
            claim_id="claim-bad-2",
            claim_type="MODEL_EXPLANATION",
            citation_ids=[],
            support_ref_count=1,
            source_identities=[],
        ),
        verified_claim(
            claim_id="claim-bad-3",
            claim_type="MODEL_EXPLANATION",
            citation_ids=[],
            support_ref_count=0,
            source_identities=["source-bad#section-bad"],
        ),
    ],
)
def test_model_explanation_with_support_or_owned_source_fails_closed(
    claim: dict[str, Any],
) -> None:
    result = project_verified_claim_spine(
        context=context(),
        verification=verified_answer(answer_claims=[claim]),
        closure=closure_result(),
    )

    assert result.status == "failed"
    assert result.failure_code in {
        "VERIFIED_CLAIM_SPINE_MODEL_EXPLANATION_SUPPORT_INVALID",
        "VERIFIED_CLAIM_SPINE_CITATION_MAPPING_MISSING",
    }


def test_claim_malformed_citation_ids_fails_closed() -> None:
    claim = verified_claim()
    claim["citation_ids"] = [{"citation_id": "claim-router_ref_1"}]

    result = project_verified_claim_spine(
        context=context(),
        verification=verified_answer(answer_claims=[claim]),
        closure=closure_result(),
    )

    assert result.status == "failed"
    assert result.failure_code == "VERIFIED_CLAIM_SPINE_CITATION_MAPPING_MISSING"


def test_claim_unknown_citation_id_fails_closed() -> None:
    claim = verified_claim(citation_ids=["unknown-citation"])

    result = project_verified_claim_spine(
        context=context(),
        verification=verified_answer(answer_claims=[claim]),
        closure=closure_result(),
    )

    assert result.status == "failed"
    assert result.failure_code == "VERIFIED_CLAIM_SPINE_CITATION_MAPPING_MISSING"


def test_claim_cannot_borrow_another_claims_citation() -> None:
    claim = verified_claim(citation_ids=["claim-other_ref_1"])

    result = project_verified_claim_spine(
        context=context(),
        verification=verified_answer(
            answer_claims=[claim],
            citations=[citation(citation_id="claim-other_ref_1", claim_id="claim-other")],
        ),
        closure=closure_result(),
    )

    assert result.status == "failed"
    assert result.failure_code == "VERIFIED_CLAIM_SPINE_CITATION_MAPPING_MISSING"


def test_duplicate_claim_citation_id_fails_closed() -> None:
    claim = verified_claim(
        citation_ids=["claim-router_ref_1", "claim-router_ref_1"],
        support_ref_count=2,
    )

    result = project_verified_claim_spine(
        context=context(),
        verification=verified_answer(answer_claims=[claim]),
        closure=closure_result(),
    )

    assert result.status == "failed"
    assert result.failure_code == "VERIFIED_CLAIM_SPINE_CITATION_MAPPING_MISSING"


def test_support_ref_count_mismatch_fails_closed() -> None:
    claim = verified_claim(support_ref_count=2)

    result = project_verified_claim_spine(
        context=context(),
        verification=verified_answer(answer_claims=[claim]),
        closure=closure_result(),
    )

    assert result.status == "failed"
    assert result.failure_code == "VERIFIED_CLAIM_SPINE_CITATION_MAPPING_MISSING"


def test_malformed_citation_item_fails_closed() -> None:
    result = project_verified_claim_spine(
        context=context(),
        verification=verified_answer(citations=["not-a-citation"]),
        closure=closure_result(),
    )

    assert result.status == "failed"
    assert result.failure_code == "VERIFIED_CLAIM_SPINE_VERIFICATION_SCHEMA_INVALID"


def test_citation_missing_citation_id_fails_closed() -> None:
    item = citation()
    item.pop("citation_id")

    result = project_verified_claim_spine(
        context=context(),
        verification=verified_answer(citations=[item]),
        closure=closure_result(),
    )

    assert result.status == "failed"
    assert result.failure_code == "VERIFIED_CLAIM_SPINE_CITATION_MAPPING_MISSING"


def test_citation_missing_claim_id_fails_closed() -> None:
    item = citation()
    item.pop("claim_id")

    result = project_verified_claim_spine(
        context=context(),
        verification=verified_answer(citations=[item]),
        closure=closure_result(),
    )

    assert result.status == "failed"
    assert result.failure_code == "VERIFIED_CLAIM_SPINE_CITATION_MAPPING_MISSING"


def test_citation_missing_evidence_id_fails_closed() -> None:
    item = citation()
    item.pop("evidence_id")

    result = project_verified_claim_spine(
        context=context(),
        verification=verified_answer(citations=[item]),
        closure=closure_result(),
    )

    assert result.status == "failed"
    assert result.failure_code == "VERIFIED_CLAIM_SPINE_CITATION_MAPPING_MISSING"


def test_citation_missing_locator_id_fails_closed() -> None:
    item = citation()
    item.pop("locator_id")

    result = project_verified_claim_spine(
        context=context(),
        verification=verified_answer(citations=[item]),
        closure=closure_result(),
    )

    assert result.status == "failed"
    assert result.failure_code == "VERIFIED_CLAIM_SPINE_CITATION_MAPPING_MISSING"


def test_two_claim_mapping_remains_claim_local() -> None:
    claim_a = verified_claim(
        claim_id="claim-a",
        surface_text="Claim A is verified.",
        citation_ids=["claim-a_ref_1"],
    )
    claim_b = verified_claim(
        claim_id="claim-b",
        surface_text="Claim B is verified.",
        citation_ids=["claim-b_ref_1"],
    )
    citation_a = citation(
        citation_id="claim-a_ref_1",
        claim_id="claim-a",
        evidence_id="ev-a",
        locator_id="loc-a",
    )
    citation_b = citation(
        citation_id="claim-b_ref_1",
        claim_id="claim-b",
        evidence_id="ev-b",
        locator_id="loc-b",
    )

    result = project_verified_claim_spine(
        context=context(),
        verification=verified_answer(
            answer_claims=[claim_a, claim_b],
            citations=[citation_a, citation_b],
        ),
        closure=closure_result(),
    )

    assert result.status == "verified_full"
    assert result.spine is not None
    [canonical_a, canonical_b] = result.spine.canonical_claims
    assert canonical_a.citations == (citation_a,)
    assert canonical_b.citations == (citation_b,)
    assert canonical_a.support_evidence_refs[0].evidence_id == "ev-a"
    assert canonical_b.support_evidence_refs[0].evidence_id == "ev-b"
    assert canonical_a.publication_eligible is True
    assert canonical_b.publication_eligible is True


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
