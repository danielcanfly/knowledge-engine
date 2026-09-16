from __future__ import annotations

import json
from typing import Any

import pytest

from knowledge_engine import m26_pa7_semantic_closure_runtime as runtime


def _requirement(facet_id: str = "durable_state") -> runtime.SemanticRequirement:
    return runtime.SemanticRequirement(
        requirement_id=facet_id,
        instruction="State the documented retention policy.",
        evidence_terms=("durable", "retains", "audit", "records"),
        visible_patterns=(),
    )


def _evidence(evidence_id: str = "ev_runtime") -> dict[str, Any]:
    passage_text = "Durable runtime retains audit records for controlled review."
    return {
        "evidence_id": evidence_id,
        "evidence_type": "passage",
        "passage_text": passage_text,
        "passage_text_sha256": runtime.canonical_sha256(passage_text),
        "title": "Runtime policy",
        "section_title": "Retention",
        "section_id": "retention",
        "concept_id": "runtime-policy",
        "source_id": "policy-source",
        "source_identity": "policy-source",
        "locator_id": "policy-locator",
        "release_id": "test-release",
        "artifact_key": "test/runtime-policy.json",
        "artifact_sha256": "artifact-sha",
        "provenance_record_sha256": "provenance-sha",
        "retrieved_at": "2026-01-01T00:00:00Z",
        "provenance": {"kind": "fixture"},
    }


def _supported_ledger() -> dict[str, Any]:
    requirement = _requirement()
    evidence = _evidence()
    classification = runtime._facet_support_classification(
        requirements=[requirement], evidence=[evidence]
    )
    return runtime._material_facet_ledger(
        requirements=[requirement],
        support_classification=classification,
        label_map={"e1": evidence},
    )


def _segment(**overrides: Any) -> dict[str, Any]:
    segment = {
        "segment_id": "s1",
        "semantic_role": "material_claim",
        "claim_id": "claim_1",
        "claim_type": "EVIDENCE_FACT",
        "text": "Durable runtime retains audit records.",
        "evidence_labels": ["e1"],
        "covers": ["durable_state"],
    }
    segment.update(overrides)
    return segment


def test_runtime_materializes_deterministic_facet_and_label_ledger() -> None:
    ledger = _supported_ledger()

    assert ledger == {
        "schema_version": runtime.MATERIAL_FACET_LEDGER_SCHEMA_VERSION,
        "facets": [
            {
                "facet_id": "durable_state",
                "instruction": "State the documented retention policy.",
                "support_state": "SUPPORTED",
                "allowed_evidence_labels": ["e1"],
                "allowed_evidence_ids": ["ev_runtime"],
                "runtime_source_ids": ["policy-source"],
            }
        ],
    }


def test_compact_claim_draft_rejects_runtime_owned_metadata() -> None:
    body = {
        "schema_version": runtime.COMPACT_CLOSURE_SCHEMA_VERSION,
        "status": "answer",
        "segments": [_segment(locator_id="provider-invented")],
        "unanswered_dimensions": [],
        "abstention_reason": None,
    }

    with pytest.raises(runtime.ClaimDraftContractError) as exc_info:
        runtime._parse_compact_provider_result(json.dumps(body))

    assert exc_info.value.code == runtime.CLAIM_DRAFT_RUNTIME_METADATA


@pytest.mark.parametrize(
    ("segment", "code"),
    [
        (_segment(covers=["invented_facet"]), runtime.CLAIM_DRAFT_UNKNOWN_FACET),
        (_segment(evidence_labels=["e99"]), runtime.CLAIM_DRAFT_UNKNOWN_LABEL),
        (_segment(evidence_labels=[]), runtime.CLAIM_DRAFT_LABEL_FACET_MISMATCH),
    ],
)
def test_claim_draft_identity_is_bounded_by_runtime_ledger(
    segment: dict[str, Any], code: str
) -> None:
    with pytest.raises(runtime.ClaimDraftContractError) as exc_info:
        runtime._validate_claim_draft_against_ledger(
            segments=[segment],
            provider_status="answer",
            unanswered_dimensions=[],
            facet_ledger=_supported_ledger(),
            label_map={"e1": _evidence()},
        )

    assert exc_info.value.code == code


def test_claim_draft_cannot_publish_runtime_unsupported_facet() -> None:
    ledger = {
        "schema_version": runtime.MATERIAL_FACET_LEDGER_SCHEMA_VERSION,
        "facets": [
            {
                "facet_id": "durable_state",
                "instruction": "State the documented retention policy.",
                "support_state": "UNSUPPORTED",
                "allowed_evidence_labels": [],
            }
        ],
    }

    with pytest.raises(runtime.ClaimDraftContractError) as exc_info:
        runtime._validate_claim_draft_against_ledger(
            segments=[_segment()],
            provider_status="answer",
            unanswered_dimensions=[],
            facet_ledger=ledger,
            label_map={"e1": _evidence()},
        )

    assert exc_info.value.code == runtime.CLAIM_DRAFT_UNSUPPORTED_FACET


def test_supported_facet_must_be_present_before_review() -> None:
    with pytest.raises(runtime.ClaimDraftContractError) as exc_info:
        runtime._validate_claim_draft_against_ledger(
            segments=[_segment(covers=[])],
            provider_status="answer",
            unanswered_dimensions=[],
            facet_ledger=_supported_ledger(),
            label_map={"e1": _evidence()},
        )

    assert exc_info.value.code == runtime.CLAIM_DRAFT_SUPPORTED_FACET_MISSING


