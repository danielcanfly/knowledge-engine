from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from .compiler_contract_v1 import (
    COMPILER_VERSION,
    CompilerFailure,
    CompilerResult,
    LocalMarkdownCompilerRequest,
    admit,
    json_bytes,
    put_immutable,
    request_from_intake_result,
)
from .compiler_markdown_v1 import candidates, materialize, raw_blocks
from .intake_v1 import canonical_json_bytes
from .storage import ObjectStore, sha256_bytes

__all__ = [
    "CompilerFailure",
    "CompilerResult",
    "LocalMarkdownCompilerRequest",
    "compile_local_markdown",
    "request_from_intake_result",
    "verify_compiler_event",
]


def _event(
    run_id: str,
    ordinal: int,
    at: str,
    before: str | None,
    after: str,
    inputs: list[str],
    outputs: list[str],
    previous: str | None,
) -> dict[str, Any]:
    payload = {
        "schema_version": "knowledge-compiler-event/v1",
        "compiler_run_id": run_id,
        "ordinal": ordinal,
        "from_state": before,
        "to_state": after,
        "event_at": at,
        "input_artifact_refs": inputs,
        "output_artifact_refs": outputs,
        "previous_event_hash": previous,
        "mutations_performed": ["compiler_review_object_write"],
    }
    return {**payload, "event_sha256": sha256_bytes(canonical_json_bytes(payload))}


def verify_compiler_event(event: Mapping[str, Any]) -> bool:
    payload = dict(event)
    expected = payload.pop("event_sha256", None)
    return isinstance(expected, str) and expected == sha256_bytes(
        canonical_json_bytes(payload)
    )


def _write_output(root: Path | None, relative: str, data: bytes) -> None:
    if root is None:
        return
    path = root.resolve() / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _reject(
    store: ObjectStore,
    request: LocalMarkdownCompilerRequest,
    failure: CompilerFailure,
    output_dir: Path | None,
) -> CompilerResult:
    run_id = request.run_id()
    prefix = f"compiler/v1/runs/{run_id}"
    rejection_key = f"compiler/v1/rejections/{run_id}.json"
    result_key = f"{prefix}/result.json"
    rejection = {
        "schema_version": "knowledge-compiler-rejection/v1",
        "compiler_run_id": run_id,
        "stage": failure.stage,
        "reason_code": failure.code,
        "message": failure.message,
        "safe_context": failure.context,
        "canonical_write_permitted": False,
        "github_write_permitted": False,
        "production_write_permitted": False,
    }
    states = [put_immutable(store, rejection_key, json_bytes(rejection))]
    result = CompilerResult(
        run_id,
        "rejected",
        result_key,
        (),
        rejection_key=rejection_key,
        failure_code=failure.code,
    )
    states.append(put_immutable(store, result_key, json_bytes(result.evidence())))
    result = replace(result, idempotent=all(states))
    _write_output(output_dir, "rejection.json", json_bytes(rejection))
    _write_output(output_dir, "compiler-result.json", json_bytes(result.to_dict()))
    return result


def _input_document(
    run_id: str,
    request: LocalMarkdownCompilerRequest,
    snapshot: dict[str, Any],
    derivative: dict[str, Any],
    intake_result: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "knowledge-compiler-input/v1",
        "compiler_run_id": run_id,
        "snapshot_ref": {
            "source_id": snapshot["source_id"],
            "snapshot_id": snapshot["snapshot_id"],
            "snapshot_key": request.snapshot_key,
            "snapshot_sha256": request.snapshot_sha256,
            "content_hash": snapshot["content_hash"],
            "connector_type": snapshot["connector_type"],
            "connector_version": snapshot["connector_version"],
        },
        "derivative_ref": {
            "derivative_id": derivative["derivative_id"],
            "derivative_key": request.derivative_key,
            "derivative_sha256": request.derivative_sha256,
            "normalized_key": request.normalized_key,
            "normalized_sha256": request.normalized_sha256,
            "normalizer_id": derivative["normalizer_id"],
            "normalizer_version": derivative["normalizer_version"],
            "media_type": derivative["mime_type"],
        },
        "admission_ref": {
            "status": intake_result["status"],
            "result_key": request.result_key,
            "result_sha256": request.result_sha256,
        },
        "effective_policy": policy,
        "compiler_identity": {
            "contract_version": "knowledge-compiler/v1",
            "structurer_version": COMPILER_VERSION,
            "extractor_version": COMPILER_VERSION,
            "resolver_version": "disabled/1.0.0",
            "synthesizer_version": "disabled/1.0.0",
            "validator_version": COMPILER_VERSION,
        },
        "canonical_source_ref": None,
    }


