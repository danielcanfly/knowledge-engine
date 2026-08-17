from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from knowledge_engine.m26_multilingual_canonicalization import (
    CanonicalizationRequest,
    CanonicalizationResult,
    SemanticFidelityContract,
)
from knowledge_engine.m26_multilingual_retrieval_adapter import (
    CandidateUnionResult,
    RetrievalChannelResult,
    RetrievalHit,
    RetrievalQuery,
)
from knowledge_engine.m26_multilingual_runtime import (
    MultilingualRuntimeDependencies,
    run_track2_multilingual_request,
)
from knowledge_engine.m26_multilingual_semantic_spine import (
    SemanticAuthorityDependencies,
)


@dataclass(frozen=True)
class Requirement:
    requirement_id: str = "req-direct"
    exact_phrase: str = "API-42"


class FixedCanonicalizer:
    def canonicalize(self, request: CanonicalizationRequest) -> CanonicalizationResult:
        return CanonicalizationResult(
            canonical_question_en="What is API-42?",
            status="ok",
            semantic_fidelity=SemanticFidelityContract(
                intent="preserved",
                identity_terms="preserved",
                technical_identifiers="preserved",
                numbers_and_units="not_applicable",
                comparison_direction="not_applicable",
                relationship_direction="not_applicable",
                negation="not_applicable",
                modality_qualifiers="not_applicable",
                multi_part_synthesis="not_applicable",
                graph_entity_references="not_applicable",
            ),
        )


class FixedRetriever:
    def __call__(self, query: RetrievalQuery) -> RetrievalChannelResult:
        return RetrievalChannelResult(
            hits=(RetrievalHit(candidate_id=f"hit-{query.query_representation}", rank=1),)
        )


class BudgetedClient:
    def __init__(self, *, max_calls: int = 4) -> None:
        self.max_calls = max_calls
        self.calls = 0

    def call(self, payload: Mapping[str, Any], call_class: str) -> Mapping[str, Any]:
        del payload, call_class
        if self.calls >= self.max_calls:
            raise RuntimeError("provider-call budget exhausted")
        self.calls += 1
        return {"ok": True}


def _semantic_authorities() -> SemanticAuthorityDependencies:
    return SemanticAuthorityDependencies(
        intent_classifier=lambda question: "direct_grounded_knowledge",
        question_contract_builder=lambda **kwargs: {
            "required_facets": [{"facet_id": "direct_answer"}]
        },
        requirement_deriver=lambda question, intent_class: (Requirement(),),
        contract_fingerprint_provider=lambda: "fingerprint/v1",
        contract_schema_version="schema/v1",
    )


def _selector(
    union: CandidateUnionResult,
    envelope: Any,
) -> tuple[Mapping[str, Any], ...]:
    del union, envelope
    return (
        {
            "evidence_id": "ev-a",
            "locator_id": "loc-a",
            "passage_text": "API-42 is an example identifier.",
            "source_identity": "source-a#section-a",
            "source_id": "source-a",
        },
    )


def _abstaining_verification() -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    return (
        {
            "answer_source": "safe_abstention",
            "safe_abstention": True,
            "reason_codes": ["TEST_SAFE_ABSTENTION"],
            "repair_attempted": False,
            "unsupported_accepted_claims": 0,
            "citation_locator_valid": True,
            "material_claim_support_verified": True,
            "semantic_contract_fingerprint": "fingerprint/v1",
        },
        {
            "semantic_contract": {"fingerprint": "fingerprint/v1"},
            "partial_answer": False,
            "semantic_review": {"claim_judgments": []},
        },
    )


def _dependencies(
    *,
    closure_provider_client: Any = None,
    closure_provider_client_factory: Any = None,
    closure_runner: Any,
) -> MultilingualRuntimeDependencies:
    retriever = FixedRetriever()
    return MultilingualRuntimeDependencies(
        canonicalization_provider=FixedCanonicalizer(),
        dense_retriever=retriever,
        lexical_retriever=retriever,
        graph_retriever=retriever,
        evidence_selector=_selector,
        semantic_authorities=_semantic_authorities(),
        closure_provider_client=closure_provider_client,
        closure_provider_client_factory=closure_provider_client_factory,
        closure_runner=closure_runner,
        endpoint_proof={"endpoint": "test"},
        requested_language_realizer=object(),
        equivalence_reviewer=object(),
    )


def _run(dependencies: MultilingualRuntimeDependencies) -> Any:
    return run_track2_multilingual_request(
        question="API-42 是什麼?",
        answer_language="auto",
        dependencies=dependencies,
    )


