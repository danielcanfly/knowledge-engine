from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from .errors import IntegrityError

SOURCE_SHA = "a6ba738d910d01d2ae99b1968f0831989934c549"
FOUNDATION_SHA = "e5ef644053d34e89c70d2ceb37521e1c59234832"
FINAL_ENGINE_SHA = "3b4d3c71adac43de2dcaddbb826d93b3f070e6c4"

PROTECTED_MUTATION_KEYS = (
    "production_deployment",
    "production_promotion",
    "production_pointer_update",
    "r2_write",
    "credential_change",
    "permanent_ledger_write",
    "rollback_dispatch",
    "retained_evidence_write",
    "source_write",
    "traffic_change",
)

EXPECTED_MILESTONES = (
    {
        "milestone": "M22.1",
        "issue": 337,
        "implementation_pr": 338,
        "reconciliation_pr": 339,
        "entry_base": "a68dfb177ab1b044d23fe5e8077548392d8aec42",
        "implementation_head": "002b04a68430f4d24c4a4ce2a05ff03a4fd4ece0",
        "implementation_merge": "02fa5715fde28eba0b9baa7629ab14dab5e15a61",
        "reconciliation_head": "1ce7b631f68b2bc280afa6a4372fd85483adc344",
        "reconciliation_merge": "5cbf5d9e2871e1ad24ffcc4d5109330c04d9fa5d",
        "dedicated_workflow": "M22.1 Reasoning Mode Isolation",
        "dedicated_run": 1,
        "ci_run": 708,
        "m17_run": 85,
        "m18_run": 144,
        "r2_run": 479,
    },
    {
        "milestone": "M22.2",
        "issue": 340,
        "implementation_pr": 342,
        "reconciliation_pr": 343,
        "entry_base": "5cbf5d9e2871e1ad24ffcc4d5109330c04d9fa5d",
        "implementation_head": "75a4d765a23e924ab79e9c7e5eca7f78138ecaf1",
        "implementation_merge": "5a62e379caed5848aa6687db026f3b34d64a4800",
        "reconciliation_head": "6c0314003cf0830ee5a5a939efc12cf3905a5744",
        "reconciliation_merge": "531f55371564daa7ccfe5ca5cda89b504464b183",
        "dedicated_workflow": "M22.2 Activation Decision Validation",
        "dedicated_run": 1,
        "ci_run": 712,
        "m17_run": 87,
        "m18_run": 148,
        "r2_run": 481,
    },
    {
        "milestone": "M22.3",
        "issue": 344,
        "implementation_pr": 345,
        "reconciliation_pr": 346,
        "entry_base": "531f55371564daa7ccfe5ca5cda89b504464b183",
        "implementation_head": "c370da653c4ba3226ef1d6c92b1ebbd43ef57aaa",
        "implementation_merge": "9442948ed180cf48ab9b45ff4c83f157dc724ccd",
        "reconciliation_head": "c243c19fa1259732be97e49dcc37438edfff2b59",
        "reconciliation_merge": "4f0bc8ee154d56d7c465194750bda5c6acd5ac65",
        "dedicated_workflow": "M22.3 Bounded Plan Validation",
        "dedicated_run": 1,
        "ci_run": 716,
        "m17_run": 89,
        "m18_run": 152,
        "r2_run": 483,
    },
    {
        "milestone": "M22.4",
        "issue": 347,
        "implementation_pr": 348,
        "reconciliation_pr": 349,
        "entry_base": "4f0bc8ee154d56d7c465194750bda5c6acd5ac65",
        "implementation_head": "3adc4ebceb30ca734432d1e642c66271643de147",
        "implementation_merge": "3c1c98ca1c70dd676367746cef08f4d4b311455f",
        "reconciliation_head": "b695524c447d986964ea5e6c4cce1a6af36da4aa",
        "reconciliation_merge": "0e7e1111fd6c08f3377529b33075a185bfebfcbd",
        "dedicated_workflow": "M22.4 Execution Trace Validation",
        "dedicated_run": 4,
        "ci_run": 724,
        "m17_run": 94,
        "m18_run": 160,
        "r2_run": 489,
    },
    {
        "milestone": "M22.5",
        "issue": 350,
        "implementation_pr": 351,
        "reconciliation_pr": 352,
        "entry_base": "0e7e1111fd6c08f3377529b33075a185bfebfcbd",
        "implementation_head": "c5403d997ea34b887e616a7740246fa49213e7a5",
        "implementation_merge": "5e2693ba238f4eaddf025dca8b243b031f14ff33",
        "reconciliation_head": "4cf54a3b7e4fee9e8a2980af08419feec1950865",
        "reconciliation_merge": "2aa77473775abb2b3c6e7260bfc8b59a2c453736",
        "dedicated_workflow": "M22.5 Grounded Answer Validation",
        "dedicated_run": 1,
        "ci_run": 728,
        "m17_run": 96,
        "m18_run": 164,
        "r2_run": 491,
    },
    {
        "milestone": "M22.6",
        "issue": 353,
        "implementation_pr": 354,
        "reconciliation_pr": 355,
        "entry_base": "2aa77473775abb2b3c6e7260bfc8b59a2c453736",
        "implementation_head": "7edb988fc0bdc4e78df45b23768cf1f12a56ee78",
        "implementation_merge": "5fb14d13030b40d92bccfe1fa164e01e639c7202",
        "reconciliation_head": "0d0e8567876c9e6878edef4c783e9e801d3ba5cc",
        "reconciliation_merge": FINAL_ENGINE_SHA,
        "dedicated_workflow": "M22.6 Offline Controlled Variant Evaluation",
        "dedicated_run": 1,
        "ci_run": 732,
        "m17_run": 98,
        "m18_run": 168,
        "r2_run": 493,
    },
)

