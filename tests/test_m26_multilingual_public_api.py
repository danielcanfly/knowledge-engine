from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from knowledge_engine import m26_multilingual_public_api, m26_public_api
from knowledge_engine.m26_multilingual_canonicalization import (
    CanonicalizationRequest,
    CanonicalizationResult,
    SemanticFidelityContract,
)
from knowledge_engine.m26_multilingual_language_envelope import (
    detect_input_language,
    requested_answer_language,
)
from knowledge_engine.m26_multilingual_retrieval_adapter import (
    CandidateUnionResult,
    RetrievalChannelResult,
    RetrievalHit,
    RetrievalQuery,
)
from knowledge_engine.m26_multilingual_runtime import (
    MultilingualRuntimeDependencies,
)
from knowledge_engine.m26_multilingual_semantic_spine import (
    SemanticAuthorityDependencies,
)

ROOT = Path(__file__).resolve().parents[1]
GATE_PATH = ROOT / "pilot/m26/m26-pa-7-resolved-production-gate.json"


@dataclass(frozen=True)
class Requirement:
    requirement_id: str = "req-direct"
    exact_phrase: str = "API-42"


class RecordingCanonicalizer:
    def __init__(self) -> None:
        self.calls: list[CanonicalizationRequest] = []

    def canonicalize(self, request: CanonicalizationRequest) -> CanonicalizationResult:
        self.calls.append(request)
        return CanonicalizationResult(
            canonical_question_en="How does API-42 preserve the LLM model?",
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


class RecordingRetriever:
    def __init__(self, prefix: str) -> None:
        self.prefix = prefix
        self.calls: list[RetrievalQuery] = []

    def __call__(self, query: RetrievalQuery) -> RetrievalChannelResult:
        self.calls.append(query)
        return RetrievalChannelResult(
            hits=(
                RetrievalHit(
                    candidate_id=f"{self.prefix}-{query.query_representation}",
                    rank=1,
                ),
            )
        )


class RecordingRealizer:
    def __init__(self) -> None:
        self.calls: list[Any] = []

    def __call__(self, request: Any) -> Mapping[str, Any]:
        self.calls.append(request)
        return {
            "claims": [
                {
                    "claim_id": claim.canonical_claim_id,
                    "requested_language_text": "請保留 API-42 與 LLM。",
                }
                for claim in request.claims
            ]
        }


class RawPassReviewer:
    def __init__(self) -> None:
        self.calls: list[Any] = []

    def __call__(self, request: Any) -> Mapping[str, Any]:
        self.calls.append(request)
        return {
            "reviews": [
                {
                    "claim_id": claim.canonical_claim_id,
                    "equivalence": "pass",
                    "no_material_factual_expansion": True,
                    "no_contradiction": True,
                    "negation_preserved": "not_applicable",
                    "modality_preserved": "not_applicable",
                    "comparison_direction_preserved": "not_applicable",
                    "relationship_direction_preserved": "not_applicable",
                    "numeric_identity_preserved": "true",
                    "entity_identity_preserved": "true",
                }
                for claim in request.claims
            ]
        }


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


def _closure_runner(**kwargs: Any) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    del kwargs
    verification = {
        "answer_source": "provider_verified_runtime_bound_semantic_closure",
        "safe_abstention": False,
        "reason_codes": [],
        "repair_attempted": False,
        "unsupported_accepted_claims": 0,
        "citation_locator_valid": True,
        "material_claim_support_verified": True,
        "semantic_contract_fingerprint": "fingerprint/v1",
        "citations": [
            {
                "citation_id": "claim-a_ref_1",
                "claim_id": "claim-a",
                "claim_role": "direct",
                "evidence_id": "ev-a",
                "locator_id": "loc-a",
                "source_identity": "source-a#section-a",
                "source_id": "source-a",
            }
        ],
        "answer_claims": [
            {
                "claim_id": "claim-a",
                "surface_text": "API-42 uses the LLM model.",
                "claim_role": "direct",
                "claim_type": "EVIDENCE_FACT",
                "facet_ids": ["direct_answer"],
                "support_mode": "exact_quote",
                "support_ref_count": 1,
                "source_identities": ["source-a#section-a"],
                "citation_ids": ["claim-a_ref_1"],
            }
        ],
    }
    closure = {
        "semantic_contract": {"fingerprint": "fingerprint/v1"},
        "partial_answer": False,
        "semantic_review": {"claim_judgments": []},
    }
    return verification, closure


@dataclass
class DependencyBundle:
    dependencies: MultilingualRuntimeDependencies
    canonicalizer: RecordingCanonicalizer
    dense: RecordingRetriever
    lexical: RecordingRetriever
    graph: RecordingRetriever
    identifier: RecordingRetriever
    realizer: RecordingRealizer
    reviewer: RawPassReviewer


def _dependencies() -> DependencyBundle:
    canonicalizer = RecordingCanonicalizer()
    dense = RecordingRetriever("dense")
    lexical = RecordingRetriever("lexical")
    graph = RecordingRetriever("graph")
    identifier = RecordingRetriever("identifier")
    realizer = RecordingRealizer()
    reviewer = RawPassReviewer()

    def selector(
        union: CandidateUnionResult,
        envelope: Any,
    ) -> tuple[Mapping[str, Any], ...]:
        assert union.mode in {"english_passthrough", "multilingual_dual_query"}
        return (
            {
                "evidence_id": "ev-a",
                "locator_id": "loc-a",
                "passage_text": "API-42 uses the LLM model.",
                "source_identity": "source-a#section-a",
                "source_id": "source-a",
            },
        )

    return DependencyBundle(
        dependencies=MultilingualRuntimeDependencies(
            canonicalization_provider=canonicalizer,
            dense_retriever=dense,
            lexical_retriever=lexical,
            graph_retriever=graph,
            identifier_retriever=identifier,
            evidence_selector=selector,
            semantic_authorities=_semantic_authorities(),
            closure_provider_client=object(),
            closure_runner=_closure_runner,
            endpoint_proof={"endpoint": "test"},
            requested_language_realizer=realizer,
            equivalence_reviewer=reviewer,
        ),
        canonicalizer=canonicalizer,
        dense=dense,
        lexical=lexical,
        graph=graph,
        identifier=identifier,
        realizer=realizer,
        reviewer=reviewer,
    )


@pytest.fixture
def configured_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("M26_PUBLIC_IP_HMAC_SECRET", "test-hmac-secret")
    monkeypatch.setenv("KNOWLEDGE_ENGINE_OWNER_SUBJECT_HASH", "93" * 32)
    monkeypatch.setenv(
        "M26_PUBLIC_ALLOWED_ORIGINS",
        "https://danielcanfly.com,http://localhost:5173",
    )
    monkeypatch.setattr(m26_public_api, "BURST_PER_MINUTE_LIMIT", 100)


def _client(
    tmp_path: Path,
    bundle: DependencyBundle,
) -> TestClient:
    return TestClient(
        m26_multilingual_public_api.create_app(
            root=ROOT,
            gate_path=GATE_PATH,
            quota_ledger=m26_public_api.PublicQuotaLedger(tmp_path / "quota.sqlite3"),
            runtime_dependencies=bundle.dependencies,
        )
    )


def _events(response: Any) -> list[dict[str, Any]]:
    events = []
    for block in response.text.strip().split("\n\n"):
        data = None
        for line in block.splitlines():
            if line.startswith("data: "):
                data = line.removeprefix("data: ")
        if data:
            events.append(json.loads(data))
    return events


def _problem(response: Any) -> dict[str, Any]:
    assert response.headers["content-type"].startswith("application/problem+json")
    return response.json()


def _terminal(events: list[dict[str, Any]]) -> dict[str, Any]:
    terminals = [event for event in events if event["type"].startswith("answer.")]
    assert len(terminals) == 1
    return terminals[0]


def test_public_contract_accepts_answer_language_and_rejects_selection_fields(
    tmp_path: Path,
    configured_env: None,
) -> None:
    bundle = _dependencies()
    client = _client(tmp_path, bundle)

    assert client.post("/v1/answers", json={"question": "你好 API-42"}).status_code == 200
    assert (
        client.post(
            "/v1/answers",
            json={"question": "你好 API-42", "answer_language": "auto"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/v1/answers",
            json={"question": "你好 API-42", "answer_language": "en"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/v1/answers",
            json={"question": "你好 API-42", "answer_language": "zh-TW"},
        ).status_code
        == 200
    )
    assert _problem(
        client.post(
            "/v1/answers",
            json={"question": "你好", "answer_language": "fr"},
        )
    )["code"] == "ANSWER_LANGUAGE_INVALID"
    for forbidden in ("provider", "model", "reviewer_model", "dense_backend"):
        assert _problem(
            client.post("/v1/answers", json={"question": "ok", forbidden: "x"})
        )["code"] == "PROVIDER_SELECTION_FORBIDDEN"


@pytest.mark.parametrize(
    "question,answer_language,expected",
    [
        ("What is API-42?", "auto", "en"),
        ("What is API-42?", "en", "en"),
        ("What is API-42?", "zh-TW", "zh-TW"),
        ("你好", "auto", "zh-TW"),
        ("你好", "en", "en"),
        ("你好", "zh-TW", "zh-TW"),
        ("API-42 是什麼?", "auto", "zh-TW"),
        ("API-42 是什麼?", "en", "en"),
        ("API-42 是什麼?", "zh-TW", "zh-TW"),
    ],
)
def test_language_resolution_matrix(
    question: str,
    answer_language: str,
    expected: str,
) -> None:
    assert requested_answer_language(
        detected_input_language=detect_input_language(question),
        answer_language=answer_language,  # type: ignore[arg-type]
    ) == expected


def test_english_auto_and_en_route_to_track1_without_track2_calls(
    tmp_path: Path,
    configured_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _dependencies()
    calls: list[Mapping[str, Any]] = []

    def fake_track1(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {
            "status": "owner_only_cited_answer",
            "safe_abstention": False,
            "answer_text": "Verified English answer.",
            "citations": [],
            "sources": [],
            "answer_claims": [],
            "provider_routing": {"provider_attempts": []},
            "reason_codes": [],
        }

    monkeypatch.setattr(m26_public_api, "run_owner_query_for_web", fake_track1)
    client = _client(tmp_path, bundle)
    for payload in (
        {"question": "What is API-42?"},
        {"question": "What is API-42?", "answer_language": "en"},
    ):
        response = client.post("/v1/answers", json=payload)
        assert response.status_code == 200
        terminal = _terminal(_events(response))
        assert terminal["type"] == "answer.completed"
        assert terminal["answer"] == "Verified English answer."

    assert len(calls) == 2
    assert bundle.canonicalizer.calls == []
    assert bundle.dense.calls == []
    assert bundle.lexical.calls == []
    assert bundle.graph.calls == []
    assert bundle.realizer.calls == []
    assert bundle.reviewer.calls == []


def test_zh_tw_auto_runs_track2_and_raw_mapping_pass_authorizes_claim(
    tmp_path: Path,
    configured_env: None,
) -> None:
    bundle = _dependencies()
    response = _client(tmp_path, bundle).post(
        "/v1/answers",
        json={"question": "API-42 是什麼?", "answer_language": "auto"},
    )

    assert response.status_code == 200
    events = _events(response)
    assert [event["seq"] for event in events] == list(range(1, len(events) + 1))
    terminal = _terminal(events)
    assert terminal["type"] == "answer.completed"
    assert terminal["final_visible_language"] == "zh-TW"
    assert terminal["answer_text"] == "請保留 API-42 與 LLM。"
    assert terminal["visible_claim_count"] == 1
    assert terminal["answer_claims"][0]["citation_ids"] == ["claim-a_ref_1"]
    assert len(bundle.canonicalizer.calls) == 1
    assert [call.query_representation for call in bundle.dense.calls] == [
        "original",
        "canonical_en",
    ]
    assert len(bundle.realizer.calls) == 1
    assert len(bundle.reviewer.calls) == 1


def test_explicit_en_for_zh_uses_canonical_path_without_realizer_or_reviewer(
    tmp_path: Path,
    configured_env: None,
) -> None:
    bundle = _dependencies()
    response = _client(tmp_path, bundle).post(
        "/v1/answers",
        json={"question": "API-42 是什麼?", "answer_language": "en"},
    )

    terminal = _terminal(_events(response))
    assert terminal["type"] == "answer.completed"
    assert terminal["final_visible_language"] == "en"
    assert terminal["answer_text"] == "API-42 uses the LLM model."
    assert len(bundle.canonicalizer.calls) == 1
    assert bundle.realizer.calls == []
    assert bundle.reviewer.calls == []


def test_english_input_explicit_zh_tw_uses_track2_publication_without_canonicalizer(
    tmp_path: Path,
    configured_env: None,
) -> None:
    bundle = _dependencies()
    response = _client(tmp_path, bundle).post(
        "/v1/answers",
        json={"question": "What is API-42?", "answer_language": "zh-TW"},
    )

    terminal = _terminal(_events(response))
    assert terminal["type"] == "answer.completed"
    assert terminal["final_visible_language"] == "zh-TW"
    assert terminal["answer_text"] == "請保留 API-42 與 LLM。"
    assert bundle.canonicalizer.calls == []
    assert len(bundle.realizer.calls) == 1
    assert len(bundle.reviewer.calls) == 1


def test_track2_sse_never_streams_unverified_answer_text_before_terminal(
    tmp_path: Path,
    configured_env: None,
) -> None:
    response = _client(tmp_path, _dependencies()).post(
        "/v1/answers",
        json={"question": "API-42 是什麼?", "answer_language": "zh-TW"},
    )

    events = _events(response)
    assert "請保留 API-42" not in "\n".join(
        json.dumps(event, sort_keys=True) for event in events[:-1]
    )
    assert _terminal(events)["answer_text"] == "請保留 API-42 與 LLM。"


def test_track2_health_identifies_isolated_staging_identity(
    tmp_path: Path,
    configured_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("M26_TRACK2_CANDIDATE_SHA", "phase6-candidate-sha")
    response = _client(tmp_path, _dependencies()).get("/v1/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["track"] == 2
    assert payload["multilingual"] is True
    assert payload["candidate_sha"] == "phase6-candidate-sha"
    assert (
        payload["reauthorized_start_sha"]
        == m26_multilingual_public_api.TRACK2_REAUTHORIZED_START_SHA
    )
    assert payload["base_sha"] == m26_multilingual_public_api.TRACK1_BASE_SHA
    assert payload["production_mutated"] is False
    assert payload["production_multilingual_enabled"] is False


def test_quota_admission_still_occurs_for_multilingual_requests(
    tmp_path: Path,
    configured_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(m26_public_api, "PER_IP_DAILY_LIMIT", 1)
    client = _client(tmp_path, _dependencies())

    assert client.post("/v1/answers", json={"question": "你好 API-42"}).status_code == 200
    assert _problem(client.post("/v1/answers", json={"question": "你好 API-42"}))[
        "code"
    ] == "DAILY_IP_LIMIT_EXCEEDED"
