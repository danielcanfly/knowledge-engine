from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from .m14_feedback_contracts import PublicFeedbackReceipt
from .m14_public_contracts import PublicAskResponse
from .m14_security_contracts import PublicProductCapabilities

M14_ACCEPTANCE_SCHEMA = "knowledge-engine-m14-public-product-acceptance/v1"
M14_REQUIRED_SLICE_ISSUES: tuple[int, ...] = (191, 192, 194, 196, 198, 200)
M14_REQUIRED_SURFACES: tuple[str, ...] = ("api", "standalone_chat", "blog_widget")
M14_REQUIRED_TRANSPORTS: tuple[str, ...] = ("json", "sse")
M14_REQUIRED_STREAM_ORDER: tuple[str, ...] = (
    "meta",
    "answer",
    "citations",
    "source_cards",
    "done",
)
M14_REQUIRED_FEEDBACK_TYPES: tuple[str, ...] = (
    "helpful",
    "unhelpful",
    "factual_correction",
    "citation_issue",
    "missing_coverage",
    "unsafe_or_inappropriate",
    "other",
)
M14_FORBIDDEN_PRODUCT_CAPABILITIES: tuple[str, ...] = (
    "server_conversation_state",
    "distributed_rate_limit",
    "wildcard_origins_allowed",
    "cross_origin_credentials",
    "direct_source_write",
    "direct_production_write",
    "contact_identity_collected",
    "raw_query_collected",
    "raw_answer_collected",
    "attachments_supported",
)
M14_FORBIDDEN_CLOSEOUT_ACTIONS: tuple[str, ...] = (
    "source_package",
    "source_pr",
    "candidate_dispatch",
    "production_write",
    "production_promotion",
    "rollback",
    "physical_delete",
    "permanent_ledger_append",
    "arbitrary_url_fetch",
    "attachment_intake",
    "server_conversation_memory",
    "automated_correction_acceptance",
)


class M14Baseline(BaseModel):
    engine_main_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    canonical_source_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    production_release_id: str
    production_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    production_pointer_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    parent_issue: int = 190
    ledger_issue: int = 30
    ledger_state: Literal["open"] = "open"
    ledger_comments: int = Field(ge=0)


class M14Prerequisite(BaseModel):
    issue_number: int
    title: str
    state: Literal["closed"] = "closed"
    state_reason: Literal["completed"] = "completed"


class M14GovernanceBoundary(BaseModel):
    source_write_allowed: bool = False
    source_package_allowed: bool = False
    source_pr_allowed: bool = False
    candidate_dispatch_allowed: bool = False
    production_write_allowed: bool = False
    rollback_allowed: bool = False
    permanent_ledger_append_allowed: bool = False
    arbitrary_url_fetch_allowed: bool = False
    attachment_intake_allowed: bool = False
    server_conversation_memory_allowed: bool = False
    automated_correction_acceptance_allowed: bool = False


class M14AcceptanceArtifact(BaseModel):
    schema_version: str = M14_ACCEPTANCE_SCHEMA
    baseline: M14Baseline
    prerequisites: list[M14Prerequisite]
    answer: PublicAskResponse
    capabilities: PublicProductCapabilities
    feedback_receipt: PublicFeedbackReceipt
    governance: M14GovernanceBoundary = M14GovernanceBoundary()
    closure_issue: int = 202
    parent_issue: int = 190
    close_parent_after_guarded_merge: bool = True
    keep_permanent_ledger_open: bool = True
    forbidden_actions: list[str] = Field(
        default_factory=lambda: list(M14_FORBIDDEN_CLOSEOUT_ACTIONS)
    )
    artifact_sha256: str | None = None


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def acceptance_artifact_sha256(artifact: M14AcceptanceArtifact) -> str:
    payload = artifact.model_dump(mode="json")
    payload["artifact_sha256"] = None
    return hashlib.sha256((_canonical_json(payload) + "\n").encode("utf-8")).hexdigest()


def finalize_acceptance_artifact(
    artifact: M14AcceptanceArtifact,
) -> M14AcceptanceArtifact:
    return artifact.model_copy(
        update={"artifact_sha256": acceptance_artifact_sha256(artifact)}
    )