def test_reviewed_renderer_uses_only_accepted_claim_text() -> None:
    rendered = runtime._render_reviewed_claim_text(
        candidate={
            "claims": [
                {"claim_id": "c1", "claim_type": "EVIDENCE_FACT", "surface_text": "A."},
                {"claim_id": "c2", "claim_type": "EVIDENCE_FACT", "surface_text": "B."},
            ]
        },
        semantic_review={
            "claim_judgments": [
                {"claim_id": "c1", "verdict": "ENTAILED"},
                {"claim_id": "c2", "verdict": "INSUFFICIENT"},
            ]
        },
    )

    assert rendered == "A."


class _AlwaysAbstainingProvider:
    def __init__(self) -> None:
        self.call_classes: list[str] = []

    def call(self, _payload: dict[str, Any], call_class: str) -> dict[str, Any]:
        self.call_classes.append(call_class)
        return {
            "text": json.dumps(
                {
                    "schema_version": runtime.FACET_LOCAL_CLAIM_SCHEMA_VERSION,
                    "claims": [],
                    "model_explanations": [],
                }
            ),
            "call_class": call_class,
            "usage": {},
        }


class _ScriptedClosureProvider:
    def __init__(self, *, review_verdicts: list[str], invalid_first: bool = False) -> None:
        self.review_verdicts = list(review_verdicts)
        self.invalid_first = invalid_first
        self.calls: list[str] = []
        self.synthesis_count = 0

    def call(self, payload: dict[str, Any], call_class: str) -> dict[str, Any]:
        self.calls.append(call_class)
        if call_class == runtime.SEMANTIC_REVIEW_CALL_CLASS:
            task = json.loads(payload["messages"][0]["content"])
            verdict = self.review_verdicts.pop(0)
            judgments = []
            for slot in task["review_slots"]:
                judgments.append(
                    {
                        "review_slot_id": str(slot["review_slot_id"]),
                        "verdict": verdict,
                    }
                )
            body = {
                "schema_version": runtime.RUNTIME_BOUND_REVIEW_SCHEMA_VERSION,
                "judgments": judgments,
            }
        else:
            task = json.loads(payload["messages"][0]["content"])
            slot_id = str(task["claim_slots"][0]["slot_id"])
            if self.invalid_first and self.synthesis_count == 0:
                slot_id = "slot_unknown"
            self.synthesis_count += 1
            body = {
                "schema_version": runtime.FACET_LOCAL_CLAIM_SCHEMA_VERSION,
                "claims": [
                    {
                        "slot_id": slot_id,
                        "text": "Durable runtime retains audit records.",
                        "claim_type": "EVIDENCE_FACT",
                    }
                ],
                "model_explanations": [],
            }
        return {"text": json.dumps(body), "usage": {}, "call_class": call_class}


class _ReviewContractRepairProvider:
    def __init__(
        self,
        *,
        review_mutations: list[str | None],
        repaired_verdict: str = "ENTAILED",
        malformed_synthesis_first: bool = False,
    ) -> None:
        self.review_mutations = list(review_mutations)
        self.repaired_verdict = repaired_verdict
        self.malformed_synthesis_first = malformed_synthesis_first
        self.calls: list[str] = []
        self.synthesis_tasks: list[dict[str, Any]] = []
        self.review_tasks: list[dict[str, Any]] = []

    def call(self, payload: dict[str, Any], call_class: str) -> dict[str, Any]:
        self.calls.append(call_class)
        task = json.loads(payload["messages"][0]["content"])
        if call_class != runtime.SEMANTIC_REVIEW_CALL_CLASS:
            self.synthesis_tasks.append(task)
            slot_id = str(task["claim_slots"][0]["slot_id"])
            if self.malformed_synthesis_first and len(self.synthesis_tasks) == 1:
                slot_id = "slot_unknown"
            body = {
                "schema_version": runtime.FACET_LOCAL_CLAIM_SCHEMA_VERSION,
                "claims": [
                    {
                        "slot_id": slot_id,
                        "text": "Durable runtime retains audit records.",
                        "claim_type": "EVIDENCE_FACT",
                    }
                ],
                "model_explanations": [],
            }
        else:
            self.review_tasks.append(task)
            mutation = (
                self.review_mutations.pop(0) if self.review_mutations else None
            )
            slot_id = str(task["review_slots"][0]["review_slot_id"])
            judgment = {
                "review_slot_id": slot_id,
                "verdict": self.repaired_verdict,
            }
            body = {
                "schema_version": runtime.RUNTIME_BOUND_REVIEW_SCHEMA_VERSION,
                "judgments": [judgment],
            }
            if mutation == "top_level":
                body["unexpected"] = True
            elif mutation == "unknown_slot":
                judgment["review_slot_id"] = "review_unknown"
            elif mutation == "duplicate_slot":
                body["judgments"].append(dict(judgment))
            elif mutation == "missing_slot":
                body["judgments"] = []
            elif mutation == "invalid_verdict":
                judgment["verdict"] = "SUPPORTED"
            elif mutation == "invalid_generic_explanation":
                judgment["verdict"] = "GENERIC_EXPLANATION"
        return {"text": json.dumps(body), "usage": {}, "call_class": call_class}


def test_false_provider_abstention_repairs_once_then_fails_closed() -> None:
    provider = _AlwaysAbstainingProvider()

    answer, closure = runtime._synthesize_and_verify(
        question="Describe the runtime retention behavior.",
        trace_id="trace-wave-b-contract",
        intent_class="direct_grounded_knowledge",
        evidence=[_evidence()],
        provider_client=provider,
        requirements=[_requirement()],
        endpoint_proof={"schema_version": "test"},
    )

    assert answer["safe_abstention"] is True
    assert provider.call_classes == ["aq_semantic_closure", "aq_semantic_closure_repair"]
    assert runtime.FACET_LOCAL_SLOT_MISSING in closure["failures"]
    assert answer["provider_call_count"] == 2


