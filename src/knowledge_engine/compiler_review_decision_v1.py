from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from .compiler_contract_v1 import CompilerFailure, json_bytes, put_immutable
from .compiler_resolution_contract_v1 import digest_object, load_json_object
from .compiler_review_decision_contract_v1 import (
    CompilerReviewDecisionRequest,
    CompilerReviewDecisionResult,
)
from .compiler_review_packet_v1 import (
    _validate_proposal_batch,
    verify_reviewer_packet_event,
)
from .compiler_source_v1 import AUDIENCE_RANK
from .intake_v1 import canonical_json_bytes
from .storage import ObjectStore, sha256_bytes


def _event(
    decision_set_id: str,
    ordinal: int,
    occurred_at: str,
    before: str | None,
    after: str,
    inputs: list[str],
    outputs: list[str],
    previous: str | None,
) -> dict[str, Any]:
    payload = {
        "schema_version": "knowledge-compiler-review-decision-event/v1",
        "decision_set_id": decision_set_id,
        "ordinal": ordinal,
        "from_state": before,
        "to_state": after,
        "event_at": occurred_at,
        "input_artifact_refs": inputs,
        "output_artifact_refs": outputs,
        "previous_event_hash": previous,
        "mutations_performed": ["compiler_review_object_write"],
    }
    return {**payload, "event_sha256": sha256_bytes(canonical_json_bytes(payload))}


def verify_review_decision_event(event: Mapping[str, Any]) -> bool:
    payload = dict(event)
    expected = payload.pop("event_sha256", None)
    return isinstance(expected, str) and expected == sha256_bytes(canonical_json_bytes(payload))


def _write_output(root: Path | None, relative: str, data: bytes) -> None:
    if root is None:
        return
    path = root.resolve() / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _validate_packet_events(store: ObjectStore, prefix: str, event_keys: Any) -> None:
    if not isinstance(event_keys, list) or not event_keys:
        raise CompilerFailure(
            "REVIEW_DECISION_PACKET_EVENT_CHAIN_INVALID",
            "validate",
            "reviewer packet event chain missing",
        )
    previous = None
    final_state = None
    for ordinal, key in enumerate(event_keys, 1):
        if not isinstance(key, str) or not key.startswith(f"{prefix}/events/"):
            raise CompilerFailure(
                "REVIEW_DECISION_PACKET_EVENT_CHAIN_INVALID",
                "validate",
                "reviewer packet event key invalid",
            )
        event = load_json_object(store, key, "reviewer packet event")
        if not verify_reviewer_packet_event(event):
            raise CompilerFailure(
                "REVIEW_DECISION_PACKET_EVENT_CHAIN_INVALID",
                "validate",
                "reviewer packet event hash invalid",
            )
        if event.get("ordinal") != ordinal or event.get("previous_event_hash") != previous:
            raise CompilerFailure(
                "REVIEW_DECISION_PACKET_EVENT_CHAIN_INVALID",
                "validate",
                "reviewer packet event chain not adjacent",
            )
        event_hash = event.get("event_sha256")
        if not isinstance(event_hash, str) or not key.endswith(f"-{event_hash}.json"):
            raise CompilerFailure(
                "REVIEW_DECISION_PACKET_EVENT_CHAIN_INVALID",
                "validate",
                "reviewer packet event key mismatch",
            )
        previous = event_hash
        final_state = event.get("to_state")
    if final_state != "review_ready":
        raise CompilerFailure(
            "REVIEW_DECISION_PACKET_EVENT_CHAIN_INVALID",
            "validate",
            "reviewer packet terminal state invalid",
        )


