from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx

from .m26_pa5_v8_live import LiveGateError, MiniMaxClient

CLOUDFLARE_PROVIDER = "cloudflare"
MINIMAX_PROVIDER = "minimax-m3"
CLOUDFLARE_MODEL = "@cf/openai/gpt-oss-120b"
MINIMAX_MODEL = "MiniMax-M3"
CLOUDFLARE_BASE_TEMPLATE = "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1"
SEMANTIC_REVIEW_CALL_CLASS = "aq_claim_semantic_entailment"

CLOUDFLARE_INPUT_NEURON_RATE = Decimal("31818") / Decimal("1000000")
CLOUDFLARE_OUTPUT_NEURON_RATE = Decimal("68182") / Decimal("1000000")
DEFAULT_CLOUDFLARE_NEURON_SOFT_LIMIT = Decimal("8500")
DEFAULT_TRANSIENT_COOLDOWN_SECONDS = 60

STATE_AVAILABLE = "AVAILABLE"
STATE_SOFT_EXHAUSTED_UNTIL_RESET = "SOFT_EXHAUSTED_UNTIL_RESET"
STATE_HARD_EXHAUSTED_UNTIL_RESET = "HARD_EXHAUSTED_UNTIL_RESET"
STATE_TEMP_COOLDOWN = "TEMP_COOLDOWN"
STATE_DISABLED_CONFIGURATION = "DISABLED_CONFIGURATION"

FALLBACK_NONE = "NONE"
FALLBACK_SOFT_EXHAUSTED = "SOFT_EXHAUSTED_UNTIL_RESET"
FALLBACK_HARD_EXHAUSTED = "HARD_EXHAUSTED_UNTIL_RESET"
FALLBACK_TEMP_COOLDOWN = "TEMP_COOLDOWN"
FALLBACK_DISABLED_CONFIGURATION = "DISABLED_CONFIGURATION"
FALLBACK_CLOUDFLARE_DAILY_QUOTA = "CLOUDFLARE_DAILY_QUOTA_3036"
FALLBACK_CLOUDFLARE_TRANSIENT = "CLOUDFLARE_TRANSIENT_OR_CAPACITY"
FALLBACK_CLOUDFLARE_CONFIGURATION = "CLOUDFLARE_CONFIGURATION_DISABLED"
MINIMAX_REVIEWER_RATE_LIMIT_429 = "MINIMAX_REVIEWER_RATE_LIMIT_429"
MINIMAX_REVIEWER_HTTP_5XX = "MINIMAX_REVIEWER_HTTP_5XX"
MINIMAX_REVIEWER_RETRY_EXHAUSTION = "MINIMAX_REVIEWER_RETRY_EXHAUSTION"
_REVIEWER_HTTP_5XX_RE = re.compile(r"^provider HTTP ([5-9]\d\d)$")


