from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from .errors import IntegrityError

ENGINE_SHA = "436e435acd8477adc11d061b34e00c5d4f4696eb"
SOURCE_SHA = "a6ba738d910d01d2ae99b1968f0831989934c549"
FOUNDATION_SHA = "e5ef644053d34e89c70d2ceb37521e1c59234832"

PHASES = (
    {
        "phase": "A",
        "milestones": ("M18.1", "M18.2", "M18.3", "M18.4", "M18.5", "M18.6", "M18.7"),
        "issues": (249, 251, 253, 255, 258, 261, 264),
        "closure_issue": 264,
        "implementation_pr": 265,
        "reconciliation_pr": 266,
        "implementation_head": "dbd610bc6589db7d8cb0f4c92868570632a50014",
        "implementation_merge": "baebca7408bdc8190e2cc35a236424ad4ce2f0c1",
        "reconciliation_head": "3659ece04b673966304bcb13fa0f67d132bbb3af",
        "reconciliation_merge": "f2957a9ce5c38f2af6f13b27c3ed55e0b67b431c",
        "contract": "tests/test_m18_7_phase_a_closure.py",
    },
    {
        "phase": "B",
        "milestones": ("M19.1", "M19.2", "M19.3", "M19.4", "M19.5", "M19.6", "M19.7"),
        "issues": (267, 270, 273, 276, 279, 282, 285),
        "closure_issue": 285,
        "implementation_pr": 288,
        "reconciliation_pr": 289,
        "implementation_head": "9ca1385a7a7afbe84fd4f2fe8d31be0b400681b4",
        "implementation_merge": "bfd45d8164e2385d87283be73697c41bfd8846a0",
        "reconciliation_head": "38a598bcc5ad4f1f6be1f892cea2121d2fab21f7",
        "reconciliation_merge": "b33d06a8f2b9896a8be29009f36cbbde4b5cb5c1",
        "contract": "packages/graph-explorer/acceptance/phase-b.ts",
    },
    {
        "phase": "C",
        "milestones": ("M20.1", "M20.2", "M20.3", "M20.4", "M20.5", "M20.6", "M20.7"),
        "issues": (290, 293, 296, 299, 302, 305, 308),
        "closure_issue": 308,
        "implementation_pr": 309,
        "reconciliation_pr": 310,
        "implementation_head": "7b959cf8637f7adf3c53099084cd13a5f95f6d1d",
        "implementation_merge": "7249bc8d812838dc20675b0eaa6ced15adc3e8c2",
        "reconciliation_head": "98eff6f395ab728c8f428d5ab1b7028318bdec0d",
        "reconciliation_merge": "ec7962edb13807246c752aee029148515a9a496a",
        "contract": "tests/test_m20_7_phase_c_acceptance.py",
    },
    {
        "phase": "D",
        "milestones": ("M21.1", "M21.2", "M21.3", "M21.4", "M21.5", "M21.6", "M21.7"),
        "issues": (312, 316, 319, 322, 325, 328, 331),
        "closure_issue": 331,
        "implementation_pr": 332,
        "reconciliation_pr": 333,
        "implementation_head": "84d19d8886f835704f69e62ea98cb585eddd05e7",
        "implementation_merge": "2f38edc9974e09c1d281ecbb8858ddfd9799e040",
        "reconciliation_head": "2d94f36567630d50d79815abd2fe37729c7c8d68",
        "reconciliation_merge": "669e1b0b31cf218e8283004f6828f40955a13eff",
        "contract": "tests/test_m21_7_phase_d_acceptance.py",
        "repair_issue": 334,
        "repair_implementation_pr": 335,
        "repair_reconciliation_pr": 336,
        "repair_implementation_head": "3745884a6de47180c955d53023f98883e7f3e75f",
        "repair_implementation_merge": "c2b27c90411b469776def052d183463df568fa71",
        "repair_reconciliation_head": "a77e85ee42b63f92486ea23e94ea2c0fcfee8847",
        "repair_reconciliation_merge": "a68dfb177ab1b044d23fe5e8077548392d8aec42",
    },
    {
        "phase": "E",
        "milestones": ("M22.1", "M22.2", "M22.3", "M22.4", "M22.5", "M22.6", "M22.7"),
        "issues": (337, 340, 344, 347, 350, 353, 356),
        "closure_issue": 356,
        "implementation_pr": 360,
        "reconciliation_pr": 361,
        "implementation_head": "d41f7d024e3d0f33ffcf50678f61f8febfb5dc0b",
        "implementation_merge": "dd6a9d78c2f491198c76788a0d8cbf191a4cdabb",
        "reconciliation_head": "0ee616f87c248191473ae21c620414eed64584fe",
        "reconciliation_merge": ENGINE_SHA,
        "contract": "tests/test_m22_7_phase_e_acceptance.py",
    },
)

NON_CANONICAL_ISSUES = (286, 287, 311, 313, 341, 357, 358, 359)
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
    "graph_neural_retrieval",
)


