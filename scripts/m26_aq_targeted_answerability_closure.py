from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from knowledge_engine.m26_aq_semantic_contract import (
    CANONICAL_RUNTIME_ENTRYPOINT,
    semantic_contract_fingerprint,
)

INTERNAL_LABEL_RE = re.compile(r"(?:\[\[?e\d+\]?\]|\be\d+\b)", re.IGNORECASE)
EXPECTED_GROUP_COUNTS = {
    "A_original_reproduction": 5,
    "B_new_variant": 5,
    "C_known_good_control": 5,
    "D_ood_control": 4,
}
RECOVERY_KEY = "universal_answerability_recovery"
RECOVERY_SCHEMAS = {"m26-aq-final-universal-recovery-telemetry/v2"}


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _is_zero_mutation(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    for item in value.values():
        if isinstance(item, bool):
            return False
        try:
            if int(item) != 0:
                return False
        except (TypeError, ValueError):
            return False
    return True


def _source_identities(row: Mapping[str, Any], *, used: bool) -> list[str]:
    trace = row.get("evidence_utilization_trace", {})
    if isinstance(trace, Mapping):
        key = "used_source_identities" if used else "selected_source_identities"
        identities = trace.get(key, [])
        if isinstance(identities, Sequence) and not isinstance(identities, str):
            return sorted({str(item) for item in identities if str(item)})
    if not used:
        selected = row.get("selected_evidence", [])
        if isinstance(selected, Sequence) and not isinstance(selected, str):
            identities = []
            for item in selected:
                if isinstance(item, Mapping):
                    identity = item.get("source_identity") or item.get("source_id")
                    if identity:
                        identities.append(str(identity))
            return sorted(set(identities))
    return []


def _integrity(row: Mapping[str, Any], key: str, default: Any = None) -> Any:
    integrity = row.get("integrity", {})
    if isinstance(integrity, Mapping) and key in integrity:
        return integrity.get(key)
    verification = row.get("multi_evidence_verification", {})
    if isinstance(verification, Mapping) and key in verification:
        return verification.get(key)
    return default


def _selected_evidence_count(row: Mapping[str, Any]) -> int:
    trace = row.get("evidence_utilization_trace", {})
    if isinstance(trace, Mapping) and isinstance(trace.get("selected_evidence_count"), int):
        return int(trace["selected_evidence_count"])
    selected = row.get("selected_evidence", [])
    return len(selected) if isinstance(selected, Sequence) and not isinstance(selected, str) else 0


def _used_evidence_count(row: Mapping[str, Any]) -> int:
    trace = row.get("evidence_utilization_trace", {})
    if isinstance(trace, Mapping) and isinstance(trace.get("used_evidence_count"), int):
        return int(trace["used_evidence_count"])
    relationship = row.get("relationship_summary", {})
    if isinstance(relationship, Mapping):
        used = relationship.get("used_evidence_ids", [])
        if isinstance(used, Sequence) and not isinstance(used, str):
            return len(used)
    return 0


def _graph_selected_count(row: Mapping[str, Any]) -> int:
    graph = row.get("graph_observability", {})
    if isinstance(graph, Mapping) and isinstance(graph.get("selected_graph_derived_evidence_count"), int):
        return int(graph["selected_graph_derived_evidence_count"])
    return 0


def _recovery_telemetry(row: Mapping[str, Any]) -> dict[str, Any]:
    verification = row.get("multi_evidence_verification", {})
    if isinstance(verification, Mapping) and isinstance(verification.get(RECOVERY_KEY), Mapping):
        return dict(verification[RECOVERY_KEY])
    semantic = row.get("semantic_closure", {})
    if isinstance(semantic, Mapping) and isinstance(semantic.get(RECOVERY_KEY), Mapping):
        return dict(semantic[RECOVERY_KEY])
    return {}


def _list_field(telemetry: Mapping[str, Any], key: str) -> list[Any]:
    value = telemetry.get(key, [])
    return list(value) if isinstance(value, list) else []


def _canonical_identity_failures(row: Mapping[str, Any], expected_sha: str) -> list[str]:
    failures: list[str] = []
    runtime = _mapping(row.get("canonical_runtime"))
    expected_fingerprint = semantic_contract_fingerprint()
    if runtime.get("build_sha") != expected_sha:
        failures.append("runtime_sha_mismatch")
    if runtime.get("entrypoint") != CANONICAL_RUNTIME_ENTRYPOINT:
        failures.append("runtime_entrypoint_mismatch")
    if runtime.get("semantic_contract_fingerprint") != expected_fingerprint:
        failures.append("runtime_fingerprint_mismatch")
    closure = _mapping(row.get("semantic_closure"))
    contract = _mapping(closure.get("semantic_contract"))
    if contract and contract.get("fingerprint") != expected_fingerprint:
        failures.append("semantic_closure_fingerprint_mismatch")
    return failures


def _validate_alignment_telemetry(telemetry: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    required = _list_field(telemetry, "required_question_facets")
    covered = _list_field(telemetry, "covered_question_facets")
    missing = _list_field(telemetry, "missing_question_facets")
    relevance = _list_field(telemetry, "recovery_selected_evidence_relevance")
    if telemetry.get("question_alignment_checked") is not True:
        failures.append("recovery:question_alignment_not_checked")
    if telemetry.get("question_alignment_passed") is not True:
        failures.append("recovery:question_alignment_not_passed")
    if telemetry.get("question_alignment_failure_codes") not in ([], None):
        failures.append("recovery:question_alignment_failures_present")
    if not required:
        failures.append("recovery:required_question_facets_empty")
    if not covered:
        failures.append("recovery:covered_question_facets_empty")
    if missing:
        failures.append("recovery:missing_question_facets_present")
    if telemetry.get("post_render_alignment_checked") is not True:
        failures.append("recovery:post_render_alignment_not_checked")
    if telemetry.get("post_render_alignment_passed") is not True:
        failures.append("recovery:post_render_alignment_not_passed")
    if telemetry.get("post_render_alignment_failure_codes") not in ([], None):
        failures.append("recovery:post_render_alignment_failures_present")
    if telemetry.get("quote_facet_support_checked") is not True:
        failures.append("recovery:quote_facet_support_not_checked")
    if telemetry.get("quote_facet_support_passed") is not True:
        failures.append("recovery:quote_facet_support_not_passed")
    if telemetry.get("recovery_relevance_threshold_met") is not True:
        failures.append("recovery:relevance_threshold_not_met")
    if not relevance:
        failures.append("recovery:missing_relevance_records")
    else:
        for record in relevance:
            if not isinstance(record, Mapping) or record.get("eligible") is not True:
                failures.append("recovery:ineligible_relevance_record")
                break
            quote = record.get("quote_support", {})
            if not isinstance(quote, Mapping) or quote.get("eligible") is not True:
                failures.append("recovery:ineligible_quote_support_record")
                break
    return failures


def _validate_recovery_telemetry(row: Mapping[str, Any], *, expected: str, group: str) -> list[str]:
    failures: list[str] = []
    telemetry = _recovery_telemetry(row)
    if group == "A_original_reproduction" and not telemetry:
        return ["recovery:missing_group_a_telemetry"]
    if not telemetry:
        return failures
    if telemetry.get("schema_version") not in RECOVERY_SCHEMAS:
        failures.append("recovery:schema_version_mismatch")
    if telemetry.get("case_specific") is not False:
        failures.append("recovery:case_specific_not_false")
    try:
        evidence_count = int(telemetry.get("recovery_input_evidence_count", 0))
        item_count = int(telemetry.get("recovery_items_count", 0))
        text_count = int(telemetry.get("recovery_text_available_count", 0))
    except (TypeError, ValueError):
        evidence_count = item_count = text_count = -1
    if expected == "answer" and group == "A_original_reproduction" and evidence_count <= 0:
        failures.append("recovery:missing_input_evidence_count")
    if item_count < 0 or text_count < 0:
        failures.append("recovery:invalid_item_or_text_count")
    answer_source = str(row.get("answer_source", ""))
    first_stage = str(telemetry.get("first_broken_stage", ""))
    hard_stop_codes = telemetry.get("universal_recovery_hard_stop_codes", [])
    hard_stop_present = isinstance(hard_stop_codes, list) and bool(hard_stop_codes)
    published = telemetry.get("published_verified_answer") is True
    should_attempt = telemetry.get("universal_recovery_should_attempt") is True
    if expected == "answer" and group == "A_original_reproduction":
        natural_provider_ok = (
            first_stage in {"not_needed", "none"}
            and not hard_stop_present
            and answer_source != "deterministic_verified_evidence_recovery"
        )
        recovery_ok = (
            should_attempt
            and telemetry.get("candidate_built") is True
            and telemetry.get("candidate_verify_result") == "verified"
            and published
            and first_stage == "none"
            and answer_source == "deterministic_verified_evidence_recovery"
        )
        if recovery_ok:
            failures.extend(_validate_alignment_telemetry(telemetry))
        if not (natural_provider_ok or recovery_ok):
            failures.append("recovery:group_a_hook_outcome_invalid")
        if telemetry.get("candidate_verify_result") == "exception":
            failures.append("recovery:candidate_exception")
    if expected == "abstain":
        if published or answer_source == "deterministic_verified_evidence_recovery":
            failures.append("recovery:ood_published_answer")
        if should_attempt and not hard_stop_present:
            failures.append("recovery:ood_attempt_without_hard_stop")
    return failures


def _is_non_blocking_group_a_telemetry_failure(
    *,
    group: str,
    product_failures: Sequence[str],
    telemetry_failures: Sequence[str],
) -> bool:
    return (
        group == "A_original_reproduction"
        and list(telemetry_failures) == ["recovery:missing_group_a_telemetry"]
        and not list(product_failures)
    )


def _validate_answerable(row: Mapping[str, Any], expected_sha: str) -> list[str]:
    failures = _canonical_identity_failures(row, expected_sha)
    answer_text = str(row.get("answer_text", ""))
    citations = row.get("citations", [])
    claims = row.get("answer_claims", [])
    status = str(row.get("status", ""))
    if status != "owner_only_cited_answer":
        failures.append("answerable:not_owner_only_cited_answer")
    if row.get("safe_abstention") is True:
        failures.append("answerable:safe_abstention_true")
    if not answer_text.strip():
        failures.append("answerable:empty_answer")
    if INTERNAL_LABEL_RE.search(answer_text):
        failures.append("answerable:visible_internal_evidence_label")
    if not isinstance(citations, list) or not citations:
        failures.append("answerable:missing_citations")
    if not isinstance(claims, list) or not claims:
        failures.append("answerable:missing_answer_claims")
    if _integrity(row, "unsupported_accepted_claims", 1) != 0:
        failures.append("answerable:unsupported_accepted_claims")
    if _integrity(row, "citation_locator_valid", False) is not True:
        failures.append("answerable:citation_locator_invalid")
    if _integrity(row, "material_claim_support_verified", False) is not True:
        failures.append("answerable:material_support_not_verified")
    if not _is_zero_mutation(row.get("mutations")):
        failures.append("answerable:mutation_detected")
    return failures


def _validate_abstain(row: Mapping[str, Any], expected_sha: str) -> list[str]:
    failures = _canonical_identity_failures(row, expected_sha)
    citations = row.get("citations", [])
    claims = row.get("answer_claims", [])
    status = str(row.get("status", ""))
    safe = (
        row.get("safe_abstention") is True
        or status == "owner_only_safe_abstention"
        or row.get("answer_source") == "safe_abstention"
    )
    if not safe:
        failures.append("abstain:not_safe_abstention")
    if isinstance(citations, list) and citations:
        failures.append("abstain:fabricated_or_unexpected_citations")
    if isinstance(claims, list) and claims:
        failures.append("abstain:unexpected_answer_claims")
    if _integrity(row, "unsupported_accepted_claims", 0) != 0:
        failures.append("abstain:unsupported_accepted_claims")
    if not _is_zero_mutation(row.get("mutations")):
        failures.append("abstain:mutation_detected")
    return failures


def _case_summary(row: Mapping[str, Any], expected: str, group: str) -> dict[str, Any]:
    accounting = row.get("accounting", {})
    telemetry = _recovery_telemetry(row)
    runtime = row.get("canonical_runtime", {}) if isinstance(row.get("canonical_runtime"), Mapping) else {}
    return {
        "case_id": row.get("case_id", ""),
        "group": group,
        "expected": expected,
        "actual_status": row.get("status", ""),
        "terminal_status": row.get("terminal_status", ""),
        "answer_source": row.get("answer_source", ""),
        "safe_abstention": row.get("safe_abstention", False),
        "provider_call_count": accounting.get("provider_call_count", "") if isinstance(accounting, Mapping) else "",
        "selected_evidence_count": _selected_evidence_count(row),
        "used_evidence_count": _used_evidence_count(row),
        "graph_selected_count": _graph_selected_count(row),
        "selected_source_identities": ";".join(_source_identities(row, used=False)),
        "used_source_identities": ";".join(_source_identities(row, used=True)),
        "citation_count": len(row.get("citations", [])) if isinstance(row.get("citations", []), list) else 0,
        "unsupported_accepted_claims": _integrity(row, "unsupported_accepted_claims", ""),
        "citation_locator_valid": _integrity(row, "citation_locator_valid", ""),
        "material_claim_support_verified": _integrity(row, "material_claim_support_verified", ""),
        "mutation_zero": _is_zero_mutation(row.get("mutations")),
        "recovery_telemetry_present": bool(telemetry),
        "recovery_should_attempt": telemetry.get("universal_recovery_should_attempt", ""),
        "recovery_candidate_built": telemetry.get("candidate_built", ""),
        "recovery_verify_result": telemetry.get("candidate_verify_result", ""),
        "recovery_first_broken_stage": telemetry.get("first_broken_stage", ""),
        "recovery_published_verified_answer": telemetry.get("published_verified_answer", ""),
        "question_alignment_checked": telemetry.get("question_alignment_checked", ""),
        "question_alignment_passed": telemetry.get("question_alignment_passed", ""),
        "required_question_facets": ";".join(str(item) for item in _list_field(telemetry, "required_question_facets")),
        "covered_question_facets": ";".join(str(item) for item in _list_field(telemetry, "covered_question_facets")),
        "missing_question_facets": ";".join(str(item) for item in _list_field(telemetry, "missing_question_facets")),
        "post_render_alignment_checked": telemetry.get("post_render_alignment_checked", ""),
        "post_render_alignment_passed": telemetry.get("post_render_alignment_passed", ""),
        "recovery_relevance_threshold_met": telemetry.get("recovery_relevance_threshold_met", ""),
        "runtime_sha": runtime.get("build_sha", ""),
        "runtime_entrypoint": runtime.get("entrypoint", ""),
        "runtime_fingerprint": runtime.get("semantic_contract_fingerprint", ""),
        "answer_text": str(row.get("answer_text", "")),
    }


def _write_csv(path: Path, summaries: Sequence[Mapping[str, Any]]) -> None:
    if not summaries:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = [key for key in summaries[0] if key != "answer_text"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for summary in summaries:
            writer.writerow({key: summary.get(key, "") for key in fieldnames})


def _write_raw_answers(path: Path, summaries: Sequence[Mapping[str, Any]]) -> None:
    lines = ["# Targeted Universal Answerability Raw Answers", ""]
    for summary in summaries:
        lines.extend(
            [
                f"## {summary['case_id']}",
                "",
                f"- group: `{summary['group']}`",
                f"- expected: `{summary['expected']}`",
                f"- actual_status: `{summary['actual_status']}`",
                f"- answer_source: `{summary['answer_source']}`",
                f"- citation_count: `{summary['citation_count']}`",
                f"- runtime_entrypoint: `{summary['runtime_entrypoint']}`",
                f"- runtime_fingerprint: `{summary['runtime_fingerprint']}`",
                f"- recovery_telemetry_present: `{summary['recovery_telemetry_present']}`",
                f"- recovery_first_broken_stage: `{summary['recovery_first_broken_stage']}`",
                f"- question_alignment_passed: `{summary['question_alignment_passed']}`",
                f"- required_question_facets: `{summary['required_question_facets']}`",
                f"- covered_question_facets: `{summary['covered_question_facets']}`",
                f"- missing_question_facets: `{summary['missing_question_facets']}`",
                f"- post_render_alignment_passed: `{summary['post_render_alignment_passed']}`",
                "",
                str(summary.get("answer_text", "")).strip() or "[empty answer]",
                "",
            ]
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def validate(
    *,
    input_path: Path,
    questions_path: Path,
    expected_sha: str,
    summary_path: Path,
    csv_path: Path,
    raw_answers_path: Path,
) -> None:
    artifact = _json(input_path)
    questions = _json(questions_path)
    question_rows = questions.get("questions", [])
    artifact_rows = artifact.get("rows", [])
    failures: list[str] = []
    expected_fingerprint = semantic_contract_fingerprint()

    if len(question_rows) != 19:
        failures.append(f"question_count:{len(question_rows)}")
    if len(artifact_rows) != 19:
        failures.append(f"row_count:{len(artifact_rows)}")
    if artifact.get("expected_deploy_sha") != expected_sha:
        failures.append("artifact_expected_sha_mismatch")
    collection = artifact.get("collection", {})
    if not isinstance(collection, Mapping) or collection.get("status") != "complete":
        failures.append("collection_not_complete")
    health = _mapping(artifact.get("health"))
    if health.get("entrypoint") != CANONICAL_RUNTIME_ENTRYPOINT:
        failures.append("health_entrypoint_mismatch")
    if health.get("semantic_contract_fingerprint") != expected_fingerprint:
        failures.append("health_fingerprint_mismatch")

    group_counts = Counter(str(item.get("group", "")) for item in question_rows)
    if dict(group_counts) != EXPECTED_GROUP_COUNTS:
        failures.append(f"group_counts:{dict(group_counts)}")
    expected_counts = Counter(str(item.get("expected", "")) for item in question_rows)
    if expected_counts != {"answer": 15, "abstain": 4}:
        failures.append(f"expected_counts:{dict(expected_counts)}")

    rows_by_id = {str(row.get("case_id", "")): row for row in artifact_rows}
    summaries: list[dict[str, Any]] = []
    non_blocking_diagnostics: list[str] = []
    for question in question_rows:
        case_id = str(question.get("case_id", ""))
        expected = str(question.get("expected", ""))
        group = str(question.get("group", ""))
        row = rows_by_id.get(case_id)
        if row is None:
            failures.append(f"{case_id}:missing_row")
            continue
        product_failures: list[str] = []
        if expected == "answer":
            product_failures.extend(_validate_answerable(row, expected_sha))
        elif expected == "abstain":
            product_failures.extend(_validate_abstain(row, expected_sha))
        else:
            failures.append(f"{case_id}:unknown_expected:{expected}")
        failures.extend(f"{case_id}:{item}" for item in product_failures)
        telemetry_failures = _validate_recovery_telemetry(row, expected=expected, group=group)
        if _is_non_blocking_group_a_telemetry_failure(
            group=group,
            product_failures=product_failures,
            telemetry_failures=telemetry_failures,
        ):
            non_blocking_diagnostics.append(f"{case_id}:recovery:missing_group_a_telemetry")
        else:
            failures.extend(f"{case_id}:{item}" for item in telemetry_failures)
        summaries.append(_case_summary(row, expected, group))

    summary = {
        "schema_version": "m26-aq-targeted-answerability-validation/v4",
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "expected_deploy_sha": expected_sha,
        "canonical_runtime_entrypoint": CANONICAL_RUNTIME_ENTRYPOINT,
        "canonical_semantic_contract_fingerprint": expected_fingerprint,
        "question_file_sha256": _sha256(questions_path),
        "input_file_sha256": _sha256(input_path),
        "rows": len(artifact_rows),
        "answerable_expected": 15,
        "abstain_expected": 4,
        "group_counts": dict(group_counts),
        "recovery_telemetry_required_for_group_a": True,
        "recovery_question_alignment_required": True,
        "case_summaries": summaries,
        "missing_group_a_telemetry_non_blocking_when_product_passes": True,
        "non_blocking_diagnostics": non_blocking_diagnostics,
    }
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    _write_csv(csv_path, summaries)
    _write_raw_answers(raw_answers_path, summaries)
    print(json.dumps({k: summary[k] for k in ("status", "rows", "failures")}, indent=2))
    if failures:
        raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--raw-answers", type=Path, required=True)
    args = parser.parse_args()
    validate(
        input_path=args.input,
        questions_path=args.questions,
        expected_sha=args.expected_sha,
        summary_path=args.summary,
        csv_path=args.csv,
        raw_answers_path=args.raw_answers,
    )


if __name__ == "__main__":
    main()
