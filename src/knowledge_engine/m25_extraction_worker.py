from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from .errors import IntegrityError
from .m21_extraction_candidates import build_candidate_packet
from .m25_extraction_common import (
    CANDIDATE_POLICY_SCHEMA,
    EXTRACTION_RECEIPT_SCHEMA,
    FOUNDATION_SHA,
    M25_2_ACCEPTED_STATUS,
    M25_3_ENGINE_BASE_SHA,
    MAX_CANDIDATES,
    MAX_CANDIDATES_PER_INPUT,
    MAX_EVIDENCE_SPANS,
    PROMPT_CONTRACT_SCHEMA,
    PROVIDER_REQUEST_SCHEMA,
    SOURCE_SHA,
    ExtractionProvider,
    _digest,
    _pretty_bytes,
    _put_immutable,
    _signed,
    _text,
)
from .m25_extraction_inputs import load_ready_extraction_inputs
from .m25_extraction_provider import execute_provider_route, validate_model_policy
from .storage import ObjectStore, sha256_bytes

SUPPORTED_KINDS = {
    "concept",
    "entity",
    "alias",
    "definition",
    "claim",
    "term",
    "duplicate_hint",
    "relation_hint",
}


def validate_prompt_contract(value: Mapping[str, Any]) -> dict[str, Any]:
    if value.get("schema_version") != PROMPT_CONTRACT_SCHEMA:
        raise IntegrityError("M25-EXTRACT-150 invalid prompt contract schema")
    _signed(value, "prompt_contract_sha256", "M25-EXTRACT-151 prompt digest mismatch")
    if (
        value.get("source_text_untrusted") is not True
        or value.get("ignore_embedded_instructions") is not True
        or value.get("secrets_must_not_be_returned") is not True
        or value.get("json_only_output") is not True
    ):
        raise IntegrityError("M25-EXTRACT-152 unsafe prompt contract")
    _text(value.get("prompt_id"), "prompt id", 160)
    _text(value.get("version"), "prompt version", 80)
    _text(value.get("system_template"), "system template", 12_000)
    _text(value.get("user_template"), "user template", 12_000)
    return dict(value)


def validate_candidate_policy(value: Mapping[str, Any]) -> dict[str, Any]:
    if value.get("schema_version") != CANDIDATE_POLICY_SCHEMA:
        raise IntegrityError("M25-EXTRACT-153 invalid candidate policy schema")
    _signed(value, "candidate_policy_sha256", "M25-EXTRACT-154 candidate policy digest mismatch")
    max_candidates = value.get("max_candidates")
    max_per_input = value.get("max_candidates_per_input")
    max_spans = value.get("max_evidence_spans_per_candidate")
    for observed, maximum, label in (
        (max_candidates, MAX_CANDIDATES, "candidate cap"),
        (max_per_input, MAX_CANDIDATES_PER_INPUT, "per-input candidate cap"),
        (max_spans, MAX_EVIDENCE_SPANS, "evidence span cap"),
    ):
        if (
            not isinstance(observed, int)
            or isinstance(observed, bool)
            or not 1 <= observed <= maximum
        ):
            raise IntegrityError(f"M25-EXTRACT-155 invalid {label}")
    kinds = value.get("supported_kinds")
    if not isinstance(kinds, list) or not kinds or len(kinds) != len(set(kinds)):
        raise IntegrityError("M25-EXTRACT-156 invalid supported candidate kinds")
    if any(kind not in SUPPORTED_KINDS for kind in kinds):
        raise IntegrityError("M25-EXTRACT-157 unsupported candidate kind policy")
    tags = value.get("allowed_tags")
    if not isinstance(tags, list) or len(tags) > 200 or len(tags) != len(set(tags)):
        raise IntegrityError("M25-EXTRACT-158 invalid allowed tags")
    if any(not isinstance(tag, str) or not tag or len(tag) > 80 for tag in tags):
        raise IntegrityError("M25-EXTRACT-158 invalid allowed tags")
    return dict(value)


