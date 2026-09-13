from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Protocol

from .errors import ReleaseConflictError
from .qa_answer_quality_evaluator import (
    ANSWER_QUALITY_RUBRIC_VERSION,
    AnswerQualitySemanticEvaluator,
)
from .storage import ObjectStore, sha256_bytes
from .suggested_questions_scoring import (
    SUGGESTED_QUESTIONS_RUBRIC_VERSION,
    SuggestedQuestionsEvaluationError,
    SuggestedQuestionsEvaluatorUnavailable,
    SuggestedQuestionsSemanticEvaluator,
    scoring_contract_fingerprint,
    semantic_answer_overlap,
)

PROMOTION_SCHEMA = "knowledge-engine-suggested-questions-promotion/v1"
PROMOTION_PREFIX = "admin/suggested-questions/promotions"
PROMOTION_MAX_CANDIDATES = 20


class SuggestedQuestionsPromotionError(ValueError):
    pass


class SuggestedQuestionsPromotionUnavailable(RuntimeError):
    pass


class SuggestedQuestionQaRepository(Protocol):
    def get_event(self, event_id: str) -> dict[str, Any]: ...

    def record_suggested_questions_evaluation(
        self,
        event_id: str,
        *,
        status: str,
        score: int | None,
        result: str | None,
        rubric_version: str,
        promotion_id: str,
        production_published: bool = False,
        publication_revision: str | None = None,
    ) -> dict[str, Any]: ...


class SuggestedQuestionRerunner(Protocol):
    def run(self, question: str) -> Mapping[str, Any]: ...


class SuggestedQuestionPublisher(Protocol):
    def publish(
        self,
        *,
        base_revision: str,
        questions: Sequence[str],
        operation_id: str,
    ) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class PromotionPreview:
    payload: Mapping[str, Any]

    @property
    def promotion_id(self) -> str:
        return str(self.payload["promotion_id"])