def test_supported_facet_declared_unresolved_is_finite_contract_failure() -> None:
    with pytest.raises(runtime.ClaimDraftContractError) as exc_info:
        runtime._validate_claim_draft_against_ledger(
            segments=[_segment()],
            provider_status="partial",
            unanswered_dimensions=["durable_state"],
            facet_ledger=_supported_ledger(),
            label_map={"e1": _evidence()},
        )

    assert exc_info.value.code == runtime.PROVIDER_UNRESOLVED_SUPPORTED_FACET


def test_review_rejection_consumes_one_repair_and_repair_review_can_pass() -> None:
    provider = _ScriptedClosureProvider(review_verdicts=["INSUFFICIENT", "ENTAILED"])

    answer, closure = runtime._synthesize_and_verify(
        question="Describe the runtime retention behavior.",
        trace_id="trace-wave-b-review-repair",
        intent_class="direct_grounded_knowledge",
        evidence=[_evidence()],
        provider_client=provider,
        requirements=[_requirement()],
        endpoint_proof={"schema_version": "test"},
    )

    assert provider.calls == [
        "aq_semantic_closure",
        runtime.SEMANTIC_REVIEW_CALL_CLASS,
        "aq_semantic_closure_repair",
        runtime.SEMANTIC_REVIEW_CALL_CLASS,
    ]
    assert answer["safe_abstention"] is False
    assert answer["repair_attempted"] is True
    assert closure["failures"] == []
    assert any(
        code.startswith("SEMANTIC_REVIEW_BLOCKED:")
        for code in answer["multi_evidence_verification"][
            "verification_failure_codes_by_attempt"
        ]
    )
    assert answer["repair_kind"] == runtime.REPAIR_KIND_SEMANTIC_VERDICT
    assert answer["repair_succeeded"] is True


def test_repeated_review_rejection_fails_closed_after_one_repair() -> None:
    provider = _ScriptedClosureProvider(review_verdicts=["INSUFFICIENT", "INSUFFICIENT"])

    answer, closure = runtime._synthesize_and_verify(
        question="Describe the runtime retention behavior.",
        trace_id="trace-wave-b-review-repeat",
        intent_class="direct_grounded_knowledge",
        evidence=[_evidence()],
        provider_client=provider,
        requirements=[_requirement()],
        endpoint_proof={"schema_version": "test"},
    )

    assert answer["safe_abstention"] is True
    assert provider.calls == [
        "aq_semantic_closure",
        runtime.SEMANTIC_REVIEW_CALL_CLASS,
        "aq_semantic_closure_repair",
        runtime.SEMANTIC_REVIEW_CALL_CLASS,
    ]
    assert answer["provider_call_count"] == 4
    assert any(code.startswith("SEMANTIC_REVIEW_BLOCKED:") for code in closure["failures"])
    assert answer["repair_kind"] == runtime.REPAIR_KIND_SEMANTIC_VERDICT


def test_structure_and_review_share_one_total_repair_budget() -> None:
    provider = _ScriptedClosureProvider(
        review_verdicts=["INSUFFICIENT"],
        invalid_first=True,
    )

    answer, closure = runtime._synthesize_and_verify(
        question="Describe the runtime retention behavior.",
        trace_id="trace-wave-b-shared-budget",
        intent_class="direct_grounded_knowledge",
        evidence=[_evidence()],
        provider_client=provider,
        requirements=[_requirement()],
        endpoint_proof={"schema_version": "test"},
    )

    assert answer["safe_abstention"] is True
    assert provider.calls == [
        "aq_semantic_closure",
        "aq_semantic_closure_repair",
        runtime.SEMANTIC_REVIEW_CALL_CLASS,
    ]
    assert answer["provider_call_count"] == 3
    assert runtime.FACET_LOCAL_SLOT_UNKNOWN in closure["failures"]
    assert answer["repair_kind"] == runtime.REPAIR_KIND_SYNTHESIS_CONTRACT


@pytest.mark.parametrize(
    "mutation",
    [
        "top_level",
        "unknown_slot",
        "duplicate_slot",
        "missing_slot",
        "invalid_verdict",
        "invalid_generic_explanation",
    ],
)
def test_native_review_contract_failure_repairs_reviewer_only(
    mutation: str,
) -> None:
    provider = _ReviewContractRepairProvider(review_mutations=[mutation, None])

    answer, closure = runtime._synthesize_and_verify(
        question="Describe the runtime retention behavior.",
        trace_id=f"trace-wave-b-review-contract-{mutation}",
        intent_class="direct_grounded_knowledge",
        evidence=[_evidence()],
        provider_client=provider,
        requirements=[_requirement()],
        endpoint_proof={"schema_version": "test"},
    )

    assert provider.calls == [
        "aq_semantic_closure",
        runtime.SEMANTIC_REVIEW_CALL_CLASS,
        runtime.SEMANTIC_REVIEW_CALL_CLASS,
    ]
    assert len(provider.synthesis_tasks) == 1
    assert answer["safe_abstention"] is False
    assert answer["provider_call_count"] == 3
    assert answer["repair_attempted"] is True
    assert answer["repair_kind"] == runtime.REPAIR_KIND_REVIEW_CONTRACT
    assert answer["repair_succeeded"] is True
    assert answer["repair_exhausted"] is False
    assert closure["failures"] == []
    assert runtime.FACET_LOCAL_SLOT_MALFORMED not in json.dumps(closure)