def validate_reviewer_packet(
    store: ObjectStore,
    reviewer_packet_id: str,
) -> dict[str, Any]:
    prefix = f"compiler/v1/reviewer-packets/{reviewer_packet_id}"
    keys = {
        "record": f"{prefix}/packet-record.json",
        "summary": f"{prefix}/summary.json",
        "proposal_index": f"{prefix}/proposal-index.json",
        "risk_report": f"{prefix}/risk-report.json",
        "quarantine_report": f"{prefix}/quarantine-report.json",
        "checklist": f"{prefix}/review-checklist.json",
        "result": f"{prefix}/result.json",
    }
    docs = {name: load_json_object(store, key, name) for name, key in keys.items()}
    record = docs["record"]
    summary = docs["summary"]
    index = docs["proposal_index"]
    risks = docs["risk_report"]
    quarantine = docs["quarantine_report"]
    checklist = docs["checklist"]
    result = docs["result"]

    for value in (record, summary, index, risks, quarantine, checklist):
        if value.get("reviewer_packet_id") != reviewer_packet_id:
            raise CompilerFailure(
                "REVIEW_DECISION_PACKET_IDENTITY_MISMATCH",
                "validate",
                "reviewer packet artifact identity mismatch",
            )
    if result.get("reviewer_packet_id") != reviewer_packet_id:
        raise CompilerFailure(
            "REVIEW_DECISION_PACKET_IDENTITY_MISMATCH",
            "validate",
            "reviewer packet result identity mismatch",
        )
    if record.get("status") != "review_ready" or result.get("status") != "review_ready":
        raise CompilerFailure(
            "REVIEW_DECISION_PACKET_INCOMPLETE",
            "validate",
            "reviewer packet is not review ready",
        )
    if record.get("human_decision_required") is not True:
        raise CompilerFailure(
            "REVIEW_DECISION_HUMAN_REVIEW_BYPASSED",
            "validate",
            "packet does not require human decision",
        )
    if summary.get("decision_state") != "awaiting_human_decision":
        raise CompilerFailure(
            "REVIEW_DECISION_STATE_INVALID",
            "validate",
            "packet decision state invalid",
        )
    if checklist.get("automatic_approval_permitted") is not False:
        raise CompilerFailure(
            "REVIEW_DECISION_AUTOMATIC_APPROVAL_FORBIDDEN",
            "validate",
            "packet permits automatic approval",
        )
    if checklist.get("human_decision_required") is not True:
        raise CompilerFailure(
            "REVIEW_DECISION_HUMAN_REVIEW_BYPASSED",
            "validate",
            "checklist does not require human decision",
        )
    for flag in (
        "canonical_write_permitted",
        "github_write_permitted",
        "production_write_permitted",
    ):
        if record.get(flag) is not False or result.get(flag) is not False:
            raise CompilerFailure(
                "REVIEW_DECISION_MUTATION_BOUNDARY_INVALID",
                "validate",
                "reviewer packet grants forbidden mutation",
            )

    _validate_packet_events(store, prefix, result.get("event_keys"))
    request = record.get("request")
    if not isinstance(request, dict):
        raise CompilerFailure(
            "REVIEW_DECISION_PACKET_RECORD_INVALID",
            "validate",
            "packet request missing",
        )
    proposal_batch_id = request.get("proposal_batch_id")
    if not isinstance(proposal_batch_id, str):
        raise CompilerFailure(
            "REVIEW_DECISION_PACKET_RECORD_INVALID",
            "validate",
            "proposal batch identity missing",
        )
    validated = _validate_proposal_batch(store, proposal_batch_id)
    proposals = validated["proposals"]
    indexed = index.get("proposals")
    risk_items = risks.get("risks")
    checklist_items = checklist.get("items")
    quarantined = validated["quarantined"]
    if not all(isinstance(value, list) for value in (indexed, risk_items, checklist_items)):
        raise CompilerFailure(
            "REVIEW_DECISION_PACKET_ARTIFACT_INVALID",
            "validate",
            "packet lists invalid",
        )
    proposal_map = {item["proposal_id"]: item for item in proposals}
    indexed_map = {
        item.get("proposal_id"): item
        for item in indexed
        if isinstance(item, dict) and isinstance(item.get("proposal_id"), str)
    }
    risk_map = {
        item.get("proposal_id"): item
        for item in risk_items
        if isinstance(item, dict) and isinstance(item.get("proposal_id"), str)
    }
    checklist_map = {
        item.get("proposal_id"): item
        for item in checklist_items
        if isinstance(item, dict) and isinstance(item.get("proposal_id"), str)
    }
    if set(indexed_map) != set(proposal_map):
        raise CompilerFailure(
            "REVIEW_DECISION_PROPOSAL_INDEX_INVALID",
            "validate",
            "packet proposal index coverage mismatch",
        )
    if set(risk_map) != set(proposal_map):
        raise CompilerFailure(
            "REVIEW_DECISION_RISK_REPORT_INVALID",
            "validate",
            "packet risk coverage mismatch",
        )
    if set(checklist_map) != set(proposal_map):
        raise CompilerFailure(
            "REVIEW_DECISION_CHECKLIST_INVALID",
            "validate",
            "packet checklist coverage mismatch",
        )
    for proposal_id, proposal in proposal_map.items():
        indexed_item = indexed_map[proposal_id]
        for field in (
            "proposal_kind",
            "resolution_id",
            "candidate_id",
            "target_ids",
            "evidence_refs",
            "effective_audience",
            "payload",
        ):
            if indexed_item.get(field) != proposal.get(field):
                raise CompilerFailure(
                    "REVIEW_DECISION_PROPOSAL_INDEX_INVALID",
                    "validate",
                    "packet proposal index mismatch",
                )
        if checklist_map[proposal_id].get("decision") is not None:
            raise CompilerFailure(
                "REVIEW_DECISION_CHECKLIST_INVALID",
                "validate",
                "packet checklist already contains a decision",
            )
        risk_level = risk_map[proposal_id].get("risk_level")
        if risk_level not in {"low", "medium", "high"}:
            raise CompilerFailure(
                "REVIEW_DECISION_RISK_REPORT_INVALID",
                "validate",
                "packet risk level invalid",
            )
    if summary.get("proposal_count") != len(proposals):
        raise CompilerFailure(
            "REVIEW_DECISION_COUNT_MISMATCH",
            "validate",
            "packet proposal count mismatch",
        )
    if summary.get("quarantine_count") != len(quarantined):
        raise CompilerFailure(
            "REVIEW_DECISION_COUNT_MISMATCH",
            "validate",
            "packet quarantine count mismatch",
        )
    artifact_hashes = {name: digest_object(store, key) for name, key in keys.items()}
    return {
        "prefix": prefix,
        "keys": keys,
        "artifact_hashes": artifact_hashes,
        "proposal_batch_id": proposal_batch_id,
        "source_snapshot_sha256": validated["source_snapshot_sha256"],
        "proposals": proposals,
        "proposal_map": proposal_map,
        "risk_map": risk_map,
        "quarantined": quarantined,
    }