def _sha(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _mapping(value: Any, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise IntegrityError(f"FINAL-AUDIT-101 {label} must be an object")
    return value


def _sequence(value: Any, *, label: str) -> tuple[Any, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise IntegrityError(f"FINAL-AUDIT-102 {label} must be a list")
    return tuple(value)


def _exact(value: Mapping[str, Any], expected: set[str], *, label: str) -> None:
    if set(value) != expected:
        raise IntegrityError(f"FINAL-AUDIT-103 {label} shape is invalid")


def _validate_phase(payload: Any, expected: Mapping[str, Any]) -> dict[str, Any]:
    phase = _mapping(payload, label="phase")
    keys = {
        "phase",
        "milestones",
        "issues",
        "closure_issue",
        "implementation_pr",
        "reconciliation_pr",
        "implementation_head",
        "implementation_merge",
        "reconciliation_head",
        "reconciliation_merge",
        "contract",
        "canonical_issues_completed",
        "implementation_merged",
        "reconciliation_merged",
        "implementation_expected_head_merge",
        "reconciliation_expected_head_merge",
        "machine_contract_passed",
    }
    if expected["phase"] == "D":
        keys.update(
            {
                "repair_issue",
                "repair_implementation_pr",
                "repair_reconciliation_pr",
                "repair_implementation_head",
                "repair_implementation_merge",
                "repair_reconciliation_head",
                "repair_reconciliation_merge",
                "repair_completed",
                "repair_expected_head_merges",
            }
        )
    _exact(phase, keys, label="phase")
    for key in expected:
        expected_value = expected[key]
        actual = tuple(phase[key]) if isinstance(expected_value, tuple) else phase[key]
        if actual != expected_value:
            raise IntegrityError(f"FINAL-AUDIT-104 phase evidence mismatch: {key}")
    for key in (
        "canonical_issues_completed",
        "implementation_merged",
        "reconciliation_merged",
        "implementation_expected_head_merge",
        "reconciliation_expected_head_merge",
        "machine_contract_passed",
    ):
        if phase[key] is not True:
            raise IntegrityError(f"FINAL-AUDIT-105 phase completion is false: {key}")
    if expected["phase"] == "D" and not (
        phase["repair_completed"] is True
        and phase["repair_expected_head_merges"] is True
    ):
        raise IntegrityError("FINAL-AUDIT-106 Phase D repair is incomplete")
    return dict(phase)


def validate_m18_m22_final_audit(payload: Mapping[str, Any]) -> dict[str, Any]:
    root = _mapping(payload, label="final audit")
    _exact(
        root,
        {
            "schema_version",
            "engine_sha",
            "source_sha",
            "foundation_sha",
            "phases",
            "non_canonical_issues",
            "non_canonical_zero_evidence_role",
            "repository_quality_gates_passed",
            "protected_state",
        },
        label="final audit",
    )
    if root["schema_version"] != "knowledge-engine-m18-m22-final-audit-evidence/v1":
        raise IntegrityError("FINAL-AUDIT-107 unsupported schema")
    if root["engine_sha"] != ENGINE_SHA:
        raise IntegrityError("FINAL-AUDIT-108 Engine identity mismatch")
    if root["source_sha"] != SOURCE_SHA or root["foundation_sha"] != FOUNDATION_SHA:
        raise IntegrityError("FINAL-AUDIT-109 governed release identity mismatch")
    if root["repository_quality_gates_passed"] is not True:
        raise IntegrityError("FINAL-AUDIT-110 repository quality gates are incomplete")

    phases_raw = _sequence(root["phases"], label="phases")
    if len(phases_raw) != len(PHASES):
        raise IntegrityError("FINAL-AUDIT-111 exactly five phases are required")
    phases = [
        _validate_phase(item, expected)
        for item, expected in zip(phases_raw, PHASES, strict=True)
    ]
    issues = [issue for phase in phases for issue in phase["issues"]]
    if len(issues) != 35 or len(set(issues)) != 35:
        raise IntegrityError("FINAL-AUDIT-112 canonical issue inventory is invalid")
    milestones = [name for phase in phases for name in phase["milestones"]]
    if len(milestones) != 35 or len(set(milestones)) != 35:
        raise IntegrityError("FINAL-AUDIT-113 canonical milestone inventory is invalid")

    noise = tuple(_sequence(root["non_canonical_issues"], label="non-canonical issues"))
    if noise != NON_CANONICAL_ISSUES:
        raise IntegrityError("FINAL-AUDIT-114 non-canonical inventory mismatch")
    if root["non_canonical_zero_evidence_role"] is not True:
        raise IntegrityError("FINAL-AUDIT-115 non-canonical issue has evidence authority")
    if set(noise).intersection(issues):
        raise IntegrityError("FINAL-AUDIT-116 canonical and non-canonical issues overlap")

    protected = _mapping(root["protected_state"], label="protected state")
    if tuple(sorted(protected)) != tuple(sorted(PROTECTED_MUTATION_KEYS)):
        raise IntegrityError("FINAL-AUDIT-117 protected state is incomplete")
    if any(protected[key] is not False for key in PROTECTED_MUTATION_KEYS):
        raise IntegrityError("FINAL-AUDIT-118 protected mutation was dispatched")

    material = {
        "engine_sha": root["engine_sha"],
        "source_sha": root["source_sha"],
        "foundation_sha": root["foundation_sha"],
        "phases": phases,
        "non_canonical_issues": list(noise),
    }
    return {
        "schema_version": "knowledge-engine-m18-m22-final-audit/v1",
        "status": "accepted",
        "audit_sha256": _sha(material),
        "engine_sha": root["engine_sha"],
        "source_sha": root["source_sha"],
        "foundation_sha": root["foundation_sha"],
        "phase_count": 5,
        "canonical_milestone_count": 35,
        "canonical_issue_count": 35,
        "non_canonical_issue_count": len(noise),
        "phases": phases,
        "post_ga_m18_m22_closed": True,
        "production_authority": False,
    }


__all__ = [
    "ENGINE_SHA",
    "FOUNDATION_SHA",
    "NON_CANONICAL_ISSUES",
    "PHASES",
    "PROTECTED_MUTATION_KEYS",
    "SOURCE_SHA",
    "validate_m18_m22_final_audit",
]