def test_review_contract_repair_reuses_immutable_slots_and_bounded_output() -> None:
    provider = _ReviewContractRepairProvider(
        review_mutations=["top_level", None]
    )

    runtime._synthesize_and_verify(
        question="Describe the runtime retention behavior.",
        trace_id="trace-wave-b-review-contract-payload",
        intent_class="direct_grounded_knowledge",
        evidence=[_evidence()],
        provider_client=provider,
        requirements=[_requirement()],
        endpoint_proof={"schema_version": "test"},
    )

    initial, repaired = provider.review_tasks
    assert repaired["question_context"] == initial["question_context"]
    assert repaired["review_slots"] == initial["review_slots"]
    contract = repaired["review_contract_repair"]
    assert contract["required_review_slot_ids"] == ["review_1"]
    assert contract["required_top_level_keys"] == ["schema_version", "judgments"]
    assert contract["required_judgment_keys"] == ["review_slot_id", "verdict"]
    assert contract["allowed_verdicts"] == [
        "ENTAILED",
        "CONTRADICTED",
        "INSUFFICIENT",
        "GENERIC_EXPLANATION",
    ]
    assert contract["candidate_claim_prose_must_remain_unchanged"] is True
    assert {"claim_id", "evidence_id", "citations", "publication_state"}.issubset(
        contract["forbidden_output_fields"]
    )


def test_repeated_review_contract_failure_fails_closed_without_synthesis_repair() -> None:
    provider = _ReviewContractRepairProvider(
        review_mutations=["top_level", "top_level"]
    )

    answer, closure = runtime._synthesize_and_verify(
        question="Describe the runtime retention behavior.",
        trace_id="trace-wave-b-review-contract-repeat",
        intent_class="direct_grounded_knowledge",
        evidence=[_evidence()],
        provider_client=provider,
        requirements=[_requirement()],
        endpoint_proof={"schema_version": "test"},
    )

    assert provider.calls == [
        "aq_semantic_closure",
        runtime.SEMANTIC_REVIEW_CALL_CLASS,
        runtime.SEMANTIC_REVIEW_CALL_CLASS,
    ]
    assert answer["safe_abstention"] is True
    assert answer["provider_call_count"] == 3
    assert answer["repair_kind"] == runtime.REPAIR_KIND_REVIEW_CONTRACT
    assert answer["repair_succeeded"] is False
    assert answer["repair_exhausted"] is True
    assert runtime.FACET_LOCAL_SLOT_MALFORMED not in closure["failures"]
    assert any("NATIVE_SEMANTIC_REVIEW_BINDING" in code for code in closure["failures"])


@pytest.mark.parametrize("verdict", ["INSUFFICIENT", "CONTRADICTED"])
def test_repaired_review_blocking_verdict_cannot_trigger_second_repair(
    verdict: str,
) -> None:
    provider = _ReviewContractRepairProvider(
        review_mutations=["top_level", None], repaired_verdict=verdict
    )

    answer, closure = runtime._synthesize_and_verify(
        question="Describe the runtime retention behavior.",
        trace_id=f"trace-wave-b-review-contract-{verdict.lower()}",
        intent_class="direct_grounded_knowledge",
        evidence=[_evidence()],
        provider_client=provider,
        requirements=[_requirement()],
        endpoint_proof={"schema_version": "test"},
    )

    assert provider.calls == [
        "aq_semantic_closure",
        runtime.SEMANTIC_REVIEW_CALL_CLASS,
        runtime.SEMANTIC_REVIEW_CALL_CLASS,
    ]
    assert answer["safe_abstention"] is True
    assert answer["repair_kind"] == runtime.REPAIR_KIND_REVIEW_CONTRACT
    assert any(
        code.endswith(f":{verdict}") for code in closure["failures"]
    )


def test_synthesis_repair_leaves_no_budget_for_review_contract_repair() -> None:
    provider = _ReviewContractRepairProvider(
        review_mutations=["top_level"], malformed_synthesis_first=True
    )

    answer, closure = runtime._synthesize_and_verify(
        question="Describe the runtime retention behavior.",
        trace_id="trace-wave-b-synthesis-then-review-contract",
        intent_class="direct_grounded_knowledge",
        evidence=[_evidence()],
        provider_client=provider,
        requirements=[_requirement()],
        endpoint_proof={"schema_version": "test"},
    )

    assert provider.calls == [
        "aq_semantic_closure",
        "aq_semantic_closure_repair",
        runtime.SEMANTIC_REVIEW_CALL_CLASS,
    ]
    assert answer["safe_abstention"] is True
    assert answer["provider_call_count"] == 3
    assert answer["repair_kind"] == runtime.REPAIR_KIND_SYNTHESIS_CONTRACT
    assert answer["repair_succeeded"] is True
    assert answer["repair_exhausted"] is True
    assert runtime.FACET_LOCAL_SLOT_UNKNOWN in closure["failures"]
    assert runtime.FACET_LOCAL_SLOT_MALFORMED not in closure["failures"]


def test_final_renderer_has_no_prose_call_and_keeps_runtime_identity() -> None:
    evidence = _evidence()
    candidate = runtime._runtime_bound_candidate(
        answer="Durable runtime retains audit records.",
        question="Describe the runtime retention behavior.",
        intent_class="direct_grounded_knowledge",
        used_items=(),
        claims=None,
        segments=[_segment()],
        label_map={"e1": evidence},
        snippet_map={"ev_runtime": evidence["passage_text"]},
        requirements=[_requirement()],
    )
    rendered = runtime._render_reviewed_claim_text(
        candidate=candidate,
        semantic_review={
            "claim_judgments": [{"claim_id": "claim_1", "verdict": "ENTAILED"}]
        },
    )

    assert rendered == "Durable runtime retains audit records."
    assert candidate["claims"][0]["support_refs"][0]["evidence_id"] == "ev_runtime"
    assert candidate["claims"][0]["support_refs"][0]["locator_id"] == "policy-locator"


def _pack_requirement(facet_id: str) -> runtime.SemanticRequirement:
    return runtime.SemanticRequirement(
        requirement_id=facet_id,
        instruction=f"Cover {facet_id}.",
        evidence_terms=(facet_id,),
        visible_patterns=(),
    )


