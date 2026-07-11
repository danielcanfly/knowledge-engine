from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path
from typing import Any

REGISTRY_SCHEMA = "knowledge-engine-m17-operator-training-registry/v1"
REPORT_SCHEMA = "knowledge-engine-m17-operator-qualification-report/v1"
REQUIRED_EXERCISES = (
    "architecture_orientation",
    "planned_governed_batch",
    "source_package_review",
    "candidate_evidence_inspection",
    "non_production_dry_run",
    "rollback_drill",
    "closeout_package",
)
ALLOWED_MODES = {"read_only", "local_output", "isolated_fixture"}
ALLOWED_REMOTE_OPERATIONS = {"get", "head"}
ALLOWED_RESULT_STATES = {"passed", "failed", "blocked", "unknown"}
FORBIDDEN_PRIVACY_FRAGMENTS = (
    "authorization:",
    "cookie:",
    "secret_value",
    "access_key",
    "raw_query",
    "raw_answer",
    "private excerpt",
    "client_ip",
    "ip_address",
    "hostname",
    "traceback",
    "exception_text",
    "s3://",
    "r2://",
    "file://",
)
FORBIDDEN_CALLS = {
    "put",
    "delete",
    "promote_release",
    "rollback_release",
    "publish_release",
    "update_ref",
    "append_comment",
    "close_batch",
}
DYNAMIC_IDENTITY_RE = re.compile(
    r"\b[0-9a-f]{40}\b|\b[0-9a-f]{64}\b|"
    r"\b20\d{6}T\d{6}Z-[0-9a-f]{8,}\b"
)
HEX64_RE = re.compile(r"[0-9a-f]{64}")
SAFE_ACTOR_RE = re.compile(r"[a-z0-9][a-z0-9._-]{2,63}")


def canonical_bytes(payload: dict[str, Any]) -> bytes:
    text = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return (text + "\n").encode("utf-8")


def finalize_report(payload: dict[str, Any]) -> dict[str, Any]:
    report = dict(payload)
    report["report_sha256"] = None
    report["report_sha256"] = hashlib.sha256(canonical_bytes(report)).hexdigest()
    return report


def verify_report(payload: dict[str, Any]) -> bool:
    declared = payload.get("report_sha256")
    if not isinstance(declared, str) or HEX64_RE.fullmatch(declared) is None:
        return False
    candidate = dict(payload)
    candidate["report_sha256"] = None
    actual = hashlib.sha256(canonical_bytes(candidate)).hexdigest()
    return actual == declared


def _load_json(path: Path, *, max_bytes: int = 2_000_000) -> Any:
    if not path.is_file():
        raise ValueError(f"file does not exist: {path}")
    if path.stat().st_size > max_bytes:
        raise ValueError(f"file exceeds byte limit: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON file: {path}") from exc


def _privacy_safe(value: Any) -> bool:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False).lower()
    return not any(item in encoded for item in FORBIDDEN_PRIVACY_FRAGMENTS)


def _safe_reference(root: Path, raw_path: str) -> Path:
    candidate = (root / raw_path).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"reference escapes repository root: {raw_path}") from exc
    return candidate


def build_training_plan(registry_path: Path) -> dict[str, Any]:
    registry = _load_json(registry_path)
    if not isinstance(registry, dict):
        raise ValueError("training registry must be an object")
    exercises = registry.get("exercises")
    qualification = registry.get("qualification")
    if not isinstance(exercises, list) or not isinstance(qualification, dict):
        raise ValueError("training registry is incomplete")
    plan = []
    for exercise in exercises:
        if not isinstance(exercise, dict):
            raise ValueError("exercise must be an object")
        plan.append(
            {
                "id": exercise.get("id"),
                "order": exercise.get("order"),
                "title": exercise.get("title"),
                "weight": exercise.get("weight"),
                "critical": exercise.get("critical"),
                "authority_mode": exercise.get("authority_mode"),
                "prerequisites": exercise.get("prerequisites"),
                "deliverables": exercise.get("deliverables"),
                "stop_conditions": exercise.get("stop_conditions"),
            }
        )
    return finalize_report(
        {
            "schema_version": REPORT_SCHEMA,
            "report_type": "training_plan",
            "status": "passed",
            "qualification": qualification,
            "exercise_count": len(plan),
            "exercises": plan,
        }
    )