def test_closure_provider_factory_is_request_scoped() -> None:
    clients: list[BudgetedClient] = []

    def factory() -> BudgetedClient:
        client = BudgetedClient()
        clients.append(client)
        return client

    seen: list[BudgetedClient] = []

    def runner(**kwargs: Any) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
        client = kwargs["provider_client"]
        seen.append(client)
        client.call({}, "closure")
        return _abstaining_verification()

    deps = _dependencies(
        closure_provider_client_factory=factory,
        closure_runner=runner,
    )

    first = _run(deps)
    second = _run(deps)

    assert first.status == "abstained"
    assert second.status == "abstained"
    assert len(clients) == 2
    assert seen[0] is clients[0]
    assert seen[1] is clients[1]
    assert seen[0] is not seen[1]
    assert (
        first.telemetry["closure_provider"]["client_instance_sequence"]
        != second.telemetry["closure_provider"]["client_instance_sequence"]
    )
    assert first.telemetry["closure_provider"]["closure_call_count_for_request"] == 1
    assert second.telemetry["closure_provider"]["closure_call_count_for_request"] == 1


def test_request_local_budget_exhaustion_is_not_inherited() -> None:
    clients: list[BudgetedClient] = []

    def factory() -> BudgetedClient:
        client = BudgetedClient(max_calls=4)
        clients.append(client)
        return client

    def runner(**kwargs: Any) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
        client = kwargs["provider_client"]
        calls_to_consume = 4 if len(clients) == 1 else 1
        for _ in range(calls_to_consume):
            client.call({}, "closure")
        return _abstaining_verification()

    deps = _dependencies(
        closure_provider_client_factory=factory,
        closure_runner=runner,
    )

    first = _run(deps)
    second = _run(deps)

    assert first.status == "abstained"
    assert second.status == "abstained"
    assert [client.calls for client in clients] == [4, 1]
    assert first.telemetry["closure_provider"]["closure_call_count_for_request"] == 4
    assert second.telemetry["closure_provider"]["closure_call_count_for_request"] == 1


def test_request_local_budget_remains_bounded_inside_one_request() -> None:
    def runner(**kwargs: Any) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
        client = kwargs["provider_client"]
        for _ in range(5):
            client.call({}, "closure")
        return _abstaining_verification()

    result = _run(
        _dependencies(
            closure_provider_client_factory=lambda: BudgetedClient(max_calls=4),
            closure_runner=runner,
        )
    )

    assert result.status == "failed"
    assert result.failure_code == "CANONICAL_CLOSURE_AUTHORITY_FAILED"
    assert "provider-call budget exhausted" in result.failure_detail
    assert result.telemetry["closure_provider"]["closure_call_count_for_request"] == 4


def test_runtime_does_not_add_retry_loop_around_frozen_closure_runner() -> None:
    calls = 0

    def runner(**kwargs: Any) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
        nonlocal calls
        del kwargs
        calls += 1
        raise RuntimeError("first closure attempt failed")

    result = _run(
        _dependencies(
            closure_provider_client_factory=lambda: BudgetedClient(max_calls=4),
            closure_runner=runner,
        )
    )

    assert calls == 1
    assert result.status == "failed"
    assert result.failure_code == "CANONICAL_CLOSURE_AUTHORITY_FAILED"


def test_explicit_closure_provider_client_remains_backward_compatible() -> None:
    client = BudgetedClient(max_calls=4)
    seen: list[BudgetedClient] = []

    def runner(**kwargs: Any) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
        seen.append(kwargs["provider_client"])
        kwargs["provider_client"].call({}, "closure")
        return _abstaining_verification()

    result = _run(
        _dependencies(
            closure_provider_client=client,
            closure_runner=runner,
        )
    )

    assert result.status == "abstained"
    assert seen == [client]
    assert client.calls == 1
    assert result.telemetry["closure_provider"]["client_source"] == "explicit_client"


def test_factory_takes_precedence_over_explicit_client() -> None:
    explicit = BudgetedClient(max_calls=4)
    factory_client = BudgetedClient(max_calls=4)
    seen: list[BudgetedClient] = []

    def runner(**kwargs: Any) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
        seen.append(kwargs["provider_client"])
        kwargs["provider_client"].call({}, "closure")
        return _abstaining_verification()

    result = _run(
        _dependencies(
            closure_provider_client=explicit,
            closure_provider_client_factory=lambda: factory_client,
            closure_runner=runner,
        )
    )

    assert result.status == "abstained"
    assert seen == [factory_client]
    assert factory_client.calls == 1
    assert explicit.calls == 0
    assert result.telemetry["closure_provider"]["client_source"] == "factory"


def test_missing_closure_provider_client_and_factory_fails_closed() -> None:
    result = _run(_dependencies(closure_runner=lambda **kwargs: _abstaining_verification()))

    assert result.status == "failed"
    assert result.failure_code == "CANONICAL_CLOSURE_DEPENDENCY_MISSING"