class CloudflareFallbackRequired(RuntimeError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def classify_semantic_reviewer_failure(error: LiveGateError) -> str | None:
    message = str(error).strip()
    if message == "provider HTTP 429":
        return MINIMAX_REVIEWER_RATE_LIMIT_429
    if message == "provider retry exhaustion":
        return MINIMAX_REVIEWER_RETRY_EXHAUSTION
    match = _REVIEWER_HTTP_5XX_RE.fullmatch(message)
    if match and 500 <= int(match.group(1)) <= 599:
        return MINIMAX_REVIEWER_HTTP_5XX
    return None


def next_utc_midnight(now: datetime | None = None) -> datetime:
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    current = current.astimezone(UTC)
    tomorrow = current.date() + timedelta(days=1)
    return datetime.combine(tomorrow, datetime.min.time(), tzinfo=UTC)


def cloudflare_gpt_oss_120b_neurons(input_tokens: int, output_tokens: int) -> Decimal:
    return (
        Decimal(max(0, input_tokens)) * CLOUDFLARE_INPUT_NEURON_RATE
        + Decimal(max(0, output_tokens)) * CLOUDFLARE_OUTPUT_NEURON_RATE
    )


def _decimal_from_env(name: str, default: Decimal) -> Decimal:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = Decimal(raw)
    except Exception:
        return default
    return value if value > 0 else default


def _int_from_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if isinstance(value, bool):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


@dataclass
class CloudflareRouterState:
    soft_limit: Decimal = DEFAULT_CLOUDFLARE_NEURON_SOFT_LIMIT
    cooldown_seconds: int = DEFAULT_TRANSIENT_COOLDOWN_SECONDS
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    state: str = STATE_AVAILABLE
    estimated_neurons_today: Decimal = Decimal("0")
    reset_at: datetime = field(default_factory=next_utc_midnight)
    cooldown_until: datetime | None = None
    last_infra_error_class: str = ""
    state_scope: str = "process_local_estimate_authoritative_provider_errors"
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def eligible_state(self) -> str:
        with self._lock:
            self._lazy_reset_locked()
            return self.state

    def route_before_call(self) -> tuple[str, str]:
        with self._lock:
            self._lazy_reset_locked()
            if self.state == STATE_AVAILABLE:
                return CLOUDFLARE_PROVIDER, FALLBACK_NONE
            if self.state == STATE_SOFT_EXHAUSTED_UNTIL_RESET:
                return MINIMAX_PROVIDER, FALLBACK_SOFT_EXHAUSTED
            if self.state == STATE_HARD_EXHAUSTED_UNTIL_RESET:
                return MINIMAX_PROVIDER, FALLBACK_HARD_EXHAUSTED
            if self.state == STATE_TEMP_COOLDOWN:
                return MINIMAX_PROVIDER, FALLBACK_TEMP_COOLDOWN
            return MINIMAX_PROVIDER, FALLBACK_DISABLED_CONFIGURATION

    def record_cloudflare_usage(self, input_tokens: int, output_tokens: int) -> Decimal:
        neurons = cloudflare_gpt_oss_120b_neurons(input_tokens, output_tokens)
        with self._lock:
            self._lazy_reset_locked()
            self.estimated_neurons_today += neurons
            if (
                self.state == STATE_AVAILABLE
                and self.estimated_neurons_today >= self.soft_limit
            ):
                self.state = STATE_SOFT_EXHAUSTED_UNTIL_RESET
                self.reset_at = next_utc_midnight(self.clock())
            return neurons

    def record_daily_quota_exhausted(self, error_class: str) -> None:
        with self._lock:
            self.last_infra_error_class = error_class
            self.state = STATE_HARD_EXHAUSTED_UNTIL_RESET
            self.reset_at = next_utc_midnight(self.clock())

    def record_transient(self, error_class: str) -> None:
        with self._lock:
            now = self._now()
            self.last_infra_error_class = error_class
            self.state = STATE_TEMP_COOLDOWN
            self.cooldown_until = now + timedelta(seconds=self.cooldown_seconds)

    def record_disabled_configuration(self, error_class: str) -> None:
        with self._lock:
            self.last_infra_error_class = error_class
            self.state = STATE_DISABLED_CONFIGURATION

    def force_state(
        self,
        state: str,
        *,
        reset_at: datetime | None = None,
        cooldown_until: datetime | None = None,
    ) -> None:
        with self._lock:
            self.state = state
            self.reset_at = reset_at or self.reset_at
            self.cooldown_until = cooldown_until

    def reset_for_tests(self) -> None:
        with self._lock:
            self.state = STATE_AVAILABLE
            self.estimated_neurons_today = Decimal("0")
            self.reset_at = next_utc_midnight(self.clock())
            self.cooldown_until = None
            self.last_infra_error_class = ""

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            self._lazy_reset_locked()
            return {
                "closure_primary": CLOUDFLARE_PROVIDER,
                "closure_primary_model": CLOUDFLARE_MODEL,
                "closure_fallback": MINIMAX_PROVIDER,
                "closure_fallback_model": MINIMAX_MODEL,
                "semantic_reviewer": MINIMAX_PROVIDER,
                "semantic_reviewer_model": MINIMAX_MODEL,
                "semantic_reviewer_primary": MINIMAX_PROVIDER,
                "semantic_reviewer_primary_model": MINIMAX_MODEL,
                "semantic_reviewer_availability_fallback": CLOUDFLARE_PROVIDER,
                "semantic_reviewer_availability_fallback_model": CLOUDFLARE_MODEL,
                "active_route": (
                    CLOUDFLARE_PROVIDER if self.state == STATE_AVAILABLE else MINIMAX_PROVIDER
                ),
                "cloudflare_state": self.state,
                "cloudflare_estimated_neurons_today": format(
                    self.estimated_neurons_today.quantize(Decimal("0.001")), "f"
                ),
                "cloudflare_soft_limit": format(self.soft_limit, "f"),
                "cloudflare_reset_at": self.reset_at.isoformat().replace("+00:00", "Z"),
                "cloudflare_cooldown_until": (
                    self.cooldown_until.isoformat().replace("+00:00", "Z")
                    if self.cooldown_until
                    else ""
                ),
                "cloudflare_last_infra_error_class": self.last_infra_error_class,
                "state_scope": self.state_scope,
                "live_model_request": False,
            }

    def _now(self) -> datetime:
        now = self.clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        return now.astimezone(UTC)

    def _lazy_reset_locked(self) -> None:
        now = self._now()
        if self.state in {
            STATE_SOFT_EXHAUSTED_UNTIL_RESET,
            STATE_HARD_EXHAUSTED_UNTIL_RESET,
        } and now >= self.reset_at:
            self.state = STATE_AVAILABLE
            self.estimated_neurons_today = Decimal("0")
            self.reset_at = next_utc_midnight(now)
            self.last_infra_error_class = ""
        if self.state == STATE_TEMP_COOLDOWN and self.cooldown_until and now >= self.cooldown_until:
            self.state = STATE_AVAILABLE
            self.cooldown_until = None


class CloudflareWorkersAIClient:
    def __init__(
        self,
        *,
        api_key: str,
        account_id: str,
        state: CloudflareRouterState,
        max_calls: int,
        timeout: float = 120.0,
    ) -> None:
        if not api_key or not account_id:
            state.record_disabled_configuration("CLOUDFLARE_CONFIGURATION_MISSING")
            raise LiveGateError("CLOUDFLARE_CONFIGURATION_MISSING")
        self.api_key = api_key
        self.account_id = account_id
        self.state = state
        self.max_calls = max_calls
        self.calls = 0
        self.cost = Decimal("0")
        self.client = httpx.Client(timeout=timeout)

    @property
    def endpoint(self) -> str:
        return CLOUDFLARE_BASE_TEMPLATE.format(account_id=self.account_id).rstrip(
            "/"
        ) + "/chat/completions"

    def call(self, payload: Mapping[str, Any], call_class: str) -> dict[str, Any]:
        if self.calls >= self.max_calls:
            raise LiveGateError("provider-call budget exhausted")
        self.calls += 1
        started = time.monotonic()
        try:
            response = self.client.post(
                self.endpoint,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=self._openai_payload(payload),
            )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise CloudflareFallbackRequired(type(exc).__name__) from exc
        if response.status_code >= 400:
            error_class = classify_cloudflare_http_error(response)
            raise CloudflareFallbackRequired(error_class)
        try:
            body = response.json()
        except ValueError as exc:
            raise CloudflareFallbackRequired("CLOUDFLARE_NON_JSON_RESPONSE") from exc
        choices = body.get("choices")
        first = choices[0] if isinstance(choices, list) and choices else {}
        message = _mapping(_mapping(first).get("message"))
        text = str(message.get("content", ""))
        usage = _usage(body)
        neurons = self.state.record_cloudflare_usage(
            usage["input_tokens"], usage["output_tokens"]
        )
        return {
            "text": text,
            "usage": usage,
            "cost_usd": "0",
            "latency_ms": int((time.monotonic() - started) * 1000),
            "response_id": str(body.get("id", "")),
            "call_class": call_class,
            "network_attempt": 1,
            "stop_reason": str(_mapping(first).get("finish_reason", "")),
            "content_block_types": ["text"] if text else [],
            "output_char_count": len(text),
            "closure_provider": CLOUDFLARE_PROVIDER,
            "closure_model": CLOUDFLARE_MODEL,
            "cloudflare_estimated_neurons": format(neurons.quantize(Decimal("0.001")), "f"),
        }

    def _openai_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "model": CLOUDFLARE_MODEL,
            "messages": [
                {
                    "role": str(message.get("role", "user")),
                    "content": message.get("content", ""),
                }
                for message in _messages(payload)
            ],
            "max_tokens": _safe_int(payload.get("max_tokens"), 2048),
            "temperature": payload.get("temperature", 0),
            "stream": False,
            "reasoning_effort": "low",
        }


