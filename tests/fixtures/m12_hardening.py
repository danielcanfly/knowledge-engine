from __future__ import annotations

import hashlib
from typing import Any

from knowledge_engine.answer_performance_metrics import AnswerPerformanceObservation
from knowledge_engine.answer_performance_metrics_v2 import (
    ClaimAlignedObservation,
    ClaimAlignment,
)
from knowledge_engine.release_quality_gate import (
    ReleaseQualityGatePolicy,
    evaluate_release_quality_gate,
)
from knowledge_engine.retrieval_citation_metrics import RetrievalCitationExpectation

RELEASE_ID = "release-fixture"
MANIFEST_SHA = "a" * 64
SOURCE_SHA = "b" * 40
PRODUCTION_RELEASE_ID = "20260708T040116Z-69a9f445699a"
PRODUCTION_MANIFEST_SHA = "c" * 64
PRODUCTION_POINTER_SHA = "d" * 64


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def golden_report() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "suite_id": "gqsuite_fixture",
        "report_id": "gqreport_fixture",
        "passed": True,
        "release_blocking": False,
        "release": {
            "release_id": RELEASE_ID,
            "manifest_sha256": MANIFEST_SHA,
        },
        "aggregate": {
            "case_count": 3,
            "passed_count": 3,
            "failed_count": 0,
            "release_blocking_count": 0,
        },
        "failure_reasons": [],
        "cases": [
            {
                "case_id": "answer-existing",
                "case_run_id": "gqrun_existing",
                "passed": True,
                "failure_reasons": [],
                "status": "answered",
                "audiences": ["internal"],
                "retrieval": {
                    "candidate_count": 2,
                    "selected_count": 1,
                    "acl_filtered_count": 1,
                    "raw_fallback_used": False,
                },
                "results": [
                    {
                        "concept_id": "ko_existing",
                        "citations": [{"source_id": "src-existing"}],
                    }
                ],
                "evaluation": {
                    "evaluation_id": "qeval_existing",
                    "passed": True,
                    "release_blocking": False,
                    "reasons": [],
                },
            },
            {
                "case_id": "answer-legacy",
                "case_run_id": "gqrun_legacy",
                "passed": True,
                "failure_reasons": [],
                "status": "answered",
                "audiences": ["public"],
                "retrieval": {
                    "candidate_count": 1,
                    "selected_count": 1,
                    "acl_filtered_count": 0,
                    "raw_fallback_used": False,
                },
                "results": [
                    {
                        "concept_id": "ko_legacy",
                        "citations": [{"source_id": "src-legacy"}],
                    }
                ],
                "evaluation": {
                    "evaluation_id": "qeval_legacy",
                    "passed": True,
                    "release_blocking": False,
                    "reasons": [],
                },
            },
            {
                "case_id": "unknown-topic",
                "case_run_id": "gqrun_unknown",
                "passed": True,
                "failure_reasons": [],
                "status": "not_found",
                "audiences": ["public"],
                "retrieval": {
                    "candidate_count": 0,
                    "selected_count": 0,
                    "acl_filtered_count": 0,
                    "raw_fallback_used": False,
                },
                "results": [],
                "evaluation": {
                    "evaluation_id": "qeval_unknown",
                    "passed": True,
                    "release_blocking": False,
                    "reasons": [],
                },
            },
        ],
    }


def retrieval_expectations() -> list[RetrievalCitationExpectation]:
    return [
        RetrievalCitationExpectation(
            case_id="answer-existing",
            relevant_concepts=frozenset({"ko_existing"}),
            expected_concepts=frozenset({"ko_existing"}),
            allowed_citation_sources=(("ko_existing", ("src-existing",)),),
        ),
        RetrievalCitationExpectation(
            case_id="answer-legacy",
            relevant_concepts=frozenset({"ko_legacy"}),
            expected_concepts=frozenset({"ko_legacy"}),
            allowed_citation_sources=(("ko_legacy", ("src-legacy",)),),
        ),
        RetrievalCitationExpectation(case_id="unknown-topic", expected_zero_result=True),
    ]


def legacy_answer_observations() -> list[AnswerPerformanceObservation]:
    return [
        AnswerPerformanceObservation(
            case_id="answer-existing",
            expected_claim_count=1,
            supported_claim_count=1,
            unsupported_claim_count=0,
            expected_fact_count=1,
            covered_fact_count=1,
            contradiction_expected=False,
            contradiction_handled=False,
            unknown_expected=False,
            unknown_handled=False,
            response_hashes=("hash-existing", "hash-existing"),
            latency_ms=(100.0, 110.0),
            token_cost_usd=(0.001, 0.001),
            index_load_ms=(25.0, 20.0),
            cache_hits=(False, True),
        ),
        AnswerPerformanceObservation(
            case_id="answer-legacy",
            expected_claim_count=1,
            supported_claim_count=1,
            unsupported_claim_count=0,
            expected_fact_count=1,
            covered_fact_count=1,
            contradiction_expected=True,
            contradiction_handled=True,
            unknown_expected=False,
            unknown_handled=False,
            response_hashes=("hash-legacy", "hash-legacy"),
            latency_ms=(120.0, 125.0),
            token_cost_usd=(0.002, 0.002),
            index_load_ms=(15.0, 10.0),
            cache_hits=(True, True),
        ),
        AnswerPerformanceObservation(
            case_id="unknown-topic",
            expected_claim_count=0,
            supported_claim_count=0,
            unsupported_claim_count=0,
            expected_fact_count=0,
            covered_fact_count=0,
            contradiction_expected=False,
            contradiction_handled=False,
            unknown_expected=True,
            unknown_handled=True,
            response_hashes=("hash-unknown", "hash-unknown"),
            latency_ms=(80.0, 85.0),
            token_cost_usd=(0.0, 0.0),
            index_load_ms=(5.0, 5.0),
            cache_hits=(True, True),
        ),
    ]


