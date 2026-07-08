from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from knowledge_engine import compiler_m11_closure_v1
from knowledge_engine.compiler_m11_closure_v1 import (
    PRODUCTION_MANIFEST_SHA256,
    PRODUCTION_POINTER_SHA256,
    PRODUCTION_RELEASE,
    M11ClosureRequest,
    reconcile_m11_closure,
    verify_m11_closure_event,
)
from knowledge_engine.compiler_review_decision_contract_v1 import (
    CompilerReviewDecisionRequest,
    CompilerSourcePRPackageRequest,
    ProposalDecisionInput,
)
from knowledge_engine.compiler_review_decision_v1 import (
    record_compiler_review_decision,
    verify_review_decision_event,
)
from knowledge_engine.compiler_review_packet_v1 import build_reviewer_packet
from knowledge_engine.compiler_source_pr_package_v1 import (
    build_source_pr_package,
    verify_source_pr_package_event,
)
from knowledge_engine.compiler_source_v1 import SOURCE_REPOSITORY, verify_source_checkout
from knowledge_engine.compiler_synthesis_v1 import synthesize_resolution_batch
from knowledge_engine.errors import IntegrityError
from knowledge_engine.intake_v1 import canonical_json_bytes
from knowledge_engine.storage import FileObjectStore
from tests.test_compiler_synthesis_review_v1 import (
    _fixture,
    _packet_request,
    _synthesis_request,
)

ROOT = Path(__file__).resolve().parents[1]
MODULES = (
    ROOT / "src/knowledge_engine/compiler_review_decision_contract_v1.py",
    ROOT / "src/knowledge_engine/compiler_review_decision_v1.py",
    ROOT / "src/knowledge_engine/compiler_source_pr_package_v1.py",
    ROOT / "src/knowledge_engine/compiler_m11_closure_v1.py",
)