class ProviderRoutingClient:
    def __init__(
        self,
        *,
        cloudflare: CloudflareWorkersAIClient | None,
        fallback: MiniMaxClient,
        reviewer: MiniMaxClient,
        state: CloudflareRouterState,
    ) -> None:
        self.cloudflare = cloudflare
        self.fallback = fallback
        self.reviewer = reviewer
        self.state = state
        self.calls = 0
        self.cost = Decimal("0")
        self.closure_provider_initial = CLOUDFLARE_PROVIDER
        self.closure_provider_final = ""
        self.fallback_used = False
        self.fallback_reason = FALLBACK_NONE
        self.semantic_reviewer_primary = MINIMAX_PROVIDER
        self.semantic_reviewer_primary_model = MINIMAX_MODEL
        self.semantic_reviewer_availability_fallback = CLOUDFLARE_PROVIDER
        self.semantic_reviewer_availability_fallback_model = CLOUDFLARE_MODEL
        self.semantic_reviewer_final = ""
        self.semantic_reviewer_final_model = ""
        self.semantic_reviewer_fallback_used = False
        self.semantic_reviewer_fallback_reason = FALLBACK_NONE
        self.semantic_reviewer_fallback_blocked_reason = ""
        self.attempts: list[dict[str, Any]] = []
        self.failed_cloudflare_selected_evidence_digest = ""
        self.fallback_selected_evidence_digest = ""
        self.reviewer_provider_diversity: bool | None = None

    def call(self, payload: Mapping[str, Any], call_class: str) -> dict[str, Any]:
        if call_class == SEMANTIC_REVIEW_CALL_CLASS:
            return self._call_semantic_reviewer(payload, call_class)

        route, reason = self.state.route_before_call()
        if route == MINIMAX_PROVIDER:
            self.fallback_used = True
            self.fallback_reason = reason
            self.closure_provider_final = MINIMAX_PROVIDER
            self.fallback_selected_evidence_digest = _selected_evidence_digest(payload)
            result = self.fallback.call(payload, call_class)
            self._record_attempt(call_class, MINIMAX_PROVIDER, MINIMAX_MODEL, result)
            return result

        if self.cloudflare is None:
            self.fallback_used = True
            self.fallback_reason = FALLBACK_DISABLED_CONFIGURATION
            self.closure_provider_final = MINIMAX_PROVIDER
            result = self.fallback.call(payload, call_class)
            self._record_attempt(call_class, MINIMAX_PROVIDER, MINIMAX_MODEL, result)
            return result

        try:
            result = self.cloudflare.call(payload, call_class)
        except CloudflareFallbackRequired as exc:
            self.failed_cloudflare_selected_evidence_digest = _selected_evidence_digest(payload)
            self._record_cloudflare_failure(exc.reason)
            raise
        self.closure_provider_final = CLOUDFLARE_PROVIDER
        self._record_attempt(call_class, CLOUDFLARE_PROVIDER, CLOUDFLARE_MODEL, result)
        return result

    def telemetry(self) -> dict[str, Any]:
        snapshot = self.state.snapshot()
        return {
            "closure_provider_initial": self.closure_provider_initial,
            "closure_provider_final": self.closure_provider_final or CLOUDFLARE_PROVIDER,
            "fallback_used": self.fallback_used,
            "fallback_reason": self.fallback_reason,
            "cloudflare_router_state": snapshot["cloudflare_state"],
            "cloudflare_estimated_neurons_today": snapshot[
                "cloudflare_estimated_neurons_today"
            ],
            "cloudflare_soft_limit": snapshot["cloudflare_soft_limit"],
            "cloudflare_reset_at": snapshot["cloudflare_reset_at"],
            "cloudflare_last_infra_error_class": snapshot[
                "cloudflare_last_infra_error_class"
            ],
            "semantic_reviewer_primary": self.semantic_reviewer_primary,
            "semantic_reviewer_primary_model": self.semantic_reviewer_primary_model,
            "semantic_reviewer_availability_fallback": (
                self.semantic_reviewer_availability_fallback
            ),
            "semantic_reviewer_availability_fallback_model": (
                self.semantic_reviewer_availability_fallback_model
            ),
            "semantic_reviewer_final": self.semantic_reviewer_final,
            "semantic_reviewer_final_model": self.semantic_reviewer_final_model,
            "semantic_reviewer_fallback_used": self.semantic_reviewer_fallback_used,
            "semantic_reviewer_fallback_reason": self.semantic_reviewer_fallback_reason,
            "semantic_reviewer_fallback_blocked_reason": (
                self.semantic_reviewer_fallback_blocked_reason
            ),
            "reviewer_provider_diversity": self._reviewer_provider_diversity(),
            "provider_attempts": list(self.attempts),
            "failed_cloudflare_selected_evidence_digest": (
                self.failed_cloudflare_selected_evidence_digest
            ),
            "fallback_selected_evidence_digest": self.fallback_selected_evidence_digest,
            "fallback_evidence_digest_match": (
                bool(self.failed_cloudflare_selected_evidence_digest)
                and self.failed_cloudflare_selected_evidence_digest
                == self.fallback_selected_evidence_digest
            )
            if self.fallback_used
            else None,
            "state_scope": snapshot["state_scope"],
        }

    def _reviewer_provider_diversity(self) -> bool | None:
        if not self.semantic_reviewer_final or not self.closure_provider_final:
            return None
        return self.semantic_reviewer_final != self.closure_provider_final

    def _call_semantic_reviewer(
        self, payload: Mapping[str, Any], call_class: str
    ) -> dict[str, Any]:
        started = time.monotonic()
        try:
            result = self.reviewer.call(payload, call_class)
        except LiveGateError as exc:
            reviewer_fallback_reason = classify_semantic_reviewer_failure(exc)
            self.semantic_reviewer_final = ""
            self.semantic_reviewer_final_model = ""
            self.semantic_reviewer_fallback_used = False
            self.semantic_reviewer_fallback_reason = FALLBACK_NONE
            self.semantic_reviewer_fallback_blocked_reason = ""
            if reviewer_fallback_reason is None:
                self._record_reviewer_attempt_failure(
                    call_class,
                    MINIMAX_PROVIDER,
                    MINIMAX_MODEL,
                    error_class=str(exc),
                    result="failed",
                    latency_ms=int((time.monotonic() - started) * 1000),
                )
                self.reviewer_provider_diversity = None
                raise

            self._record_reviewer_attempt_failure(
                call_class,
                MINIMAX_PROVIDER,
                MINIMAX_MODEL,
                error_class=str(exc),
                fallback_reason=reviewer_fallback_reason,
                result="fallback_required",
                latency_ms=int((time.monotonic() - started) * 1000),
            )
            self.semantic_reviewer_fallback_reason = reviewer_fallback_reason

            if self.cloudflare is None:
                self.semantic_reviewer_fallback_blocked_reason = "CLOUDFLARE_UNAVAILABLE"
                self.reviewer_provider_diversity = None
                raise

            cloudflare_state = self.state.eligible_state()
            if cloudflare_state != STATE_AVAILABLE:
                self.semantic_reviewer_fallback_blocked_reason = cloudflare_state
                self.reviewer_provider_diversity = None
                raise

            self.semantic_reviewer_fallback_used = True
            try:
                result = self.cloudflare.call(payload, call_class)
            except CloudflareFallbackRequired as cloudflare_exc:
                self._record_reviewer_attempt_failure(
                    call_class,
                    CLOUDFLARE_PROVIDER,
                    CLOUDFLARE_MODEL,
                    error_class=cloudflare_exc.reason,
                    fallback_reason=reviewer_fallback_reason,
                    result="fallback_required",
                )
                self._record_cloudflare_state_failure(cloudflare_exc.reason)
                self.reviewer_provider_diversity = None
                raise LiveGateError(cloudflare_exc.reason) from cloudflare_exc

            self.semantic_reviewer_final = CLOUDFLARE_PROVIDER
            self.semantic_reviewer_final_model = CLOUDFLARE_MODEL
            self._record_attempt(call_class, CLOUDFLARE_PROVIDER, CLOUDFLARE_MODEL, result)
            self.reviewer_provider_diversity = self._reviewer_provider_diversity()
            return result

        self.semantic_reviewer_final = MINIMAX_PROVIDER
        self.semantic_reviewer_final_model = MINIMAX_MODEL
        self.semantic_reviewer_fallback_used = False
        self.semantic_reviewer_fallback_reason = FALLBACK_NONE
        self.semantic_reviewer_fallback_blocked_reason = ""
        self._record_attempt(call_class, MINIMAX_PROVIDER, MINIMAX_MODEL, result)
        self.reviewer_provider_diversity = self._reviewer_provider_diversity()
        return result

    def _record_reviewer_attempt_failure(
        self,
        call_class: str,
        provider: str,
        model: str,
        *,
        error_class: str,
        result: str,
        fallback_reason: str = FALLBACK_NONE,
        latency_ms: int = 0,
    ) -> None:
        self.attempts.append(
            {
                "call_class": call_class,
                "provider": provider,
                "model": model,
                "result": result,
                "fallback_reason": fallback_reason,
                "error_class": error_class,
                "latency_ms": latency_ms,
                "network_attempt": 1,
            }
        )

    def _record_cloudflare_failure(self, error_class: str) -> None:
        self._record_cloudflare_state_failure(error_class)
        self.fallback_used = True
        self.closure_provider_final = MINIMAX_PROVIDER
        if error_class == "CLOUDFLARE_DAILY_QUOTA_EXHAUSTED_3036":
            self.fallback_reason = FALLBACK_CLOUDFLARE_DAILY_QUOTA
        elif error_class in {"CLOUDFLARE_PAID_PLAN_ONLY_5035", "CLOUDFLARE_AUTH_OR_CONFIG"}:
            self.fallback_reason = FALLBACK_CLOUDFLARE_CONFIGURATION
        else:
            self.fallback_reason = FALLBACK_CLOUDFLARE_TRANSIENT
        self.attempts.append(
            {
                "call_class": "closure",
                "provider": CLOUDFLARE_PROVIDER,
                "model": CLOUDFLARE_MODEL,
                "result": "fallback_required",
                "fallback_reason": self.fallback_reason,
                "error_class": error_class,
            }
        )

    def _record_cloudflare_state_failure(self, error_class: str) -> None:
        if error_class == "CLOUDFLARE_DAILY_QUOTA_EXHAUSTED_3036":
            self.state.record_daily_quota_exhausted(error_class)
        elif error_class in {"CLOUDFLARE_PAID_PLAN_ONLY_5035", "CLOUDFLARE_AUTH_OR_CONFIG"}:
            self.state.record_disabled_configuration(error_class)
        else:
            self.state.record_transient(error_class)

    def _record_attempt(
        self,
        call_class: str,
        provider: str,
        model: str,
        result: Mapping[str, Any],
    ) -> None:
        usage = _mapping(result.get("usage"))
        self.calls += 1
        if provider == MINIMAX_PROVIDER:
            self.cost += Decimal(str(result.get("cost_usd", "0") or "0"))
        self.attempts.append(
            {
                "call_class": call_class,
                "provider": provider,
                "model": model,
                "latency_ms": _safe_int(result.get("latency_ms")),
                "input_tokens": _safe_int(
                    usage.get("input_tokens"), _safe_int(usage.get("prompt_tokens"))
                ),
                "output_tokens": _safe_int(
                    usage.get("output_tokens"), _safe_int(usage.get("completion_tokens"))
                ),
                "stop_reason": str(result.get("stop_reason", "")),
                "network_attempt": _safe_int(result.get("network_attempt"), 1),
            }
        )