EXPECTED_CAPABILITIES = {
    "reasoning_mode_isolation": True,
    "activation_decision": True,
    "bounded_plan": True,
    "execution_trace_validation": True,
    "grounded_answer_validation": True,
    "offline_controlled_evaluation": True,
    "direct_path_preserved": True,
    "fallback_preserved": True,
    "acl_provenance_citations_preserved": True,
    "graph_neural_retrieval": False,
    "provider_call": False,
    "traffic_change": False,
    "rollout": False,
    "production_authority": False,
}


def _sha(payload: Any) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise IntegrityError(f"M22-PHASE-E-101 {label} must be an object")
    return value


def _exact(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise IntegrityError(f"M22-PHASE-E-102 {label} shape is invalid")


def _sequence(value: Any, label: str) -> tuple[Any, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise IntegrityError(f"M22-PHASE-E-103 {label} must be a list")
    return tuple(value)


def _validate_workflows(
    workflows: Any,
    *,
    expected: Mapping[str, Any],
) -> list[dict[str, Any]]:
    rows = _sequence(workflows, "workflows")
    if len(rows) != 5:
        raise IntegrityError("M22-PHASE-E-104 exactly five workflows are required")
    expected_rows = (
        (expected["dedicated_workflow"], expected["dedicated_run"]),
        ("CI", expected["ci_run"]),
        ("M17 Architecture Canon Acceptance", expected["m17_run"]),
        ("M18 Graph v2 acceptance", expected["m18_run"]),
        ("R2 Release Integration", expected["r2_run"]),
    )
    normalized: list[dict[str, Any]] = []
    for row, (name, run_number) in zip(rows, expected_rows, strict=True):
        item = _mapping(row, "workflow")
        _exact(item, {"name", "run_number", "head_sha", "conclusion"}, "workflow")
        if item["name"] != name or item["run_number"] != run_number:
            raise IntegrityError("M22-PHASE-E-105 workflow identity mismatch")
        if item["head_sha"] != expected["implementation_head"]:
            raise IntegrityError("M22-PHASE-E-106 workflow is not bound to implementation head")
        if item["conclusion"] != "success":
            raise IntegrityError("M22-PHASE-E-107 workflow did not succeed")
        normalized.append(dict(item))
    if len({(row["name"], row["run_number"]) for row in normalized}) != 5:
        raise IntegrityError("M22-PHASE-E-108 workflow evidence is duplicated")
    return normalized


def _validate_milestone(payload: Any, expected: Mapping[str, Any]) -> dict[str, Any]:
    item = _mapping(payload, "milestone")
    _exact(
        item,
        {
            "milestone",
            "issue",
            "implementation_pr",
            "reconciliation_pr",
            "entry_base",
            "implementation_head",
            "implementation_merge",
            "reconciliation_head",
            "reconciliation_merge",
            "issue_completed",
            "implementation_merged",
            "reconciliation_merged",
            "implementation_expected_head_merge",
            "reconciliation_expected_head_merge",
            "workflows",
        },
        "milestone",
    )
    for key in (
        "milestone",
        "issue",
        "implementation_pr",
        "reconciliation_pr",
        "entry_base",
        "implementation_head",
        "implementation_merge",
        "reconciliation_head",
        "reconciliation_merge",
    ):
        if item[key] != expected[key]:
            raise IntegrityError(f"M22-PHASE-E-109 milestone evidence mismatch: {key}")
    for key in (
        "issue_completed",
        "implementation_merged",
        "reconciliation_merged",
        "implementation_expected_head_merge",
        "reconciliation_expected_head_merge",
    ):
        if item[key] is not True:
            raise IntegrityError(f"M22-PHASE-E-110 milestone state is incomplete: {key}")
    return {
        **{key: item[key] for key in item if key != "workflows"},
        "workflows": _validate_workflows(item["workflows"], expected=expected),
    }


def validate_phase_e_acceptance(payload: Mapping[str, Any]) -> dict[str, Any]:
    root = _mapping(payload, "phase_e_evidence")
    _exact(
        root,
        {
            "schema_version",
            "engine_sha",
            "source_sha",
            "foundation_sha",
            "milestones",
            "capabilities",
            "protected_state",
        },
        "phase_e_evidence",
    )
    if root["schema_version"] != "knowledge-engine-m22-phase-e-evidence/v1":
        raise IntegrityError("M22-PHASE-E-111 unsupported schema")
    if root["engine_sha"] != FINAL_ENGINE_SHA:
        raise IntegrityError("M22-PHASE-E-112 final Engine identity mismatch")
    if root["source_sha"] != SOURCE_SHA or root["foundation_sha"] != FOUNDATION_SHA:
        raise IntegrityError("M22-PHASE-E-113 governed release identity mismatch")

    protected = _mapping(root["protected_state"], "protected_state")
    if tuple(sorted(protected)) != tuple(sorted(PROTECTED_MUTATION_KEYS)):
        raise IntegrityError("M22-PHASE-E-114 protected state is incomplete")
    if any(protected[name] is not False for name in PROTECTED_MUTATION_KEYS):
        raise IntegrityError("M22-PHASE-E-115 protected mutation was dispatched")

    capabilities = _mapping(root["capabilities"], "capabilities")
    if dict(capabilities) != EXPECTED_CAPABILITIES:
        raise IntegrityError("M22-PHASE-E-116 capability boundary mismatch")

    rows = _sequence(root["milestones"], "milestones")
    if len(rows) != len(EXPECTED_MILESTONES):
        raise IntegrityError("M22-PHASE-E-117 six milestones are required")
    normalized = [
        _validate_milestone(row, expected)
        for row, expected in zip(rows, EXPECTED_MILESTONES, strict=True)
    ]
    if len({row["issue"] for row in normalized}) != len(normalized):
        raise IntegrityError("M22-PHASE-E-118 milestone issues must be unique")
    if len({row["implementation_pr"] for row in normalized}) != len(normalized):
        raise IntegrityError("M22-PHASE-E-119 implementation PRs must be unique")
    if len({row["reconciliation_pr"] for row in normalized}) != len(normalized):
        raise IntegrityError("M22-PHASE-E-120 reconciliation PRs must be unique")

    for previous, current in zip(normalized, normalized[1:], strict=False):
        if current["entry_base"] != previous["reconciliation_merge"]:
            raise IntegrityError("M22-PHASE-E-121 reconciliation chain is broken")
    if normalized[-1]["reconciliation_merge"] != FINAL_ENGINE_SHA:
        raise IntegrityError("M22-PHASE-E-122 final closure merge mismatch")

    material = {
        "engine_sha": root["engine_sha"],
        "source_sha": root["source_sha"],
        "foundation_sha": root["foundation_sha"],
        "milestones": normalized,
        "capabilities": dict(capabilities),
    }
    return {
        "schema_version": "knowledge-engine-m22-phase-e-acceptance/v1",
        "phase": "E",
        "status": "accepted",
        "acceptance_sha256": _sha(material),
        "engine_sha": root["engine_sha"],
        "source_sha": root["source_sha"],
        "foundation_sha": root["foundation_sha"],
        "milestone_count": len(normalized),
        "milestones": normalized,
        "capabilities": dict(capabilities),
        "phase_e_closed": True,
        "m18_m22_final_audit_required": True,
        "production_authority": False,
    }


__all__ = [
    "EXPECTED_CAPABILITIES",
    "EXPECTED_MILESTONES",
    "FINAL_ENGINE_SHA",
    "FOUNDATION_SHA",
    "PROTECTED_MUTATION_KEYS",
    "SOURCE_SHA",
    "validate_phase_e_acceptance",
]
