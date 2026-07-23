from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from knowledge_engine.errors import AuthorizationError, IntegrityError
from knowledge_engine.m25_source_pr_executor import (
    authorize_source_pr_opening,
    build_source_pr_plan,
    content_digest,
    digest,
    materialize_test_plan,
    sign,
    validate_plan,
    validate_source_baseline,
)

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot" / "m25"


def load(name: str) -> dict:
    return json.loads((PILOT / name).read_text(encoding="utf-8"))


def inputs() -> tuple[dict, dict, dict, dict, dict]:
    return (
        load("m25-7-review-batch.synthetic.json"),
        load("m25-7-audit-export.synthetic.json"),
        load("m25-7-m25-6-acceptance.synthetic.json"),
        load("m25-7-source-baseline.synthetic.json"),
        load("m25-7-item-authority.synthetic.json"),
    )


def rebuild(*values: dict) -> dict:
    return build_source_pr_plan(*values)


def resign(value: dict, field: str) -> dict:
    return sign(value, field)


def test_committed_plan_rebuild_is_byte_identical() -> None:
    actual = rebuild(*inputs())
    expected = load("m25-7-source-pr-plan.synthetic.json")
    assert actual == expected
    assert digest({key: value for key, value in actual.items() if key != "plan_sha256"}) == actual[
        "plan_sha256"
    ]
    assert actual["item_count"] == 2
    assert actual["operation_count"] == 2
    assert actual["write_operation_count"] == 1
    assert actual["no_write_operation_count"] == 1
    assert actual["source_branch_write_permitted"] is False
    assert actual["github_pr_creation_permitted"] is False
    assert actual["source_pr_merge_permitted"] is False
    assert actual["m25_8_authorized"] is False


def test_test_only_materializer_writes_only_approved_bytes(tmp_path: Path) -> None:
    batch, audit, acceptance, baseline, authority = inputs()
    plan = rebuild(batch, audit, acceptance, baseline, authority)
    receipt = materialize_test_plan(plan, baseline, tmp_path)
    target = tmp_path / "bundle/concepts/approved-test-concept.md"
    existing = tmp_path / "bundle/concepts/existing-test-concept.md"
    assert target.exists() and existing.exists()
    expected_operation = next(
        row for row in plan["operations"] if row["disposition"] == "create"
    )
    assert target.read_text(encoding="utf-8") == expected_operation["new_content_utf8"]
    assert content_digest(target.read_text(encoding="utf-8")) == expected_operation[
        "new_content_sha256"
    ]
    assert receipt["mode"] == "test_only"
    assert receipt["written_file_count"] == 1
    assert receipt["live_source_write_permitted"] is False
    assert receipt["github_pr_creation_permitted"] is False


def test_stale_batch_fails_closed() -> None:
    batch, audit, acceptance, baseline, authority = inputs()
    batch["policy_sha256"] = "f" * 64
    with pytest.raises(IntegrityError, match="batch digest mismatch"):
        rebuild(batch, audit, acceptance, baseline, authority)


def test_incomplete_audit_fails_closed() -> None:
    batch, audit, acceptance, baseline, authority = inputs()
    audit["review_complete"] = False
    audit = resign(audit, "audit_sha256")
    authority["audit_sha256"] = audit["audit_sha256"]
    authority = resign(authority, "authority_sha256")
    with pytest.raises(IntegrityError, match="not complete and terminal"):
        rebuild(batch, audit, acceptance, baseline, authority)


def test_deferred_decision_fails_closed() -> None:
    batch, audit, acceptance, baseline, authority = inputs()
    audit["records"][-1]["action"] = "defer"
    audit["records"][-1] = resign(audit["records"][-1], "decision_sha256")
    audit["deferred_item_count"] = 1
    audit["terminal_item_count"] = 1
    audit["review_complete"] = False
    audit["admission_ready"] = False
    audit = resign(audit, "audit_sha256")
    authority["audit_sha256"] = audit["audit_sha256"]
    authority = resign(authority, "authority_sha256")
    with pytest.raises(IntegrityError, match="non-terminal"):
        rebuild(batch, audit, acceptance, baseline, authority)