def _pack_evidence(evidence_id: str) -> dict[str, Any]:
    item = _evidence(evidence_id)
    item["passage_text"] = f"Evidence for {evidence_id}."
    return item


def _pack_classification(*pairs: tuple[str, list[str]]) -> list[dict[str, Any]]:
    return [
        {
            "facet_id": facet_id,
            "support_state": "SUPPORTED",
            "supporting_evidence_ids": evidence_ids,
        }
        for facet_id, evidence_ids in pairs
    ]


def test_supported_facet_outside_global_top_six_is_force_packed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = [_pack_evidence(f"ev_{index}") for index in range(1, 8)]
    requirement = _pack_requirement("facet_a")
    classification = _pack_classification(("facet_a", ["ev_7"]))
    monkeypatch.setattr(
        runtime,
        "_provider_evidence_order",
        lambda items, _requirements, _question: list(items),
    )

    packed = runtime._facet_preserving_provider_evidence_pack(
        evidence=evidence,
        supported_requirements=[requirement],
        support_classification=classification,
        question="question",
    )

    assert [item["evidence_id"] for item in packed] == [
        "ev_7",
        "ev_1",
        "ev_2",
        "ev_3",
        "ev_4",
        "ev_5",
    ]
    assert len(packed) == runtime.MAX_PROVIDER_EVIDENCE


def test_each_supported_facet_receives_an_authorized_label() -> None:
    requirements = [_pack_requirement(f"facet_{index}") for index in range(1, 4)]
    evidence = [_pack_evidence(f"ev_{index}") for index in range(1, 4)]
    classification = _pack_classification(
        ("facet_1", ["ev_1"]),
        ("facet_2", ["ev_2"]),
        ("facet_3", ["ev_3"]),
    )
    packed = runtime._facet_preserving_provider_evidence_pack(
        evidence=evidence,
        supported_requirements=requirements,
        support_classification=classification,
        question="question",
    )
    label_map = {f"e{index}": item for index, item in enumerate(packed, start=1)}
    ledger = runtime._material_facet_ledger(
        requirements=requirements,
        support_classification=classification,
        label_map=label_map,
    )

    runtime._assert_supported_facets_representable(
        support_classification=classification,
        facet_ledger=ledger,
    )
    assert all(
        facet["allowed_evidence_ids"] and facet["allowed_evidence_labels"]
        for facet in ledger["facets"]
    )


def test_shared_evidence_satisfies_multiple_facets_without_duplication() -> None:
    evidence = [_pack_evidence("ev_shared"), _pack_evidence("ev_other")]
    requirements = [_pack_requirement("facet_a"), _pack_requirement("facet_b")]
    classification = _pack_classification(
        ("facet_a", ["ev_shared"]),
        ("facet_b", ["ev_shared"]),
    )

    packed = runtime._facet_preserving_provider_evidence_pack(
        evidence=evidence,
        supported_requirements=requirements,
        support_classification=classification,
        question="question",
    )

    assert [item["evidence_id"] for item in packed] == ["ev_shared", "ev_other"]


def test_facet_pack_order_is_deterministic_and_fills_remaining_global_slots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = [_pack_evidence(f"ev_{index}") for index in range(1, 6)]
    requirement = _pack_requirement("facet_a")
    classification = _pack_classification(("facet_a", ["ev_3"]))
    monkeypatch.setattr(
        runtime,
        "_provider_evidence_order",
        lambda items, _requirements, _question: list(items),
    )

    first = runtime._facet_preserving_provider_evidence_pack(
        evidence=evidence,
        supported_requirements=[requirement],
        support_classification=classification,
        question="question",
    )
    second = runtime._facet_preserving_provider_evidence_pack(
        evidence=evidence,
        supported_requirements=[requirement],
        support_classification=classification,
        question="question",
    )

    assert [item["evidence_id"] for item in first] == [
        "ev_3",
        "ev_1",
        "ev_2",
        "ev_4",
        "ev_5",
    ]
    assert [item["evidence_id"] for item in first] == [
        item["evidence_id"] for item in second
    ]
    assert len(first) <= runtime.MAX_PROVIDER_EVIDENCE


def test_capacity_failure_happens_before_provider_pack_can_be_called() -> None:
    requirements = [_pack_requirement(f"facet_{index}") for index in range(1, 8)]
    evidence = [_pack_evidence(f"ev_{index}") for index in range(1, 8)]
    classification = _pack_classification(
        *[(f"facet_{index}", [f"ev_{index}"]) for index in range(1, 8)]
    )

    with pytest.raises(runtime.ClaimDraftContractError) as exc_info:
        runtime._facet_preserving_provider_evidence_pack(
            evidence=evidence,
            supported_requirements=requirements,
            support_classification=classification,
            question="question",
        )

    assert exc_info.value.code == runtime.PROVIDER_EVIDENCE_PACK_UNREPRESENTABLE


def test_force_packed_label_is_accepted_for_its_supported_facet() -> None:
    requirement = _pack_requirement("facet_a")
    evidence = _pack_evidence("ev_a")
    classification = _pack_classification(("facet_a", ["ev_a"]))
    ledger = runtime._material_facet_ledger(
        requirements=[requirement],
        support_classification=classification,
        label_map={"e1": evidence},
    )

    runtime._validate_claim_draft_against_ledger(
        segments=[_segment(evidence_labels=["e1"], covers=["facet_a"])],
        provider_status="answer",
        unanswered_dimensions=[],
        facet_ledger=ledger,
        label_map={"e1": evidence},
    )


