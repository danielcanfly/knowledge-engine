from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m23_7_r1_semantic_alignment import canonical_fixture_samples
from knowledge_engine.m23_7_r3_bounded_live_reobservation import (
    FixtureWorkerInvoker,
    build_report,
    canonical_contract,
    canonical_fixture_report,
    canonical_json,
    run_bounded_live_reobservation,
    validate_contract,
    validate_report,
    validate_wrangler_config,
)


def placement() -> dict[str, object]:
    return {
        "config_sha256": "0" * 64,
        "placement_hostname_sha256": "1" * 64,
        "ai_binding": "AI",
        "generated_config_committed": False,
    }


def test_contract_and_fixture_are_deterministic() -> None:
    first = canonical_contract()
    second = canonical_contract()
    assert canonical_json(first) == canonical_json(second)
    assert (
        first["contract_sha256"]
        == "44177964da873958f1d433aab719725ff622f050bd7e96ec086cc8e06aa0f412"
    )
    report_a = canonical_fixture_report()
    report_b = canonical_fixture_report()
    assert canonical_json(report_a) == canonical_json(report_b)
    assert (
        report_a["report_sha256"]
        == "9bdd7404907e532530dc277051c8d4347bc4cf03290f76c538624aaf05154338"
    )


def test_fixture_passes_all_frozen_gates() -> None:
    report = canonical_fixture_report()
    assert report["status"] == "pass_bounded_live_reobservation"
    assert report["metrics"]["recall_at_5"] == 1.0
    assert report["metrics"]["mrr_at_10"] == 0.8125
    assert report["metrics"]["ndcg_at_10"] == pytest.approx(
        0.8615986575892965
    )
    assert report["metrics"]["worker_internal_shadow_ms"] == 780
    assert all(report["gates"].values())
    assert report["remaining_blockers"] == []
    assert report["exit"]["r3_complete"] is True
    assert report["exit"]["retrieval_quality_blocker_cleared"] is True
    assert report["exit"]["all_repair_blockers_cleared"] is True
    assert report["exit"]["promotion_eligibility_granted"] is False
    assert report["authority"]["production_retrieval"] == "lexical"


def test_quality_failure_writes_rejected_report() -> None:
    report = run_bounded_live_reobservation(
        FixtureWorkerInvoker(ranks=(None,) * 8),
        samples=canonical_fixture_samples(),
        worker_origin="fixture-placement-worker",
        placement_config=placement(),
        nonce="b" * 32,
    )
    assert report["status"] == "rejected_bounded_live_reobservation"
    assert report["metrics"]["recall_at_5"] == 0.0
    assert report["gates"]["recall_at_5"] is False
    assert report["remaining_blockers"] == [
        "blocked_pending_retrieval_quality"
    ]


def test_latency_failure_does_not_reintroduce_latency_blocker() -> None:
    report = run_bounded_live_reobservation(
        FixtureWorkerInvoker(shadow_ms=1201),
        samples=canonical_fixture_samples(),
        worker_origin="fixture-placement-worker",
        placement_config=placement(),
        nonce="c" * 32,
    )
    assert report["status"] == "rejected_bounded_live_reobservation"
    assert report["gates"]["worker_internal_shadow"] is False
    assert report["remaining_blockers"] == [
        "blocked_pending_retrieval_quality"
    ]
    assert "blocked_pending_latency" not in report["remaining_blockers"]


def test_report_digest_and_gate_tampering_fail_closed() -> None:
    report = canonical_fixture_report()
    tampered = copy.deepcopy(report)
    tampered["metrics"]["recall_at_5"] = 0.0
    with pytest.raises(IntegrityError, match="report digest mismatch"):
        validate_report(tampered)

    from knowledge_engine.m23_7_r3_bounded_live_reobservation import (
        canonical_sha256,
    )

    tampered = copy.deepcopy(report)
    tampered["gates"]["recall_at_5"] = False
    payload = dict(tampered)
    payload.pop("report_sha256")
    tampered["report_sha256"] = canonical_sha256(payload)
    with pytest.raises(IntegrityError, match="gate evaluation drifted"):
        validate_report(tampered)