def validate_m14_public_product_acceptance(
    artifact: M14AcceptanceArtifact,
) -> M14AcceptanceArtifact:
    errors: list[str] = []
    required_issues = set(M14_REQUIRED_SLICE_ISSUES)
    seen_issues = {item.issue_number for item in artifact.prerequisites}
    missing = sorted(required_issues - seen_issues)
    if missing:
        errors.append(f"missing completed M14 prerequisite issues: {missing}")
    extra = sorted(seen_issues - required_issues)
    if extra:
        errors.append(f"unexpected prerequisite issues in M14 acceptance: {extra}")

    if artifact.baseline.parent_issue != artifact.parent_issue:
        errors.append("baseline parent issue does not match closure parent issue")
    if artifact.baseline.ledger_issue == artifact.parent_issue:
        errors.append("ledger issue and parent issue must be distinct")
    if artifact.baseline.ledger_state != "open":
        errors.append("permanent ledger must remain open")
    if not artifact.keep_permanent_ledger_open:
        errors.append("closure attempted to close or mutate permanent ledger")

    answer = artifact.answer
    if answer.status != "answered":
        errors.append("public product acceptance requires an answered public response")
    if answer.audience != "public":
        errors.append("acceptance answer must be scoped to public audience")
    if answer.release_id != artifact.baseline.production_release_id:
        errors.append("answer release does not match production release baseline")
    if not answer.answer or not answer.answer.strip():
        errors.append("answered response must include answer text")
    if not answer.citations:
        errors.append("answered response must include inspectable citations")
    if not answer.source_cards:
        errors.append("answered response must include inspectable source cards")
    citation_ids = {citation.citation_id for citation in answer.citations}
    card_ids = {card.source_card_id for card in answer.source_cards}
    for citation in answer.citations:
        if citation.source_card_id not in card_ids:
            errors.append(f"citation {citation.citation_id} is missing a source card")
        if citation.uri.startswith(("s3://", "r2://", "file://")):
            errors.append(f"citation {citation.citation_id} leaks a private URI")
    for card in answer.source_cards:
        if not set(card.citation_ids).issubset(citation_ids):
            errors.append(f"source card {card.source_card_id} references unknown citations")
        if card.uri.startswith(("s3://", "r2://", "file://")):
            errors.append(f"source card {card.source_card_id} leaks a private URI")

    capabilities = artifact.capabilities
    if capabilities.surfaces != list(M14_REQUIRED_SURFACES):
        errors.append("public surfaces do not match M14 product contract")
    if capabilities.transports != list(M14_REQUIRED_TRANSPORTS):
        errors.append("public transports do not match M14 product contract")
    if capabilities.session_mode != "stateless":
        errors.append("public product must remain stateless")
    if capabilities.default_audience != "public":
        errors.append("public product default audience must be public")
    if capabilities.stream_event_order != list(M14_REQUIRED_STREAM_ORDER):
        errors.append("stream event order does not match M14 product contract")
    if capabilities.ask_path != "/v1/ask":
        errors.append("ask path changed unexpectedly")
    if capabilities.stream_path != "/v1/ask/stream":
        errors.append("stream path changed unexpectedly")
    if capabilities.standalone_path != "/ask":
        errors.append("standalone path changed unexpectedly")
    if capabilities.widget_script_path != "/embed/ask.js":
        errors.append("widget script path changed unexpectedly")
    if capabilities.feedback.path != "/v1/feedback":
        errors.append("feedback path changed unexpectedly")
    if capabilities.feedback.feedback_types != list(M14_REQUIRED_FEEDBACK_TYPES):
        errors.append("feedback type list changed unexpectedly")
    if not capabilities.feedback.immutable_intake:
        errors.append("feedback intake must be immutable")
    if not capabilities.feedback.pending_review_queue:
        errors.append("feedback must publish to pending-review queue")
    if not capabilities.security.anonymous_public_access:
        errors.append("public product must accept anonymous public questions")
    if not capabilities.security.elevated_audience_requires_authentication:
        errors.append("elevated audiences must require authentication")
    if capabilities.security.cors_mode not in {"same_origin", "exact_allowlist"}:
        errors.append("public CORS mode must be same-origin or exact allowlist")

    capability_payload = capabilities.model_dump(mode="json")
    forbidden_values = {
        "server_conversation_state": capability_payload["security"]["server_conversation_state"],
        "distributed_rate_limit": capability_payload["security"]["distributed_rate_limit"],
        "wildcard_origins_allowed": capability_payload["security"]["wildcard_origins_allowed"],
        "cross_origin_credentials": capability_payload["security"]["cross_origin_credentials"],
        "direct_source_write": capability_payload["feedback"]["direct_source_write"],
        "direct_production_write": capability_payload["feedback"]["direct_production_write"],
        "contact_identity_collected": capability_payload["feedback"]["contact_identity_collected"],
        "raw_query_collected": capability_payload["feedback"]["raw_query_collected"],
        "raw_answer_collected": capability_payload["feedback"]["raw_answer_collected"],
        "attachments_supported": capability_payload["feedback"]["attachments_supported"],
    }
    for field in M14_FORBIDDEN_PRODUCT_CAPABILITIES:
        if forbidden_values[field] is not False:
            errors.append(f"forbidden capability is enabled: {field}")

    receipt = artifact.feedback_receipt
    if receipt.status not in {"accepted", "duplicate"}:
        errors.append("feedback receipt must be accepted or duplicate")
    if receipt.feedback_type not in M14_REQUIRED_FEEDBACK_TYPES:
        errors.append("feedback receipt type is outside the public product contract")
    if receipt.request_id != answer.request_id:
        errors.append("feedback receipt must bind to the accepted answer request_id")
    if receipt.release_id != answer.release_id:
        errors.append("feedback receipt must bind to the accepted answer release_id")
    if receipt.audience != answer.audience:
        errors.append("feedback receipt must bind to the accepted answer audience")
    if receipt.curation_status != "pending_review":
        errors.append("feedback must enter pending review rather than auto-apply")
    if receipt.source_write_performed:
        errors.append("feedback must not write Source")
    if receipt.production_write_performed:
        errors.append("feedback must not mutate production")

    governance_payload = artifact.governance.model_dump(mode="json")
    for name, value in governance_payload.items():
        if value is not False:
            errors.append(f"governance boundary unexpectedly enabled: {name}")
    if "permanent_ledger_append" not in artifact.forbidden_actions:
        errors.append("permanent ledger append must remain a forbidden closeout action")

    finalized = finalize_acceptance_artifact(artifact)
    if artifact.artifact_sha256 not in {None, finalized.artifact_sha256}:
        errors.append("acceptance artifact digest does not match canonical payload")

    if errors:
        raise ValueError("M14 public product acceptance failed: " + "; ".join(errors))
    return finalized
