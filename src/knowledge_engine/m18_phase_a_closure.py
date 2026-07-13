from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from knowledge_engine.errors import IntegrityError

SCHEMA_VERSION = "knowledge-os-m18-phase-a-closure/v1"
REQUIRED_SUBMILESTONES = tuple(f"M18.{index}" for index in range(1, 7))
REQUIRED_FAIL_CLOSED_CASES = {
    "unknown_relation_type",
    "missing_target",
    "invalid_direction",
    "invalid_inverse",
    "duplicate_edge",
    "alias_collision",
    "invalid_tag",
    "missing_provenance",
    "unapproved_relation",
    "acl_broadening",
    "graph_nondeterminism",
    "renderer_field_leakage",
    "broken_internal_link",
    "wikilink_in_release",
}
REQUIRED_CHANGED_FILES = {
    ".github/workflows/m18-7-phase-a-acceptance.yml",
    "migrations/m18-7-phase-a-acceptance.json",
}
REQUIRED_MUTATION_FLAGS = {
    "candidate_publication",
    "production_publication",
    "production_pointer",
    "r2",
    "credentials",
    "permanent_ledger",
    "rollback",
}
REQUIRED_FORBIDDEN_FLAGS = {
    "automatic_relation_inference_into_source",
    "renderer_specific_canonical_fields",
    "automatic_source_or_production_promotion",
    "graph_neural_retrieval",
}
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise IntegrityError(message)


def _require_sha(value: Any, field: str) -> None:
    _require(
        isinstance(value, str) and SHA_RE.fullmatch(value) is not None,
        f"{field} must be a full lowercase commit SHA",
    )


