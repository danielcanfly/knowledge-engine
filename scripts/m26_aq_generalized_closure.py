from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from knowledge_engine.m26_aq_semantic_contract import (
    CANONICAL_RUNTIME_ENTRYPOINT,
    semantic_contract_fingerprint,
)
from m26_aq_final_closure import (
    ANSWER_SOURCE,
    EXPECTED_EDGE_COUNT,
    EXPECTED_GRAPH_SHA256,
    EXPECTED_NODE_COUNT,
    EXPECTED_RELEASE_ID,
    _provider_telemetry,
    _validate_visible_semantics,
    _zero_mutations,
)

REQUIRED_CLASSES = {
    "direct_explanatory": 2,
    "implicit_graph_relationship": 2,
    "cross_document_synthesis": 1,
    "provenance": 1,
    "no_answer": 1,
    "prompt_injection_privacy": 1,
    "grounded_but_irrelevant_adversarial": 1,
}


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _canonical_failures(row: dict[str, Any], expected_sha: str) -> list[str]:
    failures: list[str] = []
    expected_fingerprint = semantic_contract_fingerprint()
    canonical = _mapping(row.get("canonical_runtime"))
    if canonical.get("build_sha") != expected_sha:
        failures.append("runtime_sha_mismatch")
    if canonical.get("entrypoint") != CANONICAL_RUNTIME_ENTRYPOINT:
        failures.append("runtime_entrypoint_mismatch")
    if canonical.get("semantic_contract_fingerprint") != expected_fingerprint:
        failures.append("runtime_fingerprint_mismatch")
    closure = _mapping(row.get("semantic_closure"))
    contract = _mapping(closure.get("semantic_contract"))
    if contract and contract.get("fingerprint") != expected_fingerprint:
        failures.append("semantic_closure_fingerprint_mismatch")
    return failures


def _validate_answer_row(row: dict[str, Any], failures: list[str], expected_sha: str) -> None:
    case_id = str(row.get("case_id", "unknown"))
    for failure in _canonical_failures(row, expected_sha):
        failures.append(f"{case_id}:{failure}")
    accounting = _mapping(row.get("accounting"))
    provider_calls = int(accounting.get("provider_call_count", 0))
    if row.get("safe_abstention") or row.get("status") != "owner_only_cited_answer":
        failures.append(f"{case_id}:not_answered")
    if row.get("answer_source") != ANSWER_SOURCE:
        failures.append(f"{case_id}:wrong_answer_source")
    if not str(row.get("answer_text", "")).strip():
        failures.append(f"{case_id}:empty_answer")
    if not row.get("citations"):
        failures.append(f"{case_id}:missing_citations")
    if provider_calls < 1 or provider_calls > 2:
        failures.append(f"{case_id}:provider_call_count")

    integrity = _mapping(row.get("integrity"))
    if int(integrity.get("unsupported_accepted_claims", 0)) != 0:
        failures.append(f"{case_id}:unsupported_claims")
    if not integrity.get("material_claim_support_verified", False):
        failures.append(f"{case_id}:material_support_not_verified")
    if not integrity.get("citation_locator_valid", False):
        failures.append(f"{case_id}:citation_locator_invalid")

    closure = _mapping(row.get("semantic_closure"))
    if closure.get("failures"):
        failures.append(f"{case_id}:semantic_closure_failures")
    if closure.get("broad_deterministic_fallback_used") is not False:
        failures.append(f"{case_id}:deterministic_fallback")

    for telemetry in _provider_telemetry(row):
        if not isinstance(telemetry, dict):
            failures.append(f"{case_id}:invalid_provider_telemetry")
            continue
        if str(telemetry.get("stop_reason", "")).casefold() in {"max_tokens", "length"}:
            failures.append(f"{case_id}:provider_max_tokens")
        parse = telemetry.get("parse_telemetry", {})
        if not isinstance(parse, dict) or not parse.get("parse_ok", False):
            failures.append(f"{case_id}:provider_parse_failure")

    for semantic_failure in _validate_visible_semantics(row):
        failures.append(f"{case_id}:{semantic_failure}")


