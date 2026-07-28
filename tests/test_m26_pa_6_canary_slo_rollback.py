from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from knowledge_engine.m26_canary_slo_rollback import (
    CanarySloRollbackError,
    compile_canary_record,
    run_canary_benchmark,
    validate_canary_policy,
)
from knowledge_engine.m26_retrieval_envelope import verify_self_digest, with_self_digest

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot" / "m26"
SCHEMAS = ROOT / "schemas"
DOCS = ROOT / "docs" / "architecture" / "m26"
WORKFLOW = ROOT / ".github" / "workflows" / "m26-pa-6-canary-slo-rollback.yml"


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def schema_errors(schema_name: str, value: dict[str, Any]) -> list[str]:
    schema = load(SCHEMAS / schema_name)
    Draft202012Validator.check_schema(schema)
    return [
        error.message
        for error in sorted(
            Draft202012Validator(schema).iter_errors(value),
            key=lambda item: list(item.absolute_path),
        )
    ]


def test_pa6_acceptance_replays_canary_slo_rollback_benchmark() -> None:
    policy = load(PILOT / "m26-pa-6-canary-policy.json")
    cases = load(PILOT / "m26-pa-6-benchmark-cases.json")
    acceptance = load(PILOT / "m26-pa-6-acceptance.json")
    for artifact in (policy, cases, acceptance):
        verify_self_digest(artifact)

    report = run_canary_benchmark(cases, policy)
    assert schema_errors("m26-pa-6-canary-benchmark-v1.schema.json", report) == []
    assert report["status"] == "m26_pa_6_canary_slo_rollback_ready"
    assert report["case_count"] == 12
    assert report["passed_count"] == 12
    assert report["failed_count"] == 0
    assert report["self_sha256"] == acceptance["benchmark"]["report_self_sha256"]
    assert acceptance["status"] == "m26_pa_6_canary_slo_rollback_accepted"
    assert acceptance["predecessor"]["status"] == (
        "m26_pa_5_controlled_internal_shadow_pilot_accepted"
    )


def test_pa6_metrics_separate_attempted_and_authorized_traffic() -> None:
    policy = load(PILOT / "m26-pa-6-canary-policy.json")
    report = run_canary_benchmark(load(PILOT / "m26-pa-6-benchmark-cases.json"), policy)
    metrics = report["metrics"]
    assert metrics["canary_ready_count"] == 6
    assert metrics["canary_stopped_count"] == 3
    assert metrics["rollback_hold_count"] == 1
    assert metrics["authority_rejection_count"] == 2
    assert metrics["automatic_stop_condition_count"] >= 10
    assert metrics["kill_switch_verified"] is True
    assert metrics["rollback_drill_completed"] is True
    assert metrics["max_attempted_traffic_percent"] == 2.0
    assert metrics["max_authorized_traffic_percent"] <= policy["canary_policy"][
        "max_traffic_percent"
    ]
    assert metrics["full_production_traffic_count"] == 0
    assert metrics["production_pointer_mutation_count"] == 0


def test_pa6_full_production_attempt_is_rejected_without_mutation() -> None:
    policy = load(PILOT / "m26-pa-6-canary-policy.json")
    case = copy.deepcopy(load(PILOT / "m26-pa-6-benchmark-cases.json")["cases"][0])
    case["case_id"] = "pa6-test-full-production-escalation"
    case["canary"]["full_production_traffic"] = True
    case["canary"]["traffic_percent"] = 100.0
    record = compile_canary_record(case, policy)
    assert schema_errors("m26-pa-6-canary-record-v1.schema.json", record) == []
    assert record["canary_status"] == "canary_rejected_authority_escalation"
    assert record["safe_for_pa7"] is False
    assert record["full_production_traffic"] is False
    assert record["production_pointer_mutation"] is False
    assert "FULL_PRODUCTION_TRAFFIC_ESCALATION" in record["stop_codes"]
    assert "TRAFFIC_BOUND_EXCEEDED" in record["stop_codes"]


def test_pa6_kill_switch_and_rollback_policy_drift_fail_closed() -> None:
    policy = load(PILOT / "m26-pa-6-canary-policy.json")
    weakened = copy.deepcopy(policy)
    weakened["canary_policy"]["kill_switch"]["enabled"] = False
    weakened = with_self_digest(weakened)
    with pytest.raises(CanarySloRollbackError, match="PA6_KILL_SWITCH_INVALID"):
        validate_canary_policy(weakened)

    weakened = copy.deepcopy(policy)
    weakened["canary_policy"]["rollback"]["drill_completed"] = False
    weakened = with_self_digest(weakened)
    with pytest.raises(CanarySloRollbackError, match="PA6_ROLLBACK_INVALID"):
        validate_canary_policy(weakened)


def test_pa6_docs_and_workflow_are_canary_bounded() -> None:
    doc = (DOCS / "m26-pa-6-canary-slo-rollback.md").read_text(encoding="utf-8")
    reconciliation = (DOCS / "m26-pa-6-reconciliation.md").read_text(encoding="utf-8")
    normalized = " ".join(doc.split()).lower()
    assert "kill switch" in normalized
    assert "rollback drill" in normalized
    assert "full production promotion remains forbidden" in normalized
    assert "m26_pa_6_canary_slo_rollback_accepted" in reconciliation
    assert "M26.PA.7" in reconciliation

    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "permissions:\n  contents: read" in workflow
    assert "secrets." not in workflow
    assert "environment: m23-r3-diagnostic" not in workflow
    assert "src/knowledge_engine/m26_canary_slo_rollback.py" in workflow
    assert "tests/test_m26_pa_6_canary_slo_rollback.py" in workflow
