from __future__ import annotations

import argparse
import json
from pathlib import Path

from knowledge_engine.config import Settings
from knowledge_engine.m14_acceptance import (
    M14AcceptanceArtifact,
    M14Baseline,
    M14Prerequisite,
    validate_m14_public_product_acceptance,
)
from knowledge_engine.m14_feedback_contracts import PublicFeedbackReceipt
from knowledge_engine.m14_public_contracts import PublicAskResponse
from knowledge_engine.m14_security_contracts import public_product_capabilities


def _sample_answer(release_id: str) -> PublicAskResponse:
    citation_id = "cite_" + "1" * 32
    card_id = "card_" + "2" * 32
    return PublicAskResponse(
        answer="Knowledge Compiler: Public answers remain release-bound, cited and inspectable. [1]",
        status="answered",
        citations=[
            {
                "citation_id": citation_id,
                "ordinal": 1,
                "source_card_id": card_id,
                "source_id": "source-m14-acceptance",
                "source_kind": "web",
                "uri": "https://example.com/m14-public-product-acceptance",
                "retrieved_at": "2026-07-10T00:00:00Z",
                "concept_id": "concepts/knowledge-compiler",
                "section_id": "concepts/knowledge-compiler#public-product",
                "citation_scope": "claim",
                "claim_ids": ["claim-m14-public-product"],
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
                "source_id": "source-m14-acceptance",
                "title": "M14 Public Product Acceptance Fixture",
                "publisher": "Knowledge Engine",
                "display_host": "example.com",
                "source_kind": "web",
                "uri": "https://example.com/m14-public-product-acceptance",
                "retrieved_at": "2026-07-10T00:00:00Z",
                "published_at": None,
                "snapshot_available": True,
                "integrity_sha256": "a" * 64,
                "citation_ids": [citation_id],
                "concept_ids": ["concepts/knowledge-compiler"],
                "section_ids": ["concepts/knowledge-compiler#public-product"],
                "claim_ids": ["claim-m14-public-product"],
            }
        ],
        concept_ids=["concepts/knowledge-compiler"],
        release_id=release_id,
        request_id="req_" + "3" * 32,
        audience="public",
        confidence=0.95,
        not_found_reason=None,
    )


def _settings() -> Settings:
    return Settings.from_env()


def build_artifact(args: argparse.Namespace) -> M14AcceptanceArtifact:
    answer = _sample_answer(args.production_release_id)
    receipt = PublicFeedbackReceipt(
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
    return M14AcceptanceArtifact(
        baseline=M14Baseline(
            engine_main_sha=args.engine_sha,
            canonical_source_sha=args.canonical_source_sha,
            production_release_id=args.production_release_id,
            production_manifest_sha256=args.production_manifest_sha256,
            production_pointer_sha256=args.production_pointer_sha256,
            ledger_comments=args.ledger_comments,
        ),
        prerequisites=[
            M14Prerequisite(issue_number=191, title="M14.1: Public Query API and Contracts"),
            M14Prerequisite(issue_number=192, title="M14.2: Wiki-First Retrieval Experience"),
            M14Prerequisite(issue_number=194, title="M14.3: Citation Payload and Source Cards"),
            M14Prerequisite(issue_number=196, title="M14.4: Public Ask AI Interfaces"),
            M14Prerequisite(issue_number=198, title="M14.5: Audience, Security and Abuse Controls"),
            M14Prerequisite(issue_number=200, title="M14.6: Feedback and Correction Intake"),
        ],
        answer=answer,
        capabilities=public_product_capabilities(_settings()),
        feedback_receipt=receipt,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run M14.7 public product acceptance")
    parser.add_argument("--engine-sha", required=True)
    parser.add_argument("--canonical-source-sha", required=True)
    parser.add_argument("--production-release-id", required=True)
    parser.add_argument("--production-manifest-sha256", required=True)
    parser.add_argument("--production-pointer-sha256", required=True)
    parser.add_argument("--ledger-comments", type=int, required=True)
    parser.add_argument("--output", type=Path, default=Path(".artifacts/m14-public-product-acceptance.json"))
    args = parser.parse_args()

    accepted = validate_m14_public_product_acceptance(build_artifact(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(accepted.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print("M14_PUBLIC_PRODUCT_ACCEPTANCE_PASSED")
    print(f"artifact_sha256={accepted.artifact_sha256}")
    print(f"output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
