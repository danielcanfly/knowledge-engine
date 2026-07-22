from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any

from .errors import IntegrityError
from .m25_extraction_common import (
    MAX_CANDIDATES,
    MAX_FALLBACK_PROVIDERS,
    MAX_PROVIDER_ATTEMPTS,
    MODEL_POLICY_SCHEMA,
    PROVIDER_RESPONSE_SCHEMA,
    RECORDED_RESPONSE_SET_SCHEMA,
    ExtractionInput,
    ExtractionProvider,
    ProviderFailure,
    _digest,
    _scan_provider_payload,
    _signed,
    _text,
)


class RecordedResponseProvider:
    def __init__(
        self,
        *,
        provider_id: str,
        model_id: str,
        model_revision: str,
        response_set: Mapping[str, Any],
    ) -> None:
        self.provider_id = _text(provider_id, "provider id", 120)
        self.model_id = _text(model_id, "model id", 200)
        self.model_revision = _text(model_revision, "model revision", 200)
        if response_set.get("schema_version") != RECORDED_RESPONSE_SET_SCHEMA:
            raise IntegrityError("M25-EXTRACT-130 invalid recorded response set")
        _signed(
            response_set,
            "response_set_sha256",
            "M25-EXTRACT-131 recorded response set digest mismatch",
        )
        responses = response_set.get("responses")
        if not isinstance(responses, list) or not responses:
            raise IntegrityError("M25-EXTRACT-132 recorded responses missing")
        self._responses: dict[str, dict[str, Any]] = {}
        for response in responses:
            if not isinstance(response, Mapping):
                raise IntegrityError("M25-EXTRACT-133 malformed recorded response")
            request_sha = response.get("request_sha256")
            if not isinstance(request_sha, str) or request_sha in self._responses:
                raise IntegrityError("M25-EXTRACT-134 duplicate recorded request identity")
            self._responses[request_sha] = dict(response)

    def invoke(
        self,
        request_manifest: Mapping[str, Any],
        inputs: Sequence[ExtractionInput],
    ) -> Mapping[str, Any]:
        del inputs
        request_sha = request_manifest.get("request_sha256")
        response = self._responses.get(str(request_sha))
        if response is None:
            raise ProviderFailure(
                "RECORDED_RESPONSE_MISSING",
                transient=False,
                safe_message="no recorded response matches the request digest",
            )
        return copy.deepcopy(response)


def validate_model_policy(value: Mapping[str, Any]) -> dict[str, Any]:
    if value.get("schema_version") != MODEL_POLICY_SCHEMA:
        raise IntegrityError("M25-EXTRACT-135 invalid model policy schema")
    _signed(value, "model_policy_sha256", "M25-EXTRACT-136 model policy digest mismatch")
    if value.get("live_provider_calls_permitted") is not False:
        raise IntegrityError("M25-EXTRACT-137 live provider calls are not permitted")
    routes = value.get("routes")
    if not isinstance(routes, list) or not 1 <= len(routes) <= MAX_FALLBACK_PROVIDERS:
        raise IntegrityError("M25-EXTRACT-138 invalid provider route count")
    attempts = value.get("max_attempts_per_provider")
    if (
        not isinstance(attempts, int)
        or isinstance(attempts, bool)
        or not 1 <= attempts <= MAX_PROVIDER_ATTEMPTS
    ):
        raise IntegrityError("M25-EXTRACT-139 invalid provider attempt limit")
    seen: set[str] = set()
    for route in routes:
        if not isinstance(route, Mapping):
            raise IntegrityError("M25-EXTRACT-140 malformed provider route")
        if route.get("mode") != "recorded_replay":
            raise IntegrityError("M25-EXTRACT-141 unsupported provider mode")
        provider_id = _text(route.get("provider_id"), "provider id", 120)
        if provider_id in seen:
            raise IntegrityError("M25-EXTRACT-142 duplicate provider route")
        seen.add(provider_id)
        _text(route.get("model_id"), "model id", 200)
        _text(route.get("model_revision"), "model revision", 200)
    return dict(value)


def validate_provider_response(
    response: Mapping[str, Any],
    request: Mapping[str, Any],
    route: Mapping[str, Any],
    *,
    max_candidates: int,
) -> dict[str, Any]:
    if response.get("schema_version") != PROVIDER_RESPONSE_SCHEMA:
        raise IntegrityError("M25-EXTRACT-143 invalid provider response schema")
    _signed(response, "response_sha256", "M25-EXTRACT-144 provider response digest mismatch")
    if response.get("request_sha256") != request.get("request_sha256"):
        raise IntegrityError("M25-EXTRACT-145 provider response request mismatch")
    for key in ("provider_id", "model_id", "model_revision"):
        if response.get(key) != route.get(key):
            raise IntegrityError("M25-EXTRACT-146 provider identity drift")
    if (
        response.get("authority") != "candidate_only"
        or response.get("canonical_knowledge") is not False
        or response.get("production_authority") is not False
        or response.get("review_required") is not True
    ):
        raise IntegrityError("M25-EXTRACT-147 provider authority drift")
    proposals = response.get("proposals")
    if not isinstance(proposals, list) or not 1 <= len(proposals) <= min(
        max_candidates, MAX_CANDIDATES
    ):
        raise IntegrityError("M25-EXTRACT-148 provider proposal count exceeds bounds")
    _scan_provider_payload(proposals)
    return dict(response)


def execute_provider_route(
    request: Mapping[str, Any],
    inputs: Sequence[ExtractionInput],
    model_policy: Mapping[str, Any],
    providers: Mapping[str, ExtractionProvider],
    *,
    max_candidates: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    policy = validate_model_policy(model_policy)
    attempts: list[dict[str, Any]] = []
    for route in policy["routes"]:
        provider = providers.get(route["provider_id"])
        if provider is None:
            attempts.append(
                {
                    "provider_id": route["provider_id"],
                    "model_id": route["model_id"],
                    "model_revision": route["model_revision"],
                    "attempt": 0,
                    "status": "unavailable",
                    "failure_code": "PROVIDER_NOT_REGISTERED",
                }
            )
            continue
        if (
            provider.model_id != route["model_id"]
            or provider.model_revision != route["model_revision"]
        ):
            raise IntegrityError("M25-EXTRACT-149 registered provider identity mismatch")
        for attempt in range(1, policy["max_attempts_per_provider"] + 1):
            try:
                raw_response = provider.invoke(request, inputs)
                response = validate_provider_response(
                    raw_response,
                    request,
                    route,
                    max_candidates=max_candidates,
                )
            except ProviderFailure as exc:
                attempts.append(
                    {
                        "provider_id": route["provider_id"],
                        "model_id": route["model_id"],
                        "model_revision": route["model_revision"],
                        "attempt": attempt,
                        "status": "retryable" if exc.transient else "failed",
                        "failure_code": exc.code,
                    }
                )
                if not exc.transient:
                    break
                continue
            attempts.append(
                {
                    "provider_id": route["provider_id"],
                    "model_id": route["model_id"],
                    "model_revision": route["model_revision"],
                    "attempt": attempt,
                    "status": "completed",
                    "failure_code": None,
                }
            )
            return response, attempts
    failure_summary = _digest({"request": request["request_sha256"], "attempts": attempts})
    raise ProviderFailure(
        "PROVIDER_ROUTE_EXHAUSTED",
        transient=False,
        safe_message=f"all bounded provider routes failed ({failure_summary[:12]})",
    )


__all__ = [
    "RecordedResponseProvider",
    "execute_provider_route",
    "validate_model_policy",
    "validate_provider_response",
]