def assess_submission(
    registry_path: Path,
    submission_path: Path,
) -> dict[str, Any]:
    registry = _load_json(registry_path)
    submission = _load_json(submission_path)
    if not isinstance(registry, dict) or not isinstance(submission, dict):
        raise ValueError("registry and submission must be objects")
    if not _privacy_safe(submission):
        raise ValueError("submission is privacy-unsafe")

    operator_id = submission.get("operator_id")
    evaluator_id = submission.get("evaluator_id")
    attempt = submission.get("attempt")
    results = submission.get("results")
    issues: list[dict[str, str]] = []

    if not isinstance(operator_id, str) or SAFE_ACTOR_RE.fullmatch(operator_id) is None:
        issues.append(_issue("operator_id_invalid", "submission", "invalid operator ID"))
    if not isinstance(evaluator_id, str) or SAFE_ACTOR_RE.fullmatch(evaluator_id) is None:
        issues.append(_issue("evaluator_id_invalid", "submission", "invalid evaluator ID"))
    if operator_id == evaluator_id and isinstance(operator_id, str):
        issues.append(_issue("self_assessment_forbidden", "submission", "evaluator equals operator"))

    qualification = registry.get("qualification")
    exercises = registry.get("exercises")
    if not isinstance(qualification, dict) or not isinstance(exercises, list):
        raise ValueError("training registry is incomplete")
    maximum_attempts = qualification.get("maximum_attempts")
    if not isinstance(attempt, int) or not isinstance(maximum_attempts, int):
        issues.append(_issue("attempt_invalid", "submission", "attempt must be an integer"))
    elif attempt < 1 or attempt > maximum_attempts:
        issues.append(_issue("attempt_out_of_range", "submission", str(attempt)))

    if not isinstance(results, list):
        issues.append(_issue("results_missing", "submission", "results must be a list"))
        results = []

    exercise_map = {
        item.get("id"): item
        for item in exercises
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    seen: set[str] = set()
    normalized_results: list[dict[str, Any]] = []
    total_score = 0
    critical_failures: list[str] = []
    blocking_states: list[str] = []

    for result in results:
        if not isinstance(result, dict):
            issues.append(_issue("result_invalid", "submission", "result must be an object"))
            continue
        exercise_id = result.get("exercise_id")
        if not isinstance(exercise_id, str) or exercise_id not in exercise_map:
            issues.append(_issue("exercise_unknown", "submission", str(exercise_id)))
            continue
        if exercise_id in seen:
            issues.append(_issue("exercise_duplicate", exercise_id, "duplicate result"))
            continue
        seen.add(exercise_id)
        exercise = exercise_map[exercise_id]
        status = result.get("status")
        score = result.get("score")
        evidence = result.get("evidence")
        maximum = exercise.get("weight")

        if status not in ALLOWED_RESULT_STATES:
            issues.append(_issue("status_invalid", exercise_id, str(status)))
            status = "unknown"
        if not isinstance(score, int) or not isinstance(maximum, int):
            issues.append(_issue("score_invalid", exercise_id, str(score)))
            score = 0
        elif score < 0 or score > maximum:
            issues.append(_issue("score_out_of_range", exercise_id, str(score)))
            score = 0
        if status != "passed" and score != 0:
            issues.append(_issue("non_pass_score_nonzero", exercise_id, str(score)))
            score = 0

        minimum_evidence = exercise.get("minimum_evidence_items")
        evidence_items = _validate_evidence(
            exercise_id,
            evidence,
            minimum_evidence if isinstance(minimum_evidence, int) else 1,
            issues,
        )
        total_score += score
        if exercise.get("critical") is True and status != "passed":
            critical_failures.append(exercise_id)
        if status in {"blocked", "unknown"}:
            blocking_states.append(exercise_id)
        normalized_results.append(
            {
                "exercise_id": exercise_id,
                "status": status,
                "score": score,
                "maximum_score": maximum,
                "critical": exercise.get("critical") is True,
                "evidence": evidence_items,
            }
        )

    missing = sorted(set(exercise_map) - seen)
    for exercise_id in missing:
        issues.append(_issue("exercise_missing", exercise_id, "result absent"))
        if exercise_map[exercise_id].get("critical") is True:
            critical_failures.append(exercise_id)

    minimum_score = qualification.get("minimum_score")
    score_passed = isinstance(minimum_score, int) and total_score >= minimum_score
    qualified = (
        not issues
        and score_passed
        and not critical_failures
        and not blocking_states
        and len(seen) == len(exercise_map)
    )
    if blocking_states:
        status = "blocked"
    elif qualified:
        status = "qualified"
    else:
        status = "not_qualified"

    return finalize_report(
        {
            "schema_version": REPORT_SCHEMA,
            "report_type": "qualification_assessment",
            "status": status,
            "operator_id": operator_id,
            "evaluator_id": evaluator_id,
            "attempt": attempt,
            "total_score": total_score,
            "maximum_score": qualification.get("maximum_score"),
            "minimum_score": minimum_score,
            "score_passed": score_passed,
            "critical_failures": sorted(set(critical_failures)),
            "blocking_states": sorted(set(blocking_states)),
            "results": sorted(normalized_results, key=lambda item: str(item["exercise_id"])),
            "issues": sorted(issues, key=lambda item: (item["code"], item["subject"], item["detail"])),
            "qualified": qualified,
        }
    )


def _validate_evidence(
    exercise_id: str,
    evidence: Any,
    minimum: int,
    issues: list[dict[str, str]],
) -> list[dict[str, str]]:
    if not isinstance(evidence, list):
        issues.append(_issue("evidence_missing", exercise_id, "evidence must be a list"))
        return []
    normalized: list[dict[str, str]] = []
    names: set[str] = set()
    for item in evidence:
        if not isinstance(item, dict):
            issues.append(_issue("evidence_invalid", exercise_id, "item must be an object"))
            continue
        name = item.get("name")
        digest = item.get("sha256")
        if not isinstance(name, str) or SAFE_ACTOR_RE.fullmatch(name) is None:
            issues.append(_issue("evidence_name_invalid", exercise_id, str(name)))
            continue
        if name in names:
            issues.append(_issue("evidence_duplicate", exercise_id, name))
            continue
        names.add(name)
        if not isinstance(digest, str) or HEX64_RE.fullmatch(digest) is None:
            issues.append(_issue("evidence_digest_invalid", exercise_id, name))
            continue
        normalized.append({"name": name, "sha256": digest})
    if len(normalized) < minimum:
        issues.append(_issue("evidence_below_minimum", exercise_id, str(minimum)))
    return sorted(normalized, key=lambda item: item["name"])


def validate_training_registry(root: Path, registry_path: Path) -> dict[str, Any]:
    root = root.resolve()
    registry = _load_json(registry_path)
    issues: list[dict[str, str]] = []
    if not isinstance(registry, dict):
        raise ValueError("training registry must be an object")
    if registry.get("schema_version") != REGISTRY_SCHEMA:
        issues.append(_issue("schema_invalid", "registry", str(registry.get("schema_version"))))
    if not _privacy_safe(registry):
        issues.append(_issue("registry_privacy_unsafe", "registry", "forbidden content"))

    qualification = registry.get("qualification")
    exercises = registry.get("exercises")
    competencies = registry.get("required_competencies")
    if not isinstance(qualification, dict):
        issues.append(_issue("qualification_missing", "registry", "object required"))
        qualification = {}
    if not isinstance(exercises, list):
        issues.append(_issue("exercises_missing", "registry", "list required"))
        exercises = []
    if not isinstance(competencies, list) or not competencies:
        issues.append(_issue("competencies_missing", "registry", "non-empty list required"))
        competencies = []

    _validate_policy(qualification, issues)
    ids: list[str] = []
    weights = 0
    covered_competencies: set[str] = set()
    for index, exercise in enumerate(exercises, start=1):
        if not isinstance(exercise, dict):
            issues.append(_issue("exercise_invalid", str(index), "object required"))
            continue
        exercise_id = exercise.get("id")
        subject = exercise_id if isinstance(exercise_id, str) else str(index)
        if not isinstance(exercise_id, str) or not exercise_id:
            issues.append(_issue("exercise_id_invalid", subject, "missing ID"))
            continue
        ids.append(exercise_id)
        if exercise.get("order") != index:
            issues.append(_issue("exercise_order_invalid", subject, str(exercise.get("order"))))
        weight = exercise.get("weight")
        if not isinstance(weight, int) or weight <= 0:
            issues.append(_issue("exercise_weight_invalid", subject, str(weight)))
        else:
            weights += weight
        mode = exercise.get("authority_mode")
        if mode not in ALLOWED_MODES:
            issues.append(_issue("authority_mode_invalid", subject, str(mode)))
        operations = exercise.get("allowed_remote_operations")
        if not isinstance(operations, list) or not set(operations) <= ALLOWED_REMOTE_OPERATIONS:
            issues.append(_issue("remote_operations_invalid", subject, str(operations)))
        if mode != "read_only" and operations:
            issues.append(_issue("remote_operations_mode_conflict", subject, str(operations)))
        for field in (
            "deliverables",
            "passing_criteria",
            "stop_conditions",
            "references",
            "competencies",
        ):
            value = exercise.get(field)
            if not isinstance(value, list) or not value:
                issues.append(_issue(f"{field}_missing", subject, "non-empty list required"))
        exercise_competencies = exercise.get("competencies")
        if isinstance(exercise_competencies, list):
            covered_competencies.update(
                item for item in exercise_competencies if isinstance(item, str)
            )
        _validate_prerequisites(exercise, ids, issues)
        _validate_references(root, exercise, issues)

    if tuple(ids) != REQUIRED_EXERCISES:
        issues.append(_issue("exercise_coverage_invalid", "registry", ",".join(ids)))
    if len(ids) != len(set(ids)):
        issues.append(_issue("exercise_ids_duplicate", "registry", "duplicate IDs"))
    if weights != 100:
        issues.append(_issue("weight_total_invalid", "registry", str(weights)))
    missing_competencies = sorted(set(competencies) - covered_competencies)
    for competency in missing_competencies:
        issues.append(_issue("competency_uncovered", competency, "no exercise covers competency"))

    owned_docs = (
        root / "docs/operations/m17/operator-training.md",
        root / "docs/operations/m17/training-registry.json",
    )
    for path in owned_docs:
        if not path.is_file():
            issues.append(_issue("owned_document_missing", str(path.relative_to(root)), "missing"))
            continue
        text = path.read_text(encoding="utf-8")
        if DYNAMIC_IDENTITY_RE.search(text):
            issues.append(_issue("dynamic_identity_embedded", str(path.relative_to(root)), "found"))
        if not _privacy_safe(text):
            issues.append(_issue("owned_document_privacy_unsafe", str(path.relative_to(root)), "found"))

    for raw_path in (
        "src/knowledge_engine/m17_operator_qualification.py",
        "src/knowledge_engine/m17_operator_qualification_cli.py",
    ):
        path = root / raw_path
        if not path.is_file():
            issues.append(_issue("implementation_missing", raw_path, "missing"))
            continue
        issues.extend(_mutation_call_issues(path, root))

    return finalize_report(
        {
            "schema_version": REPORT_SCHEMA,
            "report_type": "training_registry_acceptance",
            "status": "passed" if not issues else "blocked",
            "exercise_count": len(exercises),
            "critical_exercise_count": sum(
                1 for item in exercises if isinstance(item, dict) and item.get("critical") is True
            ),
            "competency_count": len(competencies),
            "weight_total": weights,
            "issues": sorted(issues, key=lambda item: (item["code"], item["subject"], item["detail"])),
        }
    )


def _validate_policy(
    qualification: dict[str, Any],
    issues: list[dict[str, str]],
) -> None:
    expected = {
        "minimum_score": 85,
        "maximum_score": 100,
        "maximum_attempts": 3,
        "independent_evaluator_required": True,
        "all_critical_exercises_required": True,
        "blocked_or_unknown_disqualifies": True,
        "evidence_digest_required": True,
    }
    for field, value in expected.items():
        if qualification.get(field) != value:
            issues.append(_issue("qualification_policy_invalid", field, str(qualification.get(field))))


def _validate_prerequisites(
    exercise: dict[str, Any],
    prior_ids: list[str],
    issues: list[dict[str, str]],
) -> None:
    exercise_id = str(exercise.get("id"))
    prerequisites = exercise.get("prerequisites")
    if not isinstance(prerequisites, list):
        issues.append(_issue("prerequisites_invalid", exercise_id, "list required"))
        return
    for prerequisite in prerequisites:
        if prerequisite not in prior_ids[:-1]:
            issues.append(_issue("prerequisite_invalid", exercise_id, str(prerequisite)))


def _validate_references(
    root: Path,
    exercise: dict[str, Any],
    issues: list[dict[str, str]],
) -> None:
    subject = str(exercise.get("id"))
    references = exercise.get("references")
    if not isinstance(references, list):
        return
    for reference in references:
        if not isinstance(reference, dict):
            issues.append(_issue("reference_invalid", subject, "object required"))
            continue
        raw_path = reference.get("path")
        anchor = reference.get("anchor")
        if not isinstance(raw_path, str) or not isinstance(anchor, str):
            issues.append(_issue("reference_invalid", subject, str(reference)))
            continue
        try:
            path = _safe_reference(root, raw_path)
        except ValueError as exc:
            issues.append(_issue("reference_path_unsafe", subject, str(exc)))
            continue
        if not path.is_file():
            issues.append(_issue("reference_missing", subject, raw_path))
            continue
        if anchor not in path.read_text(encoding="utf-8"):
            issues.append(_issue("reference_anchor_missing", subject, f"{raw_path}:{anchor}"))


def _mutation_call_issues(path: Path, root: Path) -> list[dict[str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    issues = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = None
        if isinstance(node.func, ast.Name):
            name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            name = node.func.attr
        if name in FORBIDDEN_CALLS:
            issues.append(
                _issue(
                    "mutation_call_forbidden",
                    str(path.relative_to(root)),
                    f"{name}:{getattr(node, 'lineno', 0)}",
                )
            )
    return issues


def _issue(code: str, subject: str, detail: str) -> dict[str, str]:
    return {"code": code, "subject": subject, "detail": detail}
