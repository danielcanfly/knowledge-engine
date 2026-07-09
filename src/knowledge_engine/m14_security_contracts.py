from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from .config import Settings
from .m14_feedback_contracts import FEEDBACK_TYPES, FeedbackType
from .m14_interfaces import PublicInterfaceCapabilities, public_interface_capabilities


class PublicSecurityPosture(BaseModel):
    schema_version: str = "knowledge-engine-public-security/v1"
    anonymous_public_access: bool
    elevated_audience_requires_authentication: bool = True
    cors_mode: Literal["same_origin", "exact_allowlist"]
    allowed_origin_count: int
    wildcard_origins_allowed: bool = False
    cross_origin_credentials: bool = False
    rate_limit_requests: int
    rate_limit_window_seconds: int
    max_body_bytes: int
    request_timeout_seconds: float
    max_concurrent_requests: int
    distributed_rate_limit: bool = False
    server_conversation_state: bool = False


class PublicFeedbackCapabilities(BaseModel):
    schema_version: str = "knowledge-engine-public-feedback-capabilities/v1"
    enabled: bool = True
    path: str = "/v1/feedback"
    feedback_types: list[FeedbackType]
    immutable_intake: bool = True
    pending_review_queue: bool = True
    direct_source_write: bool = False
    direct_production_write: bool = False
    contact_identity_collected: bool = False
    raw_query_collected: bool = False
    raw_answer_collected: bool = False
    attachments_supported: bool = False


class PublicProductCapabilities(PublicInterfaceCapabilities):
    security: PublicSecurityPosture
    feedback: PublicFeedbackCapabilities


def public_product_capabilities(settings: Settings) -> PublicProductCapabilities:
    base = public_interface_capabilities().model_dump()
    security = PublicSecurityPosture(
        anonymous_public_access=settings.public_anonymous_enabled,
        cors_mode=(
            "exact_allowlist"
            if settings.public_allowed_origins
            else "same_origin"
        ),
        allowed_origin_count=len(settings.public_allowed_origins),
        rate_limit_requests=settings.public_rate_limit_requests,
        rate_limit_window_seconds=settings.public_rate_limit_window_seconds,
        max_body_bytes=settings.public_max_body_bytes,
        request_timeout_seconds=settings.public_request_timeout_seconds,
        max_concurrent_requests=settings.public_max_concurrent_requests,
    )
    feedback = PublicFeedbackCapabilities(feedback_types=list(FEEDBACK_TYPES))
    return PublicProductCapabilities(
        **base,
        security=security,
        feedback=feedback,
    )


def harden_public_widget_javascript(script: str) -> str:
    endpoint_block = '''    const endpoint = new URL(raw, document.baseURI);
    if (endpoint.origin !== window.location.origin) {
      throw new Error("cross-origin endpoint is disabled");
    }
    return endpoint.toString();'''
    hardened_endpoint_block = '''    const endpoint = new URL(raw, document.baseURI);
    return endpoint;'''
    if endpoint_block not in script:
        raise ValueError("widget endpoint contract changed unexpectedly")
    script = script.replace(endpoint_block, hardened_endpoint_block, 1)

    fetch_line = '''        const response = await fetch(endpointFor(this), {'''
    hardened_fetch_line = '''        const endpoint = endpointFor(this);
        const response = await fetch(endpoint, {'''
    if fetch_line not in script:
        raise ValueError("widget fetch contract changed unexpectedly")
    script = script.replace(fetch_line, hardened_fetch_line, 1)

    credentials_line = '''          credentials: "same-origin",'''
    hardened_credentials_line = '''          credentials: endpoint.origin === window.location.origin
            ? "same-origin"
            : "omit",'''
    if credentials_line not in script:
        raise ValueError("widget credential contract changed unexpectedly")
    return script.replace(credentials_line, hardened_credentials_line, 1)
