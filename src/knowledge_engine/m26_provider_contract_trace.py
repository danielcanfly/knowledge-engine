from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from contextvars import ContextVar
from typing import Any

TRACE_SCHEMA_VERSION = "m26-aq-sm-r3-provider-trace/v1"
FAST_SYNTHESIS_CONTRACT_ID = "m26-pa7-fast-cited-answer/v1"
FAST_SYNTHESIS_CALL_CLASS = "aq_fast_answer_synthesis"

_SECRET_KEY_RE = re.compile(
    r"(?:authorization|api[_-]?key|secret|password|cookie|credential|bearer|token)", re.I
)
_SAFE_KEY_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
_INTERNAL_FRAGMENT_MARKERS = (
    "definition head",
    "context modifier",
    "need relation",
    "semantic_closure",
    "support proof",
    "claim-by-claim",
    "exact quote",
    "visible coverage",
    "unanswered dimensions",
)

# Ephemeral only. The fingerprint is used to avoid attaching stale metadata when a
# response helper is invoked without the immediately preceding normalizer call.
_FAST_ATTEMPT_CONTEXT: ContextVar[tuple[str, dict[str, Any]] | None] = ContextVar(
    "m26_r3_fast_attempt_context", default=None
)


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, Mapping):
        return "mapping"
    if isinstance(value, list):
        return "list"
    if isinstance(value, str):
        return "string"
    if isinstance(value, bytes):
        return "bytes"
    if isinstance(value, int | float):
        return "number"
    return type(value).__name__


def _safe_key_sample(value: Any, *, limit: int = 24) -> list[str]:
    if not isinstance(value, Mapping):
        return []
    sampled: list[str] = []
    for key in sorted(str(item) for item in value):
        if len(sampled) >= limit:
            break
        if _SECRET_KEY_RE.search(key) or not _SAFE_KEY_RE.fullmatch(key):
            continue
        sampled.append(key)
    return sampled


def _value_shape(value: Any, *, depth: int = 0) -> dict[str, Any]:
    if depth >= 2:
        return {"type": _type_name(value)}
    if isinstance(value, Mapping):
        fields: dict[str, Any] = {}
        for key in _safe_key_sample(value, limit=16):
            child = value.get(key)
            item: dict[str, Any] = {"type": _type_name(child)}
            if isinstance(child, (str, bytes, list, Mapping)):
                item["length"] = len(child)
            if isinstance(child, Mapping):
                item["keys"] = _safe_key_sample(child, limit=8)
            fields[key] = item
        return {"type": "mapping", "key_count": len(value), "fields": fields}
    if isinstance(value, (str, bytes, list)):
        return {"type": _type_name(value), "length": len(value)}
    return {"type": _type_name(value)}


def _ephemeral_fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _fast_source_text(raw: Mapping[str, Any]) -> tuple[str, str, str]:
    """Mirror frozen _normalize_fast_provider_result source-field precedence exactly."""
    provider_text = raw.get("provider_text")
    text_value = raw.get("text", "")
    if provider_text not in (None, ""):
        return str(provider_text), "provider_text", _type_name(provider_text)
    source_field = "text" if "text" in raw else ""
    return str(text_value), source_field, _type_name(text_value)