def test_contract_budget_or_promotion_drift_fails_closed() -> None:
    from knowledge_engine.m23_7_r3_bounded_live_reobservation import (
        canonical_sha256,
    )

    changed = copy.deepcopy(canonical_contract())
    changed["thresholds"]["max_worker_internal_shadow_ms"] = 1201
    payload = dict(changed)
    payload.pop("contract_sha256")
    changed["contract_sha256"] = canonical_sha256(payload)
    with pytest.raises(IntegrityError, match="contract drifted"):
        validate_contract(changed)

    promoted = copy.deepcopy(canonical_fixture_report())
    promoted["exit"]["promotion_eligibility_granted"] = True
    payload = dict(promoted)
    payload.pop("report_sha256")
    promoted["report_sha256"] = canonical_sha256(payload)
    with pytest.raises(IntegrityError, match="promotion claimed"):
        validate_report(promoted)


def test_raw_queries_are_not_persisted() -> None:
    from knowledge_engine.m23_7_r1_semantic_alignment import (
        canonical_manifest,
        compile_probe_plan,
    )

    report = canonical_fixture_report()
    encoded = canonical_json(report)
    probes = compile_probe_plan(canonical_manifest(), canonical_fixture_samples())
    for probe in probes:
        assert probe["query_text"] not in encoded
    assert all(
        case["raw_query_persisted"] is False for case in report["cases"]
    )


def test_invalid_sample_count_and_nonce_fail_closed() -> None:
    samples = canonical_fixture_samples()
    with pytest.raises(IntegrityError, match="exactly eight samples"):
        run_bounded_live_reobservation(
            FixtureWorkerInvoker(),
            samples=samples[:-1],
            worker_origin="fixture-placement-worker",
            placement_config=placement(),
        )
    with pytest.raises(IntegrityError, match="nonce is invalid"):
        run_bounded_live_reobservation(
            FixtureWorkerInvoker(),
            samples=samples,
            worker_origin="fixture-placement-worker",
            placement_config=placement(),
            nonce="unsafe",
        )


def test_wrangler_config_is_placement_bound_and_secret_free(
    tmp_path: Path,
) -> None:
    config = {
        "name": "knowledge-engine-m23-7-r3-observation",
        "main": "worker.mjs",
        "ai": {"binding": "AI"},
        "placement": {"hostname": "qdrant.example"},
    }
    path = tmp_path / "wrangler.local.jsonc"
    path.write_text(json.dumps(config), encoding="utf-8")
    result = validate_wrangler_config(path, "https://qdrant.example")
    assert result["ai_binding"] == "AI"
    assert result["generated_config_committed"] is False

    config["M23_R3_OPERATOR_TOKEN"] = "secret"
    path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(IntegrityError, match="secret or service URL"):
        validate_wrangler_config(path, "https://qdrant.example")


def test_worker_payload_call_count_or_authority_drift_fails_closed() -> None:
    from knowledge_engine.m23_7_r1_semantic_alignment import (
        canonical_manifest,
        compile_probe_plan,
    )

    probes = compile_probe_plan(canonical_manifest(), canonical_fixture_samples())
    raw = FixtureWorkerInvoker().invoke(
        probes,
        nonce="d" * 32,
        clock_ns=lambda: 0,
    )
    changed = copy.deepcopy(raw)
    changed["payload"]["external_calls"]["qdrant_query_batch"] = 2
    with pytest.raises(IntegrityError, match="Qdrant batch count drifted"):
        build_report(
            contract=canonical_contract(),
            probes=probes,
            worker=changed,
            worker_origin="fixture-placement-worker",
            placement_config=placement(),
        )

    changed = copy.deepcopy(raw)
    changed["payload"]["authority"]["production_retrieval"] = "semantic"
    with pytest.raises(IntegrityError, match="production retrieval drifted"):
        build_report(
            contract=canonical_contract(),
            probes=probes,
            worker=changed,
            worker_origin="fixture-placement-worker",
            placement_config=placement(),
        )