def claim_aligned_observations() -> list[ClaimAlignedObservation]:
    return [
        ClaimAlignedObservation(
            case_id="answer-existing",
            expected_fact_ids=("fact-existing",),
            claims=(
                ClaimAlignment(
                    claim_id="claim-existing",
                    claim_text_sha256=_sha("Existing evidence is canonical."),
                    support_status="supported",
                    expected_fact_ids=("fact-existing",),
                    citation_source_ids=("src-existing",),
                ),
            ),
            contradiction_expected=False,
            unknown_expected=False,
            response_hashes=("hash-existing", "hash-existing"),
            latency_ms=(100.0, 110.0),
            token_cost_usd=(0.001, 0.001),
            index_load_ms=(25.0, 20.0),
            cache_hits=(False, True),
        ),
        ClaimAlignedObservation(
            case_id="answer-legacy",
            expected_fact_ids=("fact-legacy",),
            claims=(
                ClaimAlignment(
                    claim_id="claim-legacy",
                    claim_text_sha256=_sha("Legacy evidence remains."),
                    support_status="supported",
                    expected_fact_ids=("fact-legacy",),
                    citation_source_ids=("src-legacy",),
                ),
                ClaimAlignment(
                    claim_id="claim-contradiction",
                    claim_text_sha256=_sha("Agents must not retry forever."),
                    support_status="contradicted",
                    unsupported_reason="canonical source states the opposite",
                    contradiction_evidence_ids=("src-existing#retry",),
                ),
            ),
            contradiction_expected=True,
            unknown_expected=False,
            response_hashes=("hash-legacy", "hash-legacy"),
            latency_ms=(120.0, 125.0),
            token_cost_usd=(0.002, 0.002),
            index_load_ms=(15.0, 10.0),
            cache_hits=(True, True),
        ),
        ClaimAlignedObservation(
            case_id="unknown-topic",
            expected_fact_ids=(),
            claims=(
                ClaimAlignment(
                    claim_id="claim-unknown",
                    claim_text_sha256=_sha("No authorized evidence was found."),
                    support_status="unknown",
                    unknown_evidence_ids=("qeval_unknown#not_found",),
                ),
            ),
            contradiction_expected=False,
            unknown_expected=True,
            response_hashes=("hash-unknown", "hash-unknown"),
            latency_ms=(80.0, 85.0),
            token_cost_usd=(0.0, 0.0),
            index_load_ms=(5.0, 5.0),
            cache_hits=(True, True),
        ),
    ]


def release_quality_decision() -> dict[str, Any]:
    artifacts = [
        {
            "evaluation_id": "qeval_fixture",
            "schema_version": "1.0",
            "passed": True,
            "release_blocking": False,
            "stale": False,
            "audiences": ["public", "internal"],
            "release": {"release_id": RELEASE_ID, "manifest_sha256": MANIFEST_SHA},
        },
        {
            "report_id": "gqreport_fixture",
            "schema_version": "1.0",
            "passed": True,
            "release_blocking": False,
            "stale": False,
            "audiences": ["public", "internal"],
            "release": {"release_id": RELEASE_ID, "manifest_sha256": MANIFEST_SHA},
        },
        {
            "baseline_check_id": "gqbaselinecheck_fixture",
            "schema_version": "1.0",
            "passed": True,
            "release_blocking": False,
            "stale": False,
            "audiences": ["public", "internal"],
            "release": {"release_id": RELEASE_ID, "manifest_sha256": MANIFEST_SHA},
        },
    ]
    return evaluate_release_quality_gate(
        policy=ReleaseQualityGatePolicy(
            gate_id="m12-4-fixture",
            release_id=RELEASE_ID,
            manifest_sha256=MANIFEST_SHA,
            canonical_source_sha=SOURCE_SHA,
            production_release_id=PRODUCTION_RELEASE_ID,
            production_manifest_sha256=PRODUCTION_MANIFEST_SHA,
            production_pointer_sha256=PRODUCTION_POINTER_SHA,
            reviewer_identity="reviewer@example.com",
            reviewed_at="2026-07-09T02:00:00Z",
            notes="Fixture quality gate review.",
            required_artifact_ids=frozenset(
                {"qeval_fixture", "gqreport_fixture", "gqbaselinecheck_fixture"}
            ),
            approved_audiences=frozenset({"public", "internal"}),
        ),
        artifacts=artifacts,
    )