def _parse_fast_mapping_shadow(text: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Observe the frozen fast parser without changing its accepted shapes.

    Candidate construction, constrained-wrapper recognition, json.loads behavior, and
    first-mapping-wins semantics intentionally mirror the frozen baseline implementation.
    """
    candidates = [text]
    stripped = text.strip()
    constrained_wrapper = False
    synthesized_opening_brace_candidate = False
    if (
        stripped.startswith("<|start|>assistant")
        and "<|channel|>final" in stripped
        and "<|constrain|>" in stripped
        and stripped.endswith("<|return|>")
    ):
        constrained_wrapper = True
        constrained = stripped.split("<|constrain|>", 1)[1].rsplit("<|return|>", 1)[0].strip()
        candidates.append(constrained)
        if constrained.endswith("}") and re.match(
            r'^[A-Za-z_][A-Za-z0-9_]*"\s*:', constrained
        ):
            synthesized_opening_brace_candidate = True
            candidates.append('{"' + constrained)
    parsed: dict[str, Any] = {}
    decoded_mapping_index: int | None = None
    for index, candidate in enumerate(candidates):
        try:
            decoded = json.loads(candidate)
        except Exception:
            continue
        if isinstance(decoded, Mapping):
            parsed = dict(decoded)
            decoded_mapping_index = index
            break
    summary = {
        "outcome": "valid" if decoded_mapping_index is not None else "invalid",
        "candidate_count": len(candidates),
        "decoded_mapping_candidate_index": decoded_mapping_index,
        "constrained_wrapper_detected": constrained_wrapper,
        "frozen_opening_brace_candidate_used": synthesized_opening_brace_candidate,
        "normalized_type": "mapping" if decoded_mapping_index is not None else "none",
        "normalized_keys": _safe_key_sample(parsed),
        "status": str(parsed.get("status", "")),
    }
    if decoded_mapping_index is None:
        summary["failure_code"] = (
            "FAST_PARSER_INPUT_EMPTY" if not text.strip() else "FAST_PARSER_JSON_MAPPING_NOT_FOUND"
        )
    return parsed, summary


def _fast_citation_ids(parsed: Mapping[str, Any]) -> tuple[list[str], str]:
    raw_ids = parsed.get("citation_ids")
    source_key = "citation_ids"
    if raw_ids is None:
        raw_ids = parsed.get("citations")
        source_key = "citations"
    citation_ids: list[str] = []
    if isinstance(raw_ids, list):
        for item in raw_ids:
            if isinstance(item, Mapping):
                citation_id = str(
                    item.get("evidence_id")
                    or item.get("citation_id")
                    or item.get("id")
                    or ""
                ).strip()
            else:
                citation_id = str(item).strip()
            if citation_id:
                citation_ids.append(citation_id)
    return list(dict.fromkeys(citation_ids)), source_key


def _diagnose_fast_validator(
    parsed: Mapping[str, Any], *, selected_evidence_ids: Sequence[str] = ()
) -> dict[str, Any]:
    """Classify the first frozen fast-validator rejection seam, read-only."""
    status = str(parsed.get("status", "")).strip().casefold()
    answer_text = re.sub(r"\s+", " ", str(parsed.get("answer_text") or "")).strip()
    citation_ids, citation_source_key = _fast_citation_ids(parsed)
    abstention_reason = str(parsed.get("abstention_reason") or "").strip()
    selected = {str(item) for item in selected_evidence_ids}

    summary: dict[str, Any] = {
        "outcome": "valid",
        "status": status,
        "answer_text_char_count": len(answer_text),
        "citation_source_key": citation_source_key,
        "citation_count": len(citation_ids),
        "abstention_reason_present": bool(abstention_reason),
        "failure_code": "",
    }
    if status == "abstain":
        if answer_text or citation_ids or not abstention_reason:
            summary.update(
                outcome="invalid",
                failure_code="FAST_VALIDATOR_ABSTAIN_SHAPE_INVALID",
            )
        else:
            summary["outcome"] = "valid_abstain"
        return summary
    if status != "answer":
        summary.update(outcome="invalid", failure_code="FAST_VALIDATOR_STATUS_INVALID")
        return summary
    if not answer_text:
        summary.update(outcome="invalid", failure_code="FAST_VALIDATOR_ANSWER_TEXT_EMPTY")
        return summary
    if any(marker in answer_text.casefold() for marker in _INTERNAL_FRAGMENT_MARKERS):
        summary.update(
            outcome="invalid",
            failure_code="FAST_VALIDATOR_INTERNAL_FRAGMENT_LEAK",
        )
        return summary
    if not citation_ids:
        summary.update(outcome="invalid", failure_code="FAST_VALIDATOR_CITATIONS_EMPTY")
        return summary
    if selected and any(citation_id not in selected for citation_id in citation_ids):
        summary.update(
            outcome="invalid",
            failure_code="FAST_VALIDATOR_CITATION_NOT_SELECTED",
        )
        return summary
    return summary


def diagnose_fast_provider_result(
    raw: Mapping[str, Any], *, selected_evidence_ids: Sequence[str] = ()
) -> dict[str, Any]:
    """Return only privacy-safe metadata; no provider/prompt/context text is returned."""
    text, source_field, source_value_type = _fast_source_text(raw)
    parsed, parser = _parse_fast_mapping_shadow(text)
    validator = (
        _diagnose_fast_validator(parsed, selected_evidence_ids=selected_evidence_ids)
        if parser["outcome"] == "valid"
        else {"outcome": "not_reached", "failure_code": ""}
    )
    return {
        "adapter": {
            "outcome": "ok",
            "input_type": _type_name(raw),
            "sampled_non_secret_keys": _safe_key_sample(raw),
            "shape": _value_shape(raw),
            "source_field": source_field,
            "source_value_type": source_value_type,
            "parser_input_char_count": len(text),
            "parser_input_persisted": False,
        },
        "parser": parser,
        "validator": validator,
        "provider_attempt": {
            "response_type": _type_name(raw),
            "sampled_non_secret_keys": _safe_key_sample(raw),
            "shape": _value_shape(raw),
            "stop_reason": str(raw.get("stop_reason") or raw.get("finish_reason") or ""),
            "truncation_detected": str(
                raw.get("stop_reason") or raw.get("finish_reason") or ""
            )
            == "max_tokens",
            "usage": _safe_usage(raw.get("usage")),
        },
        "_ephemeral_fingerprint": _ephemeral_fingerprint(text),
    }


def _safe_usage(value: Any) -> dict[str, int]:
    usage = value if isinstance(value, Mapping) else {}
    return {
        "input_tokens": _safe_int(usage.get("input_tokens")),
        "output_tokens": _safe_int(usage.get("output_tokens")),
        "total_tokens": _safe_int(usage.get("total_tokens")),
    }


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _selected_evidence_contract(selected_evidence: Sequence[Mapping[str, Any]]) -> tuple[str, str]:
    ids = [
        str(item.get("evidence_id", ""))
        for item in selected_evidence
        if item.get("evidence_id")
    ]
    manifest = [
        {
            "evidence_id": str(item.get("evidence_id", "")),
            "locator_id": str(item.get("locator_id", "")),
            "source_id": str(item.get("source_id", "")),
        }
        for item in selected_evidence
    ]
    return _canonical_sha256(ids), _canonical_sha256(manifest)


def _contract_hash() -> str:
    return _canonical_sha256(
        {
            "contract_id": FAST_SYNTHESIS_CONTRACT_ID,
            "call_class": FAST_SYNTHESIS_CALL_CLASS,
            "output_keys": ["status", "answer_text", "citation_ids", "abstention_reason"],
            "status_values": ["answer", "abstain"],
        }
    )


def _trace_failure(trace: Mapping[str, Any]) -> tuple[str, str]:
    for stage in ("adapter", "parser", "validator"):
        item = trace.get(stage)
        if isinstance(item, Mapping) and item.get("failure_code"):
            return stage, str(item["failure_code"])
    return "", ""


def _build_persistable_trace(
    diagnostic: Mapping[str, Any],
    *,
    provider_result: Mapping[str, Any],
    provider_identity: Mapping[str, Any],
    selected_evidence: Sequence[Mapping[str, Any]],
    response: Mapping[str, Any],
) -> dict[str, Any]:
    evidence_digest, context_manifest = _selected_evidence_contract(selected_evidence)
    selected_ids = [
        str(item.get("evidence_id", "")) for item in selected_evidence if item.get("evidence_id")
    ]
    parsed = (
        provider_result.get("parsed")
        if isinstance(provider_result.get("parsed"), Mapping)
        else {}
    )
    validator = _diagnose_fast_validator(parsed, selected_evidence_ids=selected_ids)
    trace = {
        "schema_version": TRACE_SCHEMA_VERSION,
        "attempt": 1,
        "contract": {
            "prompt_contract_sha256": _contract_hash(),
            "ordered_context_manifest_sha256": context_manifest,
            "selected_evidence_digest": evidence_digest,
        },
        "provider_attempt": {
            **dict(diagnostic.get("provider_attempt", {})),
            "provider": str(provider_identity.get("provider", "unknown")),
            "model": str(provider_identity.get("model", "unknown")),
            "call_class": str(provider_result.get("call_class") or FAST_SYNTHESIS_CALL_CLASS),
            "provider_text_char_count": _safe_int(provider_result.get("provider_text_char_count")),
        },
        "privacy": {
            "synthetic_fixture": False,
            "full_provider_response_persisted": False,
            "parser_input_persisted_in_trace": False,
            "prompt_text_persisted": False,
            "context_text_persisted": False,
        },
        "adapter": _without_private(diagnostic.get("adapter")),
        "parser": _without_private(diagnostic.get("parser")),
        "validator": validator,
    }
    failure_stage, precise_code = _trace_failure(trace)
    legacy_reasons = [str(item) for item in response.get("reason_codes", []) if str(item)]
    terminal_status = str(response.get("terminal_status") or response.get("status") or "")
    terminal_is_abstain = bool(response.get("safe_abstention", False)) or terminal_status in {
        "safe_abstention",
        "owner_only_safe_abstention",
    }
    trace["fallback"] = {
        "from_state": "S3_PROVIDER_PARSE_AND_VALIDATE",
        "to_state": "S7_SAFE_ABSTAIN" if terminal_is_abstain else "S4_MODEL_SUCCESS",
        "recovery_dimension": "none",
        "blind_retry_performed": False,
        "provider_attempt_count": 1,
        "selected_evidence_digest_match": True,
    }
    trace["terminal"] = {
        "semantic_status": terminal_status,
        "reason_code": legacy_reasons[0] if legacy_reasons else "",
        "legacy_reason_codes": legacy_reasons,
        "precise_reason_code": precise_code,
        "failure_stage": failure_stage,
        "clean_bounded_terminal": True,
    }
    return trace


def _without_private(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): item for key, item in value.items() if not str(key).startswith("_")}


def _attach_trace_to_response(
    response: Mapping[str, Any],
    *,
    provider_result: Mapping[str, Any] | None,
    provider_identity: Mapping[str, Any] | None,
    selected_evidence: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    result = dict(response)
    if not isinstance(provider_result, Mapping):
        return result
    text = str(provider_result.get("provider_text", ""))
    context = _FAST_ATTEMPT_CONTEXT.get()
    diagnostic: dict[str, Any]
    if context is not None and context[0] == _ephemeral_fingerprint(text):
        diagnostic = dict(context[1])
    else:
        # Fallback observes only the already-normalized frozen parser input. It does not
        # recognize any additional provider envelope or change runtime acceptance.
        diagnostic = diagnose_fast_provider_result(
            {"provider_text": text, "stop_reason": provider_result.get("stop_reason", "")}
        )
    _FAST_ATTEMPT_CONTEXT.set(None)
    trace = _build_persistable_trace(
        diagnostic,
        provider_result=provider_result,
        provider_identity=provider_identity or {},
        selected_evidence=selected_evidence,
        response=result,
    )
    verification = result.get("multi_evidence_verification")
    merged = dict(verification) if isinstance(verification, Mapping) else {}
    merged["provider_contract_trace"] = trace
    result["multi_evidence_verification"] = merged
    return result


def install_runtime_trace() -> None:
    """Install additive wrappers; frozen parser/validator/retry functions remain untouched."""
    from . import m26_pa7_arbitrary_query_runtime as legacy

    if getattr(legacy, "_m26_r3_provider_trace_installed", False):
        return

    original_normalize = legacy._normalize_fast_provider_result
    original_abstention = legacy._fast_abstention_response
    original_answer = legacy._fast_answer_response

    legacy._m26_r3_original_normalize_fast_provider_result = original_normalize
    legacy._m26_r3_original_fast_abstention_response = original_abstention
    legacy._m26_r3_original_fast_answer_response = original_answer

    def normalize_fast_provider_result(result: Mapping[str, Any]) -> dict[str, Any]:
        diagnostic = diagnose_fast_provider_result(result)
        normalized = original_normalize(result)
        text = str(normalized.get("provider_text", ""))
        _FAST_ATTEMPT_CONTEXT.set((_ephemeral_fingerprint(text), diagnostic))
        return normalized

    def fast_abstention_response(**kwargs: Any) -> dict[str, Any]:
        response = original_abstention(**kwargs)
        return _attach_trace_to_response(
            response,
            provider_result=kwargs.get("provider_result")
            if isinstance(kwargs.get("provider_result"), Mapping)
            else None,
            provider_identity=kwargs.get("provider_identity")
            if isinstance(kwargs.get("provider_identity"), Mapping)
            else None,
            selected_evidence=kwargs.get("selected_evidence")
            if isinstance(kwargs.get("selected_evidence"), Sequence)
            else (),
        )

    def fast_answer_response(**kwargs: Any) -> dict[str, Any]:
        response = original_answer(**kwargs)
        return _attach_trace_to_response(
            response,
            provider_result=kwargs.get("provider_result")
            if isinstance(kwargs.get("provider_result"), Mapping)
            else None,
            provider_identity=kwargs.get("provider_identity")
            if isinstance(kwargs.get("provider_identity"), Mapping)
            else None,
            selected_evidence=kwargs.get("selected_evidence")
            if isinstance(kwargs.get("selected_evidence"), Sequence)
            else (),
        )

    legacy._normalize_fast_provider_result = normalize_fast_provider_result
    legacy._fast_abstention_response = fast_abstention_response
    legacy._fast_answer_response = fast_answer_response
    legacy._m26_r3_provider_trace_installed = True
