from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from knowledge_engine import m26_multilingual_public_api
from knowledge_engine.m26_aq_semantic_contract import synthesize_and_verify
from knowledge_engine.m26_multilingual_canonicalization import (
    CanonicalizationRequest,
)
from knowledge_engine.m26_multilingual_retrieval_adapter import (
    CandidateUnionResult,
    FusedRetrievalCandidate,
    RetrievalChannelResult,
    RetrievalHit,
    RetrievalQuery,
)
from knowledge_engine.m26_multilingual_staging_dependencies import (
    FrozenEvidenceSelectorAdapter,
    LiveCanonicalizationProvider,
    LiveEquivalenceReviewer,
    LiveGateError,
    LiveRequestedLanguageRealizer,
    SingleAttemptMiniMaxLanguageClient,
    StagingDenseRetriever,
    Track2StagingTrace,
    build_track2_staging_runtime_dependencies,
    track2_runtime_readiness,
)


@dataclass(frozen=True)
class FakeBundle:
    lexical_index: dict[str, Any] = None  # type: ignore[assignment]
    graph: dict[str, Any] = None  # type: ignore[assignment]
    graph_v2: dict[str, Any] = None  # type: ignore[assignment]
    provenance: dict[str, Any] = None  # type: ignore[assignment]
    release_id: str = "release"
    manifest_sha256: str = "manifest"

    def __post_init__(self) -> None:
        object.__setattr__(self, "lexical_index", self.lexical_index or {"documents": []})
        object.__setattr__(self, "graph", self.graph or {})
        object.__setattr__(self, "graph_v2", self.graph_v2 or {"edges": []})
        object.__setattr__(self, "provenance", self.provenance or {})