def build_provider_request(
    input_manifest: Mapping[str, Any],
    prompt_contract: Mapping[str, Any],
    model_policy: Mapping[str, Any],
    candidate_policy: Mapping[str, Any],
) -> dict[str, Any]:
    prompt = validate_prompt_contract(prompt_contract)
    model = validate_model_policy(model_policy)
    candidate = validate_candidate_policy(candidate_policy)
    request = {
        "schema_version": PROVIDER_REQUEST_SCHEMA,
        "plan_id": input_manifest["plan_id"],
        "m25_2_acceptance_status": M25_2_ACCEPTED_STATUS,
        "engine_base_sha": M25_3_ENGINE_BASE_SHA,
        "source_sha": SOURCE_SHA,
        "foundation_sha": FOUNDATION_SHA,
        "input_manifest_sha256": input_manifest["input_manifest_sha256"],
        "input_count": input_manifest["input_count"],
        "inputs": input_manifest["inputs"],
        "prompt_ref": {
            "prompt_id": prompt["prompt_id"],
            "version": prompt["version"],
            "prompt_contract_sha256": prompt["prompt_contract_sha256"],
        },
        "model_policy_sha256": model["model_policy_sha256"],
        "candidate_policy_sha256": candidate["candidate_policy_sha256"],
        "provider_routes": model["routes"],
        "source_text_untrusted": True,
        "ignore_embedded_instructions": True,
        "live_provider_calls_permitted": False,
        "authority": "candidate_only",
        "canonical_knowledge": False,
        "production_authority": False,
        "review_required": True,
    }
    request["request_id"] = f"m25req_{_digest(request)}"
    request["request_sha256"] = _digest(request)
    return request


def _validate_proposals_against_policy(
    proposals: Sequence[Mapping[str, Any]],
    candidate_policy: Mapping[str, Any],
    known_derivatives: set[str],
) -> None:
    if len(proposals) > candidate_policy["max_candidates"]:
        raise IntegrityError("M25-EXTRACT-159 candidate cap exceeded")
    counts: Counter[str] = Counter()
    supported = set(candidate_policy["supported_kinds"])
    for proposal in proposals:
        if not isinstance(proposal, Mapping) or proposal.get("kind") not in supported:
            raise IntegrityError("M25-EXTRACT-160 unsupported candidate proposal")
        evidence = proposal.get("evidence")
        if not isinstance(evidence, list) or not 1 <= len(evidence) <= candidate_policy[
            "max_evidence_spans_per_candidate"
        ]:
            raise IntegrityError("M25-EXTRACT-161 evidence span cap exceeded")
        derivative_ids = {
            span.get("derivative_id")
            for span in evidence
            if isinstance(span, Mapping)
        }
        if not derivative_ids or not derivative_ids <= known_derivatives:
            raise IntegrityError("M25-EXTRACT-162 proposal evidence derivative mismatch")
        for derivative_id in derivative_ids:
            counts[str(derivative_id)] += 1
    if any(count > candidate_policy["max_candidates_per_input"] for count in counts.values()):
        raise IntegrityError("M25-EXTRACT-163 per-input candidate cap exceeded")


def prepare_extraction_request(
    store: ObjectStore,
    plan_id: str,
    *,
    prompt_contract: Mapping[str, Any],
    model_policy: Mapping[str, Any],
    candidate_policy: Mapping[str, Any],
) -> dict[str, Any]:
    loaded = load_ready_extraction_inputs(store, plan_id)
    prompt = validate_prompt_contract(prompt_contract)
    model = validate_model_policy(model_policy)
    candidate = validate_candidate_policy(candidate_policy)
    request = build_provider_request(loaded["input_manifest"], prompt, model, candidate)
    contract_payloads = {
        "prompt": _pretty_bytes(prompt),
        "model-policy": _pretty_bytes(model),
        "candidate-policy": _pretty_bytes(candidate),
        "input-manifest": _pretty_bytes(loaded["input_manifest"]),
    }
    contract_keys: dict[str, str] = {}
    for name, payload in contract_payloads.items():
        key = f"admission/v1/extraction/contracts/{name}/{sha256_bytes(payload)}.json"
        _put_immutable(store, key, payload)
        contract_keys[name] = key
    request_key = (
        f"admission/v1/extraction/{plan_id}/requests/{request['request_sha256']}.json"
    )
    _put_immutable(store, request_key, _pretty_bytes(request))
    return {
        **loaded,
        "prompt_contract": prompt,
        "model_policy": model,
        "candidate_policy": candidate,
        "request": request,
        "request_key": request_key,
        "contract_keys": contract_keys,
    }


