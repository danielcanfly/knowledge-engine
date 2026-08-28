from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from .m26_google_translation_provider import (
    GoogleTranslationLLMProvider,
    TranslationProvider,
    TranslationProviderConfig,
    TranslationProviderError,
    TranslationProviderResult,
    TranslationRequest,
)
from .m26_retrieval_envelope import sha256_value
from .m26_translation_invariants import (
    bind_mixed_language_component_roles,
    detect_input_language,
    protect_spans,
    restore_protected_spans,
    validate_translation_invariants,
)

TRANSLATION_GATEWAY_SCHEMA = "m26-translation-in-gateway/v1"
TRANSLATION_GATEWAY_STATUS_READY = "IMPLEMENTATION_CANDIDATE_READY_FOR_MASTER_REAUDIT"
FAILURE_CODES = {
    "TRANSLATION_PROVIDER_FAILED",
    "TRANSLATION_TIMEOUT",
    "TRANSLATION_INVARIANT_FAILED",
    "TRANSLATION_OUTPUT_INVALID",
    "TRANSLATION_ROLE_BINDING_UNSAFE",
    "TRANSLATION_PROVIDER_CONFIG_MISSING",
}

DownstreamSealedM26 = Callable[[str], Mapping[str, Any]]


@dataclass(frozen=True)
class TranslationGatewayFailure:
    reason_code: str
    message: str
    observability: dict[str, Any]


class TranslationGatewayError(RuntimeError):
    def __init__(self, failure: TranslationGatewayFailure) -> None:
        super().__init__(failure.message)
        self.failure = failure
        self.reason_code = failure.reason_code


@dataclass(frozen=True)
class TranslationGatewayResult:
    ok: bool
    sealed_m26_response: Mapping[str, Any] | None
    translated_question_en: str
    observability: dict[str, Any]
    failure_code: str = ""
    failure_detail: str = ""


def run_translation_gateway(
    *,
    question: str,
    downstream: DownstreamSealedM26,
    provider: TranslationProvider | None = None,
    correlation_id: str = "",
    max_output_chars: int = 4_000,
) -> TranslationGatewayResult:
    started = time.monotonic()
    detected = detect_input_language(question)
    original_sha = sha256_value(question)
    observability: dict[str, Any] = {
        "schema_version": TRANSLATION_GATEWAY_SCHEMA,
        "detected_input_language": detected,
        "translation_applied": False,
        "provider": "",
        "model_resource": "",
        "region": "",
        "provider_latency_ms": 0,
        "protected_span_count": 0,
        "invariant_check_result": "not_applicable",
        "gateway_failure_code": "",
        "translated_query_sha256": "",
        "original_query_sha256": original_sha,
        "downstream_sealed_m26_request_correlation_id": correlation_id,
        "semantic_qualification_status": "external_heldout_required",
    }
    if detected == "en":
        sealed_response = downstream(question)
        translated_sha = sha256_value(question)
        observability.update(
            {
                "translation_applied": False,
                "translated_query_sha256": translated_sha,
                "invariant_check_result": "english_bypass",
                "gateway_latency_ms": _latency_ms(started),
            }
        )
        return TranslationGatewayResult(
            ok=True,
            sealed_m26_response=sealed_response,
            translated_question_en=question,
            observability=observability,
        )

    role_binding = bind_mixed_language_component_roles(question)
    if not role_binding.ok:
        return _closed_failure(
            "TRANSLATION_ROLE_BINDING_UNSAFE",
            role_binding.failure_detail or "mixed-language role binding was unsafe",
            observability,
            started,
        )
    protection = protect_spans(role_binding.rewritten_text)
    observability["protected_span_count"] = len(protection.spans)
    if provider is None:
        try:
            provider = GoogleTranslationLLMProvider(TranslationProviderConfig.from_env())
        except TranslationProviderError as exc:
            return _closed_failure(
                exc.reason_code,
                "translation provider is not configured",
                observability,
                started,
            )

    source_language = "zh-TW" if detected == "zh-TW" else ""
    provider_result = _provider_translate(
        provider,
        TranslationRequest(
            text=protection.protected_text,
            source_language=source_language,
            target_language="en",
            mime_type="text/plain",
        ),
    )
    observability.update(
        {
            "translation_applied": True,
            "provider": provider_result.provider,
            "model_resource": provider_result.model_resource,
            "region": provider_result.location,
            "provider_latency_ms": provider_result.latency_ms,
        }
    )
    if not provider_result.ok:
        return _closed_failure(
            provider_result.failure_code or "TRANSLATION_PROVIDER_FAILED",
            provider_result.failure_detail or "translation provider failed",
            observability,
            started,
        )

    restored = restore_protected_spans(provider_result.translated_text, protection)
    invariant = validate_translation_invariants(
        original_text=role_binding.rewritten_text,
        provider_text=provider_result.translated_text,
        restored_text=restored,
        protection=protection,
        provider_success=provider_result.ok,
        max_output_chars=max_output_chars,
    )
    observability["invariant_check_result"] = "pass" if invariant.ok else "failed"
    observability["invariant_checks"] = invariant.checks
    if not invariant.ok:
        return _closed_failure(
            invariant.failure_code,
            invariant.failure_detail,
            observability,
            started,
        )
    observability["translated_query_sha256"] = sha256_value(restored)
    observability["role_binding"] = {
        "applied": role_binding.applied,
        "bound_components": list(role_binding.bound_components),
    }
    sealed_response = downstream(restored)
    observability["gateway_latency_ms"] = _latency_ms(started)
    return TranslationGatewayResult(
        ok=True,
        sealed_m26_response=sealed_response,
        translated_question_en=restored,
        observability=observability,
    )