class FakeLanguageClient:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def generate_json(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return self.response


class RecordingDenseChannel:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def search(
        self,
        *,
        question: str,
        bundle: Any,
        top_k: int,
    ) -> dict[str, Any]:
        del bundle, top_k
        self.calls.append(question)
        return {
            "backend_identity": {"backend": "dense"},
            "candidates": [
                {"section_id": "doc-a", "score": 0.9},
                {"section_id": "doc-b", "score": 0.4},
            ],
        }


class RecordingRetriever:
    def __init__(self) -> None:
        self.calls: list[RetrievalQuery] = []

    def __call__(self, query: RetrievalQuery) -> RetrievalChannelResult:
        self.calls.append(query)
        return RetrievalChannelResult(
            hits=(RetrievalHit(candidate_id="doc-a", rank=1),)
        )


def test_default_app_is_wired_by_staging_factory() -> None:
    readiness = track2_runtime_readiness(
        m26_multilingual_public_api.app.state.track2_runtime_dependencies
    )
    assert readiness["multilingual_runtime_ready"] is True
    dependencies = m26_multilingual_public_api.app.state.track2_runtime_dependencies
    assert dependencies.canonicalization_provider is not None


def test_injected_dependencies_override_safely(tmp_path: Path) -> None:
    fake = m26_multilingual_public_api.MultilingualRuntimeDependencies()
    app = m26_multilingual_public_api.create_app(
        quota_ledger=m26_multilingual_public_api.public_api.PublicQuotaLedger(
            tmp_path / "quota.sqlite3"
        ),
        runtime_dependencies=fake,
    )
    assert app.state.track2_runtime_dependencies is fake


def test_readiness_false_when_mandatory_dependency_missing() -> None:
    readiness = track2_runtime_readiness(
        m26_multilingual_public_api.MultilingualRuntimeDependencies(
            canonicalization_provider=object(),
            dense_retriever=object(),
        )
    )
    assert readiness["multilingual_runtime_ready"] is False
    assert "MINIMAX_API_KEY" not in str(readiness)


def test_health_exposes_sanitized_runtime_readiness() -> None:
    response = TestClient(m26_multilingual_public_api.app).get("/v1/health")
    payload = response.json()
    readiness = payload["runtime_readiness"]
    assert readiness["multilingual_runtime_ready"] is True
    assert "MINIMAX_API_KEY" not in str(payload)


def test_live_canonicalization_provider_parses_structured_response() -> None:
    client = FakeLanguageClient(
        {
            "canonical_question_en": "How does API-42 work?",
            "semantic_fidelity": {
                "intent": "preserved",
                "identity_terms": "preserved",
                "technical_identifiers": "preserved",
                "numbers_and_units": "not_applicable",
                "comparison_direction": "not_applicable",
                "relationship_direction": "not_applicable",
                "negation": "not_applicable",
                "modality_qualifiers": "not_applicable",
                "multi_part_synthesis": "not_applicable",
                "graph_entity_references": "not_applicable",
            },
        }
    )
    provider = LiveCanonicalizationProvider(client)
    result = provider.canonicalize(
        CanonicalizationRequest(
            original_question="API-42 怎麼運作？",
            detected_input_language="zh-TW",
            requested_answer_language="zh-TW",
        )
    )
    assert result.ok is True
    assert result.canonical_question_en == "How does API-42 work?"
    assert client.calls[0]["purpose"] == "multilingual_canonicalization"


def test_live_canonicalization_provider_fails_closed_on_malformed_response() -> None:
    provider = LiveCanonicalizationProvider(FakeLanguageClient({"canonical_question_en": "x"}))
    result = provider.canonicalize(
        CanonicalizationRequest(
            original_question="API-42 怎麼運作？",
            detected_input_language="zh-TW",
            requested_answer_language="zh-TW",
        )
    )
    assert result.status == "failed"
    assert result.failure_code == "CANONICALIZATION_PROVIDER_SCHEMA_INVALID"


def test_requested_language_realizer_preserves_claim_ids() -> None:
    client = FakeLanguageClient(
        {
            "claims": [
                {"claim_id": "claim-a", "requested_language_text": "請保留 API-42。"},
                {"claim_id": "claim-b", "requested_language_text": "請保留 LLM。"},
            ]
        }
    )
    realizer = LiveRequestedLanguageRealizer(client)
    request = type(
        "Request",
        (),
        {
            "requested_answer_language": "zh-TW",
            "claims": (
                type(
                    "Claim",
                    (),
                    {
                        "canonical_claim_id": "claim-a",
                        "canonical_surface_text_en": "Keep API-42.",
                        "preservation_markers": ("API-42",),
                    },
                )(),
                type(
                    "Claim",
                    (),
                    {
                        "canonical_claim_id": "claim-b",
                        "canonical_surface_text_en": "Keep LLM.",
                        "preservation_markers": ("LLM",),
                    },
                )(),
            ),
        },
    )()
    result = realizer(request)
    assert [item["claim_id"] for item in result["claims"]] == ["claim-a", "claim-b"]


def test_equivalence_reviewer_accepts_complete_raw_pass_mapping() -> None:
    client = FakeLanguageClient(
        {
            "reviews": [
                {
                    "claim_id": "claim-a",
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
            ]
        }
    )
    reviewer = LiveEquivalenceReviewer(client)
    request = type(
        "Request",
        (),
        {
            "requested_answer_language": "zh-TW",
            "claims": (
                type(
                    "Claim",
                    (),
                    {
                        "canonical_claim_id": "claim-a",
                        "canonical_surface_text_en": "Keep API-42.",
                        "requested_language_text_zh_tw": "請保留 API-42。",
                        "marker_preservation_status": "pass",
                        "preservation_markers": ("API-42",),
                    },
                )(),
            ),
        },
    )()
    result = reviewer(request)
    assert result["reviews"][0]["equivalence"] == "pass"


def test_equivalence_reviewer_fails_closed_on_string_booleans() -> None:
    client = FakeLanguageClient(
        {
            "reviews": [
                {
                    "claim_id": "claim-a",
                    "equivalence": "pass",
                    "no_material_factual_expansion": "true",
                    "no_contradiction": "true",
                    "negation_preserved": "not_applicable",
                    "modality_preserved": "not_applicable",
                    "comparison_direction_preserved": "not_applicable",
                    "relationship_direction_preserved": "not_applicable",
                    "numeric_identity_preserved": "true",
                    "entity_identity_preserved": "true",
                }
            ]
        }
    )
    reviewer = LiveEquivalenceReviewer(client)
    request = type(
        "Request",
        (),
        {
            "requested_answer_language": "zh-TW",
            "claims": (
                type(
                    "Claim",
                    (),
                    {
                        "canonical_claim_id": "claim-a",
                        "canonical_surface_text_en": "Keep API-42.",
                        "requested_language_text_zh_tw": "請保留 API-42。",
                        "marker_preservation_status": "pass",
                        "preservation_markers": ("API-42",),
                    },
                )(),
            ),
        },
    )()
    with pytest.raises(LiveGateError):
        reviewer(request)


def test_single_attempt_language_client_has_no_retry_loop() -> None:
    client = SingleAttemptMiniMaxLanguageClient(api_key="test-key")
    assert client.max_network_attempts == 1


def test_dense_original_and_canonical_adapter_calls_once_each() -> None:
    trace = Track2StagingTrace(
        dense_channel=RecordingDenseChannel(),
        bundle=FakeBundle(),
    )
    retriever = StagingDenseRetriever(trace)
    retriever(
        RetrievalQuery(
            channel="dense",
            query_representation="original",
            query_text="原始問題",
        )
    )
    retriever(
        RetrievalQuery(
            channel="dense",
            query_representation="canonical_en",
            query_text="Canonical question",
        )
    )
    assert trace.dense_channel.calls == ["原始問題", "Canonical question"]


def test_frozen_evidence_selector_invokes_frozen_selector_seam(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trace = Track2StagingTrace(dense_channel=RecordingDenseChannel(), bundle=FakeBundle())
    trace.lexical_results["canonical_en"] = {
        "results": [
            {
                "section_id": "doc-a",
                "score": 1.0,
                "citations": [],
                "relation_expansions": [],
                "score_components": {"graph": 0, "relation_graph": 0},
            }
        ]
    }
    trace.dense_results["canonical_en"] = {
        "backend_identity": {"backend": "dense"},
        "candidates": [{"section_id": "doc-a", "score": 1.0}],
    }
    recorded: dict[str, Any] = {}

    def fake_select_evidence(**kwargs: Any) -> list[dict[str, Any]]:
        recorded["kwargs"] = kwargs
        return [
            {
                "section_id": "doc-a",
                "evidence_type": "passage",
                "evidence_id": "ev-a",
                "locator_id": "loc-a",
                "source_identity": "source-a",
                "source_id": "source-a",
                "citation_id": "c-a",
                "citations": [],
            }
        ]

    def fake_strengthen_evidence(**kwargs: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        return list(kwargs["evidence"]), {"required": False, "matched": False}

    monkeypatch.setattr(
        "knowledge_engine.m26_pa7_arbitrary_query_runtime._select_evidence",
        fake_select_evidence,
    )
    monkeypatch.setattr(
        "knowledge_engine.m26_pa7_semantic_closure_runtime._strengthen_evidence",
        fake_strengthen_evidence,
    )

    adapter = FrozenEvidenceSelectorAdapter(trace)
    evidence = adapter(
        CandidateUnionResult(
            status="ok",
            mode="multilingual_dual_query",
            candidates=(
                FusedRetrievalCandidate(
                    candidate_id="doc-a",
                    fusion_score=1.0,
                    contributions=(),
                ),
            ),
        ),
        type(
            "Envelope",
            (),
            {
                "detected_input_language": "zh-TW",
                "canonical_question_en": "How does API-42 work?",
                "original_question": "API-42 怎麼運作？",
            },
        )(),
    )
    assert adapter.frozen_symbol == "m26_pa7_arbitrary_query_runtime._select_evidence"
    assert recorded["kwargs"]["question"] == "How does API-42 work?"
    assert evidence[0]["section_id"] == "doc-a"
    assert trace.endpoint_proof == {"required": False, "matched": False}


def test_build_track2_staging_runtime_dependencies_uses_accepted_closure_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acct")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "token")
    monkeypatch.setenv("QDRANT_URL", "https://example.invalid")
    monkeypatch.setenv("QDRANT_API_KEY_READ", "qdrant-key")
    monkeypatch.setenv("M26_PA7_DENSE_COLLECTION", "collection")
    monkeypatch.setattr(
        "knowledge_engine.m26_multilingual_staging_dependencies.load_production_answer_bundle",
        lambda: FakeBundle(),
    )
    monkeypatch.setattr(
        "knowledge_engine.m26_multilingual_staging_dependencies.legacy.dense_channel_from_env",
        lambda require_remote=True: RecordingDenseChannel(),
    )
    monkeypatch.setattr(
        "knowledge_engine.m26_multilingual_staging_dependencies.build_provider_routing_client",
        lambda **kwargs: object(),
    )

    deps = build_track2_staging_runtime_dependencies()
    assert deps.closure_runner is synthesize_and_verify
    assert deps.evidence_selector is not None
