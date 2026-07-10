from __future__ import annotations

import hashlib
import json
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

M15_FEEDBACK_TRIAGE_SCHEMA = "knowledge-engine-feedback-triage/v1"


class FeedbackCategory(StrEnum):
    FACTUAL_ERROR = "factual_error"
    STALE_INFORMATION = "stale_information"
    CITATION_PROBLEM = "citation_problem"
    ACCESS_PROBLEM = "access_problem"
    QUALITY_PROBLEM = "quality_problem"


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TriageState(StrEnum):
    ACTIONABLE = "actionable"
    DUPLICATE = "duplicate"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    POLICY_REJECTED = "policy_rejected"
    NO_CHANGE = "no_change"


class DispositionReason(StrEnum):
    EVIDENCE_ACCEPTED = "evidence_accepted"
    DUPLICATE_FINGERPRINT = "duplicate_fingerprint"
    CONFIDENCE_TOO_LOW = "confidence_too_low"
    IDENTITY_DRIFT = "identity_drift"
    UNSAFE_EVIDENCE = "unsafe_evidence"
    INFORMATIONAL_ONLY = "informational_only"


class CandidateState(StrEnum):
    PENDING_HUMAN_REVIEW = "pending_human_review"


_FORBIDDEN_FRAGMENTS = (
    "bearer ",
    "authorization:",
    "cookie:",
    "jwt",
    "raw_query",
    "raw_answer",
    "private excerpt",
    "s3://",
    "r2://",
    "file://",
)


class FeedbackEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feedback_id: str = Field(min_length=3, max_length=128, pattern=r"^[a-zA-Z0-9._:-]+$")
    category: FeedbackCategory
    severity: Severity
    confidence: float = Field(ge=0, le=1)
    summary_code: str = Field(min_length=3, max_length=64, pattern=r"^[a-z0-9._:-]+$")
    target_id: str = Field(min_length=3, max_length=128, pattern=r"^[a-zA-Z0-9._:-]+$")
    engine_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    expected_engine_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    source_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    expected_source_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    release_id: str = Field(min_length=8, max_length=128)
    audience: str = Field(pattern=r"^(private|internal|public)$")

    @model_validator(mode="after")
    def reject_unsafe_values(self) -> "FeedbackEvidence":
        encoded = json.dumps(self.model_dump(mode="json"), sort_keys=True).lower()
        if any(fragment in encoded for fragment in _FORBIDDEN_FRAGMENTS):
            raise ValueError("feedback evidence contains forbidden private or secret material")
        return self


class CorrectionCandidate(BaseModel):
    schema_version: str = M15_FEEDBACK_TRIAGE_SCHEMA
    candidate_id: str
    state: CandidateState = CandidateState.PENDING_HUMAN_REVIEW
    target_id: str
    category: FeedbackCategory
    severity: Severity
    audience: str
    evidence_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class TriageDecision(BaseModel):
    feedback_id: str
    state: TriageState
    reason: DispositionReason
    candidate: CorrectionCandidate | None = None


class FeedbackTriageReport(BaseModel):
    schema_version: str = M15_FEEDBACK_TRIAGE_SCHEMA
    decisions: list[TriageDecision]
    artifact_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class FeedbackAuthority(BaseModel):
    source_write_allowed: bool = False
    source_pr_allowed: bool = False
    candidate_dispatch_allowed: bool = False
    automatic_correction_allowed: bool = False
    merge_allowed: bool = False
    production_write_allowed: bool = False
    permanent_ledger_append_allowed: bool = False

    @model_validator(mode="after")
    def reject_authority(self) -> "FeedbackAuthority":
        enabled = sorted(name for name, value in self.model_dump().items() if value)
        if enabled:
            raise ValueError(f"M15.6 is review-gated; authority enabled: {enabled}")
        return self


def _canonical_sha256(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def feedback_fingerprint(item: FeedbackEvidence) -> str:
    payload = item.model_dump(mode="json")
    payload.pop("feedback_id")
    return _canonical_sha256(payload)


def finalize_candidate(candidate: CorrectionCandidate) -> CorrectionCandidate:
    payload = candidate.model_dump(mode="json")
    payload["artifact_sha256"] = None
    digest = _canonical_sha256(payload)
    if candidate.artifact_sha256 not in {None, digest}:
        raise ValueError("correction candidate digest mismatch")
    return candidate.model_copy(update={"artifact_sha256": digest})


def triage_feedback(items: list[FeedbackEvidence], *, minimum_confidence: float = 0.75) -> FeedbackTriageReport:
    if minimum_confidence < 0 or minimum_confidence > 1:
        raise ValueError("minimum_confidence must be between 0 and 1")
    seen: set[str] = set()
    decisions: list[TriageDecision] = []
    for item in sorted(items, key=lambda value: value.feedback_id):
        fingerprint = feedback_fingerprint(item)
        candidate = None
        if item.engine_sha != item.expected_engine_sha or item.source_sha != item.expected_source_sha:
            state, reason = TriageState.POLICY_REJECTED, DispositionReason.IDENTITY_DRIFT
        elif fingerprint in seen:
            state, reason = TriageState.DUPLICATE, DispositionReason.DUPLICATE_FINGERPRINT
        elif item.confidence < minimum_confidence:
            state, reason = TriageState.INSUFFICIENT_EVIDENCE, DispositionReason.CONFIDENCE_TOO_LOW
        elif item.category == FeedbackCategory.QUALITY_PROBLEM and item.severity == Severity.LOW:
            state, reason = TriageState.NO_CHANGE, DispositionReason.INFORMATIONAL_ONLY
        else:
            state, reason = TriageState.ACTIONABLE, DispositionReason.EVIDENCE_ACCEPTED
            candidate = finalize_candidate(
                CorrectionCandidate(
                    candidate_id=f"candidate:{fingerprint[:24]}",
                    target_id=item.target_id,
                    category=item.category,
                    severity=item.severity,
                    audience=item.audience,
                    evidence_fingerprint=fingerprint,
                )
            )
        seen.add(fingerprint)
        decisions.append(TriageDecision(feedback_id=item.feedback_id, state=state, reason=reason, candidate=candidate))
    decisions.sort(key=lambda value: (value.feedback_id, value.state.value, value.reason.value))
    report = FeedbackTriageReport(decisions=decisions)
    return finalize_report(report)


def finalize_report(report: FeedbackTriageReport) -> FeedbackTriageReport:
    payload = report.model_dump(mode="json")
    payload["artifact_sha256"] = None
    digest = _canonical_sha256(payload)
    if report.artifact_sha256 not in {None, digest}:
        raise ValueError("feedback triage report digest mismatch")
    return report.model_copy(update={"artifact_sha256": digest})