def run_owner_translation_gateway_for_web(
    *,
    root: Path,
    gate_path: Path,
    request_payload: Mapping[str, Any],
    owner_subject_hash: str,
    provider: TranslationProvider | None = None,
    public_request: bool = False,
    provider_client: Any = None,
    dense_channel: Any = None,
    require_remote_dense: bool = False,
    max_provider_calls: int | None = None,
    max_cost: Decimal | None = None,
    correlation_id: str = "",
    event_sink: Callable[[Mapping[str, Any]], None] | None = None,
) -> dict[str, Any]:
    from .m26_ask_api import run_owner_query_for_web, validate_query_request

    question = validate_query_request(request_payload)

    def downstream(translated_question: str) -> Mapping[str, Any]:
        kwargs: dict[str, Any] = {
            "root": root,
            "gate_path": gate_path,
            "request_payload": {"question": translated_question},
            "owner_subject_hash": owner_subject_hash,
            "public_request": public_request,
            "provider_client": provider_client,
            "dense_channel": dense_channel,
            "require_remote_dense": require_remote_dense,
            "event_sink": event_sink,
        }
        if max_provider_calls is not None:
            kwargs["max_provider_calls"] = max_provider_calls
        if max_cost is not None:
            kwargs["max_cost"] = max_cost
        return run_owner_query_for_web(**kwargs)

    result = run_translation_gateway(
        question=question,
        downstream=downstream,
        provider=provider,
        correlation_id=correlation_id,
    )
    if not result.ok:
        raise TranslationGatewayError(
            TranslationGatewayFailure(
                reason_code=result.failure_code,
                message=result.failure_detail,
                observability=result.observability,
            )
        )
    dto = dict(result.sealed_m26_response or {})
    dto["translation_gateway"] = result.observability
    return dto


def _provider_translate(
    provider: TranslationProvider,
    request: TranslationRequest,
) -> TranslationProviderResult:
    try:
        return provider.translate(request)
    except TranslationProviderError as exc:
        return TranslationProviderResult(
            ok=False,
            failure_code=exc.reason_code,
            failure_detail="translation provider configuration failed",
        )


def _closed_failure(
    code: str,
    detail: str,
    observability: dict[str, Any],
    started: float,
) -> TranslationGatewayResult:
    if code not in FAILURE_CODES:
        code = "TRANSLATION_INVARIANT_FAILED"
    updated = dict(observability)
    updated["gateway_failure_code"] = code
    updated["gateway_latency_ms"] = _latency_ms(started)
    return TranslationGatewayResult(
        ok=False,
        sealed_m26_response=None,
        translated_question_en="",
        observability=updated,
        failure_code=code,
        failure_detail=detail,
    )


def _latency_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
