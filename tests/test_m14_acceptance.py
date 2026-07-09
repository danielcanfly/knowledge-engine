from __future__ import annotations

from pathlib import Path

import pytest

from knowledge_engine.config import Settings
from knowledge_engine.m14_acceptance import (
    M14_ACCEPTANCE_SCHEMA,
    M14AcceptanceArtifact,
    M14Baseline,
    M14Prerequisite,
    finalize_acceptance_artifact,
    validate_m14_public_product_acceptance,
)
from knowledge_engine.m14_feedback_contracts import PublicFeedbackReceipt
from knowledge_engine.m14_interfaces import PUBLIC_STREAM_SCHEMA
from knowledge_engine.m14_public_contracts import PublicAskResponse
from knowledge_engine.m14_security_contracts import public_product_capabilities


def _baseline() -> M14Baseline:
    return M14Baseline(
        engine_main_sha="f4ae4d3469d9fcf734ca3466d4cd98727fa48620",
        canonical_source_sha="2126db2ed4d372d3d61464fe31a86fc0243a1f24",
        production_release_id="20260708T040116Z-69a9f445699a",
        production_manifest_sha256=(
            "2b2630cfe3e8a6e25a8f210d68c70f3b9a31b3b26f33c6e3e41b8cc1676fc0bb"
        ),
        production_pointer_sha256=(
            "38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5"
        ),
        ledger_comments=13,
    )


def _prerequisites() -> list[M14Prerequisite]:
    return [
        M14Prerequisite(issue_number=191, title="M14.1: Public Query API and Contracts"),
        M14Prerequisite(issue_number=192, title="M14.2: Wiki-First Retrieval Experience"),
        M14Prerequisite(issue_number=194, title="M14.3: Citation Payload and Source Cards"),
        M14Prerequisite(issue_number=196, title="M14.4: Public Ask AI Interfaces"),
        M14Prerequisite(issue_number=198, title="M14.5: Audience, Security and Abuse Controls"),
        M14Prerequisite(issue_number=200, title="M14.6: Feedback and Correction Intake"),
    ]


def _answer() -> PublicAskResponse:
    citation_id = "cite_" + "1" * 32
    card_id = "card_" + "2" * 32
    return PublicAskResponse(
        answer="Knowledge Compiler: Verify every public answer against release-bound sources. [1]",
        status="answered",
        citations=[
            {
                "citation_id": citation_id,
                "ordinal": 1,
                "source_card_id": card_id,
                "source_id": "source-public-product",
                "source_kind": "web",
                "uri": "https://example.com/public-product-acceptance",
                "retrieved_at": "2026-07-10T00:00:00Z",
                "concept_id": "concepts/knowledge-compiler",
                "section_id": "concepts/knowledge-compiler#public-product",
                "citation_scope": "claim",
                "claim_ids": ["claim-public-product"],
                "support": "direct",
                "locator": {"heading": "Public product acceptance"},
                "claim_confidence": 0.99,
                "review_status": "human_approved",
                "derivation_type": "synthesized",
            }
        ],
        source_cards=[
            {
                "source_card_id": card_id,
                "ordinal": 1,
                "source_id": "source-public-product",
                "title": "Public Product Acceptance Fixture",
                "publisher": "Knowledge Engine",
                "display_host": "example.com",
                "source_kind": "web",
                "uri": "https://example.com/public-product-acceptance",
                "retrieved_at": "2026-07-10T00:00:00Z",
                "published_at": None,
                "snapshot_available": True,
                "integrity_sha256": "a" * 64,
                "citation_ids": [citation_id],
                "concept_ids": ["concepts/knowledge-compiler"],
                "section_ids": ["concepts/knowledge-compiler#public-product"],
                "claim_ids": ["claim-public-product"],
            }
        ],
        concept_ids=["concepts/knowledge-compiler"],
        release_id="20260708T040116Z-69a9f445699a",
        request_id="req_" + "3" * 32,
        audience="public",
        confidence=0.94,
        not_found_reason=None,
    )


def _receipt(answer: PublicAskResponse) -> PublicFeedbackReceipt:
    return PublicFeedbackReceipt(
        feedback_id="fb_" + "4" * 32,
        status="accepted",
        feedback_type="factual_correction",
        request_id=answer.request_id,
        release_id=answer.release_id,
        audience=answer.audience,
        received_at="2026-07-10T00:00:01Z",
        curation_status="pending_review",
        privacy_redactions_applied=True,
        source_write_performed=False,
        production_write_performed=False,
    )


