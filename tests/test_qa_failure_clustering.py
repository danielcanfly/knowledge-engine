from __future__ import annotations

import json
import sqlite3

from knowledge_engine.qa_answer_quality_evaluator import (
    ANSWER_QUALITY_CRITERION_MAX,
    AnswerQualityEvaluation,
    ProviderAnswerQualityEvaluator,
    StaticAnswerQualityEvaluator,
    canonical_failure_provenance,
)
from knowledge_engine.qa_answer_quality_sqlite import SqliteQaRepository
from knowledge_engine.qa_failure_clustering import (
    FAILURE_CLUSTER_IDENTITY_VERSION,
    FAILURE_CLUSTER_LEXICAL_FALLBACK_VERSION,
    FailureIntentFamily,
    normalize_failure_intent,
)
from knowledge_engine.storage import FileObjectStore


def response(request_id: str, **overrides) -> dict:
    value = {
        "request_id": request_id,
        "status": "owner_only_cited_answer",
        "answer_text": "A supported answer.",
        "citations": [{"citation_id": "c1", "source_id": "s1"}],
        "selected_evidence": [{"source_id": "s1", "quote": "support"}],
        "integrity": {
            "unsupported_accepted_claims": 0,
            "material_claim_support_verified": True,
            "citation_locator_valid": True,
        },
    }
    value.update(overrides)
    return value


def repository(tmp_path) -> SqliteQaRepository:
    return SqliteQaRepository(
        FileObjectStore(tmp_path / "objects"), db_path=tmp_path / "qa.sqlite"
    )


def failing_evaluator(
    *,
    intent: FailureIntentFamily | None,
    codes: tuple[str, ...] = (),
    weakest: str = "correctness_grounding",
) -> StaticAnswerQualityEvaluator:
    criteria = dict(ANSWER_QUALITY_CRITERION_MAX)
    criteria[weakest] = max(0, criteria[weakest] - 20)
    score = sum(criteria.values())
    stage, failure_class, signature = canonical_failure_provenance(
        hard_fail_codes=codes,
        criterion_scores=criteria,
    )
    return StaticAnswerQualityEvaluator(
        AnswerQualityEvaluation(
            score=score,
            result="fail",
            criterion_scores=criteria,
            hard_fail_codes=codes,
            failure_class=failure_class,
            failure_stage=stage,
            failure_signature=signature,
            evaluator_provider="qualified-provider",
            evaluator_model="qualified-model",
            failure_intent=intent,
        )
    )


def record_fail(repo, *, request_id: str, question: str, evaluator, payload=None):
    answer = payload or response(request_id)
    event = repo.record_answer(question=question, response=answer, latency_ms=1)
    return repo.evaluate_event(
        event["event_id"], evaluator=evaluator, answer_payload=answer
    )


def test_intent_family_normalizes_case_order_and_punctuation() -> None:
    first = normalize_failure_intent(
        {
            "task": "COMPARE",
            "subjects": [" Routing ", "Replanning!", "routing"],
            "qualifiers": ["During execution", "during   execution"],
        }
    )
    second = normalize_failure_intent(
        {
            "task": "compare",
            "subjects": ["replanning", "routing"],
            "qualifiers": ["during execution"],
        }
    )
    assert first == second == FailureIntentFamily(
        task="compare",
        subjects=("replanning", "routing"),
        qualifiers=("during execution",),
    )


def test_intent_family_truncation_is_independent_of_provider_order() -> None:
    subjects = [f"subject-{index}" for index in range(12)]
    first = normalize_failure_intent({"task": "compare", "subjects": subjects})
    second = normalize_failure_intent(
        {"task": "compare", "subjects": list(reversed(subjects))}
    )
    assert first == second
    assert first is not None
    assert len(first.subjects) == 8


def test_same_semantic_intent_and_failure_signature_share_cluster(tmp_path) -> None:
    repo = repository(tmp_path)
    intent = FailureIntentFamily(task="compare", subjects=("replanning", "routing"))
    first = record_fail(
        repo,
        request_id="a",
        question="What is the difference between routing and replanning?",
        evaluator=failing_evaluator(intent=intent),
    )
    second = record_fail(
        repo,
        request_id="b",
        question="How do routing and replanning differ?",
        evaluator=failing_evaluator(intent=intent),
    )
    assert first["failure_signature"] == second["failure_signature"]
    assert first["cluster_id"] == second["cluster_id"]
    cluster = repo.list_clusters()[0]
    assert cluster["count"] == 2
    assert set(cluster["variants"]) == {
        "What is the difference between routing and replanning?",
        "How do routing and replanning differ?",
    }
    assert cluster["intent_family"] == intent.to_payload()
    assert cluster["cluster_match_method"] == "semantic_evaluator"
    assert cluster["cluster_identity_version"] == FAILURE_CLUSTER_IDENTITY_VERSION
    stored = repo.get_event(first["event_id"])
    assert stored["evaluator"]["failure_signature"] == first["failure_signature"]
    assert stored["evaluator"]["failure_stage"] == cluster["failure_stage"]
    assert stored["evaluator"]["failure_class"] == cluster["failure_class"]