def _facet_local_slots(
    *facet_ids: str,
) -> tuple[
    list[dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, str],
]:
    requirements = [_pack_requirement(facet_id) for facet_id in facet_ids]
    evidence = [_pack_evidence(f"ev_{index}") for index in range(1, len(facet_ids) + 1)]
    classification = _pack_classification(
        *[
            (facet_id, [f"ev_{index}"])
            for index, facet_id in enumerate(facet_ids, start=1)
        ]
    )
    label_map = {
        f"e{index}": item for index, item in enumerate(evidence, start=1)
    }
    ledger = runtime._material_facet_ledger(
        requirements=requirements,
        support_classification=classification,
        label_map=label_map,
    )
    snippet_map = {
        str(item["evidence_id"]): str(item["passage_text"]) for item in evidence
    }
    slots = runtime._facet_local_provider_slots(
        requirements=requirements,
        facet_ledger=ledger,
        label_map=label_map,
        snippet_map=snippet_map,
    )
    return slots, label_map, snippet_map


def _slot_result(*slot_ids: str) -> str:
    return json.dumps(
        {
            "schema_version": runtime.FACET_LOCAL_CLAIM_SCHEMA_VERSION,
            "claims": [
                {
                    "slot_id": slot_id,
                    "text": f"Evidence-backed prose for {slot_id}.",
                    "claim_type": "EVIDENCE_FACT",
                }
                for slot_id in slot_ids
            ],
            "model_explanations": [],
        }
    )


def test_facet_local_slots_are_deterministic_and_runtime_owned() -> None:
    slots, _label_map, _snippet_map = _facet_local_slots("facet_a", "facet_b")

    assert [(slot["slot_id"], slot["facet_id"]) for slot in slots] == [
        ("slot_1", "facet_a"),
        ("slot_2", "facet_b"),
    ]
    assert slots[0]["allowed_evidence_ids"] == ["ev_1"]
    assert slots[0]["allowed_evidence_labels"] == ["e1"]
    assert slots[1]["allowed_evidence_ids"] == ["ev_2"]


@pytest.mark.parametrize(
    ("text", "code"),
    [
        (_slot_result("slot_unknown"), runtime.FACET_LOCAL_SLOT_UNKNOWN),
        (_slot_result("slot_1", "slot_1"), runtime.FACET_LOCAL_SLOT_DUPLICATE),
        (_slot_result("slot_1"), runtime.FACET_LOCAL_SLOT_MISSING),
    ],
)
def test_facet_local_slot_identity_is_strict(text: str, code: str) -> None:
    slots, _label_map, _snippet_map = _facet_local_slots("facet_a", "facet_b")

    with pytest.raises(runtime.ClaimDraftContractError) as exc_info:
        runtime._parse_facet_local_provider_result(text, slots=slots)

    assert exc_info.value.code == code


@pytest.mark.parametrize(
    "injected_key",
    [
        "evidence_labels",
        "evidence_ids",
        "source_id",
        "citation",
        "facet_id",
        "covers",
        "unanswered_dimensions",
        "status",
    ],
)
def test_facet_local_provider_cannot_inject_runtime_metadata(
    injected_key: str,
) -> None:
    slots, _label_map, _snippet_map = _facet_local_slots("facet_a")
    body = json.loads(_slot_result("slot_1"))
    body["claims"][0][injected_key] = []

    with pytest.raises(runtime.ClaimDraftContractError) as exc_info:
        runtime._parse_facet_local_provider_result(json.dumps(body), slots=slots)

    assert exc_info.value.code == runtime.FACET_LOCAL_SLOT_MALFORMED


def test_runtime_binds_slot_to_all_prebound_local_evidence() -> None:
    requirement = _pack_requirement("facet_a")
    first = _pack_evidence("ev_1")
    second = _pack_evidence("ev_2")
    label_map = {"e1": first, "e2": second}
    classification = _pack_classification(("facet_a", ["ev_1", "ev_2"]))
    ledger = runtime._material_facet_ledger(
        requirements=[requirement],
        support_classification=classification,
        label_map=label_map,
    )
    snippets = {"ev_1": first["passage_text"], "ev_2": second["passage_text"]}
    slots = runtime._facet_local_provider_slots(
        requirements=[requirement],
        facet_ledger=ledger,
        label_map=label_map,
        snippet_map=snippets,
    )
    drafts = runtime._parse_facet_local_provider_result(
        _slot_result("slot_1"), slots=slots
    )

    candidate = runtime._runtime_bound_facet_local_candidate(
        drafts=drafts,
        slots=slots,
        label_map=label_map,
        snippet_map=snippets,
        question="question",
        intent_class="direct_grounded_knowledge",
        unresolved_required_ids=[],
    )

    claim = candidate["claims"][0]
    assert claim["facet_ids"] == ["facet_a"]
    assert claim["covers"] == ["facet_a"]
    assert claim["evidence_labels"] == ["e1", "e2"]
    assert [ref["evidence_id"] for ref in claim["support_refs"]] == [
        "ev_1",
        "ev_2",
    ]


def test_unsupported_runtime_facet_gets_no_provider_slot() -> None:
    requirement = _pack_requirement("facet_a")
    ledger = {
        "schema_version": runtime.MATERIAL_FACET_LEDGER_SCHEMA_VERSION,
        "facets": [
            {
                "facet_id": "facet_a",
                "instruction": requirement.instruction,
                "support_state": "UNSUPPORTED",
                "allowed_evidence_ids": [],
                "allowed_evidence_labels": [],
            }
        ],
    }

    assert runtime._facet_local_provider_slots(
        requirements=[requirement],
        facet_ledger=ledger,
        label_map={},
        snippet_map={},
    ) == []


def test_model_explanation_cannot_replace_a_supported_slot() -> None:
    slots, _label_map, _snippet_map = _facet_local_slots("facet_a")
    body = {
        "schema_version": runtime.FACET_LOCAL_CLAIM_SCHEMA_VERSION,
        "claims": [],
        "model_explanations": ["Generic connective prose."],
    }

    with pytest.raises(runtime.ClaimDraftContractError) as exc_info:
        runtime._parse_facet_local_provider_result(json.dumps(body), slots=slots)

    assert exc_info.value.code == runtime.FACET_LOCAL_SLOT_MISSING


