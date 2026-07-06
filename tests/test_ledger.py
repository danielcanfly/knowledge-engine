from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledge_engine.ledger import LedgerError, build_production_ledger_comment

RELEASE_ID = "20260706T024200Z-19b86982de27"
MANIFEST_SHA = "8697f5ab6258d8545328fd32cea60b09c2c80aef4599611b0571a0553ea24a7e"
PREVIOUS_RELEASE_ID = "20260703T074814Z-1b18538bfbac"
PREVIOUS_MANIFEST_SHA = "eab8d4191cba77e06e594d09bb48450635efd36e55e8accc14cec88e78e7de95"
SOURCE_SHA = "6254725c38969e46e65aadcba13a8803b0d8a6a9"
BUILDER_SHA = "1b55c68a441def01a5277c94b350efab1437459d"
FOUNDATION_SHA = "d12c7c416c950d743d4cd5e7964fd3c3bc0d9062"
CONTROL_PLANE_SHA = "c" * 40
POINTER_SHA = "e481074e1f96dac72eabcf579a087642f926aa6c4cdc13352178ee804bf6e6cf"
CITATION_URL = "https://www.danielcanfly.com/en/blog/the-atlas-of-agent-design-patterns-part-1/"


def _write_json(root: Path, name: str, payload: dict) -> None:
    (root / name).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _base_request() -> dict:
    return {
        "actor": "danielcanfly",
        "builder_sha": BUILDER_SHA,
        "candidate_channel": f"candidate-source-{SOURCE_SHA}",
        "expected_acl_status": "not_found",
        "expected_citation_url": CITATION_URL,
        "expected_previous_manifest_sha256": PREVIOUS_MANIFEST_SHA,
        "expected_previous_release_id": PREVIOUS_RELEASE_ID,
        "expected_public_status": "answered",
        "foundation_sha": FOUNDATION_SHA,
        "manifest_sha256": MANIFEST_SHA,
        "operation_id": "m5-agent-architecture-6d-6254725c-001",
        "post_promote_acl_query": "quartz lantern protocol",
        "post_promote_public_query": "six-dimensional map of LLM agent architectures",
        "reason": "Promote the approved M5 six-dimensional agent architecture Source batch.",
        "release_id": RELEASE_ID,
        "schema_version": "production-promotion-request/v1",
        "source_repository": "danielcanfly/knowledge-source",
        "source_sha": SOURCE_SHA,
    }


def _write_evidence(root: Path) -> None:
    request = _base_request()
    normalized = {
        **request,
        "control_plane_sha": CONTROL_PLANE_SHA,
    }

    _write_json(root, "request.json", request)
    _write_json(
        root,
        "request.normalized.json",
        normalized,
    )
    _write_json(
        root,
        "request-validation.json",
        {
            "github_env": {},
            "request": normalized,
            "status": "valid",
        },
    )
    _write_json(
        root,
        "precondition.json",
        {
            "loaded_at": "2026-07-06T09:27:44Z",
            "manifest_sha256": MANIFEST_SHA,
            "release_id": RELEASE_ID,
        },
    )
    _write_json(
        root,
        "candidate_identity.json",
        {
            "builder_sha": BUILDER_SHA,
            "candidate_channel": f"candidate-source-{SOURCE_SHA}",
            "control_plane_sha": CONTROL_PLANE_SHA,
            "foundation_sha": FOUNDATION_SHA,
            "manifest_key": f"releases/{RELEASE_ID}/manifest.json",
            "manifest_sha256": MANIFEST_SHA,
            "operation_id": "m5-agent-architecture-6d-6254725c-001",
            "release_id": RELEASE_ID,
            "source_repository": "danielcanfly/knowledge-source",
            "source_sha": SOURCE_SHA,
            "status": "candidate_verified",
        },
    )
    _write_json(
        root,
        "promotion_result.json",
        {
            "builder_sha": BUILDER_SHA,
            "control_plane_sha": CONTROL_PLANE_SHA,
            "foundation_sha": FOUNDATION_SHA,
            "idempotent": True,
            "intent_key": "not_written_for_already_promoted_replay",
            "manifest_sha256": MANIFEST_SHA,
            "operation_id": "m5-agent-architecture-6d-6254725c-001",
            "previous_manifest_sha256": PREVIOUS_MANIFEST_SHA,
            "previous_release_id": PREVIOUS_RELEASE_ID,
            "production_pointer_sha256": POINTER_SHA,
            "receipt_key": "not_written_for_already_promoted_replay",
            "release_id": RELEASE_ID,
            "source_sha": SOURCE_SHA,
            "status": "already_promoted",
        },
    )
    _write_json(
        root,
        "post_refresh.json",
        {
            "loaded_at": "2026-07-06T09:27:49Z",
            "manifest_sha256": MANIFEST_SHA,
            "release_id": RELEASE_ID,
        },
    )
    _write_json(
        root,
        "post-promote-public-query.json",
        {
            "query": "six-dimensional map of LLM agent architectures",
            "results": [
                {
                    "citations": [
                        {
                            "source_id": "source_blog_agent_architecture_6d",
                            "uri": CITATION_URL,
                        }
                    ],
                    "concept_id": "concepts/six-dimensional-map",
                    "score": 68,
                    "title": "Six-dimensional map of LLM agent architectures",
                }
            ],
            "retrieval": {
                "acl_filtered_count": 1,
                "candidate_count": 2,
                "raw_fallback_used": False,
                "selected_count": 2,
                "strategy": "wiki_first_lexical",
            },
            "status": "answered",
        },
    )
    _write_json(
        root,
        "post-promote-acl-query.json",
        {
            "non_answer_reason": "no_authorized_match",
            "query": "quartz lantern protocol",
            "results": [],
            "retrieval": {
                "acl_filtered_count": 1,
                "candidate_count": 0,
                "raw_fallback_used": False,
                "selected_count": 0,
                "strategy": "wiki_first_lexical",
            },
            "status": "not_found",
        },
    )
    _write_json(
        root,
        "post_query_acceptance.json",
        {
            "acl_query": {
                "acl_filtered_count": 1,
                "expected_status": "not_found",
                "raw_fallback_used": False,
                "status": "not_found",
            },
            "promotion": {
                "status": "already_promoted",
            },
            "public_query": {
                "citation_count": 1,
                "expected_citation_url": CITATION_URL,
                "expected_status": "answered",
                "raw_fallback_used": False,
                "status": "answered",
            },
        },
    )
    _write_json(
        root,
        "idempotency_observation.json",
        {
            "current": {
                "manifest_sha256": MANIFEST_SHA,
                "release_id": RELEASE_ID,
            },
            "expected_previous": {
                "manifest_sha256": PREVIOUS_MANIFEST_SHA,
                "release_id": PREVIOUS_RELEASE_ID,
            },
            "expected_target": {
                "manifest_sha256": MANIFEST_SHA,
                "release_id": RELEASE_ID,
            },
            "state": "already_target",
        },
    )


