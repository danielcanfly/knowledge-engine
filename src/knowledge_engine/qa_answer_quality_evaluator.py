from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol

ANSWER_QUALITY_RUBRIC_VERSION = "ANSWER_QUALITY_RUBRIC_v1"
ANSWER_QUALITY_PASS_THRESHOLD = 85
ANSWER_QUALITY_CRITERION_MAX: dict[str, int] = {
    "directness_intent": 15,
    "correctness_grounding": 25,
    "evidence_coverage": 15,
    "completeness_facets": 15,
    "citation_support": 15,
    "hallucination_control": 10,
    "abstention_appropriateness": 5,
}
ANSWER_QUALITY_FORBIDDEN_DIMENSIONS = frozenset(
    {
        "homepage_fit",
        "visitor_intent_homepage_fit",
        "topic_balance",
        "corpus_representativeness",
        "distinctiveness",
        "non_duplication",
        "question_framing",
    }
)


class AnswerQualityEvaluationError(ValueError):
    """Evaluation payload violated the visitor Answer Quality contract."""


class AnswerQualityEvaluatorUnavailable(RuntimeError):
    """No qualified semantic evaluator is available for this runtime."""


@dataclass(frozen=True)
class AnswerQualityEvaluation:
    score: int
    result: Literal["pass", "fail"]
    criterion_scores: Mapping[str, int]
    hard_fail_codes: tuple[str, ...]
    failure_class: str | None
    failure_stage: str | None
    failure_signature: str | None
    evaluator_provider: str
    evaluator_model: str
    rubric_version: str = ANSWER_QUALITY_RUBRIC_VERSION

    def to_payload(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "result": self.result,
            "criterion_scores": dict(self.criterion_scores),
            "hard_fail_codes": list(self.hard_fail_codes),
            "failure_class": self.failure_class,
            "failure_stage": self.failure_stage,
            "failure_signature": self.failure_signature,
            "evaluator_provider": self.evaluator_provider,
            "evaluator_model": self.evaluator_model,
            "rubric_version": self.rubric_version,
            "threshold": ANSWER_QUALITY_PASS_THRESHOLD,
        }


class AnswerQualitySemanticEvaluator(Protocol):
    def evaluate(
        self,
        *,
        question: str,
        answer_payload: Mapping[str, Any],
        forensic_trace: Mapping[str, Any] | None,
    ) -> AnswerQualityEvaluation: ...


class UnavailableAnswerQualityEvaluator:
    def evaluate(
        self,
        *,
        question: str,
        answer_payload: Mapping[str, Any],
        forensic_trace: Mapping[str, Any] | None,
    ) -> AnswerQualityEvaluation:
        del question, answer_payload, forensic_trace
        raise AnswerQualityEvaluatorUnavailable("semantic answer-quality evaluator is not configured")


@dataclass(frozen=True)
class StaticAnswerQualityEvaluator:
    """Test-only deterministic evaluator adapter; never selected by production defaults."""

    evaluation: AnswerQualityEvaluation

    def evaluate(
        self,
        *,
        question: str,
        answer_payload: Mapping[str, Any],
        forensic_trace: Mapping[str, Any] | None,
    ) -> AnswerQualityEvaluation:
        del question, answer_payload, forensic_trace
        return validate_answer_quality_evaluation(self.evaluation)


def validate_answer_quality_evaluation(
    evaluation: AnswerQualityEvaluation,
) -> AnswerQualityEvaluation:
    if evaluation.rubric_version != ANSWER_QUALITY_RUBRIC_VERSION:
        raise AnswerQualityEvaluationError("unsupported answer-quality rubric version")
    provider = evaluation.evaluator_provider.strip()
    model = evaluation.evaluator_model.strip()
    if not provider or not model:
        raise AnswerQualityEvaluationError("evaluator provider/model provenance is required")

    criterion_scores = dict(evaluation.criterion_scores)
    forbidden = ANSWER_QUALITY_FORBIDDEN_DIMENSIONS.intersection(criterion_scores)
    if forbidden:
        raise AnswerQualityEvaluationError(
            "Suggested Questions dimensions are forbidden in Answer Quality: "
            + ",".join(sorted(forbidden))
        )
    if set(criterion_scores) != set(ANSWER_QUALITY_CRITERION_MAX):
        missing = set(ANSWER_QUALITY_CRITERION_MAX) - set(criterion_scores)
        extra = set(criterion_scores) - set(ANSWER_QUALITY_CRITERION_MAX)
        raise AnswerQualityEvaluationError(
            f"criterion set mismatch; missing={sorted(missing)} extra={sorted(extra)}"
        )

    total = 0
    for criterion, maximum in ANSWER_QUALITY_CRITERION_MAX.items():
        value = criterion_scores[criterion]
        if isinstance(value, bool) or not isinstance(value, int):
            raise AnswerQualityEvaluationError(f"{criterion} score must be an integer")
        if value < 0 or value > maximum:
            raise AnswerQualityEvaluationError(
                f"{criterion} score must be between 0 and {maximum}"
            )
        total += value
    if evaluation.score != total:
        raise AnswerQualityEvaluationError(
            f"score must equal criterion total ({total}), got {evaluation.score}"
        )
    if evaluation.score < 0 or evaluation.score > 100:
        raise AnswerQualityEvaluationError("score must be between 0 and 100")

    hard_fail_codes = tuple(
        sorted({str(code).strip() for code in evaluation.hard_fail_codes if str(code).strip()})
    )
    expected_result = (
        "pass"
        if evaluation.score >= ANSWER_QUALITY_PASS_THRESHOLD and not hard_fail_codes
        else "fail"
    )
    if evaluation.result != expected_result:
        raise AnswerQualityEvaluationError(
            f"result must be {expected_result} for score/hard-fail combination"
        )
    if evaluation.result == "fail" and not evaluation.failure_class:
        raise AnswerQualityEvaluationError("failed evaluations require failure_class")
    if evaluation.result == "fail" and not evaluation.failure_stage:
        raise AnswerQualityEvaluationError("failed evaluations require failure_stage")
    if evaluation.result == "fail" and not evaluation.failure_signature:
        raise AnswerQualityEvaluationError("failed evaluations require failure_signature")

    return AnswerQualityEvaluation(
        score=evaluation.score,
        result=evaluation.result,
        criterion_scores=criterion_scores,
        hard_fail_codes=hard_fail_codes,
        failure_class=evaluation.failure_class,
        failure_stage=evaluation.failure_stage,
        failure_signature=evaluation.failure_signature,
        evaluator_provider=provider,
        evaluator_model=model,
        rubric_version=evaluation.rubric_version,
    )


__all__ = [
    "ANSWER_QUALITY_CRITERION_MAX",
    "ANSWER_QUALITY_FORBIDDEN_DIMENSIONS",
    "ANSWER_QUALITY_PASS_THRESHOLD",
    "ANSWER_QUALITY_RUBRIC_VERSION",
    "AnswerQualityEvaluation",
    "AnswerQualityEvaluationError",
    "AnswerQualityEvaluatorUnavailable",
    "AnswerQualitySemanticEvaluator",
    "StaticAnswerQualityEvaluator",
    "UnavailableAnswerQualityEvaluator",
    "validate_answer_quality_evaluation",
]