def _validate_abstention_row(row: dict[str, Any], failures: list[str], expected_sha: str) -> None:
    case_id = str(row.get("case_id", "unknown"))
    for failure in _canonical_failures(row, expected_sha):
        failures.append(f"{case_id}:{failure}")
    accounting = _mapping(row.get("accounting"))
    provider_calls = int(accounting.get("provider_call_count", 0))
    if not row.get("safe_abstention") or row.get("status") != "owner_only_safe_abstention":
        failures.append(f"{case_id}:expected_safe_abstention")
    if provider_calls < 0 or provider_calls > 2:
        failures.append(f"{case_id}:provider_call_count")
    if str(row.get("answer_text", "")).strip():
        failures.append(f"{case_id}:abstention_has_answer_text")
    if row.get("citations"):
        failures.append(f"{case_id}:abstention_has_citations")


def validate(*, input_path: Path, expected_sha: str, minimum: int) -> None:
    artifact = json.loads(input_path.read_text(encoding="utf-8"))
    failures: list[str] = []
    expected_fingerprint = semantic_contract_fingerprint()
    health = _mapping(artifact.get("health"))
    graph = _mapping(artifact.get("graph"))

    if health.get("http_status") != 200 or health.get("status") != "ok":
        failures.append("health_not_ok")
    if health.get("build_sha") != expected_sha:
        failures.append("health_build_sha_mismatch")
    if health.get("entrypoint") != CANONICAL_RUNTIME_ENTRYPOINT:
        failures.append("wrong_production_entrypoint")
    if health.get("semantic_contract_fingerprint") != expected_fingerprint:
        failures.append("health_semantic_fingerprint_mismatch")

    if graph.get("http_status") != 200 or graph.get("status") != "ok":
        failures.append("graph_not_ok")
    if graph.get("graph_scope") != "full_current_production_relation_graph":
        failures.append("graph_scope_mismatch")
    if graph.get("release_id") != EXPECTED_RELEASE_ID:
        failures.append("graph_release_mismatch")
    if graph.get("graph_v2_sha256") != EXPECTED_GRAPH_SHA256:
        failures.append("graph_sha_mismatch")
    if graph.get("node_count") != EXPECTED_NODE_COUNT or graph.get("edge_count") != EXPECTED_EDGE_COUNT:
        failures.append("graph_population_mismatch")

    rows = artifact.get("rows", [])
    if not isinstance(rows, list):
        rows = []
        failures.append("rows_not_list")
    if len(rows) < minimum:
        failures.append(f"population_below_minimum:{len(rows)}<{minimum}")

    class_counts: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict):
            failures.append("invalid_row")
            continue
        case_id = str(row.get("case_id", "unknown"))
        class_name = str(row.get("class", ""))
        class_counts[class_name] = class_counts.get(class_name, 0) + 1
        if row.get("http_status") != 200:
            failures.append(f"{case_id}:http")
            continue
        if not _zero_mutations(row.get("mutations", {})):
            failures.append(f"{case_id}:protected_mutation")
        expected = str(row.get("expected", "answer"))
        if expected == "abstain":
            _validate_abstention_row(row, failures, expected_sha)
        elif expected == "answer":
            _validate_answer_row(row, failures, expected_sha)
        else:
            failures.append(f"{case_id}:unknown_expected:{expected}")

    for class_name, required in REQUIRED_CLASSES.items():
        if class_counts.get(class_name, 0) < required:
            failures.append(f"class_coverage:{class_name}:{class_counts.get(class_name, 0)}<{required}")

    privacy = _mapping(artifact.get("privacy"))
    for key in ("raw_backend_token_recorded", "raw_owner_hash_recorded", "provider_secret_recorded"):
        if privacy.get(key) is not False:
            failures.append(f"privacy:{key}")

    if failures:
        print(json.dumps({"status": "FAIL", "failures": sorted(set(failures))}, indent=2))
        raise SystemExit(1)
    print(
        json.dumps(
            {"status": "PASS", "rows": len(rows), "class_counts": class_counts, "deploy_sha": expected_sha},
            indent=2,
            sort_keys=True,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--minimum", type=int, default=20)
    args = parser.parse_args()
    validate(input_path=args.input, expected_sha=args.expected_sha, minimum=args.minimum)


if __name__ == "__main__":
    main()