def _run(root: Path, *args: str) -> str:
    completed = subprocess.run(
        list(args),
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _json(store: FileObjectStore, key: str) -> dict[str, Any]:
    value = json.loads(store.get(key))
    assert isinstance(value, dict)
    return value


def _put(store: FileObjectStore, key: str, value: dict[str, Any]) -> None:
    store.put(
        key,
        (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(),
        content_type="application/json",
    )


def _concept(
    concept_id: str,
    title: str,
    body: str,
    *,
    audience: str = "public",
    aliases: tuple[str, ...] = (),
) -> str:
    alias_lines = ""
    if aliases:
        alias_lines = "aliases:\n" + "".join(f"  - {item}\n" for item in aliases)
    return (
        "---\n"
        "type: Concept\n"
        f"title: {title}\n"
        f"description: Fixture for {title}.\n"
        f"{alias_lines}"
        f"x-kos-id: {concept_id}\n"
        f"x-kos-audience: {audience}\n"
        "---\n"
        f"# {title}\n\n"
        f"{body.strip()}\n"
    )


def _source(tmp_path: Path) -> tuple[Path, str, dict[str, Any], list[dict[str, Any]]]:
    root = tmp_path / "source"
    root.mkdir(parents=True)
    _run(root, "git", "init")
    _run(root, "git", "config", "user.email", "fixture@example.com")
    _run(root, "git", "config", "user.name", "Fixture")
    concepts = root / "bundle/concepts"
    concepts.mkdir(parents=True)
    (concepts / "existing.md").write_text(
        _concept(
            "ko_existing",
            "Existing Topic",
            "Existing evidence is canonical.\nAgents must retry forever.",
            audience="internal",
            aliases=("Old Alias",),
        ),
        encoding="utf-8",
    )
    (concepts / "legacy.md").write_text(
        _concept("ko_legacy", "Legacy Topic", "Legacy evidence remains."),
        encoding="utf-8",
    )
    (root / "bundle/README.md").write_text("# Fixture Source\n", encoding="utf-8")
    _run(root, "git", "add", ".")
    _run(root, "git", "commit", "-m", "fixture")
    source_sha = _run(root, "git", "rev-parse", "HEAD")
    snapshot, source_concepts = verify_source_checkout(root, SOURCE_REPOSITORY, source_sha)
    return root, source_sha, snapshot, source_concepts


def _prepare_pipeline(
    tmp_path: Path,
) -> tuple[FileObjectStore, Path, str, Any, Any]:
    store = FileObjectStore(tmp_path / "store")
    resolution_batch_id = _fixture(store)
    prefix = f"compiler/v1/resolutions/{resolution_batch_id}"

    resolution_key = f"{prefix}/resolutions.json"
    resolution_set = _json(store, resolution_key)
    removed = {
        item["candidate_id"]
        for item in resolution_set["resolutions"]
        if item["outcome"] == "contradiction"
    }
    resolution_set["resolutions"] = [
        item for item in resolution_set["resolutions"] if item["outcome"] != "contradiction"
    ]
    resolution_set["resolution_count"] = len(resolution_set["resolutions"])
    _put(store, resolution_key, resolution_set)

    compiler_run_id = resolution_set["compiler_run_id"]
    candidate_key = f"compiler/v1/runs/{compiler_run_id}/extraction/candidates.json"
    candidate_set = _json(store, candidate_key)
    candidate_set["candidates"] = [
        item for item in candidate_set["candidates"] if item["candidate_id"] not in removed
    ]
    candidate_set["candidate_count"] = len(candidate_set["candidates"])
    _put(store, candidate_key, candidate_set)

    source_root, source_sha, snapshot, source_concepts = _source(tmp_path)
    _put(store, f"{prefix}/source-snapshot.json", snapshot)

    index_key = f"{prefix}/candidate-index.json"
    index = _json(store, index_key)
    index["source_snapshot_sha256"] = snapshot["source_snapshot_sha256"]
    index["concept_count"] = len(source_concepts)
    index["concepts"] = [
        {
            "concept_id": item["concept_id"],
            "path": item["path"],
            "title": item["title"],
            "aliases": item["aliases"],
            "audience": item["audience"],
        }
        for item in source_concepts
    ]
    _put(store, index_key, index)

    validation_key = f"{prefix}/validation-report.json"
    validation = _json(store, validation_key)
    validation["source_snapshot_sha256"] = snapshot["source_snapshot_sha256"]
    validation["candidate_count"] = len(candidate_set["candidates"])
    validation["resolution_count"] = len(resolution_set["resolutions"])
    _put(store, validation_key, validation)

    record_key = f"{prefix}/resolution-record.json"
    record = _json(store, record_key)
    record["request"]["source_commit_sha"] = source_sha
    record["resolution_count"] = len(resolution_set["resolutions"])
    _put(store, record_key, record)

    result_key = f"{prefix}/result.json"
    result = _json(store, result_key)
    result["source_snapshot_sha256"] = snapshot["source_snapshot_sha256"]
    result["resolution_count"] = len(resolution_set["resolutions"])
    _put(store, result_key, result)

    synthesis = synthesize_resolution_batch(store, _synthesis_request(resolution_batch_id))
    assert synthesis.status == "review_only_complete"
    assert synthesis.quarantine_count == 0
    packet = build_reviewer_packet(store, _packet_request(synthesis.proposal_batch_id))
    assert packet.status == "review_ready"
    assert packet.quarantine_count == 0
    return store, source_root, source_sha, synthesis, packet


def _decision_request(
    store: FileObjectStore,
    packet: Any,
    *,
    omit_last: bool = False,
    broaden_update: bool = False,
    acknowledge_high_risk: bool = True,
) -> CompilerReviewDecisionRequest:
    assert packet.packet_prefix
    proposal_index = _json(store, f"{packet.packet_prefix}/proposal-index.json")
    decisions = []
    proposals = sorted(proposal_index["proposals"], key=lambda item: item["proposal_id"])
    if omit_last:
        proposals = proposals[:-1]
    for proposal in proposals:
        audience = proposal["effective_audience"]
        if broaden_update and proposal["proposal_kind"] == "concept_update":
            audience = "public"
        decisions.append(
            ProposalDecisionInput(
                proposal_id=proposal["proposal_id"],
                decision="approved",
                notes=f"Reviewed {proposal['proposal_kind']} against evidence.",
                approved_audience=audience,
                high_risk_acknowledged=(
                    acknowledge_high_risk and proposal["proposal_kind"] == "supersession_update"
                ),
            )
        )
    return CompilerReviewDecisionRequest(
        reviewer_packet_id=packet.reviewer_packet_id,
        reviewer="reviewer@example.com",
        reviewed_at="2026-07-08T11:00:00Z",
        notes="Explicit fixture review of every proposal.",
        decisions=tuple(decisions),
    )


def test_m11_6_and_m11_7_end_to_end_replay_and_boundaries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, source_root, source_sha, _, packet = _prepare_pipeline(tmp_path)
    before_status = _run(source_root, "git", "status", "--porcelain", "--untracked-files=all")

    decision = record_compiler_review_decision(
        store,
        _decision_request(store, packet),
        tmp_path / "decision-output",
    )
    assert decision.status == "recorded"
    assert decision.decision_count == 4
    assert decision.approved_count == 4
    assert decision.source_package_permitted is True
    assert decision.idempotent is False
    assert decision.decision_prefix
    previous = None
    for key in decision.event_keys:
        event = _json(store, key)
        assert verify_review_decision_event(event)
        assert event["previous_event_hash"] == previous
        previous = event["event_sha256"]
    replay = record_compiler_review_decision(store, _decision_request(store, packet))
    assert replay.to_dict() == {**decision.to_dict(), "idempotent": True}

    package_request = CompilerSourcePRPackageRequest(
        decision_set_id=decision.decision_set_id,
        source_repository=SOURCE_REPOSITORY,
        source_commit_sha=source_sha,
        packaged_at="2026-07-08T11:30:00Z",
        actor="compiler-review-bot",
    )
    package = build_source_pr_package(
        store,
        package_request,
        source_root,
        tmp_path / "package-output",
    )
    assert package.status == "review_only_complete"
    assert package.approved_proposal_count == 4
    assert package.file_plan_count == 4
    assert package.manual_review_count == 2
    assert package.source_pr_creation_permitted is False
    assert package.direct_apply_permitted is False
    assert package.canonical_write_permitted is False
    assert package.package_prefix
    plan = _json(store, f"{package.package_prefix}/file-plan.json")
    assert {item["operation"] for item in plan["plans"]} == {
        "add",
        "replace",
        "verify_no_change",
        "manual_supersession_review",
    }
    previous = None
    for key in package.event_keys:
        event = _json(store, key)
        assert verify_source_pr_package_event(event)
        assert event["previous_event_hash"] == previous
        previous = event["event_sha256"]
    package_replay = build_source_pr_package(store, package_request, source_root)
    assert package_replay.to_dict() == {**package.to_dict(), "idempotent": True}
    assert _run(source_root, "git", "status", "--porcelain", "--untracked-files=all") == before_status

    monkeypatch.setattr(compiler_m11_closure_v1, "M11_SOURCE_SHA", source_sha)
    closure_request = M11ClosureRequest(
        source_pr_package_id=package.source_pr_package_id,
        source_commit_sha=source_sha,
        production_release=PRODUCTION_RELEASE,
        production_manifest_sha256=PRODUCTION_MANIFEST_SHA256,
        production_pointer_sha256=PRODUCTION_POINTER_SHA256,
        reconciled_at="2026-07-08T12:00:00Z",
    )
    closure = reconcile_m11_closure(
        store,
        closure_request,
        source_root,
        tmp_path / "closure-output",
    )
    assert closure.status == "closure_ready"
    assert closure.canonical_write_permitted is False
    assert closure.github_write_permitted is False
    assert closure.production_write_permitted is False
    assert closure.ledger_write_permitted is False
    assert closure.closure_prefix
    report = _json(store, f"{closure.closure_prefix}/reconciliation-report.json")
    assert report["next_milestone"] == "M12"
    assert report["m11_slice_status"]["M11.7"] == "closure_ready"
    matrix = _json(store, f"{closure.closure_prefix}/invariant-matrix.json")
    assert matrix["all_passed"] is True
    assert all(matrix["invariants"].values()) is not True
    assert matrix["invariants"]["automatic_approval_permitted"] is False
    assert matrix["invariants"]["canonical_source_written"] is False
    previous = None
    for key in closure.event_keys:
        event = _json(store, key)
        assert verify_m11_closure_event(event)
        assert event["previous_event_hash"] == previous
        previous = event["event_sha256"]
    closure_replay = reconcile_m11_closure(store, closure_request, source_root)
    assert closure_replay.to_dict() == {**closure.to_dict(), "idempotent": True}


def test_decision_fails_closed_for_incomplete_broadening_and_high_risk(
    tmp_path: Path,
) -> None:
    store, _, _, _, packet = _prepare_pipeline(tmp_path)

    incomplete = record_compiler_review_decision(
        store,
        _decision_request(store, packet, omit_last=True),
    )
    assert incomplete.status == "rejected"
    assert incomplete.failure_code == "REVIEW_DECISION_COVERAGE_INCOMPLETE"

    broadened = record_compiler_review_decision(
        store,
        _decision_request(store, packet, broaden_update=True),
    )
    assert broadened.status == "rejected"
    assert broadened.failure_code == "REVIEW_DECISION_POLICY_BROADENING"

    unacknowledged = record_compiler_review_decision(
        store,
        _decision_request(store, packet, acknowledge_high_risk=False),
    )
    assert unacknowledged.status == "rejected"
    assert unacknowledged.failure_code == "REVIEW_DECISION_HIGH_RISK_ACK_REQUIRED"


def test_source_pr_package_rejects_dirty_source(tmp_path: Path) -> None:
    store, source_root, source_sha, _, packet = _prepare_pipeline(tmp_path)
    decision = record_compiler_review_decision(store, _decision_request(store, packet))
    (source_root / "untracked.txt").write_text("dirty", encoding="utf-8")
    package = build_source_pr_package(
        store,
        CompilerSourcePRPackageRequest(
            decision_set_id=decision.decision_set_id,
            source_repository=SOURCE_REPOSITORY,
            source_commit_sha=source_sha,
            packaged_at="2026-07-08T11:30:00Z",
            actor="compiler-review-bot",
        ),
        source_root,
    )
    assert package.status == "rejected"
    assert package.failure_code == "SOURCE_DIRTY"


def test_closure_rejects_changed_production_pointer(tmp_path: Path) -> None:
    request = M11ClosureRequest(
        source_pr_package_id=f"sprp_{'a' * 64}",
        source_commit_sha=compiler_m11_closure_v1.M11_SOURCE_SHA,
        production_release=PRODUCTION_RELEASE,
        production_manifest_sha256=PRODUCTION_MANIFEST_SHA256,
        production_pointer_sha256="f" * 64,
        reconciled_at="2026-07-08T12:00:00Z",
    )
    store = FileObjectStore(tmp_path / "store")
    result = reconcile_m11_closure(store, request, tmp_path / "missing-source")
    assert result.status == "rejected"
    assert result.failure_code == "M11_CLOSURE_PRODUCTION_POINTER_CHANGED"


def test_review_governance_immutable_collision_fails_hard(tmp_path: Path) -> None:
    store, _, _, _, packet = _prepare_pipeline(tmp_path)
    request = _decision_request(store, packet)
    decision = record_compiler_review_decision(store, request)
    assert decision.decision_prefix
    key = f"{decision.decision_prefix}/decisions.json"
    value = _json(store, key)
    value["decision_count"] = 999
    _put(store, key, value)
    with pytest.raises(IntegrityError):
        record_compiler_review_decision(store, request)


def test_m11_6_and_m11_7_modules_have_no_forbidden_governance_surface() -> None:
    forbidden_imports = {
        "boto3",
        "httpx",
        "requests",
        "socket",
        "openai",
        "anthropic",
    }
    forbidden_calls = {
        "create_pull_request",
        "merge_pull_request",
        "promote",
        "rollback",
        "delete",
    }
    for path in MODULES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported.update(
            (node.module or "").split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        )
        assert imported.isdisjoint(forbidden_imports)
        calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        assert calls.isdisjoint(forbidden_calls)
