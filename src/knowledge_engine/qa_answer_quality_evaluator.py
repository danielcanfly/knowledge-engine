# ruff: noqa: E501

from __future__ import annotations

import hashlib
import json
import re
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
    evaluator_version: str = "aq-semantic-evaluator/v1"
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
            "evaluator_version": self.evaluator_version,
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


class AnswerQualityProvider(Protocol):
    """Existing repo provider seam used by the semantic evaluator adapter."""

    def call(self, payload: Mapping[str, Any], call_class: str) -> Mapping[str, Any]: ...


SEMANTIC_EVALUATOR_VERSION = "aq-semantic-evaluator/v1"
SEMANTIC_EVALUATION_CALL_CLASS = "answer_quality_evaluation"
_DETERMINISTIC_HARD_FAILS = {
    "UNSUPPORTED_ACCEPTED_CLAIMS": "unsupported_accepted_claims",
    "MATERIAL_CLAIM_SUPPORT_UNVERIFIED": "material_claim_support_verified",
    "CITATION_LOCATOR_INVALID": "citation_locator_valid",
}


def deterministic_hard_fail_codes(answer_payload: Mapping[str, Any]) -> tuple[str, ...]:
    """Return runtime-owned failures; model output cannot override these facts."""
    integrity = answer_payload.get("integrity")
    integrity = integrity if isinstance(integrity, Mapping) else {}
    codes = {
        code
        for code, field in _DETERMINISTIC_HARD_FAILS.items()
        if (field == "unsupported_accepted_claims" and int(integrity.get(field, 0) or 0) > 0)
        or (field != "unsupported_accepted_claims" and integrity.get(field) is False)
    }
    status_value = str(
        answer_payload.get("terminal_status") or answer_payload.get("status") or ""
    ).casefold()
    if any(marker in status_value for marker in ("error", "invalid", "failed")):
        codes.add("RUNTIME_OR_PROVIDER_FAILURE")
    answer = str(answer_payload.get("answer_text") or answer_payload.get("answer") or "").strip()
    safe_abstention = bool(answer_payload.get("safe_abstention")) or status_value in {
        "not_found",
        "abstain",
        "safe_abstain",
    }
    evidence = any(
        isinstance(answer_payload.get(key), list) and answer_payload.get(key)
        for key in ("selected_evidence", "citations", "sources", "source_cards")
    )
    if not answer and not safe_abstention:
        codes.add("EMPTY_ANSWER")
    if answer and not safe_abstention and not evidence:
        codes.add("ANSWER_WITHOUT_MEANINGFUL_EVIDENCE")
    reason_codes = answer_payload.get("reason_codes")
    if (
        safe_abstention
        and not (isinstance(reason_codes, list) and reason_codes)
        and status_value not in {"not_found", "abstain", "safe_abstain"}
    ):
        codes.add("UNEXPLAINED_ABSTENTION")
    return tuple(sorted(codes))


def build_semantic_evaluation_input(
    *, question: str, answer_payload: Mapping[str, Any], forensic_trace: Mapping[str, Any] | None
) -> dict[str, Any]:
    """Build a bounded, evidence-aware package; secrets are excluded by construction."""
    allowed = {
        "status",
        "terminal_status",
        "answer_text",
        "answer",
        "safe_abstention",
        "reason_codes",
        "citations",
        "sources",
        "source_cards",
        "answer_claims",
        "semantic_closure",
        "selected_evidence",
        "evidence_utilization_trace",
        "retrieval",
        "provider_routing",
        "integrity",
        "identities",
        "canonical_runtime",
    }
    payload = {key: answer_payload[key] for key in allowed if key in answer_payload}
    package = {"question": " ".join(str(question).split()), "answer": payload}
    if forensic_trace:
        package["runtime_trace"] = {
            key: forensic_trace[key]
            for key in ("timing", "provider_events", "correlation_id", "sse_terminal")
            if key in forensic_trace
        }
    return package