def compile_local_markdown(
    store: ObjectStore,
    request: LocalMarkdownCompilerRequest,
    output_dir: Path | None = None,
) -> CompilerResult:
    run_id = request.run_id()
    prefix = f"compiler/v1/runs/{run_id}"
    try:
        request.validate()
        snapshot, derivative, intake_result, text, policy = admit(store, request)
        input_key = f"{prefix}/input.json"
        blocks_key = f"{prefix}/structured/blocks.json"
        map_key = f"{prefix}/structured/source-map.json"
        candidates_key = f"{prefix}/extraction/candidates.json"
        result_key = f"{prefix}/result.json"

        raw = raw_blocks(text, request.max_blocks)
        blocks, maps = materialize(
            run_id,
            text,
            raw,
            snapshot["snapshot_id"],
            derivative["derivative_id"],
            request.normalized_sha256,
            policy["audience"],
        )
        extracted = candidates(
            run_id,
            blocks,
            maps,
            policy["audience"],
            request.max_candidates,
        )
        input_doc = _input_document(
            run_id,
            request,
            snapshot,
            derivative,
            intake_result,
            policy,
        )
        docs = {
            input_key: input_doc,
            blocks_key: {
                "schema_version": "knowledge-compiler-structured-block-set/v1",
                "compiler_run_id": run_id,
                "block_count": len(blocks),
                "blocks": blocks,
            },
            map_key: {
                "schema_version": "knowledge-compiler-source-map-set/v1",
                "compiler_run_id": run_id,
                "source_map_count": len(maps),
                "source_maps": maps,
            },
            candidates_key: {
                "schema_version": "knowledge-compiler-extraction-candidate-set/v1",
                "compiler_run_id": run_id,
                "candidate_count": len(extracted),
                "candidates": extracted,
            },
        }
        at = snapshot.get("retrieved_at")
        if not isinstance(at, str) or not at.endswith("Z"):
            raise CompilerFailure(
                "INVALID_TIMESTAMP", "admit", "retrieval timestamp invalid"
            )
        stages = [
            (
                None,
                "admitted",
                [request.snapshot_key, request.derivative_key, request.result_key],
                [input_key],
            ),
            ("admitted", "structured", [input_key], [blocks_key, map_key]),
            ("structured", "extracted", [blocks_key, map_key], [candidates_key]),
            (
                "extracted",
                "review_only_complete",
                [candidates_key],
                [result_key],
            ),
        ]
        events = []
        previous = None
        for ordinal, (before, after, inputs, outputs) in enumerate(stages, 1):
            value = _event(
                run_id,
                ordinal,
                at,
                before,
                after,
                inputs,
                outputs,
                previous,
            )
            events.append(value)
            previous = value["event_sha256"]
        event_keys = tuple(
            f"{prefix}/events/{event['ordinal']:06d}-{event['event_sha256']}.json"
            for event in events
        )
        result = CompilerResult(
            run_id,
            "review_only_complete",
            result_key,
            event_keys,
            input_key=input_key,
            blocks_key=blocks_key,
            source_map_key=map_key,
            candidates_key=candidates_key,
            block_count=len(blocks),
            candidate_count=len(extracted),
        )
        states = [
            put_immutable(store, key, json_bytes(value))
            for key, value in docs.items()
        ]
        for key, event in zip(event_keys, events, strict=True):
            states.append(put_immutable(store, key, json_bytes(event)))
        states.append(put_immutable(store, result_key, json_bytes(result.evidence())))
        result = replace(result, idempotent=all(states))

        for key, value in docs.items():
            relative = key.removeprefix(prefix + "/")
            _write_output(output_dir, relative, json_bytes(value))
        _write_output(output_dir, "compiler-result.json", json_bytes(result.to_dict()))
        return result
    except CompilerFailure as failure:
        return _reject(store, request, failure, output_dir)
