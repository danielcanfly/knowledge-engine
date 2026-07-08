from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from .compiler_contract_v1 import CompilerFailure, json_bytes, put_immutable
from .compiler_evidence_v1 import validate_compiler_run
from .compiler_resolution_contract_v1 import (
    RESOLUTION_OUTCOMES,
    ResolutionBatchResult,
    SourceResolutionRequest,
)
from .compiler_source_v1 import (
    AUDIENCE_RANK,
    explicit_supersession,
    has_negation,
    jaccard,
    normalize_text,
    tokens,
    verify_source_checkout,
    without_negation,
)
from .intake_v1 import canonical_json_bytes
from .storage import ObjectStore, sha256_bytes


def _target_lookup(concepts: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    values: dict[str, list[dict[str, Any]]] = {}
    for concept in concepts:
        for value in [concept["concept_id"], concept["title"], *concept["aliases"]]:
            values.setdefault(normalize_text(value), []).append(concept)
    return values


def _match_observations(value: str, concepts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidate_tokens = tokens(value)
    observations = []
    for concept in concepts:
        score = jaccard(candidate_tokens, set(concept["tokens"]))
        observations.append(
            {
                "target_id": concept["concept_id"],
                "method": "token_jaccard",
                "score": round(score, 6),
                "observation_only": True,
            }
        )
    return sorted(observations, key=lambda item: (-item["score"], item["target_id"]))


def _resolve_candidate(
    compiler_run_id: str,
    candidate: dict[str, Any],
    concepts: list[dict[str, Any]],
    source_snapshot_sha256: str,
    input_audience: str,
    strong_match_threshold: float,
    contradiction_threshold: float,
) -> dict[str, Any]:
    candidate_id = candidate["candidate_id"]
    value = candidate["value"]
    candidate_type = candidate["candidate_type"]
    normalized = normalize_text(value)
    evidence_refs = [candidate_id, *(item["source_map_id"] for item in candidate["evidence_refs"])]
    observations = _match_observations(value, concepts)
    lookup = _target_lookup(concepts)
    target_ids: list[str] = []
    reason_codes: list[str] = []
    supersession_basis = None
    outcome = "unresolved_conflict"
    review_status = "pending_conflict_review"
    synthesis_eligible = False

    if (
        candidate.get("status") == "rejected_unsupported"
        or candidate.get("synthesis_eligible") is False
    ):
        outcome = "rejected_unsupported_claim"
        review_status = "rejected"
        reason_codes = ["UNSUPPORTED_CANDIDATE"]
    else:
        marker = explicit_supersession(value)
        if marker is not None:
            target_label, basis = marker
            targets = lookup.get(normalize_text(target_label), [])
            if len(targets) == 1 and basis:
                target = targets[0]
                target_ids = [target["concept_id"]]
                outcome = "supersession"
                review_status = "pending_conflict_review"
                synthesis_eligible = True
                reason_codes = ["EXPLICIT_SUPERSESSION_MARKER", "EXACT_SUPERSESSION_TARGET"]
                supersession_basis = {
                    "superseded_target_id": target["concept_id"],
                    "basis": basis,
                    "effective_at": None,
                    "evidence_refs": evidence_refs,
                }
            else:
                outcome = "unresolved_conflict"
                reason_codes = ["SUPERSESSION_TARGET_AMBIGUOUS"]
        elif candidate_type in {"date", "citation"}:
            outcome = "unresolved_conflict"
            reason_codes = ["NON_STANDALONE_CANDIDATE_REQUIRES_CONTEXT"]
        else:
            exact_alias = [
                concept for concept in concepts if normalized in concept["alias_normalized"]
            ]
            exact_title = [
                concept for concept in concepts if normalized == concept["title_normalized"]
            ]
            exact_represented = [
                concept
                for concept in concepts
                if normalized and normalized in concept["exact_values"]
            ]
            if candidate_type == "concept" and len(exact_alias) == 1:
                target_ids = [exact_alias[0]["concept_id"]]
                outcome = "alias"
                review_status = "pending_human_review"
                synthesis_eligible = True
                reason_codes = ["EXACT_ALIAS_IDENTITY"]
            elif candidate_type == "concept" and len(exact_title) == 1:
                target_ids = [exact_title[0]["concept_id"]]
                outcome = "existing_concept_update"
                review_status = "pending_human_review"
                synthesis_eligible = True
                reason_codes = ["EXACT_TITLE_IDENTITY", "NEW_EVIDENCE_REQUIRES_REVIEW"]
            elif len(exact_represented) == 1:
                target_ids = [exact_represented[0]["concept_id"]]
                outcome = "duplicate"
                review_status = "pending_human_review"
                synthesis_eligible = False
                reason_codes = ["EXACT_SOURCE_REPRESENTATION"]
            elif len(exact_represented) > 1:
                target_ids = sorted(concept["concept_id"] for concept in exact_represented)
                outcome = "unresolved_conflict"
                reason_codes = ["MULTIPLE_EXACT_SOURCE_REPRESENTATIONS"]
            else:
                conflict_targets = []
                candidate_tokens = without_negation(tokens(value))
                for concept in concepts:
                    for sentence in concept["sentences"]:
                        score = jaccard(candidate_tokens, without_negation(tokens(sentence)))
                        if score >= contradiction_threshold and has_negation(value) != has_negation(
                            sentence
                        ):
                            conflict_targets.append((concept, sentence, score))
                unique_conflicts = {item[0]["concept_id"]: item for item in conflict_targets}
                if len(unique_conflicts) == 1:
                    target = next(iter(unique_conflicts.values()))[0]
                    target_ids = [target["concept_id"]]
                    outcome = "contradiction"
                    review_status = "pending_conflict_review"
                    synthesis_eligible = False
                    reason_codes = ["EXPLICIT_POLARITY_CONFLICT", "STRONG_SUBJECT_OVERLAP"]
                elif len(unique_conflicts) > 1:
                    target_ids = sorted(unique_conflicts)
                    outcome = "unresolved_conflict"
                    reason_codes = ["MULTIPLE_CONTRADICTION_TARGETS"]
                else:
                    strong = [
                        item for item in observations if item["score"] >= strong_match_threshold
                    ]
                    if not strong:
                        outcome = "new_concept"
                        review_status = "pending_human_review"
                        synthesis_eligible = True
                        reason_codes = ["NO_VIABLE_SOURCE_TARGET"]
                    elif len(strong) == 1:
                        target_ids = [strong[0]["target_id"]]
                        outcome = "existing_concept_update"
                        review_status = "pending_human_review"
                        synthesis_eligible = True
                        reason_codes = ["ONE_STRONG_SOURCE_TARGET", "NEW_EVIDENCE_REQUIRES_REVIEW"]
                    else:
                        target_ids = sorted(item["target_id"] for item in strong)
                        outcome = "unresolved_conflict"
                        reason_codes = ["MULTIPLE_VIABLE_SOURCE_TARGETS"]

    target_audiences = {concept["concept_id"]: concept["audience"] for concept in concepts}
    effective_rank = AUDIENCE_RANK[candidate["effective_audience"]]
    for target_id in target_ids:
        effective_rank = max(effective_rank, AUDIENCE_RANK[target_audiences[target_id]])
    effective_audience = next(
        audience for audience, rank in AUDIENCE_RANK.items() if rank == effective_rank
    )
    if AUDIENCE_RANK[effective_audience] < AUDIENCE_RANK[input_audience]:
        raise CompilerFailure(
            "RESOLUTION_POLICY_BROADENING", "resolve", "resolution audience broadened"
        )

    identity = {
        "compiler_run_id": compiler_run_id,
        "candidate_id": candidate_id,
        "source_snapshot_sha256": source_snapshot_sha256,
        "outcome": outcome,
        "target_ids": target_ids,
        "reason_codes": reason_codes,
        "evidence_refs": evidence_refs,
        "effective_audience": effective_audience,
    }
    resolution_id = "cres_" + sha256_bytes(canonical_json_bytes(identity))
    result = {
        "schema_version": "knowledge-compiler-resolution/v1",
        "resolution_id": resolution_id,
        "compiler_run_id": compiler_run_id,
        "candidate_id": candidate_id,
        "outcome": outcome,
        "target_ids": target_ids,
        "evidence_refs": evidence_refs,
        "reason_codes": reason_codes,
        "match_observations": observations,
        "supersession_basis": supersession_basis,
        "effective_audience": effective_audience,
        "review_status": review_status,
        "synthesis_eligible": synthesis_eligible,
        "canonical_write_permitted": False,
    }
    if outcome not in RESOLUTION_OUTCOMES:
        raise CompilerFailure("RESOLUTION_OUTCOME_INVALID", "resolve", "resolver outcome invalid")
    return result


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
        "schema_version": "knowledge-compiler-resolution-event/v1",
        "resolution_batch_id": batch_id,
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


def verify_resolution_event(event: Mapping[str, Any]) -> bool:
    payload = dict(event)
    expected = payload.pop("event_sha256", None)
    return isinstance(expected, str) and expected == sha256_bytes(canonical_json_bytes(payload))


def _write_output(root: Path | None, relative: str, data: bytes) -> None:
    if root is None:
        return
    path = root.resolve() / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _reject(
    store: ObjectStore,
    request: SourceResolutionRequest,
    failure: CompilerFailure,
    output_dir: Path | None,
) -> ResolutionBatchResult:
    attempt_id = request.attempt_id()
    prefix = f"compiler/v1/resolution-rejections/{attempt_id}"
    rejection_key = f"{prefix}/evidence.json"
    result_key = f"{prefix}/result.json"
    rejection = {
        "schema_version": "knowledge-compiler-resolution-rejection/v1",
        "resolution_attempt_id": attempt_id,
        "compiler_run_id": request.compiler_run_id,
        "stage": failure.stage,
        "reason_code": failure.code,
        "message": failure.message,
        "safe_context": failure.context,
        "canonical_write_permitted": False,
        "github_write_permitted": False,
        "production_write_permitted": False,
    }
    states = [put_immutable(store, rejection_key, json_bytes(rejection))]
    result = ResolutionBatchResult(
        resolution_batch_id=attempt_id,
        compiler_run_id=request.compiler_run_id,
        status="rejected",
        result_key=result_key,
        event_keys=(),
        rejection_key=rejection_key,
        failure_code=failure.code,
    )
    states.append(put_immutable(store, result_key, json_bytes(result.evidence())))
    result = replace(result, idempotent=all(states))
    _write_output(output_dir, "rejection.json", json_bytes(rejection))
    _write_output(output_dir, "resolution-result.json", json_bytes(result.to_dict()))
    return result


def resolve_compiler_run(
    store: ObjectStore,
    request: SourceResolutionRequest,
    source_root: Path,
    output_dir: Path | None = None,
) -> ResolutionBatchResult:
    try:
        request.validate()
        compiler = validate_compiler_run(store, request.compiler_run_id, request.max_candidates)
        source_snapshot, concepts = verify_source_checkout(
            source_root,
            request.source_repository,
            request.source_commit_sha,
        )
        source_snapshot_sha256 = source_snapshot["source_snapshot_sha256"]
        batch_identity = {
            "schema_version": "knowledge-compiler-resolution-batch/v1",
            "request": request.identity(),
            "compiler_artifact_hashes": compiler["artifact_hashes"],
            "source_snapshot_sha256": source_snapshot_sha256,
        }
        batch_id = "rslv_" + sha256_bytes(canonical_json_bytes(batch_identity))
        prefix = f"compiler/v1/resolutions/{batch_id}"
        record_key = f"{prefix}/resolution-record.json"
        snapshot_key = f"{prefix}/source-snapshot.json"
        candidate_index_key = f"{prefix}/candidate-index.json"
        resolutions_key = f"{prefix}/resolutions.json"
        validation_key = f"{prefix}/validation-report.json"
        result_key = f"{prefix}/result.json"

        resolutions = [
            _resolve_candidate(
                request.compiler_run_id,
                candidate,
                concepts,
                source_snapshot_sha256,
                compiler["input_audience"],
                request.strong_match_threshold,
                request.contradiction_threshold,
            )
            for candidate in compiler["candidates"]
        ]
        outcome_counts = {outcome: 0 for outcome in sorted(RESOLUTION_OUTCOMES)}
        for resolution in resolutions:
            outcome_counts[resolution["outcome"]] += 1

        candidate_index = {
            "schema_version": "knowledge-compiler-source-candidate-index/v1",
            "resolution_batch_id": batch_id,
            "source_snapshot_sha256": source_snapshot_sha256,
            "concept_count": len(concepts),
            "concepts": [
                {
                    "concept_id": concept["concept_id"],
                    "path": concept["path"],
                    "title": concept["title"],
                    "aliases": concept["aliases"],
                    "audience": concept["audience"],
                }
                for concept in concepts
            ],
            "canonical_write_permitted": False,
        }
        validation_report = {
            "schema_version": "knowledge-compiler-resolution-validation/v1",
            "resolution_batch_id": batch_id,
            "compiler_run_id": request.compiler_run_id,
            "compiler_artifact_hashes": compiler["artifact_hashes"],
            "source_snapshot_sha256": source_snapshot_sha256,
            "candidate_count": len(compiler["candidates"]),
            "resolution_count": len(resolutions),
            "all_candidates_evidence_valid": True,
            "source_checkout_clean": True,
            "source_identity_exact": True,
            "audience_broadening_detected": False,
            "canonical_write_permitted": False,
            "github_write_permitted": False,
            "production_write_permitted": False,
        }
        record = {
            **batch_identity,
            "resolution_batch_id": batch_id,
            "resolver_version": request.resolver_version,
            "status": "review_only_complete",
            "resolution_count": len(resolutions),
            "outcome_counts": outcome_counts,
            "canonical_write_permitted": False,
            "github_write_permitted": False,
            "production_write_permitted": False,
        }
        docs = {
            record_key: record,
            snapshot_key: source_snapshot,
            candidate_index_key: candidate_index,
            resolutions_key: {
                "schema_version": "knowledge-compiler-resolution-set/v1",
                "resolution_batch_id": batch_id,
                "compiler_run_id": request.compiler_run_id,
                "resolution_count": len(resolutions),
                "resolutions": resolutions,
                "canonical_write_permitted": False,
            },
            validation_key: validation_report,
        }

        stages = [
            (
                None,
                "validated_input",
                list(compiler["artifact_keys"].values()),
                [validation_key],
            ),
            (
                "validated_input",
                "source_indexed",
                [validation_key],
                [snapshot_key, candidate_index_key],
            ),
            (
                "source_indexed",
                "resolved",
                [candidate_index_key],
                [resolutions_key],
            ),
            (
                "resolved",
                "review_only_complete",
                [resolutions_key],
                [record_key, result_key],
            ),
        ]
        events = []
        previous = None
        for ordinal, (before, after, inputs, outputs) in enumerate(stages, 1):
            event = _event(
                batch_id,
                ordinal,
                request.resolved_at,
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
        result = ResolutionBatchResult(
            resolution_batch_id=batch_id,
            compiler_run_id=request.compiler_run_id,
            status="review_only_complete",
            result_key=result_key,
            event_keys=event_keys,
            resolution_count=len(resolutions),
            outcome_counts=outcome_counts,
            source_snapshot_sha256=source_snapshot_sha256,
            resolution_prefix=prefix,
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
        _write_output(output_dir, "resolution-result.json", json_bytes(result.to_dict()))
        return result
    except CompilerFailure as failure:
        return _reject(store, request, failure, output_dir)