def test_live_browser_reviewer_cannot_be_knowledge_authority() -> None:
    batch, audit, acceptance, baseline, authority = inputs()
    baseline["mode"] = "live"
    baseline["source_repository"] = "danielcanfly/knowledge-source"
    baseline = resign(baseline, "manifest_sha256")
    authority["mode"] = "live"
    authority["actor"] = "browser-reviewer"
    authority["source_manifest_sha256"] = baseline["manifest_sha256"]
    for record in audit["records"]:
        record["reviewer"] = "browser-reviewer"
    previous = None
    for record in audit["records"]:
        record["previous_decision_sha256"] = previous
        updated = resign(record, "decision_sha256")
        record.clear()
        record.update(updated)
        previous = record["decision_sha256"]
    for decision, record in zip(authority["decisions"], audit["records"], strict=True):
        decision["decision_sha256"] = record["decision_sha256"]
    audit = resign(audit, "audit_sha256")
    authority["audit_sha256"] = audit["audit_sha256"]
    authority = resign(authority, "authority_sha256")
    with pytest.raises(AuthorizationError, match="browser actor"):
        rebuild(batch, audit, acceptance, baseline, authority)


def test_authority_must_bind_exact_decision_digest() -> None:
    batch, audit, acceptance, baseline, authority = inputs()
    authority["decisions"][0]["decision_sha256"] = "f" * 64
    authority = resign(authority, "authority_sha256")
    with pytest.raises(AuthorizationError, match="exact decision"):
        rebuild(batch, audit, acceptance, baseline, authority)


def test_authority_must_cover_every_item() -> None:
    batch, audit, acceptance, baseline, authority = inputs()
    authority["decisions"].pop()
    authority["item_count"] = 1
    authority = resign(authority, "authority_sha256")
    with pytest.raises(AuthorizationError, match="full item population"):
        rebuild(batch, audit, acceptance, baseline, authority)


def test_cross_item_path_collision_fails_closed() -> None:
    batch, audit, acceptance, baseline, authority = inputs()
    reject = authority["decisions"][1]
    create = copy.deepcopy(authority["decisions"][0]["source_operations"][0])
    create["operation_id"] = "collision-op"
    reject["action"] = "approve"
    reject["source_operations"] = [create]
    audit["records"][1]["action"] = "approve"
    audit["records"][1] = resign(audit["records"][1], "decision_sha256")
    audit = resign(audit, "audit_sha256")
    reject["decision_sha256"] = audit["records"][1]["decision_sha256"]
    authority["audit_sha256"] = audit["audit_sha256"]
    authority = resign(authority, "authority_sha256")
    with pytest.raises(AuthorizationError, match="path collision"):
        rebuild(batch, audit, acceptance, baseline, authority)


def test_unsafe_path_fails_closed() -> None:
    batch, audit, acceptance, baseline, authority = inputs()
    authority["decisions"][0]["source_operations"][0]["path"] = "../outside.md"
    authority = resign(authority, "authority_sha256")
    with pytest.raises(IntegrityError, match="unsafe Source path"):
        rebuild(batch, audit, acceptance, baseline, authority)


def test_unapproved_byte_drift_fails_closed() -> None:
    batch, audit, acceptance, baseline, authority = inputs()
    authority["decisions"][0]["source_operations"][0]["new_content_utf8"] += "drift\n"
    authority = resign(authority, "authority_sha256")
    with pytest.raises(IntegrityError, match="bytes digest mismatch"):
        rebuild(batch, audit, acceptance, baseline, authority)


def test_stale_source_manifest_fails_closed() -> None:
    batch, audit, acceptance, baseline, authority = inputs()
    authority["source_manifest_sha256"] = "f" * 64
    authority = resign(authority, "authority_sha256")
    with pytest.raises(AuthorizationError, match="stale"):
        rebuild(batch, audit, acceptance, baseline, authority)