class ObjectStoreSuggestedQuestionsPromotionStore:
    def __init__(self, store: ObjectStore, *, prefix: str = PROMOTION_PREFIX) -> None:
        self.store = store
        self.prefix = prefix.strip("/")

    def _key(self, promotion_id: str) -> str:
        return f"{self.prefix}/{promotion_id}.json"

    def get(self, promotion_id: str) -> dict[str, Any]:
        try:
            payload = json.loads(self.store.get(self._key(promotion_id)).decode("utf-8"))
        except FileNotFoundError as exc:
            raise KeyError(promotion_id) from exc
        if not isinstance(payload, dict) or payload.get("schema_version") != PROMOTION_SCHEMA:
            raise SuggestedQuestionsPromotionError("invalid stored promotion record")
        return payload

    def create(self, promotion_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        body_payload = dict(payload)
        body_payload["schema_version"] = PROMOTION_SCHEMA
        body_payload["promotion_id"] = promotion_id
        body_payload.setdefault("record_revision", 1)
        body = _json_bytes(body_payload)
        key = self._key(promotion_id)
        try:
            self.store.put(
                key,
                body,
                content_type="application/json",
                sha256=sha256_bytes(body),
                only_if_absent=True,
            )
            return body_payload
        except ReleaseConflictError:
            existing = self.get(promotion_id)
            if _json_bytes(existing) != body:
                raise SuggestedQuestionsPromotionError("promotion operation identity already contains different content")
            return existing

    def replace(self, promotion_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        key = self._key(promotion_id)
        metadata = self.store.head(key)
        if metadata is None:
            raise KeyError(promotion_id)
        current = self.get(promotion_id)
        next_payload = dict(payload)
        next_payload["schema_version"] = PROMOTION_SCHEMA
        next_payload["promotion_id"] = promotion_id
        next_payload["record_revision"] = int(current.get("record_revision", 1)) + 1
        body = _json_bytes(next_payload)
        self.store.put(
            key,
            body,
            content_type="application/json",
            sha256=sha256_bytes(body),
            expected_etag=metadata.etag,
        )
        return next_payload


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()


def _unique_ids(values: Sequence[str]) -> list[str]:
    if len(values) > PROMOTION_MAX_CANDIDATES:
        raise SuggestedQuestionsPromotionError(
            f"at most {PROMOTION_MAX_CANDIDATES} QA events may be previewed at once"
        )
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        item = str(raw).strip()
        if not item:
            raise SuggestedQuestionsPromotionError("event_ids must be non-empty")
        if item not in seen:
            result.append(item)
            seen.add(item)
    if not result:
        raise SuggestedQuestionsPromotionError("at least one event_id is required")
    return result


def _historically_eligible(event: Mapping[str, Any]) -> bool:
    evaluator = event.get("evaluator") if isinstance(event.get("evaluator"), Mapping) else {}
    suggested = (
        event.get("suggested_questions")
        if isinstance(event.get("suggested_questions"), Mapping)
        else {}
    )
    return bool(
        event.get("evaluation_status") == "ANSWERED"
        and event.get("result") == "pass"
        and evaluator.get("rubric_version") == ANSWER_QUALITY_RUBRIC_VERSION
        and suggested.get("eligible") is True
    )


def _answer_provenance(answer: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": answer.get("status"),
        "terminal_status": answer.get("terminal_status"),
        "trace_id": answer.get("trace_id"),
        "canonical_runtime": deepcopy(answer.get("canonical_runtime"))
        if isinstance(answer.get("canonical_runtime"), Mapping)
        else {},
        "identities": deepcopy(answer.get("identities"))
        if isinstance(answer.get("identities"), Mapping)
        else {},
        "citation_source_ids": [
            str(item.get("source_id") or item.get("id") or item.get("citation_id"))
            for item in answer.get("citations", [])
            if isinstance(item, Mapping)
            and (item.get("source_id") or item.get("id") or item.get("citation_id"))
        ][:40]
        if isinstance(answer.get("citations"), list)
        else [],
    }


def build_promotion_preview(
    *,
    promotion_id: str,
    event_ids: Sequence[str],
    qa_repository: SuggestedQuestionQaRepository,
    rerunner: SuggestedQuestionRerunner,
    aq_evaluator: AnswerQualitySemanticEvaluator,
    sq_evaluator: SuggestedQuestionsSemanticEvaluator,
    existing_questions: Sequence[str],
    source_revision: str,
    source_evidence_digest: str,
    observed_at: str,
) -> dict[str, Any]:
    selected = _unique_ids(event_ids)
    events: list[dict[str, Any]] = []
    for event_id in selected:
        try:
            event = qa_repository.get_event(event_id)
        except KeyError:
            events.append(
                {
                    "event_id": event_id,
                    "status": "rejected",
                    "reason_codes": ["QA_EVENT_NOT_FOUND"],
                }
            )
            continue
        events.append(event)

    batch_questions = [
        str(event.get("question") or "")
        for event in events
        if event.get("question") and event.get("status") != "rejected"
    ]
    candidates: list[dict[str, Any]] = []
    answer_by_event: dict[str, Mapping[str, Any]] = {}

    for event in events:
        event_id = str(event.get("event_id") or "")
        if event.get("status") == "rejected" and event.get("reason_codes") == ["QA_EVENT_NOT_FOUND"]:
            candidates.append(event)
            continue
        question = str(event.get("question") or "").strip()
        base = {
            "event_id": event_id,
            "question": question,
            "historical_aq": {
                "score": event.get("score"),
                "result": event.get("result"),
                "evaluation_status": event.get("evaluation_status"),
                "evaluator": deepcopy(event.get("evaluator"))
                if isinstance(event.get("evaluator"), Mapping)
                else {},
            },
        }
        if not _historically_eligible(event):
            base.update(status="rejected", reason_codes=["HISTORICAL_AQ_NOT_ELIGIBLE"])
            candidates.append(base)
            continue
        try:
            answer = dict(rerunner.run(question))
            current_aq = aq_evaluator.evaluate(
                question=question,
                answer_payload=answer,
                forensic_trace=None,
            )
        except Exception as exc:
            base.update(
                status="not_evaluated",
                reason_codes=["PROMOTION_RERUN_OR_AQ_UNAVAILABLE"],
                diagnostic=type(exc).__name__,
            )
            candidates.append(base)
            continue

        base["rerun"] = _answer_provenance(answer)
        base["current_aq"] = current_aq.to_payload()
        answer_by_event[event_id] = answer
        if current_aq.result != "pass":
            base.update(status="rejected", reason_codes=["CURRENT_AQ_NOT_PASS"])
            candidates.append(base)
            continue
        try:
            sq = sq_evaluator.evaluate(
                question=question,
                answer_payload=answer,
                existing_questions=existing_questions,
                batch_questions=batch_questions,
            )
        except (SuggestedQuestionsEvaluationError, SuggestedQuestionsEvaluatorUnavailable) as exc:
            base.update(
                status="not_evaluated",
                reason_codes=["SUGGESTED_QUESTIONS_EVALUATION_UNAVAILABLE"],
                diagnostic=type(exc).__name__,
            )
            candidates.append(base)
            continue
        base["suggested_questions_evaluation"] = sq.to_payload()
        base["status"] = "eligible" if sq.result == "pass" else "rejected"
        base["reason_codes"] = list(sq.hard_fail_codes)
        candidates.append(base)

    # Deterministic second guard for rerun-answer/citation overlap among otherwise eligible
    # candidates. This supplements, but does not replace, semantic duplicate judgment.
    eligible = [item for item in candidates if item.get("status") == "eligible"]
    for index, left in enumerate(eligible):
        if left.get("status") != "eligible":
            continue
        for right in eligible[index + 1 :]:
            if right.get("status") != "eligible":
                continue
            left_answer = answer_by_event.get(str(left["event_id"]))
            right_answer = answer_by_event.get(str(right["event_id"]))
            if left_answer is None or right_answer is None:
                continue
            overlap = semantic_answer_overlap(left_answer, right_answer)
            if (
                overlap["citation_source_jaccard"] >= 0.95
                and overlap["answer_token_jaccard"] >= 0.92
            ):
                left_score = int(left["suggested_questions_evaluation"]["score"])
                right_score = int(right["suggested_questions_evaluation"]["score"])
                loser = right
                winner = left
                if right_score > left_score or (
                    right_score == left_score and str(right["event_id"]) < str(left["event_id"])
                ):
                    loser, winner = left, right
                loser["status"] = "rejected"
                loser["reason_codes"] = sorted(
                    set(loser.get("reason_codes", [])) | {"DUPLICATE_BATCH"}
                )
                sq_payload = (
                    dict(loser.get("suggested_questions_evaluation"))
                    if isinstance(loser.get("suggested_questions_evaluation"), Mapping)
                    else {}
                )
                sq_payload["hard_fail_codes"] = sorted(
                    set(sq_payload.get("hard_fail_codes", [])) | {"DUPLICATE_BATCH"}
                )
                sq_payload["result"] = "fail"
                sq_payload["duplicate_of"] = winner.get("question")
                loser["suggested_questions_evaluation"] = sq_payload
                loser["duplicate_of_event_id"] = winner["event_id"]
                loser["answer_overlap"] = overlap

    return {
        "schema_version": PROMOTION_SCHEMA,
        "promotion_id": promotion_id,
        "status": "review_ready",
        "record_revision": 1,
        "created_at": observed_at,
        "base_revision": source_revision,
        "source_evidence_digest": source_evidence_digest,
        "scoring_contract": {
            "rubric_version": SUGGESTED_QUESTIONS_RUBRIC_VERSION,
            "fingerprint": scoring_contract_fingerprint(),
        },
        "requested_event_ids": selected,
        "candidates": candidates,
        "summary": {
            "requested": len(selected),
            "eligible": sum(1 for item in candidates if item.get("status") == "eligible"),
            "rejected": sum(1 for item in candidates if item.get("status") == "rejected"),
            "not_evaluated": sum(1 for item in candidates if item.get("status") == "not_evaluated"),
        },
        "publication": None,
    }



def record_preview_evaluations(
    record: Mapping[str, Any],
    qa_repository: SuggestedQuestionQaRepository,
) -> None:
    """Project a durable preview result onto QA events after the preview is stored."""
    promotion_id = str(record.get("promotion_id") or "")
    if not promotion_id:
        raise SuggestedQuestionsPromotionError("promotion record is missing promotion_id")
    for item in record.get("candidates", []):
        if not isinstance(item, Mapping):
            continue
        event_id = str(item.get("event_id") or "")
        if not event_id or item.get("question") is None:
            continue
        sq_payload = item.get("suggested_questions_evaluation")
        sq_score = sq_payload.get("score") if isinstance(sq_payload, Mapping) else None
        sq_result = sq_payload.get("result") if isinstance(sq_payload, Mapping) else None
        status = (
            "eligible"
            if item.get("status") == "eligible"
            else "not_evaluated"
            if item.get("status") == "not_evaluated"
            else "evaluated_rejected"
            if isinstance(sq_payload, Mapping)
            else "ineligible"
        )
        try:
            qa_repository.record_suggested_questions_evaluation(
                event_id,
                status=status,
                score=int(sq_score) if isinstance(sq_score, int) else None,
                result=str(sq_result) if sq_result is not None else None,
                rubric_version=SUGGESTED_QUESTIONS_RUBRIC_VERSION,
                promotion_id=promotion_id,
                production_published=False,
            )
        except (KeyError, AttributeError):
            continue

def publish_promotion(
    *,
    record: Mapping[str, Any],
    selected_event_ids: Sequence[str],
    current_source_revision: str,
    publisher: SuggestedQuestionPublisher,
    publish_operation_id: str,
    qa_repository: SuggestedQuestionQaRepository,
) -> dict[str, Any]:
    if record.get("status") == "published":
        publication = record.get("publication") if isinstance(record.get("publication"), Mapping) else {}
        prior_selection = [str(item) for item in publication.get("selected_event_ids", [])]
        chosen = _unique_ids(selected_event_ids)
        if chosen != prior_selection:
            raise SuggestedQuestionsPromotionError(
                "promotion was already published with a different candidate selection"
            )
        return dict(record)
    if record.get("status") != "review_ready":
        raise SuggestedQuestionsPromotionError("promotion is not review-ready")
    if str(record.get("base_revision")) != str(current_source_revision):
        raise ReleaseConflictError("Suggested Questions base revision changed after preview")
    chosen = _unique_ids(selected_event_ids)
    by_id = {
        str(item.get("event_id")): item
        for item in record.get("candidates", [])
        if isinstance(item, Mapping)
    }
    missing = [event_id for event_id in chosen if event_id not in by_id]
    if missing:
        raise SuggestedQuestionsPromotionError("selected event is not part of the preview")
    ineligible = [event_id for event_id in chosen if by_id[event_id].get("status") != "eligible"]
    if ineligible:
        raise SuggestedQuestionsPromotionError("only preview-eligible candidates may be published")
    questions = [str(by_id[event_id]["question"]) for event_id in chosen]
    publication = dict(
        publisher.publish(
            base_revision=current_source_revision,
            questions=questions,
            operation_id=publish_operation_id,
        )
    )
    if not publication.get("readback_verified"):
        raise SuggestedQuestionsPromotionError("homepage publication readback was not verified")
    updated = deepcopy(dict(record))
    updated["status"] = "published"
    updated["publication"] = {
        **publication,
        "selected_event_ids": chosen,
        "publish_operation_id": publish_operation_id,
    }
    for event_id in chosen:
        item = by_id[event_id]
        sq_payload = item.get("suggested_questions_evaluation")
        try:
            qa_repository.record_suggested_questions_evaluation(
                event_id,
                status="published",
                score=int(sq_payload.get("score")) if isinstance(sq_payload, Mapping) else None,
                result=str(sq_payload.get("result")) if isinstance(sq_payload, Mapping) else "pass",
                rubric_version=SUGGESTED_QUESTIONS_RUBRIC_VERSION,
                promotion_id=str(record["promotion_id"]),
                production_published=True,
                publication_revision=str(publication.get("revision") or "") or None,
            )
        except (KeyError, AttributeError):
            pass
    return updated


__all__ = [
    "ObjectStoreSuggestedQuestionsPromotionStore",
    "PROMOTION_MAX_CANDIDATES",
    "PROMOTION_SCHEMA",
    "PromotionPreview",
    "SuggestedQuestionPublisher",
    "SuggestedQuestionQaRepository",
    "SuggestedQuestionRerunner",
    "SuggestedQuestionsPromotionError",
    "SuggestedQuestionsPromotionUnavailable",
    "build_promotion_preview",
    "publish_promotion",
    "record_preview_evaluations",
]