def _parse_provider_json(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    text = str(value or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AnswerQualityEvaluationError("semantic evaluator output is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise AnswerQualityEvaluationError("semantic evaluator output must be a JSON object")
    return parsed


class ProviderAnswerQualityEvaluator:
    """Evidence-aware semantic adapter backed by an existing provider client."""

    def __init__(
        self,
        provider: AnswerQualityProvider,
        *,
        provider_name: str,
        model: str,
        evaluator_version: str = SEMANTIC_EVALUATOR_VERSION,
    ) -> None:
        self.provider = provider
        self.provider_name = provider_name.strip()
        self.model = model.strip()
        self.evaluator_version = evaluator_version.strip()

    def evaluate(
        self,
        *,
        question: str,
        answer_payload: Mapping[str, Any],
        forensic_trace: Mapping[str, Any] | None,
    ) -> AnswerQualityEvaluation:
        if not self.provider_name or not self.model:
            raise AnswerQualityEvaluationError("evaluator provider/model provenance is required")
        package = build_semantic_evaluation_input(
            question=question, answer_payload=answer_payload, forensic_trace=forensic_trace
        )
        prompt = (
            "Evaluate only the backend answer quality using the supplied question, answer, "
            "citations, selected evidence, retrieval and integrity context. Do not use outside "
            "knowledge. Do not score homepage or Suggested Questions properties. Return JSON "
            "with exactly criterion_scores (the seven fixed names, integer values), hard_fail_codes, "
            "failure_class, failure_stage, and failure_signature. The server computes total and verdict."
        )
        raw = self.provider.call(
            {
                "model": self.model,
                "max_tokens": 700,
                "temperature": 0,
                "stream": False,
                "system": prompt,
                "messages": [{"role": "user", "content": json.dumps(package, ensure_ascii=False)}],
            },
            SEMANTIC_EVALUATION_CALL_CLASS,
        )
        output = _parse_provider_json(raw.get("text") if isinstance(raw, Mapping) else raw)
        criteria = output.get("criterion_scores", output.get("criteria"))
        if not isinstance(criteria, Mapping):
            raise AnswerQualityEvaluationError("criterion_scores object is required")
        normalized_criteria: dict[str, int] = {}
        for name, value in criteria.items():
            if isinstance(value, Mapping):
                value = value.get("score")
            normalized_criteria[str(name)] = value
        model_codes = output.get("hard_fail_codes", output.get("hard_fail_reasons", []))
        if not isinstance(model_codes, list):
            raise AnswerQualityEvaluationError("hard_fail_codes must be a list")
        codes = tuple(
            sorted(
                set(str(code).strip() for code in model_codes if str(code).strip())
                | set(deterministic_hard_fail_codes(answer_payload))
            )
        )
        score = sum(
            value
            for name, value in normalized_criteria.items()
            if name in ANSWER_QUALITY_CRITERION_MAX
            and isinstance(value, int)
            and not isinstance(value, bool)
        )
        result = "pass" if score >= ANSWER_QUALITY_PASS_THRESHOLD and not codes else "fail"
        failure_class = output.get("failure_class")
        failure_stage = output.get("failure_stage")
        failure_signature = output.get("failure_signature")
        if result == "fail":
            failure_class = str(failure_class or "quality_below_threshold")
            failure_stage = str(failure_stage or "answer_quality")
            failure_signature = str(
                failure_signature
                or hashlib.sha256(
                    json.dumps({"codes": codes, "score": score}, sort_keys=True).encode()
                ).hexdigest()[:24]
            )
        evaluation = AnswerQualityEvaluation(
            score=score,
            result=result,
            criterion_scores=normalized_criteria,
            hard_fail_codes=codes,
            failure_class=failure_class,
            failure_stage=failure_stage,
            failure_signature=failure_signature,
            evaluator_provider=self.provider_name,
            evaluator_model=self.model,
            evaluator_version=self.evaluator_version,
        )
        return validate_answer_quality_evaluation(evaluation)


class UnavailableAnswerQualityEvaluator:
    def evaluate(
        self,
        *,
        question: str,
        answer_payload: Mapping[str, Any],
        forensic_trace: Mapping[str, Any] | None,
    ) -> AnswerQualityEvaluation:
        del question, answer_payload, forensic_trace
        raise AnswerQualityEvaluatorUnavailable(
            "semantic answer-quality evaluator is not configured"
        )


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
            raise AnswerQualityEvaluationError(f"{criterion} score must be between 0 and {maximum}")
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
        evaluator_version=evaluation.evaluator_version,
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
    "AnswerQualityProvider",
    "ProviderAnswerQualityEvaluator",
    "SEMANTIC_EVALUATOR_VERSION",
    "SEMANTIC_EVALUATION_CALL_CLASS",
    "build_semantic_evaluation_input",
    "deterministic_hard_fail_codes",
    "StaticAnswerQualityEvaluator",
    "UnavailableAnswerQualityEvaluator",
    "validate_answer_quality_evaluation",
]
