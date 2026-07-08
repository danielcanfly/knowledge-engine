from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .compiler_contract_v1 import CompilerFailure
from .compiler_resolution_contract_v1 import digest_object, load_json_object
from .compiler_source_v1 import AUDIENCE_RANK
from .compiler_v1 import verify_compiler_event
from .intake_v1 import canonical_json_bytes
from .storage import ObjectStore, sha256_bytes

CANDIDATE_TYPES = {
    "entity",
    "concept",
    "claim",
    "definition",
    "decision",
    "date",
    "relationship",
    "citation",
}


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _block_identity(block: Mapping[str, Any]) -> str:
    payload = {
        "compiler_run_id": block.get("compiler_run_id"),
        "ordinal": block.get("ordinal"),
        "kind": block.get("kind"),
        "level": block.get("level"),
        "text": block.get("text"),
        "source_map_ids": block.get("source_map_ids"),
        "effective_audience": block.get("effective_audience"),
        "canonical_write_permitted": block.get("canonical_write_permitted"),
    }
    return "block_" + sha256_bytes(canonical_json_bytes(payload))


def _map_identity(source_map: Mapping[str, Any]) -> str:
    payload = {
        "compiler_run_id": source_map.get("compiler_run_id"),
        "snapshot_id": source_map.get("snapshot_id"),
        "derivative_id": source_map.get("derivative_id"),
        "normalized_sha256": source_map.get("normalized_sha256"),
        "segments": source_map.get("segments"),
    }
    return "smap_" + sha256_bytes(canonical_json_bytes(payload))


def _candidate_identity(candidate: Mapping[str, Any]) -> str:
    payload = {
        "compiler_run_id": candidate.get("compiler_run_id"),
        "candidate_type": candidate.get("candidate_type"),
        "value": candidate.get("value"),
        "evidence_refs": candidate.get("evidence_refs"),
        "extraction_method": candidate.get("extraction_method"),
    }
    return "cand_" + sha256_bytes(canonical_json_bytes(payload))


def _validate_compiler_events(
    store: ObjectStore,
    prefix: str,
    event_keys: Any,
) -> None:
    if not isinstance(event_keys, list) or not event_keys:
        raise CompilerFailure(
            "RESOLUTION_EVENT_CHAIN_INVALID", "validate", "compiler event chain missing"
        )
    previous = None
    final_state = None
    for expected_ordinal, event_key in enumerate(event_keys, 1):
        if not isinstance(event_key, str) or not event_key.startswith(f"{prefix}/events/"):
            raise CompilerFailure(
                "RESOLUTION_EVENT_CHAIN_INVALID", "validate", "compiler event key invalid"
            )
        event = load_json_object(store, event_key, "compiler event")
        if not verify_compiler_event(event):
            raise CompilerFailure(
                "RESOLUTION_EVENT_CHAIN_INVALID", "validate", "compiler event hash invalid"
            )
        if event.get("ordinal") != expected_ordinal or event.get("previous_event_hash") != previous:
            raise CompilerFailure(
                "RESOLUTION_EVENT_CHAIN_INVALID", "validate", "compiler event chain not adjacent"
            )
        event_hash = event.get("event_sha256")
        if not isinstance(event_hash, str) or not event_key.endswith(f"-{event_hash}.json"):
            raise CompilerFailure(
                "RESOLUTION_EVENT_CHAIN_INVALID", "validate", "compiler event key mismatch"
            )
        previous = event_hash
        final_state = event.get("to_state")
    if final_state != "review_only_complete":
        raise CompilerFailure(
            "RESOLUTION_EVENT_CHAIN_INVALID", "validate", "compiler terminal state invalid"
        )


