from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from .compiler_contract_v1 import CompilerFailure, json_bytes, put_immutable
from .compiler_resolution_contract_v1 import digest_object, load_json_object
from .compiler_resolution_v1 import verify_resolution_event
from .compiler_source_v1 import AUDIENCE_RANK
from .compiler_synthesis_contract_v1 import (
    ELIGIBLE_OUTCOMES,
    PROPOSAL_KINDS,
    SynthesisProposalRequest,
    SynthesisProposalResult,
)
from .intake_v1 import canonical_json_bytes
from .storage import ObjectStore, sha256_bytes


def _event(
    batch_id: str,
    ordinal: int,
    occurred_at: str,
    before: str | None,
    after: str,
    inputs: list[str],
    outputs: list[str],
    previous: str | None,
) -> dict[str, Any]:
    payload = {
        "schema_version": "knowledge-compiler-synthesis-event/v1",
        "proposal_batch_id": batch_id,
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


def verify_synthesis_event(event: Mapping[str, Any]) -> bool:
    payload = dict(event)
    expected = payload.pop("event_sha256", None)
    return isinstance(expected, str) and expected == sha256_bytes(canonical_json_bytes(payload))


def _write_output(root: Path | None, relative: str, data: bytes) -> None:
    if root is None:
        return
    path = root.resolve() / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _validate_resolution_events(store: ObjectStore, prefix: str, event_keys: Any) -> None:
    if not isinstance(event_keys, list) or not event_keys:
        raise CompilerFailure(
            "SYNTHESIS_RESOLUTION_EVENT_CHAIN_INVALID",
            "validate",
            "resolution event chain missing",
        )
    previous = None
    final_state = None
    for ordinal, key in enumerate(event_keys, 1):
        if not isinstance(key, str) or not key.startswith(f"{prefix}/events/"):
            raise CompilerFailure(
                "SYNTHESIS_RESOLUTION_EVENT_CHAIN_INVALID",
                "validate",
                "resolution event key invalid",
            )
        event = load_json_object(store, key, "resolution event")
        if not verify_resolution_event(event):
            raise CompilerFailure(
                "SYNTHESIS_RESOLUTION_EVENT_CHAIN_INVALID",
                "validate",
                "resolution event hash invalid",
            )
        if event.get("ordinal") != ordinal or event.get("previous_event_hash") != previous:
            raise CompilerFailure(
                "SYNTHESIS_RESOLUTION_EVENT_CHAIN_INVALID",
                "validate",
                "resolution event chain not adjacent",
            )
        event_hash = event.get("event_sha256")
        if not isinstance(event_hash, str) or not key.endswith(f"-{event_hash}.json"):
            raise CompilerFailure(
                "SYNTHESIS_RESOLUTION_EVENT_CHAIN_INVALID",
                "validate",
                "resolution event key mismatch",
            )
        previous = event_hash
        final_state = event.get("to_state")
    if final_state != "review_only_complete":
        raise CompilerFailure(
            "SYNTHESIS_RESOLUTION_EVENT_CHAIN_INVALID",
            "validate",
            "resolution terminal state invalid",
        )


def _validate_resolution_batch(
    store: ObjectStore,
    resolution_batch_id: str,
) -> dict[str, Any]:
    prefix = f"compiler/v1/resolutions/{resolution_batch_id}"
    keys = {
        "record": f"{prefix}/resolution-record.json",
        "snapshot": f"{prefix}/source-snapshot.json",
        "candidate_index": f"{prefix}/candidate-index.json",
        "resolutions": f"{prefix}/resolutions.json",
        "validation": f"{prefix}/validation-report.json",
        "result": f"{prefix}/result.json",
    }
    docs = {name: load_json_object(store, key, name) for name, key in keys.items()}
    record = docs["record"]
    result = docs["result"]
    resolution_set = docs["resolutions"]
    candidate_index = docs["candidate_index"]
    snapshot = docs["snapshot"]
    validation = docs["validation"]

    if record.get("resolution_batch_id") != resolution_batch_id:
        raise CompilerFailure(
            "SYNTHESIS_RESOLUTION_IDENTITY_MISMATCH",
            "validate",
            "resolution record identity mismatch",
        )
    if record.get("status") != "review_only_complete":
        raise CompilerFailure(
            "SYNTHESIS_RESOLUTION_INCOMPLETE",
            "validate",
            "resolution record is not complete",
        )
    if result.get("resolution_batch_id") != resolution_batch_id:
        raise CompilerFailure(
            "SYNTHESIS_RESOLUTION_IDENTITY_MISMATCH",
            "validate",
            "resolution result identity mismatch",
        )
    if result.get("status") != "review_only_complete":
        raise CompilerFailure(
            "SYNTHESIS_RESOLUTION_INCOMPLETE",
            "validate",
            "resolution result is not complete",
        )
    _validate_resolution_events(store, prefix, result.get("event_keys"))

    compiler_run_id = record.get("request", {}).get("compiler_run_id")
    if not isinstance(compiler_run_id, str):
        raise CompilerFailure(
            "SYNTHESIS_RESOLUTION_RECORD_INVALID",
            "validate",
            "compiler run identity missing",
        )
    source_snapshot_sha256 = snapshot.get("source_snapshot_sha256")
    if not isinstance(source_snapshot_sha256, str):
        raise CompilerFailure(
            "SYNTHESIS_SOURCE_SNAPSHOT_INVALID",
            "validate",
            "source snapshot digest missing",
        )
    for value in (candidate_index, resolution_set, validation):
        if value.get("resolution_batch_id") != resolution_batch_id:
            raise CompilerFailure(
                "SYNTHESIS_RESOLUTION_IDENTITY_MISMATCH",
                "validate",
                "resolution artifact identity mismatch",
            )
    if validation.get("all_candidates_evidence_valid") is not True:
        raise CompilerFailure(
            "SYNTHESIS_EVIDENCE_NOT_VALIDATED",
            "validate",
            "resolution evidence is not fully validated",
        )
    if validation.get("audience_broadening_detected") is not False:
        raise CompilerFailure(
            "SYNTHESIS_POLICY_BROADENING",
            "validate",
            "resolution batch reports audience broadening",
        )
    if any(
        value.get(flag) is not False
        for value in (record, result, validation, resolution_set, candidate_index)
        for flag in (
            "canonical_write_permitted",
            "github_write_permitted",
            "production_write_permitted",
        )
        if flag in value
    ):
        raise CompilerFailure(
            "SYNTHESIS_MUTATION_BOUNDARY_INVALID",
            "validate",
            "resolution artifact grants forbidden mutation",
        )

    resolutions = resolution_set.get("resolutions")
    concepts = candidate_index.get("concepts")
    if not isinstance(resolutions, list) or not isinstance(concepts, list):
        raise CompilerFailure(
            "SYNTHESIS_RESOLUTION_SET_INVALID",
            "validate",
            "resolution set or candidate index invalid",
        )
    resolution_ids: set[str] = set()
    for item in resolutions:
        if not isinstance(item, dict):
            raise CompilerFailure(
                "SYNTHESIS_RESOLUTION_SET_INVALID", "validate", "resolution must be an object"
            )
        resolution_id = item.get("resolution_id")
        if not isinstance(resolution_id, str) or resolution_id in resolution_ids:
            raise CompilerFailure(
                "SYNTHESIS_RESOLUTION_DUPLICATE",
                "validate",
                "resolution identity missing or duplicated",
            )
        resolution_ids.add(resolution_id)
        if item.get("compiler_run_id") != compiler_run_id:
            raise CompilerFailure(
                "SYNTHESIS_RESOLUTION_IDENTITY_MISMATCH",
                "validate",
                "resolution compiler identity mismatch",
            )
        if item.get("effective_audience") not in AUDIENCE_RANK:
            raise CompilerFailure(
                "SYNTHESIS_AUDIENCE_INVALID", "validate", "resolution audience invalid"
            )
        if item.get("canonical_write_permitted") is not False:
            raise CompilerFailure(
                "SYNTHESIS_MUTATION_BOUNDARY_INVALID",
                "validate",
                "resolution grants canonical write",
            )
        evidence_refs = item.get("evidence_refs")
        if not isinstance(evidence_refs, list) or not evidence_refs:
            raise CompilerFailure(
                "SYNTHESIS_EVIDENCE_MISSING", "validate", "resolution evidence missing"
            )

    candidate_key = f"compiler/v1/runs/{compiler_run_id}/extraction/candidates.json"
    candidate_set = load_json_object(store, candidate_key, "compiler candidate set")
    candidates = candidate_set.get("candidates")
    if candidate_set.get("compiler_run_id") != compiler_run_id or not isinstance(candidates, list):
        raise CompilerFailure(
            "SYNTHESIS_CANDIDATE_SET_INVALID", "validate", "candidate set invalid"
        )
    candidate_map = {
        item.get("candidate_id"): item
        for item in candidates
        if isinstance(item, dict) and isinstance(item.get("candidate_id"), str)
    }
    for resolution in resolutions:
        candidate_id = resolution.get("candidate_id")
        if candidate_id not in candidate_map:
            raise CompilerFailure(
                "SYNTHESIS_ORPHAN_RESOLUTION",
                "validate",
                "resolution candidate is missing",
            )
        if candidate_id not in resolution["evidence_refs"]:
            raise CompilerFailure(
                "SYNTHESIS_EVIDENCE_DISCONTINUITY",
                "validate",
                "candidate identity not preserved in resolution evidence",
            )

    artifact_hashes = {name: digest_object(store, key) for name, key in keys.items()}
    artifact_hashes["candidate_set"] = digest_object(store, candidate_key)
    return {
        "prefix": prefix,
        "keys": keys,
        "artifact_hashes": artifact_hashes,
        "compiler_run_id": compiler_run_id,
        "source_snapshot_sha256": source_snapshot_sha256,
        "resolutions": resolutions,
        "candidate_map": candidate_map,
        "concept_map": {
            item["concept_id"]: item
            for item in concepts
            if isinstance(item, dict) and isinstance(item.get("concept_id"), str)
        },
    }


def _proposal_for(
    resolution_batch_id: str,
    source_snapshot_sha256: str,
    resolution: dict[str, Any],
    candidate: dict[str, Any],
    concept_map: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    outcome = resolution["outcome"]
    kind = ELIGIBLE_OUTCOMES[outcome]
    target_ids = resolution.get("target_ids", [])
    if not isinstance(target_ids, list):
        raise CompilerFailure(
            "SYNTHESIS_TARGET_INVALID", "synthesize", "proposal target IDs invalid"
        )
    if kind == "concept_create" and target_ids:
        raise CompilerFailure(
            "SYNTHESIS_TARGET_INVALID", "synthesize", "new concept may not have a target"
        )
    if kind != "concept_create" and len(target_ids) != 1:
        raise CompilerFailure(
            "SYNTHESIS_TARGET_INVALID",
            "synthesize",
            "targeted proposal requires exactly one target",
        )
    for target_id in target_ids:
        if target_id not in concept_map:
            raise CompilerFailure(
                "SYNTHESIS_TARGET_INVALID", "synthesize", "proposal target is absent"
            )

    value = candidate.get("value")
    if not isinstance(value, str) or not value.strip():
        raise CompilerFailure(
            "SYNTHESIS_CANDIDATE_INVALID", "synthesize", "candidate value is empty"
        )
    evidence_refs = resolution["evidence_refs"]
    payload: dict[str, Any]
    if kind == "concept_create":
        payload = {
            "operation": "create_concept_draft",
            "suggested_title": value.strip().splitlines()[0][:160],
            "claim_text": value.strip(),
        }
    elif kind == "concept_update":
        payload = {
            "operation": "append_evidence_bound_claim",
            "target_id": target_ids[0],
            "claim_text": value.strip(),
        }
    elif kind == "alias_add":
        payload = {
            "operation": "add_alias",
            "target_id": target_ids[0],
            "alias": value.strip(),
        }
    else:
        basis = resolution.get("supersession_basis")
        if not isinstance(basis, dict) or basis.get("superseded_target_id") != target_ids[0]:
            raise CompilerFailure(
                "SYNTHESIS_SUPERSESSION_INVALID",
                "synthesize",
                "supersession basis is missing or inconsistent",
            )
        payload = {
            "operation": "mark_superseded",
            "target_id": target_ids[0],
            "basis": basis.get("basis"),
            "claim_text": value.strip(),
        }

    identity = {
        "resolution_batch_id": resolution_batch_id,
        "resolution_id": resolution["resolution_id"],
        "candidate_id": resolution["candidate_id"],
        "proposal_kind": kind,
        "target_ids": target_ids,
        "evidence_refs": evidence_refs,
        "effective_audience": resolution["effective_audience"],
        "source_snapshot_sha256": source_snapshot_sha256,
        "payload": payload,
    }
    proposal_id = "cprop_" + sha256_bytes(canonical_json_bytes(identity))
    proposal = {
        "schema_version": "knowledge-compiler-synthesis-proposal/v1",
        "proposal_id": proposal_id,
        **identity,
        "provider": "none",
        "provider_invocation_permitted": False,
        "review_status": "pending_human_review",
        "canonical_write_permitted": False,
        "github_write_permitted": False,
        "production_write_permitted": False,
    }
    if proposal["proposal_kind"] not in PROPOSAL_KINDS:
        raise CompilerFailure(
            "SYNTHESIS_PROPOSAL_KIND_INVALID", "synthesize", "proposal kind invalid"
        )
    return proposal


def _reject(
    store: ObjectStore,
    request: SynthesisProposalRequest,
    failure: CompilerFailure,
    output_dir: Path | None,
) -> SynthesisProposalResult:
    attempt_id = request.attempt_id()
    prefix = f"compiler/v1/synthesis-rejections/{attempt_id}"
    rejection_key = f"{prefix}/evidence.json"
    result_key = f"{prefix}/result.json"
    rejection = {
        "schema_version": "knowledge-compiler-synthesis-rejection/v1",
        "synthesis_attempt_id": attempt_id,
        "resolution_batch_id": request.resolution_batch_id,
        "stage": failure.stage,
        "reason_code": failure.code,
        "message": failure.message,
        "safe_context": failure.context,
        "canonical_write_permitted": False,
        "github_write_permitted": False,
        "production_write_permitted": False,
    }
    states = [put_immutable(store, rejection_key, json_bytes(rejection))]
    result = SynthesisProposalResult(
        proposal_batch_id=attempt_id,
        resolution_batch_id=request.resolution_batch_id,
        status="rejected",
        result_key=result_key,
        event_keys=(),
        rejection_key=rejection_key,
        failure_code=failure.code,
    )
    states.append(put_immutable(store, result_key, json_bytes(result.evidence())))
    result = replace(result, idempotent=all(states))
    _write_output(output_dir, "rejection.json", json_bytes(rejection))
    _write_output(output_dir, "synthesis-result.json", json_bytes(result.to_dict()))
    return result


def synthesize_resolution_batch(
    store: ObjectStore,
    request: SynthesisProposalRequest,
    output_dir: Path | None = None,
) -> SynthesisProposalResult:
    try:
        request.validate()
        resolved = _validate_resolution_batch(store, request.resolution_batch_id)
        proposals: list[dict[str, Any]] = []
        quarantine: list[dict[str, Any]] = []
        for resolution in resolved["resolutions"]:
            candidate = resolved["candidate_map"][resolution["candidate_id"]]
            outcome = resolution.get("outcome")
            eligible = resolution.get("synthesis_eligible") is True
            if outcome in ELIGIBLE_OUTCOMES and eligible:
                proposals.append(
                    _proposal_for(
                        request.resolution_batch_id,
                        resolved["source_snapshot_sha256"],
                        resolution,
                        candidate,
                        resolved["concept_map"],
                    )
                )
            else:
                quarantine.append(
                    {
                        "schema_version": "knowledge-compiler-synthesis-quarantine-item/v1",
                        "resolution_id": resolution["resolution_id"],
                        "candidate_id": resolution["candidate_id"],
                        "outcome": outcome,
                        "reason_codes": [
                            "OUTCOME_NOT_SYNTHESIS_ELIGIBLE"
                            if outcome not in ELIGIBLE_OUTCOMES
                            else "RESOLUTION_MARKED_INELIGIBLE"
                        ],
                        "evidence_refs": resolution["evidence_refs"],
                        "effective_audience": resolution["effective_audience"],
                        "canonical_write_permitted": False,
                    }
                )
        if len(proposals) > request.max_proposals:
            raise CompilerFailure(
                "SYNTHESIS_LIMIT_EXCEEDED", "synthesize", "proposal limit exceeded"
            )
        proposal_ids = [item["proposal_id"] for item in proposals]
        if len(proposal_ids) != len(set(proposal_ids)):
            raise CompilerFailure(
                "SYNTHESIS_PROPOSAL_DUPLICATE", "synthesize", "proposal identity duplicated"
            )

        identity = {
            "schema_version": "knowledge-compiler-synthesis-batch/v1",
            "request": request.identity(),
            "resolution_artifact_hashes": resolved["artifact_hashes"],
            "source_snapshot_sha256": resolved["source_snapshot_sha256"],
        }
        batch_id = "synp_" + sha256_bytes(canonical_json_bytes(identity))
        prefix = f"compiler/v1/proposals/{batch_id}"
        record_key = f"{prefix}/proposal-record.json"
        proposal_key = f"{prefix}/proposal-set.json"
        claim_map_key = f"{prefix}/claim-map.json"
        quarantine_key = f"{prefix}/quarantine.json"
        validation_key = f"{prefix}/validation-report.json"
        result_key = f"{prefix}/result.json"

        claim_map = {
            "schema_version": "knowledge-compiler-proposal-claim-map/v1",
            "proposal_batch_id": batch_id,
            "claims": [
                {
                    "proposal_id": item["proposal_id"],
                    "resolution_id": item["resolution_id"],
                    "candidate_id": item["candidate_id"],
                    "evidence_refs": item["evidence_refs"],
                    "source_snapshot_sha256": item["source_snapshot_sha256"],
                }
                for item in proposals
            ],
        }
        docs = {
            record_key: {
                **identity,
                "proposal_batch_id": batch_id,
                "status": "review_only_complete",
                "proposal_count": len(proposals),
                "quarantine_count": len(quarantine),
                "provider": "none",
                "canonical_write_permitted": False,
                "github_write_permitted": False,
                "production_write_permitted": False,
            },
            proposal_key: {
                "schema_version": "knowledge-compiler-synthesis-proposal-set/v1",
                "proposal_batch_id": batch_id,
                "resolution_batch_id": request.resolution_batch_id,
                "proposal_count": len(proposals),
                "proposals": proposals,
                "canonical_write_permitted": False,
            },
            claim_map_key: claim_map,
            quarantine_key: {
                "schema_version": "knowledge-compiler-synthesis-quarantine/v1",
                "proposal_batch_id": batch_id,
                "quarantine_count": len(quarantine),
                "items": quarantine,
                "canonical_write_permitted": False,
            },
            validation_key: {
                "schema_version": "knowledge-compiler-synthesis-validation/v1",
                "proposal_batch_id": batch_id,
                "resolution_batch_id": request.resolution_batch_id,
                "resolution_artifact_hashes": resolved["artifact_hashes"],
                "all_resolution_evidence_valid": True,
                "all_proposals_evidence_bound": True,
                "provider_invocations": 0,
                "audience_broadening_detected": False,
                "orphan_proposals_detected": False,
                "canonical_write_permitted": False,
                "github_write_permitted": False,
                "production_write_permitted": False,
            },
        }
        stages = [
            (None, "validated_resolution", list(resolved["keys"].values()), [validation_key]),
            (
                "validated_resolution",
                "proposals_planned",
                [validation_key],
                [proposal_key, quarantine_key],
            ),
            (
                "proposals_planned",
                "evidence_bound",
                [proposal_key],
                [claim_map_key],
            ),
            (
                "evidence_bound",
                "review_only_complete",
                [claim_map_key],
                [record_key, result_key],
            ),
        ]
        events = []
        previous = None
        for ordinal, (before, after, inputs, outputs) in enumerate(stages, 1):
            event = _event(
                batch_id,
                ordinal,
                request.proposed_at,
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
        result = SynthesisProposalResult(
            proposal_batch_id=batch_id,
            resolution_batch_id=request.resolution_batch_id,
            status="review_only_complete",
            result_key=result_key,
            event_keys=event_keys,
            proposal_count=len(proposals),
            quarantine_count=len(quarantine),
            proposal_prefix=prefix,
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
        _write_output(output_dir, "synthesis-result.json", json_bytes(result.to_dict()))
        return result
    except CompilerFailure as failure:
        return _reject(store, request, failure, output_dir)
