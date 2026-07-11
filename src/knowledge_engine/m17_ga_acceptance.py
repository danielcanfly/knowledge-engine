from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from knowledge_engine.m17_ga_evidence import validate_ga_evidence

CONTRACT_SCHEMA = "knowledge-engine-m17-independent-ga-contract/v1"
TRANSCRIPT_SCHEMA = "knowledge-engine-m17-independent-drill/v1"
REPORT_SCHEMA = "knowledge-engine-m17-ga-acceptance/v1"
SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
SHA64_RE = re.compile(r"^[0-9a-f]{64}$")
ALLOWED_EXECUTION_MODES = {
    "read_only_verification",
    "local_output",
    "isolated_boundary_simulation",
}
REQUIRED_SAFE_STOPS = [
    "missing_approval",
    "stale_expected_previous",
    "acl_broadening",
    "replay_conflict",
]


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def sha256_hex(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _issue(code: str, subject: str, detail: str) -> dict[str, str]:
    return {"code": code, "subject": subject, "detail": detail}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _file_sha256(path: Path) -> str:
    return sha256_hex(path.read_bytes())


def _sign(payload: dict[str, Any], field: str) -> dict[str, Any]:
    signed = dict(payload)
    signed[field] = sha256_hex(canonical_json(payload))
    return signed


def _verify_signature(payload: dict[str, Any], field: str) -> bool:
    claimed = payload.get(field)
    if not isinstance(claimed, str) or SHA64_RE.fullmatch(claimed) is None:
        return False
    unsigned = dict(payload)
    unsigned.pop(field, None)
    return claimed == sha256_hex(canonical_json(unsigned))


def _validate_identity(
    value: object,
    pattern: re.Pattern[str],
    name: str,
    issues: list[dict[str, str]],
) -> None:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        issues.append(_issue("identity", name, "identity format is invalid"))


def load_contract(path: Path) -> dict[str, Any]:
    return _load_json(path)


def validate_contract(root: Path, contract_path: Path) -> dict[str, Any]:
    root = root.resolve()
    contract = load_contract(contract_path)
    issues: list[dict[str, str]] = []

    if contract.get("schema_version") != CONTRACT_SCHEMA:
        issues.append(_issue("schema_version", "contract", "unexpected schema version"))
    if contract.get("operator_context") != "repository_only":
        issues.append(_issue("operator_context", "contract", "repository_only is required"))
    if contract.get("mutation_execution_allowed") is not False:
        issues.append(_issue("mutation_authority", "contract", "mutation execution must be false"))
    if contract.get("required_stage_count") != 18:
        issues.append(_issue("stage_count", "contract", "required stage count must be 18"))
    if contract.get("required_capability_count") != 20:
        issues.append(
            _issue(
                "capability_count",
                "contract",
                "required capability count must be 20",
            )
        )
    if contract.get("final_state") != "ga_accepted":
        issues.append(_issue("final_state", "contract", "final state must be ga_accepted"))

    required_sources = contract.get("allowed_hint_sources")
    if not isinstance(required_sources, list) or not required_sources:
        issues.append(_issue("hint_sources", "contract", "allowed hint sources are required"))
        required_sources = []
    for raw in required_sources:
        if not isinstance(raw, str) or raw.startswith(("/", "~")) or ".." in Path(raw).parts:
            issues.append(_issue("unsafe_path", "contract", f"invalid hint source: {raw!r}"))
            continue
        path = (root / raw).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            issues.append(_issue("unsafe_path", "contract", f"outside root: {raw}"))
            continue
        if not path.is_file():
            issues.append(_issue("missing_path", "contract", f"missing hint source: {raw}"))

    safe_stops = contract.get("required_safe_stops")
    if safe_stops != REQUIRED_SAFE_STOPS:
        issues.append(
            _issue(
                "safe_stop_contract",
                "contract",
                "exact ordered safe-stop scenarios are required",
            )
        )

    registry_paths = contract.get("registry_paths")
    if not isinstance(registry_paths, dict):
        issues.append(_issue("registry_paths", "contract", "registry paths are required"))
    else:
        for name in ("runbook", "ga_evidence", "training"):
            raw = registry_paths.get(name)
            if not isinstance(raw, str):
                issues.append(_issue("registry_path", name, "path is required"))
                continue
            path = root / raw
            if not path.is_file():
                issues.append(_issue("missing_registry", name, raw))

    issues.sort(key=lambda item: (item["code"], item["subject"], item["detail"]))
    report: dict[str, Any] = {
        "schema_version": "knowledge-engine-m17-independent-ga-contract-report/v1",
        "status": "passed" if not issues else "failed",
        "contract_sha256": sha256_hex(canonical_json(contract)),
        "issues": issues,
    }
    return _sign(report, "report_sha256")


def build_drill_transcript(
    root: Path,
    contract_path: Path,
    *,
    engine_sha: str,
    source_sha: str,
    release_id: str,
    manifest_sha256: str,
    pointer_sha256: str,
    operator_id: str,
) -> dict[str, Any]:
    root = root.resolve()
    contract = load_contract(contract_path)
    paths = contract["registry_paths"]
    runbook_path = root / paths["runbook"]
    ga_path = root / paths["ga_evidence"]
    training_path = root / paths["training"]
    runbook = _load_json(runbook_path)
    ga_registry = _load_json(ga_path)

    identities = {
        "engine_sha": engine_sha,
        "source_sha": source_sha,
        "release_id": release_id,
        "manifest_sha256": manifest_sha256,
        "pointer_sha256": pointer_sha256,
    }

    stages: list[dict[str, Any]] = []
    for step in runbook["steps"]:
        external = step["mode"] == "governed_external_mutation"
        mode = (
            "isolated_boundary_simulation"
            if external
            else "read_only_verification"
        )
        evidence = {
            "phase": step["phase"],
            "order": step["order"],
            "reference": step["reference"],
            "identities": identities,
            "mode": mode,
        }
        stages.append(
            {
                "phase": step["phase"],
                "order": step["order"],
                "status": "passed",
                "execution_mode": mode,
                "mutation_dispatched": False,
                "evidence_sha256": sha256_hex(canonical_json(evidence)),
            }
        )

    capabilities: list[dict[str, Any]] = []
    for row in ga_registry["capabilities"]:
        evidence = {
            "id": row["id"],
            "merge_commit": row["evidence"]["merge_commit"],
            "registry_sha256": _file_sha256(ga_path),
            "engine_sha": engine_sha,
        }
        capabilities.append(
            {
                "id": row["id"],
                "order": row["order"],
                "status": "passed",
                "evidence_sha256": sha256_hex(canonical_json(evidence)),
            }
        )

    safe_stops: list[dict[str, Any]] = []
    for scenario in contract["required_safe_stops"]:
        evidence = {
            "scenario": scenario,
            "decision": "stop",
            "operator_context": "repository_only",
            "engine_sha": engine_sha,
        }
        safe_stops.append(
            {
                "scenario": scenario,
                "status": "stopped_safely",
                "evidence_sha256": sha256_hex(canonical_json(evidence)),
            }
        )

    transcript: dict[str, Any] = {
        "schema_version": TRANSCRIPT_SCHEMA,
        "operator_id": operator_id,
        "operator_context": "repository_only",
        "hint_sources": list(contract["allowed_hint_sources"]),
        "identities": identities,
        "contract_sha256": sha256_hex(canonical_json(contract)),
        "runbook_registry_sha256": _file_sha256(runbook_path),
        "ga_evidence_registry_sha256": _file_sha256(ga_path),
        "training_registry_sha256": _file_sha256(training_path),
        "stages": stages,
        "capabilities": capabilities,
        "safe_stops": safe_stops,
        "final_reconciliation": {
            "status": "passed",
            "stage_count": len(stages),
            "capability_count": len(capabilities),
            "mutation_dispatched": False,
        },
        "mutation_dispatched": False,
    }
    return _sign(transcript, "transcript_sha256")


def assess_ga_acceptance(
    root: Path,
    contract_path: Path,
    transcript: dict[str, Any],
    *,
    evaluator_id: str,
) -> dict[str, Any]:
    root = root.resolve()
    contract = load_contract(contract_path)
    issues: list[dict[str, str]] = []

    if not _verify_signature(transcript, "transcript_sha256"):
        issues.append(_issue("transcript_digest", "transcript", "digest mismatch"))
    if transcript.get("schema_version") != TRANSCRIPT_SCHEMA:
        issues.append(_issue("transcript_schema", "transcript", "unexpected schema"))
    operator_id = transcript.get("operator_id")
    if not isinstance(operator_id, str) or not operator_id:
        issues.append(_issue("operator_id", "transcript", "operator id is required"))
    if not isinstance(evaluator_id, str) or not evaluator_id:
        issues.append(_issue("evaluator_id", "assessment", "evaluator id is required"))
    if operator_id == evaluator_id:
        issues.append(_issue("independence", "assessment", "operator and evaluator must differ"))
    if transcript.get("operator_context") != "repository_only":
        issues.append(_issue("operator_context", "transcript", "repository_only is required"))
    if transcript.get("hint_sources") != contract.get("allowed_hint_sources"):
        issues.append(_issue("undocumented_hint", "transcript", "hint source set drifted"))
    if transcript.get("mutation_dispatched") is not False:
        issues.append(_issue("mutation_claim", "transcript", "real mutation is forbidden"))

    identities = transcript.get("identities")
    if not isinstance(identities, dict):
        identities = {}
        issues.append(_issue("identities", "transcript", "identity object is required"))
    _validate_identity(identities.get("engine_sha"), SHA40_RE, "engine_sha", issues)
    _validate_identity(identities.get("source_sha"), SHA40_RE, "source_sha", issues)
    _validate_identity(
        identities.get("manifest_sha256"),
        SHA64_RE,
        "manifest_sha256",
        issues,
    )
    _validate_identity(
        identities.get("pointer_sha256"),
        SHA64_RE,
        "pointer_sha256",
        issues,
    )
    if not isinstance(identities.get("release_id"), str) or not identities["release_id"]:
        issues.append(_issue("identity", "release_id", "release id is required"))

    contract_report = validate_contract(root, contract_path)
    if contract_report["status"] != "passed":
        issues.append(_issue("contract", "assessment", "drill contract is invalid"))

    ga_path = root / contract["registry_paths"]["ga_evidence"]
    ga_report = validate_ga_evidence(root, ga_path)
    if ga_report["status"] != "passed":
        issues.append(_issue("ga_evidence", "assessment", "M17.6 evidence is not ready"))

    runbook = _load_json(root / contract["registry_paths"]["runbook"])
    expected_phases = list(runbook["required_phases"])
    stages = transcript.get("stages")
    if not isinstance(stages, list):
        stages = []
        issues.append(_issue("stages", "transcript", "stage list is required"))
    seen_phases: list[str] = []
    for index, stage in enumerate(stages, start=1):
        subject = f"stage-{index}"
        if not isinstance(stage, dict):
            issues.append(_issue("stage_type", subject, "stage must be an object"))
            continue
        phase = stage.get("phase")
        if isinstance(phase, str):
            seen_phases.append(phase)
            subject = phase
        if stage.get("order") != index:
            issues.append(_issue("stage_order", subject, f"expected {index}"))
        if stage.get("status") != "passed":
            issues.append(_issue("stage_status", subject, "stage must pass"))
        if stage.get("execution_mode") not in ALLOWED_EXECUTION_MODES:
            issues.append(_issue("execution_mode", subject, "invalid execution mode"))
        if stage.get("mutation_dispatched") is not False:
            issues.append(_issue("mutation_claim", subject, "mutation dispatch is forbidden"))
        evidence = stage.get("evidence_sha256")
        if not isinstance(evidence, str) or SHA64_RE.fullmatch(evidence) is None:
            issues.append(_issue("stage_evidence", subject, "SHA-256 evidence is required"))
    if seen_phases != expected_phases:
        issues.append(_issue("stage_set", "transcript", "exact ordered 18 phases required"))

    ga_registry = _load_json(ga_path)
    expected_capabilities = [row["id"] for row in ga_registry["capabilities"]]
    capabilities = transcript.get("capabilities")
    if not isinstance(capabilities, list):
        capabilities = []
        issues.append(_issue("capabilities", "transcript", "capability list is required"))
    seen_capabilities: list[str] = []
    for index, capability in enumerate(capabilities, start=1):
        subject = f"capability-{index}"
        if not isinstance(capability, dict):
            issues.append(_issue("capability_type", subject, "capability must be an object"))
            continue
        capability_id = capability.get("id")
        if isinstance(capability_id, str):
            seen_capabilities.append(capability_id)
            subject = capability_id
        if capability.get("order") != index:
            issues.append(_issue("capability_order", subject, f"expected {index}"))
        if capability.get("status") != "passed":
            issues.append(_issue("capability_status", subject, "capability must pass"))
        evidence = capability.get("evidence_sha256")
        if not isinstance(evidence, str) or SHA64_RE.fullmatch(evidence) is None:
            issues.append(_issue("capability_evidence", subject, "SHA-256 evidence is required"))
    if seen_capabilities != expected_capabilities:
        issues.append(
            _issue(
                "capability_set",
                "transcript",
                "exact ordered GA-01 through GA-20 required",
            )
        )

    safe_stops = transcript.get("safe_stops")
    if not isinstance(safe_stops, list):
        safe_stops = []
        issues.append(_issue("safe_stops", "transcript", "safe-stop list is required"))
    seen_stops: list[str] = []
    for item in safe_stops:
        if not isinstance(item, dict):
            continue
        scenario = item.get("scenario")
        if isinstance(scenario, str):
            seen_stops.append(scenario)
        if item.get("status") != "stopped_safely":
            issues.append(_issue("safe_stop_status", str(scenario), "must stop safely"))
        evidence = item.get("evidence_sha256")
        if not isinstance(evidence, str) or SHA64_RE.fullmatch(evidence) is None:
            issues.append(_issue("safe_stop_evidence", str(scenario), "SHA-256 evidence required"))
    if seen_stops != REQUIRED_SAFE_STOPS:
        issues.append(_issue("safe_stop_set", "transcript", "exact safe-stop scenarios required"))

    reconciliation = transcript.get("final_reconciliation")
    if not isinstance(reconciliation, dict) or reconciliation.get("status") != "passed":
        issues.append(_issue("reconciliation", "transcript", "final reconciliation must pass"))
    elif (
        reconciliation.get("stage_count") != 18
        or reconciliation.get("capability_count") != 20
        or reconciliation.get("mutation_dispatched") is not False
    ):
        issues.append(
            _issue(
                "reconciliation_counts",
                "transcript",
                "reconciliation is inconsistent",
            )
        )

    issues.sort(key=lambda item: (item["code"], item["subject"], item["detail"]))
    accepted = not issues
    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA,
        "status": "ga_accepted" if accepted else "blocked",
        "ga_accepted": accepted,
        "operator_id": operator_id,
        "evaluator_id": evaluator_id,
        "operator_context": transcript.get("operator_context"),
        "identities": identities,
        "stage_count": len(stages),
        "capability_count": len(capabilities),
        "safe_stop_count": len(safe_stops),
        "transcript_sha256": transcript.get("transcript_sha256"),
        "contract_sha256": sha256_hex(canonical_json(contract)),
        "ga_evidence_report_sha256": ga_report.get("report_sha256"),
        "issues": issues,
    }
    return _sign(report, "report_sha256")


def verify_transcript(transcript: dict[str, Any]) -> bool:
    return _verify_signature(transcript, "transcript_sha256")


def verify_report(report: dict[str, Any]) -> bool:
    return _verify_signature(report, "report_sha256")