def _canonical_bytes(record: dict[str, Any]) -> bytes:
    return (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode()


def phase_a_closure_sha256(record: dict[str, Any]) -> str:
    """Return the stable digest of a validated Phase A closure record."""
    validate_phase_a_closure(record)
    return hashlib.sha256(_canonical_bytes(record)).hexdigest()


def validate_phase_a_closure(
    record: dict[str, Any],
    *,
    repository_root: Path | None = None,
) -> None:
    """Fail closed unless all M18 Phase A closure evidence is complete."""
    _require(isinstance(record, dict), "closure record must be an object")
    _require(record.get("schema_version") == SCHEMA_VERSION, "invalid closure schema")
    _require(record.get("milestone") == "M18.7", "closure milestone must be M18.7")
    _require(
        record.get("status") == "ready_for_reconciliation",
        "closure status must be ready_for_reconciliation",
    )
    _require(record.get("issue") == 264, "closure issue must be #264")

    repositories = record.get("repositories")
    _require(isinstance(repositories, dict), "repositories must be an object")
    _require(
        set(repositories) == {"engine_base", "source", "foundation"},
        "closure must pin Engine base, Source, and Foundation",
    )
    for name, value in repositories.items():
        _require_sha(value, f"repositories.{name}")

    submilestones = record.get("completed_submilestones")
    _require(isinstance(submilestones, list), "completed_submilestones must be a list")
    by_id = {
        item.get("id"): item
        for item in submilestones
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    _require(
        set(by_id) == set(REQUIRED_SUBMILESTONES)
        and len(submilestones) == len(REQUIRED_SUBMILESTONES),
        "M18.1 through M18.6 must each be reconciled exactly once",
    )
    for milestone in REQUIRED_SUBMILESTONES:
        item = by_id[milestone]
        _require(item.get("status") == "complete", f"{milestone} is not complete")
        _require(
            isinstance(item.get("issue"), int) and item["issue"] > 0,
            f"{milestone} issue is invalid",
        )
        _require(
            item.get("production_mutation_dispatched") is False,
            f"{milestone} production mutation must be false",
        )
        path = item.get("reconciliation")
        _require(
            isinstance(path, str) and path.startswith("docs/architecture/m18/"),
            f"{milestone} reconciliation path is invalid",
        )
        if repository_root is not None:
            evidence = repository_root / path
            _require(evidence.is_file(), f"{milestone} reconciliation is missing")
            evidence_text = evidence.read_text(encoding="utf-8")
            expected_status = (
                "Status: baseline contract" if milestone == "M18.1" else "Status: complete"
            )
            _require(expected_status in evidence_text, f"{milestone} is not reconciled")
            _require(
                "Production mutation dispatched: false" in evidence_text,
                f"{milestone} mutation evidence is missing",
            )

    source = record.get("source_acceptance")
    _require(isinstance(source, dict), "source_acceptance must be an object")
    _require(
        source.get("repository") == "danielcanfly/knowledge-source",
        "unexpected Source repository",
    )
    _require(source.get("pull_request") == 18, "Source acceptance must be PR #18")
    for field in ("base_sha", "head_sha", "merge_sha"):
        _require_sha(source.get(field), f"source_acceptance.{field}")
    _require(
        repositories["source"] == source["merge_sha"],
        "Source repository pin must equal the acceptance merge SHA",
    )
    _require(
        set(source.get("changed_files", [])) == REQUIRED_CHANGED_FILES
        and len(source.get("changed_files", [])) == len(REQUIRED_CHANGED_FILES),
        "Source acceptance changed-file scope is invalid",
    )
    _require(source.get("comments") == 0, "Source acceptance has unresolved comments")
    _require(source.get("reviews") == 0, "Source acceptance has unresolved reviews")
    _require(
        source.get("unresolved_threads") == 0,
        "Source acceptance has unresolved review threads",
    )
    workflows = source.get("exact_head_workflows")
    _require(isinstance(workflows, list) and workflows, "Source workflows are missing")
    _require(
        all(
            isinstance(item, dict)
            and isinstance(item.get("name"), str)
            and item.get("conclusion") == "success"
            and isinstance(item.get("run_number"), int)
            for item in workflows
        ),
        "every Source exact-head workflow must succeed",
    )

    expected = record.get("expected")
    _require(
        expected
        == {
            "concepts": 5,
            "graph_v2_edges": 5,
            "tag_assignments": 19,
            "aliases": 10,
            "authored_relations": 3,
            "generated_inverse_edges": 2,
            "public_concepts": 4,
            "internal_concepts": 1,
        },
        "Phase A graph counts do not match the governed migration",
    )

    runtime = record.get("runtime")
    _require(isinstance(runtime, dict), "runtime closure must be an object")
    _require(
        runtime
        == {
            "legacy_release_without_graph_v2_loads": True,
            "relation_graph_optional": True,
            "relation_aware_expansion_default": False,
            "enabled_acceptance_test_only": True,
            "maximum_hops": 1,
            "maximum_neighbors_per_seed": 20,
            "acl_rechecked": True,
            "public_retrieval_evidence_exposed": False,
        },
        "Runtime compatibility or safety boundary drifted",
    )

    coverage = record.get("fail_closed_coverage")
    _require(isinstance(coverage, dict), "fail_closed_coverage must be an object")
    _require(
        set(coverage) == REQUIRED_FAIL_CLOSED_CASES,
        "fail-closed coverage must exactly match the M18 acceptance contract",
    )
    source_test_prefix = (
        f"danielcanfly/knowledge-source@{source['head_sha']}:tests/"
    )
    _require(
        all(
            isinstance(value, str)
            and (value.startswith("tests/") or value.startswith(source_test_prefix))
            for value in coverage.values()
        ),
        "every fail-closed case must map to a local or exact-Source test",
    )
    if repository_root is not None:
        _require(
            all(
                value.startswith(source_test_prefix)
                or (repository_root / value).is_file()
                for value in coverage.values()
            ),
            "local fail-closed test evidence is missing",
        )

    compatibility = record.get("compatibility")
    _require(
        compatibility
        == {
            "lexical_baseline_preserved": True,
            "generic_links_separate_from_typed_relations": True,
            "v1_supported_during_bounded_migration": True,
        },
        "M18 compatibility contract drifted",
    )

    mutation = record.get("mutation")
    _require(isinstance(mutation, dict), "mutation must be an object")
    _require(
        mutation.get("object_store_backend") == "filesystem",
        "closure acceptance must use the filesystem object store",
    )
    _require(
        set(mutation) == REQUIRED_MUTATION_FLAGS | {"object_store_backend"},
        "mutation flags do not match the governed boundary",
    )
    _require(
        all(mutation[name] is False for name in REQUIRED_MUTATION_FLAGS),
        "M18.7 may not mutate protected state",
    )

    forbidden = record.get("forbidden")
    _require(isinstance(forbidden, dict), "forbidden must be an object")
    _require(
        set(forbidden) == REQUIRED_FORBIDDEN_FLAGS,
        "forbidden flags do not match the M18 acceptance contract",
    )
    _require(
        all(forbidden[name] is False for name in REQUIRED_FORBIDDEN_FLAGS),
        "a forbidden M18 behavior was enabled",
    )
    _require(record.get("m19_started") is False, "M19 must not start during M18 closure")

    if repository_root is not None:
        acceptance_path = repository_root / "docs/architecture/m18/m18-acceptance-contract.json"
        acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))
        _require(
            set(acceptance["fail_closed_cases"]) == REQUIRED_FAIL_CLOSED_CASES,
            "closure coverage drifted from the M18 acceptance contract",
        )
        _require(
            set(acceptance["forbidden"]) == REQUIRED_FORBIDDEN_FLAGS,
            "closure forbidden flags drifted from the M18 acceptance contract",
        )


def evaluate_phase_a_closure(
    record: dict[str, Any],
    *,
    repository_root: Path | None = None,
) -> dict[str, Any]:
    validate_phase_a_closure(record, repository_root=repository_root)
    digest = hashlib.sha256(_canonical_bytes(record)).hexdigest()
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "ready_for_reconciliation",
        "closure_sha256": digest,
        "closure_id": f"m18-phase-a-{digest[:16]}",
        "completed_submilestones": list(REQUIRED_SUBMILESTONES),
        "fail_closed_case_count": len(REQUIRED_FAIL_CLOSED_CASES),
        "production_mutation_dispatched": False,
        "m19_started": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate M18 Phase A closure evidence")
    parser.add_argument("record", type=Path)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    record = json.loads(args.record.read_text(encoding="utf-8"))
    result = evaluate_phase_a_closure(record, repository_root=args.repository_root)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