_ROUTER_STATE = CloudflareRouterState()


def default_router_state() -> CloudflareRouterState:
    _ROUTER_STATE.soft_limit = _decimal_from_env(
        "CLOUDFLARE_NEURON_SOFT_LIMIT", DEFAULT_CLOUDFLARE_NEURON_SOFT_LIMIT
    )
    _ROUTER_STATE.cooldown_seconds = _int_from_env(
        "CLOUDFLARE_TRANSIENT_COOLDOWN_SECONDS", DEFAULT_TRANSIENT_COOLDOWN_SECONDS
    )
    return _ROUTER_STATE


def build_provider_routing_client(
    *,
    max_provider_calls: int,
    max_cost: Decimal,
    state: CloudflareRouterState | None = None,
) -> ProviderRoutingClient:
    router_state = state or default_router_state()
    fallback = MiniMaxClient(
        os.environ.get("MINIMAX_API_KEY", ""),
        max_calls=max_provider_calls,
        max_cost=max_cost,
    )
    reviewer = MiniMaxClient(
        os.environ.get("MINIMAX_API_KEY", ""),
        max_calls=max_provider_calls,
        max_cost=max_cost,
    )
    cloudflare: CloudflareWorkersAIClient | None = None
    try:
        cloudflare = CloudflareWorkersAIClient(
            api_key=_cloudflare_inference_api_key_from_env(),
            account_id=os.environ.get("CLOUDFLARE_ACCOUNT_ID", ""),
            state=router_state,
            max_calls=max_provider_calls,
        )
    except LiveGateError:
        cloudflare = None
    return ProviderRoutingClient(
        cloudflare=cloudflare,
        fallback=fallback,
        reviewer=reviewer,
        state=router_state,
    )