def _load_normalized(
    store: ObjectStore,
    compiler_input: dict[str, Any],
) -> tuple[str, str]:
    derivative_ref = compiler_input.get("derivative_ref")
    snapshot_ref = compiler_input.get("snapshot_ref")
    admission_ref = compiler_input.get("admission_ref")
    policy = compiler_input.get("effective_policy")
    if not all(isinstance(item, dict) for item in (derivative_ref, snapshot_ref, admission_ref, policy)):
        raise CompilerFailure(
            "RESOLUTION_COMPILER_INPUT_INVALID", "validate", "compiler input incomplete"
        )
    for ref, key_name, hash_name in (
        (snapshot_ref, "snapshot_key", "snapshot_sha256"),
        (derivative_ref, "derivative_key", "derivative_sha256"),
        (admission_ref, "result_key", "result_sha256"),
    ):
        key = ref.get(key_name)
        digest = ref.get(hash_name)
        if not isinstance(key, str) or not isinstance(digest, str):
            raise CompilerFailure(
                "RESOLUTION_COMPILER_INPUT_INVALID", "validate", "compiler reference invalid"
            )
        digest_object(store, key, digest)
    normalized_key = derivative_ref.get("normalized_key")
    normalized_sha256 = derivative_ref.get("normalized_sha256")
    if not isinstance(normalized_key, str) or not isinstance(normalized_sha256, str):
        raise CompilerFailure(
            "RESOLUTION_COMPILER_INPUT_INVALID", "validate", "normalized reference invalid"
        )
    try:
        normalized_bytes = store.get(normalized_key)
    except FileNotFoundError as exc:
        raise CompilerFailure(
            "RESOLUTION_OBJECT_MISSING", "validate", "normalized object missing"
        ) from exc
    if sha256_bytes(normalized_bytes) != normalized_sha256:
        raise CompilerFailure(
            "RESOLUTION_HASH_MISMATCH", "validate", "normalized object hash mismatch"
        )
    try:
        normalized_text = normalized_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CompilerFailure(
            "RESOLUTION_OBJECT_INVALID", "validate", "normalized object is not UTF-8"
        ) from exc
    input_audience = policy.get("audience")
    if input_audience not in AUDIENCE_RANK or policy.get("may_broaden") is not False:
        raise CompilerFailure(
            "RESOLUTION_POLICY_INVALID", "validate", "compiler policy invalid"
        )
    return normalized_text, str(input_audience)