class _NoMaterialProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.tasks: list[dict[str, Any]] = []

    def call(self, payload: dict[str, Any], call_class: str) -> dict[str, Any]:
        self.calls.append(call_class)
        task = json.loads(payload["messages"][0]["content"])
        self.tasks.append(task)
        if call_class == runtime.SEMANTIC_REVIEW_CALL_CLASS:
            body = {
                "schema_version": runtime.RUNTIME_BOUND_REVIEW_SCHEMA_VERSION,
                "judgments": [
                    {
                        "review_slot_id": slot["review_slot_id"],
                        "verdict": "ENTAILED",
                    }
                    for slot in task["review_slots"]
                ],
            }
        else:
            body = {
                "schema_version": runtime.FACET_LOCAL_CLAIM_SCHEMA_VERSION,
                "claims": [
                    {
                        "slot_id": slot["slot_id"],
                        "text": "Durable runtime retains audit records.",
                        "claim_type": "EVIDENCE_FACT",
                    }
                    for slot in task["claim_slots"]
                ],
                "model_explanations": [],
            }
        return {
            "text": json.dumps(body),
            "call_class": call_class,
            "usage": {},
        }


def test_no_material_facet_uses_runtime_bound_native_slot() -> None:
    provider = _NoMaterialProvider()

    answer, closure = runtime._synthesize_and_verify(
        question="Describe the runtime.",
        trace_id="trace-no-material-facet",
        intent_class="direct_grounded_knowledge",
        evidence=[_evidence()],
        provider_client=provider,
        requirements=[],
        endpoint_proof={"schema_version": "test"},
    )

    assert answer["safe_abstention"] is False
    assert provider.calls == ["aq_semantic_closure", runtime.SEMANTIC_REVIEW_CALL_CLASS]
    assert closure["provider_contract"] == "no_material_runtime_bound_semantic_closure/v1"
    assert closure["no_material_answer_slot"] is True
    assert provider.tasks[0]["claim_slots"][0]["evidence"]


def _native_candidate(*, explanation: bool = False) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    slots, label_map, snippets = _facet_local_slots("facet_a")
    drafts = {
        "claims": [
            {
                "slot_id": "slot_1",
                "text": "Evidence-backed prose for slot_1.",
                "claim_type": "EVIDENCE_FACT",
            }
        ],
        "model_explanations": ["Generally useful connective prose."] if explanation else [],
    }
    candidate = runtime._runtime_bound_facet_local_candidate(
        drafts=drafts,
        slots=slots,
        label_map=label_map,
        snippet_map=snippets,
        question="question",
        intent_class="direct_grounded_knowledge",
        unresolved_required_ids=[],
    )
    return candidate, slots


def test_native_review_payload_exposes_only_runtime_review_slot_output() -> None:
    candidate, _slots = _native_candidate()
    payload, review_slots = runtime._runtime_bound_semantic_review_payload(
        question="question",
        intent_class="direct_grounded_knowledge",
        candidate=candidate,
        evidence=[_pack_evidence("ev_1")],
    )
    task = json.loads(payload["messages"][0]["content"])

    assert set(task["output"]) == {"schema_version", "judgments"}
    assert set(task["output"]["judgments"][0]) == {"review_slot_id", "verdict"}
    assert set(task["review_slots"][0]) == {
        "review_slot_id",
        "claim_type",
        "surface_text",
        "local_evidence",
    }
    assert review_slots[0]["claim_id"] == "slot_1_claim"
    assert review_slots[0]["allowed_evidence_ids"] == ["ev_1"]


@pytest.mark.parametrize("mutation", ["unknown", "duplicate", "missing"])
def test_native_review_slots_require_exact_one_to_one_coverage(mutation: str) -> None:
    candidate, _slots = _native_candidate()
    review_slots = runtime._runtime_review_slots(
        candidate=candidate, evidence=[_pack_evidence("ev_1")]
    )
    judgments = [{"review_slot_id": "review_1", "verdict": "ENTAILED"}]
    if mutation == "unknown":
        judgments[0]["review_slot_id"] = "review_unknown"
    elif mutation == "duplicate":
        judgments.append(dict(judgments[0]))
    else:
        judgments = []

    with pytest.raises(ValueError):
        runtime._normalize_runtime_bound_semantic_review(
            {
                "schema_version": runtime.RUNTIME_BOUND_REVIEW_SCHEMA_VERSION,
                "judgments": judgments,
            },
            review_slots=review_slots,
            candidate=candidate,
        )


def test_native_entailed_review_maps_runtime_claim_and_evidence_identity() -> None:
    candidate, _slots = _native_candidate()
    review_slots = runtime._runtime_review_slots(
        candidate=candidate, evidence=[_pack_evidence("ev_1")]
    )

    review = runtime._normalize_runtime_bound_semantic_review(
        {
            "schema_version": runtime.RUNTIME_BOUND_REVIEW_SCHEMA_VERSION,
            "judgments": [{"review_slot_id": "review_1", "verdict": "ENTAILED"}],
        },
        review_slots=review_slots,
        candidate=candidate,
    )

    assert review["claim_judgments"] == [
        {"claim_id": "slot_1_claim", "verdict": "ENTAILED", "evidence_ids": ["ev_1"]}
    ]
    assert not runtime._semantic_review_has_out_of_local_evidence(
        review, runtime._candidate_claim_by_id(candidate)
    )