def _cloudflare_inference_api_key_from_env() -> str:
    return os.environ.get("CLOUDFLARE_WORKER_AI_RESTFUL_API_KEY") or os.environ.get(
        "CLOUDFLARE_AI_TOKEN", ""
    )


def provider_status_dto(state: CloudflareRouterState | None = None) -> dict[str, Any]:
    return (state or default_router_state()).snapshot()


def classify_cloudflare_http_error(response: httpx.Response) -> str:
    codes: set[int] = set()
    try:
        body = response.json()
    except ValueError:
        body = {}
    for error in body.get("errors", []) if isinstance(body, Mapping) else []:
        if isinstance(error, Mapping):
            codes.add(_safe_int(error.get("code")))
    if response.status_code == 429 and 3036 in codes:
        return "CLOUDFLARE_DAILY_QUOTA_EXHAUSTED_3036"
    if response.status_code == 429 and 3040 in codes:
        return "CLOUDFLARE_TRANSIENT_CAPACITY_3040"
    if response.status_code == 403 and 5035 in codes:
        return "CLOUDFLARE_PAID_PLAN_ONLY_5035"
    if response.status_code in {401, 403, 404}:
        return "CLOUDFLARE_AUTH_OR_CONFIG"
    if response.status_code == 429:
        return "CLOUDFLARE_RATE_LIMIT_OR_CAPACITY_429"
    if response.status_code >= 500:
        return f"CLOUDFLARE_HTTP_{response.status_code}"
    return f"CLOUDFLARE_HTTP_{response.status_code}"