def test_same_intent_but_different_failure_fingerprint_is_separate(tmp_path) -> None:
    repo = repository(tmp_path)
    intent = FailureIntentFamily(task="compare", subjects=("replanning", "routing"))
    first = record_fail(
        repo,
        request_id="a",
        question="Compare routing and replanning",
        evaluator=failing_evaluator(intent=intent, codes=("UNSUPPORTED_ACCEPTED_CLAIMS",)),
        payload=response(
            "a",
            integrity={
                "unsupported_accepted_claims": 1,
                "material_claim_support_verified": True,
                "citation_locator_valid": True,
            },
        ),
    )
    second = record_fail(
        repo,
        request_id="b",
        question="How do routing and replanning differ?",
        evaluator=failing_evaluator(intent=intent, codes=("CITATION_LOCATOR_INVALID",)),
        payload=response(
            "b",
            integrity={
                "unsupported_accepted_claims": 0,
                "material_claim_support_verified": True,
                "citation_locator_valid": False,
            },
        ),
    )
    assert first["failure_signature"] != second["failure_signature"]
    assert first["cluster_id"] != second["cluster_id"]
    assert len(repo.list_clusters()) == 2


def test_quality_failure_signature_is_question_independent_but_dimension_sensitive() -> None:
    correctness = dict(ANSWER_QUALITY_CRITERION_MAX)
    correctness["correctness_grounding"] = 5
    completeness = dict(ANSWER_QUALITY_CRITERION_MAX)
    completeness["completeness_facets"] = 0
    first = canonical_failure_provenance(hard_fail_codes=(), criterion_scores=correctness)
    second = canonical_failure_provenance(hard_fail_codes=(), criterion_scores=correctness)
    third = canonical_failure_provenance(hard_fail_codes=(), criterion_scores=completeness)
    assert first == second
    assert first[2] != third[2]


def test_verified_semantic_paraphrase_reopens_same_cluster_version(tmp_path) -> None:
    repo = repository(tmp_path)
    intent = FailureIntentFamily(task="compare", subjects=("replanning", "routing"))
    first = record_fail(
        repo,
        request_id="a",
        question="What is the difference between routing and replanning?",
        evaluator=failing_evaluator(intent=intent),
    )
    cluster_id = first["cluster_id"]
    repo.export_new_failures()
    repo.transition_cluster(cluster_id, state="IN_REPAIR")
    repo.transition_cluster(cluster_id, state="RESOLVED", resolved_by_release="rel-fixed")
    repo.transition_cluster(cluster_id, state="VERIFIED", resolved_by_release="rel-fixed")

    second = record_fail(
        repo,
        request_id="b",
        question="How do routing and replanning differ?",
        evaluator=failing_evaluator(intent=intent),
    )
    assert second["cluster_id"] == cluster_id
    cluster = repo.list_clusters()[0]
    assert cluster["lifecycle"] == "REOPENED"
    assert cluster["version"] == 2
    exported = repo.export_new_failures()
    assert exported["membership"] == [f"{cluster_id}:2"]


def test_missing_semantic_intent_uses_explicit_lexical_fallback_without_dropping_fail(
    tmp_path,
) -> None:
    repo = repository(tmp_path)
    event = record_fail(
        repo,
        request_id="fallback",
        question="How do routing and replanning differ?",
        evaluator=failing_evaluator(intent=None),
    )
    assert event["evaluation_status"] == "ANSWERED"
    assert event["result"] == "fail"
    cluster = repo.list_clusters()[0]
    assert cluster["cluster_match_method"] == "lexical_fallback"
    assert cluster["cluster_identity_version"] == FAILURE_CLUSTER_LEXICAL_FALLBACK_VERSION
    assert cluster["intent_family"]["task"] == "lexical_fallback"


def test_malformed_semantic_intent_uses_explicit_lexical_fallback(tmp_path) -> None:
    repo = repository(tmp_path)
    malformed = normalize_failure_intent(
        {"task": "invented_task", "subjects": ["routing", "replanning"]}
    )
    assert malformed is None
    event = record_fail(
        repo,
        request_id="malformed",
        question="Compare routing and replanning",
        evaluator=failing_evaluator(intent=malformed),
    )
    assert event["result"] == "fail"
    cluster = repo.list_clusters()[0]
    assert cluster["cluster_match_method"] == "lexical_fallback"


