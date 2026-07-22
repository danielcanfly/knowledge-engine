from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from .errors import IntegrityError, ReleaseConflictError
from .intake_v1 import canonical_json_bytes
from .storage import ObjectStore, sha256_bytes

M25_3_ENGINE_BASE_SHA = "cc83a1e6bae1dce45fca50d3fdb515c26a70d0f9"
SOURCE_SHA = "acf78596ace8a7366688ccef72b507204d09d9f9"
FOUNDATION_SHA = "e5ef644053d34e89c70d2ceb37521e1c59234832"
M25_2_ACCEPTED_STATUS = "m25_2_intake_orchestrator_accepted"

PROMPT_CONTRACT_SCHEMA = "knowledge-engine-m25-prompt-contract/v1"
MODEL_POLICY_SCHEMA = "knowledge-engine-m25-model-policy/v1"
CANDIDATE_POLICY_SCHEMA = "knowledge-engine-m25-candidate-policy/v1"
PROVIDER_REQUEST_SCHEMA = "knowledge-engine-m25-provider-request/v1"
PROVIDER_RESPONSE_SCHEMA = "knowledge-engine-m25-provider-response/v1"
EXTRACTION_RECEIPT_SCHEMA = "knowledge-engine-m25-extraction-receipt/v1"
RECORDED_RESPONSE_SET_SCHEMA = "knowledge-engine-m25-recorded-response-set/v1"

MAX_INPUTS = 100
MAX_INPUT_TEXT_CHARS = 1_000_000
MAX_CANDIDATES = 1_000
MAX_CANDIDATES_PER_INPUT = 250
MAX_EVIDENCE_SPANS = 16
MAX_PROVIDER_ATTEMPTS = 3
MAX_FALLBACK_PROVIDERS = 3
MAX_SAFE_STRING = 4_000

PROMPT_INJECTION_PATTERNS = {
    "ignore_previous_instructions": re.compile(
        r"(?i)\bignore\s+(?:all\s+)?previous\s+instructions\b"
    ),
    "system_prompt_request": re.compile(
        r"(?i)\b(?:reveal|print|show)\s+the\s+system\s+prompt\b"
    ),
    "role_override": re.compile(r"(?i)\byou\s+are\s+now\b"),
    "tool_override": re.compile(r"(?i)\b(?:call|invoke|use)\s+the\s+(?:tool|function)\b"),
}
SECRET_PATTERNS = {
    "private_key": re.compile(r"-----BEGIN (?:OPENSSH |RSA |EC )?PRIVATE KEY-----"),
    "github_token": re.compile(r"\bgh(?:p|o|u|s|r)_[A-Za-z0-9]{30,}\b"),
    "aws_access_key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "bearer_token": re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{20,}\b"),
    "generic_secret": re.compile(
        r"(?i)\b(?:api[_-]?key|secret|password|access[_-]?token)\b"
        r"\s*[:=]\s*[A-Za-z0-9_+/=.-]{12,}"
    ),
}
FORBIDDEN_PROVIDER_FIELDS = {
    "approved",
    "canonical",
    "canonical_knowledge",
    "production_authority",
    "source_write",
    "source_mutation",
    "system_prompt",
    "tool_call",
    "credentials",
    "api_key",
    "token",
    "password",
}


class ProviderFailure(RuntimeError):
    def __init__(self, code: str, *, transient: bool, safe_message: str) -> None:
        super().__init__(f"{code}: {safe_message}")
        self.code = code
        self.transient = transient
        self.safe_message = safe_message


@dataclass(frozen=True)
class ExtractionInput:
    item_id: str
    derivative_id: str
    audience: str
    text: str
    text_sha256: str
    normalized_key: str
    warnings: tuple[str, ...]


class ExtractionProvider(Protocol):
    provider_id: str
    model_id: str
    model_revision: str

    def invoke(
        self,
        request_manifest: Mapping[str, Any],
        inputs: Sequence[ExtractionInput],
    ) -> Mapping[str, Any]: ...