def _reject(
    store: ObjectStore,
    request: CompilerReviewDecisionRequest,
    failure: CompilerFailure,
    output_dir: Path | None,
) -> CompilerReviewDecisionResult:
    attempt_id = request.attempt_id()
    prefix = f"compiler/v1/review-decision-rejections/{attempt_id}"
    rejection_key = f"{prefix}/evidence.json"
    result_key = f"{prefix}/result.json"
    rejection = {
        "schema_version": "knowledge-compiler-review-decision-rejection/v1",
        "review_decision_attempt_id": attempt_id,
        "reviewer_packet_id": request.reviewer_packet_id,
        "stage": failure.stage,
        "reason_code": failure.code,
        "message": failure.message,
        "safe_context": failure.context,
        "canonical_write_permitted": False,
        "github_write_permitted": False,
        "production_write_permitted": False,
    }
    states = [put_immutable(store, rejection_key, json_bytes(rejection))]
    result = CompilerReviewDecisionResult(
        decision_set_id=attempt_id,
        reviewer_packet_id=request.reviewer_packet_id,
        status="rejected",
        result_key=result_key,
        event_keys=(),
        rejection_key=rejection_key,
        failure_code=failure.code,
    )
    states.append(put_immutable(store, result_key, json_bytes(result.evidence())))
    result = replace(result, idempotent=all(states))
    _write_output(output_dir, "rejection.json", json_bytes(rejection))
    _write_output(output_dir, "review-decision-result.json", json_bytes(result.to_dict()))
    return result