@pytest.mark.parametrize("verdict", ["INSUFFICIENT", "CONTRADICTED"])
def test_native_blocking_verdicts_remain_blocking(verdict: str) -> None:
    candidate, _slots = _native_candidate()
    slots = runtime._runtime_review_slots(
        candidate=candidate, evidence=[_pack_evidence("ev_1")]
    )
    review = runtime._normalize_runtime_bound_semantic_review(
        {
            "schema_version": runtime.RUNTIME_BOUND_REVIEW_SCHEMA_VERSION,
            "judgments": [{"review_slot_id": "review_1", "verdict": verdict}],
        },
        review_slots=slots,
        candidate=candidate,
    )

    assert runtime._semantic_review_blocking_failures(review) == [
        f"SEMANTIC_REVIEW_BLOCKED:slot_1_claim:{verdict}"
    ]


def test_generic_explanation_verdict_is_limited_to_model_explanation() -> None:
    candidate, _slots = _native_candidate()
    slots = runtime._runtime_review_slots(
        candidate=candidate, evidence=[_pack_evidence("ev_1")]
    )
    with pytest.raises(ValueError):
        runtime._normalize_runtime_bound_semantic_review(
            {
                "schema_version": runtime.RUNTIME_BOUND_REVIEW_SCHEMA_VERSION,
                "judgments": [
                    {"review_slot_id": "review_1", "verdict": "GENERIC_EXPLANATION"}
                ],
            },
            review_slots=slots,
            candidate=candidate,
        )


def test_native_visible_coverage_requires_exact_renderer_invariant() -> None:
    candidate, _slots = _native_candidate()
    candidate["answer_text"] += " unstructured provider prose"
    slots = runtime._runtime_review_slots(
        candidate=candidate, evidence=[_pack_evidence("ev_1")]
    )
    with pytest.raises(ValueError, match="renderer invariant"):
        runtime._normalize_runtime_bound_semantic_review(
            {
                "schema_version": runtime.RUNTIME_BOUND_REVIEW_SCHEMA_VERSION,
                "judgments": [{"review_slot_id": "review_1", "verdict": "ENTAILED"}],
            },
            review_slots=slots,
            candidate=candidate,
        )


@pytest.mark.parametrize(
    ("verdict", "expected"),
    [
        ("INSUFFICIENT", "narrow to one atomic proposition"),
        ("CONTRADICTED", "correct polarity, direction, identity"),
    ],
)
def test_dynamic_review_failure_generates_slot_local_repair_directive(
    verdict: str, expected: str
) -> None:
    directives = runtime._bounded_repair_directives(
        [f"SEMANTIC_REVIEW_BLOCKED:slot_1_claim:{verdict}"],
        claim_slot_by_claim_id={"slot_1_claim": "slot_1"},
        only_slot_id="slot_1",
    )

    assert len(directives) == 1
    assert "runtime slot slot_1" in directives[0]
    assert expected in directives[0]


def test_repair_payload_repeats_real_slots_and_forbids_legacy_shape() -> None:
    requirement = _pack_requirement("facet_a")
    evidence = _pack_evidence("ev_1")
    payload, _ledger, _labels, _snippets, slots = runtime._facet_local_provider_payload(
        question="question",
        intent_class="direct_grounded_knowledge",
        evidence=[evidence],
        requirements=[requirement],
        support_classification=_pack_classification(("facet_a", ["ev_1"])),
        repair=True,
        previous_failures=["SEMANTIC_REVIEW_BLOCKED:slot_1_claim:INSUFFICIENT"],
    )
    task = json.loads(payload["messages"][0]["content"])

    assert task["required_slot_ids"] == ["slot_1"]
    assert task["facet_local_output"]["claims"][0]["slot_id"] == "slot_1"
    assert task["claim_slots"][0]["repair_directives"]
    with pytest.raises(runtime.ClaimDraftContractError) as exc_info:
        runtime._parse_facet_local_provider_result(
            json.dumps(
                {
                    "schema_version": runtime.COMPACT_CLOSURE_SCHEMA_VERSION,
                    "status": "answer",
                    "segments": [],
                }
            ),
            slots=slots,
            allow_legacy_compatibility=False,
        )
    assert exc_info.value.code == runtime.FACET_LOCAL_SLOT_MALFORMED


class _NoMaterialAbstainingProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def call(self, _payload: dict[str, Any], call_class: str) -> dict[str, Any]:
        self.calls.append(call_class)
        return {
            "text": json.dumps(
                {
                    "schema_version": runtime.COMPACT_CLOSURE_SCHEMA_VERSION,
                    "status": "abstain",
                    "segments": [],
                }
            ),
            "call_class": call_class,
            "usage": {},
        }


def test_no_material_provider_abstention_is_bounded_contract_failure() -> None:
    provider = _NoMaterialAbstainingProvider()
    answer, closure = runtime._synthesize_and_verify(
        question="Describe the runtime.",
        trace_id="trace-no-material-abstain",
        intent_class="direct_grounded_knowledge",
        evidence=[_evidence()],
        provider_client=provider,
        requirements=[],
        endpoint_proof={"schema_version": "test"},
    )

    assert answer["safe_abstention"] is True
    assert provider.calls == ["aq_semantic_closure", "aq_semantic_closure_repair"]
    assert runtime.PROVIDER_FALSE_ABSTENTION in closure["failures"]
    assert closure["provider_contract"] == "no_material_runtime_bound_semantic_closure/v1"


@pytest.mark.parametrize(
    "stage",
    ["facet_local_binding", "native_semantic_review_binding", "no_material_slot_binding"],
)
def test_native_post_parse_stages_are_never_reported_as_unknown(stage: str) -> None:
    leaf = runtime._post_parse_exception_leaf(ValueError("bounded failure"), stage=stage)
    assert leaf == f"M26_PPVE_099_UNCLASSIFIED_VALUE_ERROR_{stage.upper()}"
    assert "UNKNOWN_STAGE" not in leaf