def validate_compiler_run(
    store: ObjectStore,
    compiler_run_id: str,
    max_candidates: int,
) -> dict[str, Any]:
    prefix = f"compiler/v1/runs/{compiler_run_id}"
    keys = {
        "input": f"{prefix}/input.json",
        "blocks": f"{prefix}/structured/blocks.json",
        "maps": f"{prefix}/structured/source-map.json",
        "candidates": f"{prefix}/extraction/candidates.json",
        "result": f"{prefix}/result.json",
    }
    compiler_input = load_json_object(store, keys["input"], "compiler input")
    block_set = load_json_object(store, keys["blocks"], "block set")
    map_set = load_json_object(store, keys["maps"], "source-map set")
    candidate_set = load_json_object(store, keys["candidates"], "candidate set")
    result = load_json_object(store, keys["result"], "compiler result")

    for label, value in (
        ("input", compiler_input),
        ("blocks", block_set),
        ("maps", map_set),
        ("candidates", candidate_set),
    ):
        if value.get("compiler_run_id") != compiler_run_id:
            raise CompilerFailure(
                "RESOLUTION_IDENTITY_MISMATCH", "validate", f"{label} run identity mismatch"
            )
    if compiler_input.get("schema_version") != "knowledge-compiler-input/v1":
        raise CompilerFailure(
            "RESOLUTION_COMPILER_INPUT_INVALID", "validate", "compiler input schema invalid"
        )
    if block_set.get("schema_version") != "knowledge-compiler-structured-block-set/v1":
        raise CompilerFailure(
            "RESOLUTION_BLOCK_SET_INVALID", "validate", "block set schema invalid"
        )
    if map_set.get("schema_version") != "knowledge-compiler-source-map-set/v1":
        raise CompilerFailure(
            "RESOLUTION_SOURCE_MAP_SET_INVALID", "validate", "source-map set schema invalid"
        )
    if candidate_set.get("schema_version") != "knowledge-compiler-extraction-candidate-set/v1":
        raise CompilerFailure(
            "RESOLUTION_CANDIDATE_SET_INVALID", "validate", "candidate set schema invalid"
        )
    if result.get("compiler_run_id") != compiler_run_id or result.get("status") != "review_only_complete":
        raise CompilerFailure(
            "RESOLUTION_COMPILER_STATE_INVALID",
            "validate",
            "compiler result is not review-only complete",
        )
    if result.get("result_key") != keys["result"]:
        raise CompilerFailure(
            "RESOLUTION_IDENTITY_MISMATCH", "validate", "compiler result key mismatch"
        )
    if result.get("input_key") != keys["input"] or result.get("blocks_key") != keys["blocks"]:
        raise CompilerFailure(
            "RESOLUTION_IDENTITY_MISMATCH", "validate", "compiler artifact keys mismatch"
        )
    if result.get("source_map_key") != keys["maps"] or result.get("candidates_key") != keys["candidates"]:
        raise CompilerFailure(
            "RESOLUTION_IDENTITY_MISMATCH", "validate", "compiler artifact keys mismatch"
        )
    _validate_compiler_events(store, prefix, result.get("event_keys"))
    normalized_text, input_audience = _load_normalized(store, compiler_input)
    normalized_sha256 = compiler_input["derivative_ref"]["normalized_sha256"]

    blocks = block_set.get("blocks")
    maps = map_set.get("source_maps")
    candidates = candidate_set.get("candidates")
    if not isinstance(blocks, list) or block_set.get("block_count") != len(blocks):
        raise CompilerFailure(
            "RESOLUTION_BLOCK_SET_INVALID", "validate", "block set invalid"
        )
    if not isinstance(maps, list) or map_set.get("source_map_count") != len(maps):
        raise CompilerFailure(
            "RESOLUTION_SOURCE_MAP_SET_INVALID", "validate", "source-map set invalid"
        )
    if not isinstance(candidates, list) or candidate_set.get("candidate_count") != len(candidates):
        raise CompilerFailure(
            "RESOLUTION_CANDIDATE_SET_INVALID", "validate", "candidate set invalid"
        )
    if len(candidates) > max_candidates:
        raise CompilerFailure(
            "RESOLUTION_CANDIDATE_LIMIT_EXCEEDED", "validate", "candidate limit exceeded"
        )

    block_by_id: dict[str, dict[str, Any]] = {}
    for block in blocks:
        if not isinstance(block, dict) or block.get("schema_version") != "knowledge-compiler-structured-block/v1":
            raise CompilerFailure(
                "RESOLUTION_BLOCK_INVALID", "validate", "structured block invalid"
            )
        block_id = block.get("block_id")
        if block_id != _block_identity(block) or block_id in block_by_id:
            raise CompilerFailure(
                "RESOLUTION_BLOCK_INVALID", "validate", "structured block identity invalid"
            )
        if block.get("canonical_write_permitted") is not False:
            raise CompilerFailure(
                "RESOLUTION_WRITE_BOUNDARY_INVALID", "validate", "block write boundary invalid"
            )
        block_by_id[str(block_id)] = block
    for block in blocks:
        parent = block.get("parent_block_id")
        if parent is not None and parent not in block_by_id:
            raise CompilerFailure(
                "RESOLUTION_BLOCK_INVALID", "validate", "block parent missing"
            )

    map_by_id: dict[str, dict[str, Any]] = {}
    for source_map in maps:
        if not isinstance(source_map, dict) or source_map.get("schema_version") != "knowledge-compiler-source-map/v1":
            raise CompilerFailure(
                "RESOLUTION_SOURCE_MAP_INVALID", "validate", "source map invalid"
            )
        map_id = source_map.get("source_map_id")
        if map_id != _map_identity(source_map) or map_id in map_by_id:
            raise CompilerFailure(
                "RESOLUTION_SOURCE_MAP_INVALID", "validate", "source-map identity invalid"
            )
        if source_map.get("normalized_sha256") != normalized_sha256:
            raise CompilerFailure(
                "RESOLUTION_SOURCE_MAP_INVALID", "validate", "normalized hash drift"
            )
        segments = source_map.get("segments")
        if not isinstance(segments, list) or not segments:
            raise CompilerFailure(
                "RESOLUTION_SOURCE_MAP_INVALID", "validate", "source-map segments invalid"
            )
        for ordinal, segment in enumerate(segments):
            if not isinstance(segment, dict) or segment.get("segment_ordinal") != ordinal:
                raise CompilerFailure(
                    "RESOLUTION_SOURCE_MAP_INVALID", "validate", "source-map segment invalid"
                )
            start = segment.get("normalized_start_char")
            end = segment.get("normalized_end_char")
            if not isinstance(start, int) or not isinstance(end, int) or not 0 <= start < end <= len(normalized_text):
                raise CompilerFailure(
                    "RESOLUTION_SOURCE_MAP_INVALID", "validate", "source-map offsets invalid"
                )
            quote = normalized_text[start:end]
            if segment.get("quote") != quote or segment.get("quote_sha256") != sha256_bytes(quote.encode()):
                raise CompilerFailure(
                    "RESOLUTION_SOURCE_MAP_INVALID", "validate", "source-map quote invalid"
                )
            if segment.get("normalized_start_line") != _line_number(normalized_text, start):
                raise CompilerFailure(
                    "RESOLUTION_SOURCE_MAP_INVALID", "validate", "source-map start line invalid"
                )
            if segment.get("normalized_end_line") != _line_number(normalized_text, max(start, end - 1)):
                raise CompilerFailure(
                    "RESOLUTION_SOURCE_MAP_INVALID", "validate", "source-map end line invalid"
                )
        map_by_id[str(map_id)] = source_map

    for block in blocks:
        map_ids = block.get("source_map_ids")
        if not isinstance(map_ids, list) or not map_ids or any(item not in map_by_id for item in map_ids):
            raise CompilerFailure(
                "RESOLUTION_BLOCK_INVALID", "validate", "block source-map reference invalid"
            )

    validated_candidates = []
    seen_candidate_ids = set()
    for candidate in candidates:
        if not isinstance(candidate, dict) or candidate.get("schema_version") != "knowledge-compiler-extraction-candidate/v1":
            raise CompilerFailure(
                "RESOLUTION_CANDIDATE_INVALID", "validate", "candidate invalid"
            )
        if candidate.get("candidate_type") not in CANDIDATE_TYPES:
            raise CompilerFailure(
                "RESOLUTION_CANDIDATE_INVALID", "validate", "candidate type invalid"
            )
        if not isinstance(candidate.get("value"), str) or not candidate["value"].strip():
            raise CompilerFailure(
                "RESOLUTION_CANDIDATE_INVALID", "validate", "candidate value invalid"
            )
        candidate_id = candidate.get("candidate_id")
        if candidate_id != _candidate_identity(candidate) or candidate_id in seen_candidate_ids:
            raise CompilerFailure(
                "RESOLUTION_CANDIDATE_INVALID", "validate", "candidate identity invalid"
            )
        seen_candidate_ids.add(candidate_id)
        if candidate.get("compiler_run_id") != compiler_run_id:
            raise CompilerFailure(
                "RESOLUTION_CANDIDATE_INVALID", "validate", "candidate run mismatch"
            )
        candidate_audience = candidate.get("effective_audience")
        if candidate_audience not in AUDIENCE_RANK:
            raise CompilerFailure(
                "RESOLUTION_POLICY_INVALID", "validate", "candidate audience invalid"
            )
        if AUDIENCE_RANK[candidate_audience] < AUDIENCE_RANK[input_audience]:
            raise CompilerFailure(
                "RESOLUTION_POLICY_BROADENING", "validate", "candidate audience broadened"
            )
        if candidate.get("canonical_write_permitted") is not False:
            raise CompilerFailure(
                "RESOLUTION_WRITE_BOUNDARY_INVALID", "validate", "candidate write boundary invalid"
            )
        status = candidate.get("status")
        eligible = candidate.get("synthesis_eligible")
        if status not in {"candidate", "rejected_unsupported"}:
            raise CompilerFailure(
                "RESOLUTION_CANDIDATE_INVALID", "validate", "candidate status invalid"
            )
        if status == "rejected_unsupported" and eligible is not False:
            raise CompilerFailure(
                "RESOLUTION_CANDIDATE_INVALID", "validate", "unsupported candidate eligible"
            )
        evidence_refs = candidate.get("evidence_refs")
        if not isinstance(evidence_refs, list) or not evidence_refs:
            raise CompilerFailure(
                "RESOLUTION_CANDIDATE_INVALID", "validate", "candidate evidence missing"
            )
        for evidence in evidence_refs:
            if not isinstance(evidence, dict):
                raise CompilerFailure(
                    "RESOLUTION_CANDIDATE_INVALID", "validate", "candidate evidence invalid"
                )
            block_id = evidence.get("block_id")
            map_id = evidence.get("source_map_id")
            if block_id not in block_by_id or map_id not in map_by_id:
                raise CompilerFailure(
                    "RESOLUTION_CANDIDATE_INVALID", "validate", "candidate evidence target missing"
                )
            if map_id not in block_by_id[block_id].get("source_map_ids", []):
                raise CompilerFailure(
                    "RESOLUTION_CANDIDATE_INVALID", "validate", "candidate evidence link invalid"
                )
            quote_hashes = {
                segment["quote_sha256"] for segment in map_by_id[map_id]["segments"]
            }
            if evidence.get("quote_sha256") not in quote_hashes:
                raise CompilerFailure(
                    "RESOLUTION_CANDIDATE_INVALID", "validate", "candidate quote hash invalid"
                )
        validated_candidates.append(candidate)

    artifact_hashes = {name: digest_object(store, key) for name, key in keys.items()}
    artifact_hashes["normalized"] = normalized_sha256
    return {
        "compiler_input": compiler_input,
        "blocks": blocks,
        "source_maps": maps,
        "candidates": validated_candidates,
        "artifact_keys": keys,
        "artifact_hashes": artifact_hashes,
        "input_audience": input_audience,
    }