def record_compiler_review_decision(
    store: ObjectStore,
    request: CompilerReviewDecisionRequest,
    output_dir: Path | None = None,
) -> CompilerReviewDecisionResult:
    try:
        request.validate()
        packet = validate_reviewer_packet(store, request.reviewer_packet_id)
        request_map = {item.proposal_id: item for item in request.decisions}
        if set(request_map) != set(packet["proposal_map"]):
            raise CompilerFailure(
                "REVIEW_DECISION_COVERAGE_INCOMPLETE",
                "decide",
                "every proposal requires exactly one explicit decision",
            )
        decisions = []
        counts = {"approved": 0, "rejected": 0, "needs_changes": 0}
        for proposal_id in sorted(request_map):
            item = request_map[proposal_id]
            proposal = packet["proposal_map"][proposal_id]
            risk = packet["risk_map"][proposal_id]
            if item.decision == "approved":
                proposal_audience = proposal.get("effective_audience")
                if proposal_audience not in AUDIENCE_RANK:
                    raise CompilerFailure(
                        "REVIEW_DECISION_AUDIENCE_INVALID",
                        "decide",
                        "proposal audience invalid",
                    )
                if AUDIENCE_RANK[item.approved_audience or "public"] < AUDIENCE_RANK[
                    proposal_audience
                ]:
                    raise CompilerFailure(
                        "REVIEW_DECISION_POLICY_BROADENING",
                        "decide",
                        "approved audience broadens proposal audience",
                    )
                if risk.get("risk_level") == "high" and not item.high_risk_acknowledged:
                    raise CompilerFailure(
                        "REVIEW_DECISION_HIGH_RISK_ACK_REQUIRED",
                        "decide",
                        "high-risk approval requires explicit acknowledgement",
                    )
            counts[item.decision] += 1
            decisions.append(
                {
                    "schema_version": "knowledge-compiler-proposal-decision/v1",
                    "proposal_id": proposal_id,
                    "proposal_kind": proposal["proposal_kind"],
                    "resolution_id": proposal["resolution_id"],
                    "candidate_id": proposal["candidate_id"],
                    "decision": item.decision,
                    "notes": item.notes.strip(),
                    "approved_audience": item.approved_audience,
                    "risk_level": risk["risk_level"],
                    "high_risk_acknowledged": item.high_risk_acknowledged,
                    "reviewer": request.reviewer,
                    "reviewed_at": request.reviewed_at,
                    "evidence_refs": proposal["evidence_refs"],
                    "source_snapshot_sha256": proposal["source_snapshot_sha256"],
                    "canonical_write_permitted": False,
                    "github_write_permitted": False,
                    "production_write_permitted": False,
                }
            )
        source_package_permitted = (
            counts["approved"] > 0
            and counts["needs_changes"] == 0
            and not packet["quarantined"]
        )
        identity = {
            "schema_version": "knowledge-compiler-review-decision-set/v1",
            "request": request.identity(),
            "packet_artifact_hashes": packet["artifact_hashes"],
            "proposal_batch_id": packet["proposal_batch_id"],
            "source_snapshot_sha256": packet["source_snapshot_sha256"],
        }
        decision_set_id = "rvwd_" + sha256_bytes(canonical_json_bytes(identity))
        prefix = f"compiler/v1/review-decisions/{decision_set_id}"
        record_key = f"{prefix}/decision-record.json"
        decisions_key = f"{prefix}/decisions.json"
        validation_key = f"{prefix}/validation-report.json"
        result_key = f"{prefix}/result.json"
        docs = {
            record_key: {
                **identity,
                "decision_set_id": decision_set_id,
                "reviewer_packet_id": request.reviewer_packet_id,
                "status": "recorded",
                "decision_count": len(decisions),
                "approved_count": counts["approved"],
                "rejected_count": counts["rejected"],
                "needs_changes_count": counts["needs_changes"],
                "source_package_permitted": source_package_permitted,
                "automatic_approval_permitted": False,
                "canonical_write_permitted": False,
                "github_write_permitted": False,
                "production_write_permitted": False,
            },
            decisions_key: {
                "schema_version": "knowledge-compiler-proposal-decision-set/v1",
                "decision_set_id": decision_set_id,
                "reviewer_packet_id": request.reviewer_packet_id,
                "decision_count": len(decisions),
                "decisions": decisions,
                "canonical_write_permitted": False,
            },
            validation_key: {
                "schema_version": "knowledge-compiler-review-decision-validation/v1",
                "decision_set_id": decision_set_id,
                "reviewer_packet_id": request.reviewer_packet_id,
                "all_proposals_explicitly_decided": True,
                "audience_broadening_detected": False,
                "automatic_approval_detected": False,
                "quarantine_count": len(packet["quarantined"]),
                "source_package_permitted": source_package_permitted,
                "canonical_write_permitted": False,
                "github_write_permitted": False,
                "production_write_permitted": False,
            },
        }
        stages = [
            (None, "validated_packet", list(packet["keys"].values()), [validation_key]),
            ("validated_packet", "decisions_recorded", [validation_key], [decisions_key]),
            (
                "decisions_recorded",
                "review_complete",
                [decisions_key],
                [record_key, result_key],
            ),
        ]
        events = []
        previous = None
        for ordinal, (before, after, inputs, outputs) in enumerate(stages, 1):
            event = _event(
                decision_set_id,
                ordinal,
                request.reviewed_at,
                before,
                after,
                inputs,
                outputs,
                previous,
            )
            events.append(event)
            previous = event["event_sha256"]
        event_keys = tuple(
            f"{prefix}/events/{event['ordinal']:06d}-{event['event_sha256']}.json"
            for event in events
        )
        result = CompilerReviewDecisionResult(
            decision_set_id=decision_set_id,
            reviewer_packet_id=request.reviewer_packet_id,
            status="recorded",
            result_key=result_key,
            event_keys=event_keys,
            decision_count=len(decisions),
            approved_count=counts["approved"],
            rejected_count=counts["rejected"],
            needs_changes_count=counts["needs_changes"],
            source_package_permitted=source_package_permitted,
            decision_prefix=prefix,
        )
        states = [
            put_immutable(store, key, json_bytes(value)) for key, value in sorted(docs.items())
        ]
        for key, event in zip(event_keys, events, strict=True):
            states.append(put_immutable(store, key, json_bytes(event)))
        states.append(put_immutable(store, result_key, json_bytes(result.evidence())))
        result = replace(result, idempotent=all(states))
        for key, value in docs.items():
            _write_output(output_dir, key.removeprefix(prefix + "/"), json_bytes(value))
        _write_output(output_dir, "review-decision-result.json", json_bytes(result.to_dict()))
        return result
    except CompilerFailure as failure:
        return _reject(store, request, failure, output_dir)