def test_export_carries_semantic_cluster_identity_metadata(tmp_path) -> None:
    repo = repository(tmp_path)
    intent = FailureIntentFamily(task="compare", subjects=("replanning", "routing"))
    record_fail(
        repo,
        request_id="export",
        question="How do routing and replanning differ?",
        evaluator=failing_evaluator(intent=intent),
    )
    exported = repo.export_new_failures()
    row = json.loads(exported["jsonl"].splitlines()[0])
    assert row["intent_family"] == intent.to_payload()
    assert row["cluster_match_method"] == "semantic_evaluator"
    assert row["cluster_identity_version"] == FAILURE_CLUSTER_IDENTITY_VERSION
    assert repo.export_new_failures() == {
        "created": False,
        "reason": "NO_NEW_FAILURES",
    }


def test_provider_semantic_judge_returns_non_scoring_question_intent_metadata() -> None:
    class Provider:
        def __init__(self):
            self.payload = None

        def call(self, payload, call_class):
            self.payload = payload
            assert call_class == "answer_quality_evaluation"
            return {
                "text": json.dumps(
                    {
                        "criterion_scores": {
                            **ANSWER_QUALITY_CRITERION_MAX,
                            "correctness_grounding": 5,
                        },
                        "hard_fail_codes": [],
                        "question_intent": {
                            "task": "compare",
                            "subjects": ["routing", "replanning"],
                            "qualifiers": [],
                        },
                    }
                )
            }

    provider = Provider()
    result = ProviderAnswerQualityEvaluator(
        provider,
        provider_name="qualified-provider",
        model="qualified-model",
    ).evaluate(
        question="What is the difference between routing and replanning?",
        answer_payload=response("provider"),
        forensic_trace=None,
    )
    assert result.result == "fail"
    assert result.failure_intent == FailureIntentFamily(
        task="compare", subjects=("replanning", "routing")
    )
    assert "question_intent" in provider.payload["system"]
    assert "Paraphrases with the same intent" in provider.payload["system"]
    assert result.score == sum(result.criterion_scores.values())


def test_existing_v2_cluster_table_migrates_additive_identity_columns(tmp_path) -> None:
    db_path = tmp_path / "legacy-v2.sqlite"
    with sqlite3.connect(db_path) as db:
        db.executescript(
            """
            CREATE TABLE qa_events(
              event_id TEXT PRIMARY KEY, timestamp TEXT NOT NULL, question TEXT NOT NULL,
              score INTEGER, result TEXT, evaluation_status TEXT NOT NULL,
              latency_ms INTEGER NOT NULL, country TEXT NOT NULL,
              release_identity_json TEXT NOT NULL, index_identity_json TEXT NOT NULL,
              evaluator_json TEXT NOT NULL, evaluation_error_code TEXT, evaluated_at TEXT,
              evaluation_latency_ms INTEGER, dedupe_identity TEXT NOT NULL, trace_id TEXT NOT NULL,
              failure_class TEXT, failure_signature TEXT, cluster_id TEXT, failure_trace_key TEXT,
              suggested_questions_json TEXT NOT NULL
            );
            CREATE TABLE qa_clusters(
              cluster_id TEXT PRIMARY KEY, representative_question TEXT NOT NULL,
              variants_json TEXT NOT NULL, event_count INTEGER NOT NULL,
              first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
              failure_stage TEXT NOT NULL, failure_signature TEXT NOT NULL,
              failure_class TEXT NOT NULL, sample_trace_ids_json TEXT NOT NULL,
              lifecycle TEXT NOT NULL, version INTEGER NOT NULL,
              export_history_json TEXT NOT NULL, resolved_by_release TEXT,
              last_seen_release_json TEXT NOT NULL, ignored_reason TEXT
            );
            INSERT INTO qa_clusters VALUES(
              'legacy-cluster','Q','[\"Q\"]',1,'2026-09-07T00:00:00Z','2026-09-07T00:00:00Z',
              'answer_quality','sig','quality_below_threshold','[]','NEW',1,'[]',NULL,'{}',NULL
            );
            """
        )
    repo = SqliteQaRepository(FileObjectStore(tmp_path / "objects"), db_path=db_path)
    cluster = repo.list_clusters()[0]
    assert cluster["cluster_match_method"] == "legacy"
    assert cluster["cluster_identity_version"] == "legacy/v1"
    assert cluster["intent_family"] == {}
    with sqlite3.connect(db_path) as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(qa_clusters)")}
    assert {
        "intent_family_json",
        "cluster_match_method",
        "cluster_identity_version",
    }.issubset(columns)