def test_replace_requires_exact_old_digest() -> None:
    batch, audit, acceptance, baseline, authority = inputs()
    op = authority["decisions"][0]["source_operations"][0]
    op["disposition"] = "replace"
    op["path"] = "bundle/concepts/existing-test-concept.md"
    op["expected_old_sha256"] = "f" * 64
    authority = resign(authority, "authority_sha256")
    with pytest.raises(IntegrityError, match="stale replace"):
        rebuild(batch, audit, acceptance, baseline, authority)


def test_rejected_decision_cannot_write() -> None:
    batch, audit, acceptance, baseline, authority = inputs()
    reject = authority["decisions"][1]
    reject["source_operations"] = [copy.deepcopy(authority["decisions"][0]["source_operations"][0])]
    reject["source_operations"][0]["operation_id"] = "rejected-write"
    reject["source_operations"][0]["path"] = "bundle/concepts/rejected-write.md"
    authority = resign(authority, "authority_sha256")
    with pytest.raises(IntegrityError, match="rejected decision"):
        rebuild(batch, audit, acceptance, baseline, authority)


def test_plan_tampering_fails_validation() -> None:
    plan = load("m25-7-source-pr-plan.synthetic.json")
    plan["github_pr_creation_permitted"] = True
    with pytest.raises(IntegrityError, match="plan digest mismatch"):
        validate_plan(plan)


def test_source_baseline_self_digest_and_file_digest_are_enforced() -> None:
    baseline = load("m25-7-source-baseline.synthetic.json")
    baseline["files"][0]["content_utf8"] += "drift"
    baseline = resign(baseline, "manifest_sha256")
    with pytest.raises(IntegrityError, match="file digest mismatch"):
        validate_source_baseline(baseline)


def test_test_plan_cannot_receive_source_pr_opening_authority() -> None:
    plan = load("m25-7-source-pr-plan.synthetic.json")
    approval = sign(
        {
            "schema_version": "knowledge-engine-m25-7-plan-approval/v1",
            "actor": "synthetic-knowledge-owner",
            "actor_role": "knowledge_owner",
            "authority_comment_id": 1,
            "plan_sha256": plan["plan_sha256"],
            "source_repository": plan["source_repository"],
            "source_base_sha": plan["source_base_sha"],
            "approved_branch_name": plan["branch"]["name"],
            "approved_for_source_branch_and_pr": True,
            "approved_for_merge": False,
        },
        "approval_sha256",
    )
    with pytest.raises(AuthorizationError, match="test or synthetic"):
        authorize_source_pr_opening(plan, approval)


def test_live_exact_plan_approval_authorizes_opening_but_not_merge() -> None:
    plan = load("m25-7-source-pr-plan.synthetic.json")
    plan["mode"] = "live"
    plan["source_repository"] = "danielcanfly/knowledge-source"
    plan = resign(plan, "plan_sha256")
    approval = sign(
        {
            "schema_version": "knowledge-engine-m25-7-plan-approval/v1",
            "actor": "huaihsuanbusiness",
            "actor_role": "knowledge_owner",
            "authority_comment_id": 123456,
            "plan_sha256": plan["plan_sha256"],
            "source_repository": plan["source_repository"],
            "source_base_sha": plan["source_base_sha"],
            "approved_branch_name": plan["branch"]["name"],
            "approved_for_source_branch_and_pr": True,
            "approved_for_merge": False,
        },
        "approval_sha256",
    )
    receipt = authorize_source_pr_opening(plan, approval)
    assert receipt["source_branch_write_permitted"] is True
    assert receipt["github_pr_creation_permitted"] is True
    assert receipt["source_pr_merge_permitted"] is False
    assert receipt["release_mutation_permitted"] is False
    assert receipt["production_mutation_permitted"] is False
    assert receipt["m25_8_authorized"] is False