def test_build_production_ledger_comment_records_verified_evidence(
    tmp_path: Path,
) -> None:
    _write_evidence(tmp_path)

    comment = build_production_ledger_comment(
        evidence_dir=tmp_path,
        run_id="28781616604",
        run_url="https://github.com/danielcanfly/knowledge-engine/actions/runs/28781616604",
        workflow_name="M5 Production Promotion",
        event_name="workflow_dispatch",
        head_sha=CONTROL_PLANE_SHA,
    )

    assert "## Automated M5 production ledger entry" in comment
    assert "- Actions run ID: `28781616604`" in comment
    assert f"- Release ID: `{RELEASE_ID}`" in comment
    assert "- Production precondition state: `already_target`" in comment
    assert "- Promotion status: `already_promoted`" in comment
    assert "- Idempotent: `true`" in comment
    assert f"- Expected citation URL returned: `{CITATION_URL}`" in comment
    assert "- ACL actual status: `not_found`" in comment
    assert "not a human approval decision" in comment


def test_build_production_ledger_rejects_missing_evidence(tmp_path: Path) -> None:
    _write_evidence(tmp_path)
    (tmp_path / "promotion_result.json").unlink()

    with pytest.raises(LedgerError, match="missing evidence file"):
        build_production_ledger_comment(
            evidence_dir=tmp_path,
            run_id="1",
            run_url="https://example.invalid/run",
            workflow_name="M5 Production Promotion",
            event_name="workflow_dispatch",
            head_sha=CONTROL_PLANE_SHA,
        )


def test_build_production_ledger_rejects_raw_fallback(tmp_path: Path) -> None:
    _write_evidence(tmp_path)
    public_query = json.loads(
        (tmp_path / "post-promote-public-query.json").read_text(
            encoding="utf-8",
        )
    )
    public_query["retrieval"]["raw_fallback_used"] = True
    _write_json(tmp_path, "post-promote-public-query.json", public_query)

    with pytest.raises(LedgerError, match="public raw_fallback_used"):
        build_production_ledger_comment(
            evidence_dir=tmp_path,
            run_id="1",
            run_url="https://example.invalid/run",
            workflow_name="M5 Production Promotion",
            event_name="workflow_dispatch",
            head_sha=CONTROL_PLANE_SHA,
        )


def test_build_production_ledger_rejects_missing_expected_citation(
    tmp_path: Path,
) -> None:
    _write_evidence(tmp_path)
    public_query = json.loads(
        (tmp_path / "post-promote-public-query.json").read_text(
            encoding="utf-8",
        )
    )
    public_query["results"][0]["citations"][0]["uri"] = "https://example.invalid/"
    _write_json(tmp_path, "post-promote-public-query.json", public_query)

    with pytest.raises(LedgerError, match="expected citation URL"):
        build_production_ledger_comment(
            evidence_dir=tmp_path,
            run_id="1",
            run_url="https://example.invalid/run",
            workflow_name="M5 Production Promotion",
            event_name="workflow_dispatch",
            head_sha=CONTROL_PLANE_SHA,
        )
