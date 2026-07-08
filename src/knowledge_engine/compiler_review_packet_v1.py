from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from .compiler_contract_v1 import CompilerFailure, json_bytes, put_immutable
from .compiler_resolution_contract_v1 import digest_object, load_json_object
from .compiler_review_packet_contract_v1 import ReviewerPacketRequest, ReviewerPacketResult
from .compiler_source_v1 import AUDIENCE_RANK
from .compiler_synthesis_contract_v1 import ELIGIBLE_OUTCOMES, PROPOSAL_KINDS
from .compiler_synthesis_v1 import _validate_resolution_batch, verify_synthesis_event
from .intake_v1 import canonical_json_bytes
from .storage import ObjectStore, sha256_bytes

_OPERATION_BY_KIND = {
    "concept_create": "create_concept_draft",
    "concept_update": "append_evidence_bound_claim",
    "alias_add": "add_alias",
    "supersession_update": "mark_superseded",
}
_RISK_BY_KIND = {
    "concept_create": "medium",
    "concept_update": "medium",
    "alias_add": "low",
    "supersession_update": "high",
}


def _event(
    packet_id: str,
    ordinal: int,
    occurred_at: str,
    before: str | None,
    after: str,
    inputs: list[str],
    outputs: list[str],
    previous: str | None,
) -> dict[str, Any]:
    payload = {
        "schema_version": "knowledge-compiler-reviewer-packet-event/v1",
        "reviewer_packet_id": packet_id,
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


def verify_reviewer_packet_event(event: Mapping[str, Any]) -> bool:
    payload = dict(event)
    expected = payload.pop("event_sha256", None)
    return isinstance(expected, str) and expected == sha256_bytes(canonical_json_bytes(payload))


def _write_output(root: Path | None, relative: str, data: bytes) -> None:
    if root is None:
        return
    path = root.resolve() / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _validate_synthesis_events(store: ObjectStore, prefix: str, event_keys: Any) -> None:
    if not isinstance(event_keys, list) or not event_keys:
        raise CompilerFailure(
            "REVIEW_PACKET_EVENT_CHAIN_INVALID", "validate", "synthesis event chain missing"
        )
    previous = None
    final_state = None
    for ordinal, key in enumerate(event_keys, 1):
        if not isinstance(key, str) or not key.startswith(f"{prefix}/events/"):
            raise CompilerFailure(
                "REVIEW_PACKET_EVENT_CHAIN_INVALID",
                "validate",
                "synthesis event key invalid",
            )
        event = load_json_object(store, key, "synthesis event")
        if not verify_synthesis_event(event):
            raise CompilerFailure(
                "REVIEW_PACKET_EVENT_CHAIN_INVALID",
                "validate",
                "synthesis event hash invalid",
            )
        if event.get("ordinal") != ordinal or event.get("previous_event_hash") != previous:
            raise CompilerFailure(
                "REVIEW_PACKET_EVENT_CHAIN_INVALID",
                "validate",
                "synthesis event chain not adjacent",
            )
        event_hash = event.get("event_sha256")
        if not isinstance(event_hash, str) or not key.endswith(f"-{event_hash}.json"):
            raise CompilerFailure(
                "REVIEW_PACKET_EVENT_CHAIN_INVALID",
                "validate",
                "synthesis event key mismatch",
            )
        previous = event_hash
        final_state = event.get("to_state")
    if final_state != "review_only_complete":
        raise CompilerFailure(
            "REVIEW_PACKET_EVENT_CHAIN_INVALID",
            "validate",
            "synthesis terminal state invalid",
        )


def _validate_proposal_batch(store: ObjectStore, proposal_batch_id: str) -> dict[str, Any]:
    prefix = f"compiler/v1/proposals/{proposal_batch_id}"
    keys = {
        "record": f"{prefix}/proposal-record.json",
        "proposals": f"{prefix}/proposal-set.json",
        "claim_map": f"{prefix}/claim-map.json",
        "quarantine": f"{prefix}/quarantine.json",
        "validation": f"{prefix}/validation-report.json",
        "result": f"{prefix}/result.json",
    }
    docs = {name: load_json_object(store, key, name) for name, key in keys.items()}
    record = docs["record"]
    result = docs["result"]
    proposal_set = docs["proposals"]
    claim_map = docs["claim_map"]
    quarantine = docs["quarantine"]
    validation = docs["validation"]

    if record.get("proposal_batch_id") != proposal_batch_id:
        raise CompilerFailure(
            "REVIEW_PACKET_IDENTITY_MISMATCH", "validate", "proposal record mismatch"
        )
    if record.get("status") != "review_only_complete":
        raise CompilerFailure(
            "REVIEW_PACKET_PROPOSAL_INCOMPLETE", "validate", "proposal batch incomplete"
        )
    if result.get("proposal_batch_id") != proposal_batch_id:
        raise CompilerFailure(
            "REVIEW_PACKET_IDENTITY_MISMATCH", "validate", "proposal result mismatch"
        )
    if result.get("status") != "review_only_complete":
        raise CompilerFailure(
            "REVIEW_PACKET_PROPOSAL_INCOMPLETE", "validate", "proposal result incomplete"
        )
    _validate_synthesis_events(store, prefix, result.get("event_keys"))

    for value in (proposal_set, claim_map, quarantine, validation):
        if value.get("proposal_batch_id") != proposal_batch_id:
            raise CompilerFailure(
                "REVIEW_PACKET_IDENTITY_MISMATCH",
                "validate",
                "proposal artifact identity mismatch",
            )
    if validation.get("all_resolution_evidence_valid") is not True:
        raise CompilerFailure(
            "REVIEW_PACKET_EVIDENCE_INVALID",
            "validate",
            "resolution evidence was not validated",
        )
    if validation.get("all_proposals_evidence_bound") is not True:
        raise CompilerFailure(
            "REVIEW_PACKET_EVIDENCE_INVALID",
            "validate",
            "proposal evidence is incomplete",
        )
    if validation.get("provider_invocations") != 0:
        raise CompilerFailure(
            "REVIEW_PACKET_PROVIDER_BOUNDARY_INVALID",
            "validate",
            "provider invocation detected",
        )
    if validation.get("audience_broadening_detected") is not False:
        raise CompilerFailure(
            "REVIEW_PACKET_POLICY_BROADENING",
            "validate",
            "proposal batch reports audience broadening",
        )
    if validation.get("orphan_proposals_detected") is not False:
        raise CompilerFailure(
            "REVIEW_PACKET_ORPHAN_PROPOSAL", "validate", "proposal batch reports orphan"
        )

    request = record.get("request")
    if not isinstance(request, dict):
        raise CompilerFailure(
            "REVIEW_PACKET_RECORD_INVALID", "validate", "synthesis request missing"
        )
    resolution_batch_id = request.get("resolution_batch_id")
    if not isinstance(resolution_batch_id, str):
        raise CompilerFailure(
            "REVIEW_PACKET_RECORD_INVALID", "validate", "resolution batch identity missing"
        )
    resolved = _validate_resolution_batch(store, resolution_batch_id)
    resolution_map = {item["resolution_id"]: item for item in resolved["resolutions"]}

    proposals = proposal_set.get("proposals")
    claims = claim_map.get("claims")
    quarantined = quarantine.get("items")
    if not all(isinstance(value, list) for value in (proposals, claims, quarantined)):
        raise CompilerFailure(
            "REVIEW_PACKET_ARTIFACT_INVALID", "validate", "proposal lists invalid"
        )
    if proposal_set.get("proposal_count") != len(proposals):
        raise CompilerFailure(
            "REVIEW_PACKET_COUNT_MISMATCH", "validate", "proposal count mismatch"
        )
    if quarantine.get("quarantine_count") != len(quarantined):
        raise CompilerFailure(
            "REVIEW_PACKET_COUNT_MISMATCH", "validate", "quarantine count mismatch"
        )

    proposal_ids: set[str] = set()
    proposal_resolution_ids: set[str] = set()
    for proposal in proposals:
        if not isinstance(proposal, dict):
            raise CompilerFailure(
                "REVIEW_PACKET_PROPOSAL_INVALID", "validate", "proposal must be object"
            )
        proposal_id = proposal.get("proposal_id")
        resolution_id = proposal.get("resolution_id")
        if not isinstance(proposal_id, str) or proposal_id in proposal_ids:
            raise CompilerFailure(
                "REVIEW_PACKET_PROPOSAL_DUPLICATE",
                "validate",
                "proposal identity missing or duplicated",
            )
        proposal_ids.add(proposal_id)
        if not isinstance(resolution_id, str) or resolution_id in proposal_resolution_ids:
            raise CompilerFailure(
                "REVIEW_PACKET_RESOLUTION_DUPLICATE",
                "validate",
                "proposal resolution duplicated",
            )
        proposal_resolution_ids.add(resolution_id)
        resolution = resolution_map.get(resolution_id)
        if resolution is None:
            raise CompilerFailure(
                "REVIEW_PACKET_ORPHAN_PROPOSAL", "validate", "proposal resolution missing"
            )
        expected_kind = ELIGIBLE_OUTCOMES.get(resolution.get("outcome"))
        if resolution.get("synthesis_eligible") is not True or expected_kind is None:
            raise CompilerFailure(
                "REVIEW_PACKET_INELIGIBLE_LEAKAGE",
                "validate",
                "ineligible resolution leaked into proposals",
            )
        kind = proposal.get("proposal_kind")
        if kind != expected_kind or kind not in PROPOSAL_KINDS:
            raise CompilerFailure(
                "REVIEW_PACKET_PROPOSAL_KIND_INVALID", "validate", "proposal kind mismatch"
            )
        if proposal.get("candidate_id") != resolution.get("candidate_id"):
            raise CompilerFailure(
                "REVIEW_PACKET_EVIDENCE_DISCONTINUITY",
                "validate",
                "proposal candidate mismatch",
            )
        if proposal.get("evidence_refs") != resolution.get("evidence_refs"):
            raise CompilerFailure(
                "REVIEW_PACKET_EVIDENCE_DISCONTINUITY",
                "validate",
                "proposal evidence mismatch",
            )
        if proposal.get("target_ids") != resolution.get("target_ids"):
            raise CompilerFailure(
                "REVIEW_PACKET_TARGET_MISMATCH", "validate", "proposal target mismatch"
            )
        if proposal.get("source_snapshot_sha256") != resolved["source_snapshot_sha256"]:
            raise CompilerFailure(
                "REVIEW_PACKET_SOURCE_MISMATCH", "validate", "source snapshot mismatch"
            )
        audience = proposal.get("effective_audience")
        if audience not in AUDIENCE_RANK:
            raise CompilerFailure(
                "REVIEW_PACKET_AUDIENCE_INVALID", "validate", "proposal audience invalid"
            )
        resolution_audience = resolution["effective_audience"]
        if AUDIENCE_RANK[audience] < AUDIENCE_RANK[resolution_audience]:
            raise CompilerFailure(
                "REVIEW_PACKET_POLICY_BROADENING", "validate", "proposal audience broadened"
            )
        payload = proposal.get("payload")
        if not isinstance(payload, dict) or payload.get("operation") != _OPERATION_BY_KIND[kind]:
            raise CompilerFailure(
                "REVIEW_PACKET_PAYLOAD_INVALID", "validate", "proposal payload invalid"
            )
        if proposal.get("provider") != "none":
            raise CompilerFailure(
                "REVIEW_PACKET_PROVIDER_BOUNDARY_INVALID",
                "validate",
                "proposal names a provider",
            )
        if proposal.get("provider_invocation_permitted") is not False:
            raise CompilerFailure(
                "REVIEW_PACKET_PROVIDER_BOUNDARY_INVALID",
                "validate",
                "proposal permits provider invocation",
            )
        if proposal.get("review_status") != "pending_human_review":
            raise CompilerFailure(
                "REVIEW_PACKET_REVIEW_STATUS_INVALID",
                "validate",
                "proposal bypasses human review",
            )
        for flag in (
            "canonical_write_permitted",
            "github_write_permitted",
            "production_write_permitted",
        ):
            if proposal.get(flag) is not False:
                raise CompilerFailure(
                    "REVIEW_PACKET_MUTATION_BOUNDARY_INVALID",
                    "validate",
                    "proposal grants forbidden mutation",
                )

    claim_by_proposal = {
        item.get("proposal_id"): item for item in claims if isinstance(item, dict)
    }
    if set(claim_by_proposal) != proposal_ids or len(claims) != len(proposals):
        raise CompilerFailure(
            "REVIEW_PACKET_CLAIM_MAP_INVALID", "validate", "claim map coverage mismatch"
        )
    for proposal in proposals:
        claim = claim_by_proposal[proposal["proposal_id"]]
        for field in (
            "resolution_id",
            "candidate_id",
            "evidence_refs",
            "source_snapshot_sha256",
        ):
            if claim.get(field) != proposal.get(field):
                raise CompilerFailure(
                    "REVIEW_PACKET_CLAIM_MAP_INVALID",
                    "validate",
                    "claim map evidence mismatch",
                )

    quarantine_ids: set[str] = set()
    for item in quarantined:
        if not isinstance(item, dict):
            raise CompilerFailure(
                "REVIEW_PACKET_QUARANTINE_INVALID",
                "validate",
                "quarantine item must be object",
            )
        resolution_id = item.get("resolution_id")
        if not isinstance(resolution_id, str) or resolution_id in quarantine_ids:
            raise CompilerFailure(
                "REVIEW_PACKET_QUARANTINE_INVALID",
                "validate",
                "quarantine identity missing or duplicated",
            )
        quarantine_ids.add(resolution_id)
        resolution = resolution_map.get(resolution_id)
        if resolution is None:
            raise CompilerFailure(
                "REVIEW_PACKET_QUARANTINE_INVALID",
                "validate",
                "quarantine resolution missing",
            )
        if item.get("candidate_id") != resolution.get("candidate_id"):
            raise CompilerFailure(
                "REVIEW_PACKET_EVIDENCE_DISCONTINUITY",
                "validate",
                "quarantine candidate mismatch",
            )
        if item.get("evidence_refs") != resolution.get("evidence_refs"):
            raise CompilerFailure(
                "REVIEW_PACKET_EVIDENCE_DISCONTINUITY",
                "validate",
                "quarantine evidence mismatch",
            )
        if item.get("canonical_write_permitted") is not False:
            raise CompilerFailure(
                "REVIEW_PACKET_MUTATION_BOUNDARY_INVALID",
                "validate",
                "quarantine grants canonical write",
            )

    if proposal_resolution_ids & quarantine_ids:
        raise CompilerFailure(
            "REVIEW_PACKET_COVERAGE_OVERLAP",
            "validate",
            "resolution appears in proposal and quarantine",
        )
    if proposal_resolution_ids | quarantine_ids != set(resolution_map):
        raise CompilerFailure(
            "REVIEW_PACKET_COVERAGE_INCOMPLETE",
            "validate",
            "resolution coverage is incomplete",
        )

    artifact_hashes = {name: digest_object(store, key) for name, key in keys.items()}
    return {
        "keys": keys,
        "artifact_hashes": artifact_hashes,
        "resolution_batch_id": resolution_batch_id,
        "source_snapshot_sha256": resolved["source_snapshot_sha256"],
        "proposals": proposals,
        "quarantined": quarantined,
    }


def _reject(
    store: ObjectStore,
    request: ReviewerPacketRequest,
    failure: CompilerFailure,
    output_dir: Path | None,
) -> ReviewerPacketResult:
    attempt_id = request.attempt_id()
    prefix = f"compiler/v1/reviewer-packet-rejections/{attempt_id}"
    rejection_key = f"{prefix}/evidence.json"
    result_key = f"{prefix}/result.json"
    rejection = {
        "schema_version": "knowledge-compiler-reviewer-packet-rejection/v1",
        "reviewer_packet_attempt_id": attempt_id,
        "proposal_batch_id": request.proposal_batch_id,
        "stage": failure.stage,
        "reason_code": failure.code,
        "message": failure.message,
        "safe_context": failure.context,
        "human_decision_required": True,
        "canonical_write_permitted": False,
        "github_write_permitted": False,
        "production_write_permitted": False,
    }
    states = [put_immutable(store, rejection_key, json_bytes(rejection))]
    result = ReviewerPacketResult(
        reviewer_packet_id=attempt_id,
        proposal_batch_id=request.proposal_batch_id,
        status="rejected",
        result_key=result_key,
        event_keys=(),
        rejection_key=rejection_key,
        failure_code=failure.code,
    )
    states.append(put_immutable(store, result_key, json_bytes(result.evidence())))
    result = replace(result, idempotent=all(states))
    _write_output(output_dir, "rejection.json", json_bytes(rejection))
    _write_output(output_dir, "reviewer-packet-result.json", json_bytes(result.to_dict()))
    return result


def build_reviewer_packet(
    store: ObjectStore,
    request: ReviewerPacketRequest,
    output_dir: Path | None = None,
) -> ReviewerPacketResult:
    try:
        request.validate()
        validated = _validate_proposal_batch(store, request.proposal_batch_id)
        proposals = validated["proposals"]
        quarantined = validated["quarantined"]
        if len(proposals) + len(quarantined) > request.max_items:
            raise CompilerFailure(
                "REVIEW_PACKET_LIMIT_EXCEEDED", "assemble", "review item limit exceeded"
            )

        risks = [
            {
                "proposal_id": item["proposal_id"],
                "proposal_kind": item["proposal_kind"],
                "risk_level": _RISK_BY_KIND[item["proposal_kind"]],
                "reason_codes": [
                    "DESTRUCTIVE_CANONICAL_SEMANTICS"
                    if item["proposal_kind"] == "supersession_update"
                    else "HUMAN_CANONICAL_REVIEW_REQUIRED"
                ],
            }
            for item in proposals
        ]
        high_risk_count = sum(item["risk_level"] == "high" for item in risks)
        identity = {
            "schema_version": "knowledge-compiler-reviewer-packet-batch/v1",
            "request": request.identity(),
            "proposal_artifact_hashes": validated["artifact_hashes"],
            "resolution_batch_id": validated["resolution_batch_id"],
            "source_snapshot_sha256": validated["source_snapshot_sha256"],
        }
        packet_id = "rvwp_" + sha256_bytes(canonical_json_bytes(identity))
        prefix = f"compiler/v1/reviewer-packets/{packet_id}"
        record_key = f"{prefix}/packet-record.json"
        summary_key = f"{prefix}/summary.json"
        index_key = f"{prefix}/proposal-index.json"
        risk_key = f"{prefix}/risk-report.json"
        quarantine_key = f"{prefix}/quarantine-report.json"
        checklist_key = f"{prefix}/review-checklist.json"
        result_key = f"{prefix}/result.json"

        docs = {
            record_key: {
                **identity,
                "reviewer_packet_id": packet_id,
                "status": "review_ready",
                "human_decision_required": True,
                "canonical_write_permitted": False,
                "github_write_permitted": False,
                "production_write_permitted": False,
            },
            summary_key: {
                "schema_version": "knowledge-compiler-reviewer-packet-summary/v1",
                "reviewer_packet_id": packet_id,
                "proposal_batch_id": request.proposal_batch_id,
                "proposal_count": len(proposals),
                "quarantine_count": len(quarantined),
                "high_risk_count": high_risk_count,
                "decision_state": "awaiting_human_decision",
                "human_decision_required": True,
            },
            index_key: {
                "schema_version": "knowledge-compiler-reviewer-proposal-index/v1",
                "reviewer_packet_id": packet_id,
                "proposals": [
                    {
                        "proposal_id": item["proposal_id"],
                        "proposal_kind": item["proposal_kind"],
                        "resolution_id": item["resolution_id"],
                        "candidate_id": item["candidate_id"],
                        "target_ids": item["target_ids"],
                        "evidence_refs": item["evidence_refs"],
                        "effective_audience": item["effective_audience"],
                        "payload": item["payload"],
                    }
                    for item in proposals
                ],
            },
            risk_key: {
                "schema_version": "knowledge-compiler-reviewer-risk-report/v1",
                "reviewer_packet_id": packet_id,
                "high_risk_count": high_risk_count,
                "risks": risks,
            },
            quarantine_key: {
                "schema_version": "knowledge-compiler-reviewer-quarantine-report/v1",
                "reviewer_packet_id": packet_id,
                "quarantine_count": len(quarantined),
                "items": quarantined,
                "release_blocking": bool(quarantined),
            },
            checklist_key: {
                "schema_version": "knowledge-compiler-review-checklist/v1",
                "reviewer_packet_id": packet_id,
                "items": [
                    {
                        "proposal_id": item["proposal_id"],
                        "checks": [
                            "verify_claim_against_evidence_refs",
                            "verify_target_and_identity",
                            "verify_audience_and_private_data_risk",
                            "approve_reject_or_request_changes",
                        ],
                        "decision": None,
                        "decided_by": None,
                        "decided_at": None,
                    }
                    for item in proposals
                ],
                "automatic_approval_permitted": False,
                "human_decision_required": True,
            },
        }
        stages = [
            (None, "validated_proposals", list(validated["keys"].values()), [summary_key]),
            ("validated_proposals", "risk_assessed", [summary_key], [risk_key]),
            (
                "risk_assessed",
                "review_packet_assembled",
                [risk_key],
                [index_key, quarantine_key, checklist_key],
            ),
            (
                "review_packet_assembled",
                "review_ready",
                [index_key, checklist_key],
                [record_key, result_key],
            ),
        ]
        events = []
        previous = None
        for ordinal, (before, after, inputs, outputs) in enumerate(stages, 1):
            event = _event(
                packet_id,
                ordinal,
                request.assembled_at,
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
        result = ReviewerPacketResult(
            reviewer_packet_id=packet_id,
            proposal_batch_id=request.proposal_batch_id,
            status="review_ready",
            result_key=result_key,
            event_keys=event_keys,
            proposal_count=len(proposals),
            quarantine_count=len(quarantined),
            high_risk_count=high_risk_count,
            packet_prefix=prefix,
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
        _write_output(output_dir, "reviewer-packet-result.json", json_bytes(result.to_dict()))
        return result
    except CompilerFailure as failure:
        return _reject(store, request, failure, output_dir)