def _normalized(value: Any) -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, Mapping):
        return {str(key): _normalized(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalized(item) for item in value]
    return value


def _canonical_bytes(value: Any) -> bytes:
    return canonical_json_bytes(_normalized(value))


def _pretty_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            _normalized(value),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return sha256_bytes(_canonical_bytes(value))


def _signed(value: Mapping[str, Any], field: str, code: str) -> str:
    unsigned = dict(value)
    claimed = unsigned.pop(field, None)
    if not isinstance(claimed, str) or claimed != _digest(unsigned):
        raise IntegrityError(code)
    return claimed


def _text(value: Any, label: str, maximum: int = MAX_SAFE_STRING) -> str:
    if not isinstance(value, str):
        raise IntegrityError(f"M25-EXTRACT-101 invalid {label}")
    normalized = " ".join(unicodedata.normalize("NFC", value).split())
    if not normalized or len(normalized) > maximum:
        raise IntegrityError(f"M25-EXTRACT-101 invalid {label}")
    return normalized


def _hex(value: Any, size: int, label: str) -> str:
    if not isinstance(value, str) or len(value) != size:
        raise IntegrityError(f"M25-EXTRACT-102 invalid {label}")
    if any(character not in "0123456789abcdef" for character in value):
        raise IntegrityError(f"M25-EXTRACT-102 invalid {label}")
    return value


def _secret_findings(value: str) -> list[str]:
    return sorted(name for name, pattern in SECRET_PATTERNS.items() if pattern.search(value))


def _prompt_findings(value: str) -> list[str]:
    return sorted(
        name for name, pattern in PROMPT_INJECTION_PATTERNS.items() if pattern.search(value)
    )


def _scan_provider_payload(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key) in FORBIDDEN_PROVIDER_FIELDS:
                raise IntegrityError("M25-EXTRACT-103 provider authority escalation field")
            _scan_provider_payload(child)
        return
    if isinstance(value, list):
        for child in value:
            _scan_provider_payload(child)
        return
    if isinstance(value, str) and _secret_findings(value):
        raise IntegrityError("M25-EXTRACT-104 secret-like provider payload")


def _put_immutable(
    store: ObjectStore,
    key: str,
    data: bytes,
    *,
    content_type: str = "application/json",
) -> bool:
    digest = sha256_bytes(data)
    current = store.head(key)
    if current is not None:
        if current.sha256 != digest or store.get(key) != data:
            raise IntegrityError(f"M25-EXTRACT-105 immutable collision at {key}")
        return True
    try:
        store.put(
            key,
            data,
            content_type=content_type,
            sha256=digest,
            only_if_absent=True,
        )
    except ReleaseConflictError as exc:
        current = store.head(key)
        if current is None or current.sha256 != digest or store.get(key) != data:
            raise IntegrityError(f"M25-EXTRACT-105 immutable collision at {key}") from exc
        return True
    return False


__all__ = [
    "CANDIDATE_POLICY_SCHEMA",
    "EXTRACTION_RECEIPT_SCHEMA",
    "ExtractionInput",
    "ExtractionProvider",
    "FOUNDATION_SHA",
    "MAX_CANDIDATES",
    "MAX_CANDIDATES_PER_INPUT",
    "MAX_EVIDENCE_SPANS",
    "MAX_FALLBACK_PROVIDERS",
    "MAX_INPUTS",
    "MAX_INPUT_TEXT_CHARS",
    "MAX_PROVIDER_ATTEMPTS",
    "MODEL_POLICY_SCHEMA",
    "M25_2_ACCEPTED_STATUS",
    "M25_3_ENGINE_BASE_SHA",
    "PROMPT_CONTRACT_SCHEMA",
    "PROVIDER_REQUEST_SCHEMA",
    "PROVIDER_RESPONSE_SCHEMA",
    "ProviderFailure",
    "RECORDED_RESPONSE_SET_SCHEMA",
    "SOURCE_SHA",
    "_digest",
    "_hex",
    "_pretty_bytes",
    "_prompt_findings",
    "_put_immutable",
    "_scan_provider_payload",
    "_secret_findings",
    "_signed",
    "_text",
]