def execute_extraction(
    store: ObjectStore,
    plan_id: str,
    *,
    prompt_contract: Mapping[str, Any],
    model_policy: Mapping[str, Any],
    candidate_policy: Mapping[str, Any],
    providers: Mapping[str, ExtractionProvider],
) -> dict[str, Any]:
    prepared = prepare_extraction_request(
        store,
        plan_id,
        prompt_contract=prompt_contract,
        model_policy=model_policy,
        candidate_policy=candidate_policy,
    )
    response, attempts = execute_provider_route(
        prepared["request"],
        prepared["inputs"],
        prepared["model_policy"],
        providers,
        max_candidates=prepared["candidate_policy"]["max_candidates"],
    )
    proposals = response["proposals"]
    known_derivatives = {value.derivative_id for value in prepared["inputs"]}
    _validate_proposals_against_policy(
        proposals,
        prepared["candidate_policy"],
        known_derivatives,
    )
    bundle = prepared["bundle"]
    candidate_packet = build_candidate_packet(
        bundle["m21_compatibility_plan"],
        bundle["checkpoint"]["m21_checkpoint"],
        prepared["derivatives"],
        proposals,
        allowed_tags=prepared["candidate_policy"]["allowed_tags"],
    )
    response_key = (
        f"admission/v1/extraction/{plan_id}/responses/{response['response_sha256']}.json"
    )
    packet_key = (
        f"admission/v1/extraction/{plan_id}/candidate-packets/"
        f"{candidate_packet['packet_sha256']}.json"
    )
    _put_immutable(store, response_key, _pretty_bytes(response))
    _put_immutable(store, packet_key, _pretty_bytes(candidate_packet))
    warning_count = sum(len(value.warnings) for value in prepared["inputs"])
    receipt = {
        "schema_version": EXTRACTION_RECEIPT_SCHEMA,
        "plan_id": plan_id,
        "request_sha256": prepared["request"]["request_sha256"],
        "response_sha256": response["response_sha256"],
        "candidate_packet_sha256": candidate_packet["packet_sha256"],
        "provider_id": response["provider_id"],
        "model_id": response["model_id"],
        "model_revision": response["model_revision"],
        "provider_attempts": attempts,
        "input_count": len(prepared["inputs"]),
        "candidate_count": candidate_packet["candidate_count"],
        "source_warning_count": warning_count,
        "replay_deterministic": True,
        "provider_variability_isolated": True,
        "live_provider_call_performed": False,
        "credentials_used": False,
        "raw_source_text_persisted_in_request_or_receipt": False,
        "authority": "candidate_only",
        "canonical_knowledge": False,
        "production_authority": False,
        "source_mutation_performed": False,
        "review_required": True,
        "artifact_keys": {
            "request": prepared["request_key"],
            "response": response_key,
            "candidate_packet": packet_key,
            "prompt_contract": prepared["contract_keys"]["prompt"],
            "model_policy": prepared["contract_keys"]["model-policy"],
            "candidate_policy": prepared["contract_keys"]["candidate-policy"],
            "input_manifest": prepared["contract_keys"]["input-manifest"],
        },
    }
    receipt["receipt_id"] = f"m25receipt_{_digest(receipt)}"
    receipt["receipt_sha256"] = _digest(receipt)
    receipt_key = (
        f"admission/v1/extraction/{plan_id}/receipts/{receipt['receipt_sha256']}.json"
    )
    _put_immutable(store, receipt_key, _pretty_bytes(receipt))
    return {
        "request": prepared["request"],
        "response": response,
        "candidate_packet": candidate_packet,
        "receipt": receipt,
        "receipt_key": receipt_key,
    }


__all__ = [
    "build_provider_request",
    "execute_extraction",
    "prepare_extraction_request",
    "validate_candidate_policy",
    "validate_prompt_contract",
]