def _messages(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    system = str(payload.get("system", ""))
    if system:
        messages.append({"role": "system", "content": system})
    for message in payload.get("messages", []):
        if isinstance(message, Mapping):
            messages.append(
                {
                    "role": str(message.get("role", "user")),
                    "content": message.get("content", ""),
                }
            )
    return messages


def _selected_evidence_digest(payload: Mapping[str, Any]) -> str:
    task = _task_from_provider_payload(payload)
    evidence = task.get("evidence") or task.get("evidence_bundle") or []
    material = []
    if isinstance(evidence, list):
        for item in evidence:
            if not isinstance(item, Mapping):
                continue
            material.append(
                {
                    "id": str(item.get("id", item.get("evidence_id", ""))),
                    "evidence_id": str(item.get("evidence_id", item.get("id", ""))),
                    "locator_id": str(item.get("locator_id", "")),
                    "source_identity": str(item.get("source_identity", "")),
                    "section_id": str(item.get("section_id", "")),
                    "concept_id": str(item.get("concept_id", "")),
                    "artifact_sha256": str(item.get("artifact_sha256", "")),
                    "release_id": str(item.get("release_id", "")),
                    "text_sha256": str(item.get("text_sha256", "")),
                    "edge_id": str(item.get("edge_id", "")),
                    "relation_type": str(item.get("relation_type", "")),
                }
            )
    encoded = json.dumps(
        material,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _task_from_provider_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    for message in payload.get("messages", []):
        if not isinstance(message, Mapping):
            continue
        content = message.get("content")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, Mapping) and part.get("text"):
                    try:
                        parsed = json.loads(str(part["text"]))
                    except ValueError:
                        continue
                    return dict(parsed) if isinstance(parsed, Mapping) else {}
        if isinstance(content, str):
            try:
                parsed = json.loads(content)
            except ValueError:
                continue
            return dict(parsed) if isinstance(parsed, Mapping) else {}
    return {}


def _usage(body: Mapping[str, Any]) -> dict[str, int]:
    usage = _mapping(body.get("usage"))
    input_tokens = _safe_int(usage.get("prompt_tokens"), _safe_int(usage.get("input_tokens")))
    output_tokens = _safe_int(
        usage.get("completion_tokens"), _safe_int(usage.get("output_tokens"))
    )
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": _safe_int(usage.get("total_tokens"), input_tokens + output_tokens),
    }