def _settings() -> Settings:
    return Settings(
        app_env="test",
        auth_mode="disabled",
        jwt_issuer=None,
        jwt_jwks_url=None,
        jwt_audience=None,
        jwt_default_audiences=("public",),
        object_store_backend="filesystem",
        filesystem_store_root=Path(".artifacts/test-store"),
        r2_endpoint_url=None,
        r2_bucket=None,
        r2_access_key_id=None,
        r2_secret_access_key=None,
        r2_region="auto",
        channel="production",
        cache_dir=Path(".artifacts/test-cache"),
        log_level="INFO",
    )


def _artifact() -> M14AcceptanceArtifact:
    answer = _answer()
    return M14AcceptanceArtifact(
        baseline=_baseline(),
        prerequisites=_prerequisites(),
        answer=answer,
        capabilities=public_product_capabilities(_settings()),
        feedback_receipt=_receipt(answer),
    )


def test_m14_acceptance_artifact_accepts_full_public_product_contract() -> None:
    accepted = validate_m14_public_product_acceptance(_artifact())
    citation = accepted.answer.citations[0]
    source_card = accepted.answer.source_cards[0]

    assert accepted.schema_version == M14_ACCEPTANCE_SCHEMA
    assert accepted.artifact_sha256 is not None
    assert len(accepted.artifact_sha256) == 64
    assert accepted.baseline.parent_issue == 190
    assert accepted.baseline.ledger_issue == 30
    assert accepted.baseline.ledger_state == "open"
    assert accepted.keep_permanent_ledger_open is True
    assert accepted.answer.status == "answered"
    assert citation.source_card_id == source_card.source_card_id
    assert accepted.capabilities.stream_schema_version == PUBLIC_STREAM_SCHEMA
    assert accepted.capabilities.feedback.immutable_intake is True
    assert accepted.feedback_receipt.curation_status == "pending_review"
    assert accepted.governance.source_write_allowed is False
    assert accepted.governance.production_write_allowed is False
    assert "permanent_ledger_append" in accepted.forbidden_actions


def test_m14_acceptance_requires_all_completed_prerequisite_slices() -> None:
    artifact = _artifact()
    artifact.prerequisites = artifact.prerequisites[:-1]
    with pytest.raises(ValueError, match="missing completed M14 prerequisite issues"):
        validate_m14_public_product_acceptance(artifact)


def test_m14_acceptance_rejects_uncited_or_non_public_answer() -> None:
    artifact = _artifact()
    artifact.answer = artifact.answer.model_copy(update={"audience": "internal"})
    artifact.feedback_receipt = artifact.feedback_receipt.model_copy(
        update={"audience": "internal"}
    )
    with pytest.raises(ValueError, match="public audience"):
        validate_m14_public_product_acceptance(artifact)

    artifact = _artifact()
    artifact.answer = artifact.answer.model_copy(
        update={"citations": [], "source_cards": []}
    )
    with pytest.raises(ValueError, match="inspectable citations"):
        validate_m14_public_product_acceptance(artifact)


def test_m14_acceptance_rejects_feedback_or_governance_mutation() -> None:
    artifact = _artifact()
    artifact.feedback_receipt = artifact.feedback_receipt.model_copy(
        update={"source_write_performed": True}
    )
    with pytest.raises(ValueError, match="must not write Source"):
        validate_m14_public_product_acceptance(artifact)

    artifact = _artifact()
    artifact.governance = artifact.governance.model_copy(
        update={"permanent_ledger_append_allowed": True}
    )
    with pytest.raises(ValueError, match="governance boundary"):
        validate_m14_public_product_acceptance(artifact)


def test_m14_acceptance_digest_is_canonical_and_detects_tampering() -> None:
    accepted = finalize_acceptance_artifact(_artifact())
    replay = validate_m14_public_product_acceptance(accepted)
    assert replay.artifact_sha256 == accepted.artifact_sha256

    tampered = accepted.model_copy(update={"artifact_sha256": "0" * 64})
    with pytest.raises(ValueError, match="digest"):
        validate_m14_public_product_acceptance(tampered)
