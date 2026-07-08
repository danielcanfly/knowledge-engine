from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

from .errors import IntegrityError, ReleaseConflictError
from .intake_v1 import IntakeResult, canonical_json_bytes, verify_event as verify_intake_event
from .storage import ObjectStore, sha256_bytes

COMPILER_VERSION = "local-markdown-reference/1.0.0"
KEY_RE = re.compile(r"^(?!/)(?!.*(?:^|/)\.\.(?:/|$))[A-Za-z0-9._/-]+$")
HASH_RE = re.compile(r"^[a-f0-9]{64}$")
AUDIENCES = {"public", "internal", "confidential", "restricted"}


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


class CompilerFailure(IntegrityError):
    def __init__(self, code: str, stage: str, message: str, **context: Any) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.stage = stage
        self.message = message
        self.context = context


@dataclass(frozen=True)
class LocalMarkdownCompilerRequest:
    snapshot_key: str
    snapshot_sha256: str
    derivative_key: str
    derivative_sha256: str
    normalized_key: str
    normalized_sha256: str
    result_key: str
    result_sha256: str
    max_blocks: int = 5000
    max_candidates: int = 10000

    def payload(self) -> dict[str, Any]:
        return {
            "schema_version": "knowledge-compiler-request/v1",
            **asdict(self),
            "compiler_version": COMPILER_VERSION,
        }

    def run_id(self) -> str:
        return "crun_" + sha256_bytes(canonical_json_bytes(self.payload()))

    def validate(self) -> None:
        prefixes = {
            "snapshot_key": "intake/v1/snapshots/",
            "derivative_key": "intake/v1/normalized/",
            "normalized_key": "intake/v1/normalized/",
            "result_key": "intake/v1/attempts/",
        }
        for name, prefix in prefixes.items():
            value = getattr(self, name)
            if not isinstance(value, str) or not KEY_RE.fullmatch(value):
                raise CompilerFailure("INVALID_OBJECT_KEY", "request", f"invalid {name}")
            if not value.startswith(prefix):
                raise CompilerFailure(
                    "INVALID_OBJECT_NAMESPACE", "request", f"invalid {name}"
                )
        for name in (
            "snapshot_sha256",
            "derivative_sha256",
            "normalized_sha256",
            "result_sha256",
        ):
            if not HASH_RE.fullmatch(getattr(self, name)):
                raise CompilerFailure("INVALID_HASH", "request", f"invalid {name}")
        if not 1 <= self.max_blocks <= 100000:
            raise CompilerFailure("INVALID_LIMIT", "request", "max_blocks is invalid")
        if not 1 <= self.max_candidates <= 200000:
            raise CompilerFailure("INVALID_LIMIT", "request", "max_candidates is invalid")


@dataclass(frozen=True)
class CompilerResult:
    compiler_run_id: str
    status: str
    result_key: str
    event_keys: tuple[str, ...]
    input_key: str | None = None
    blocks_key: str | None = None
    source_map_key: str | None = None
    candidates_key: str | None = None
    rejection_key: str | None = None
    block_count: int = 0
    candidate_count: int = 0
    idempotent: bool = False
    failure_code: str | None = None
    canonical_write_permitted: bool = False
    production_write_permitted: bool = False

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["event_keys"] = list(self.event_keys)
        return value

    def evidence(self) -> dict[str, Any]:
        value = self.to_dict()
        value.pop("idempotent")
        return value


def request_from_intake_result(
    store: ObjectStore, result: IntakeResult
) -> LocalMarkdownCompilerRequest:
    if result.status != "accepted_for_compilation":
        raise CompilerFailure("ADMISSION_NOT_ACCEPTED", "request", "intake was not accepted")
    keys = (result.snapshot_key, result.derivative_key, result.normalized_key, result.result_key)
    if any(not key for key in keys):
        raise CompilerFailure(
            "INCOMPLETE_INTAKE_RESULT", "request", "missing intake reference"
        )

    def digest(key: str) -> str:
        try:
            return sha256_bytes(store.get(key))
        except FileNotFoundError as exc:
            raise CompilerFailure(
                "MISSING_OBJECT", "request", "missing intake object", key=key
            ) from exc

    return LocalMarkdownCompilerRequest(
        snapshot_key=str(result.snapshot_key),
        snapshot_sha256=digest(str(result.snapshot_key)),
        derivative_key=str(result.derivative_key),
        derivative_sha256=digest(str(result.derivative_key)),
        normalized_key=str(result.normalized_key),
        normalized_sha256=digest(str(result.normalized_key)),
        result_key=result.result_key,
        result_sha256=digest(result.result_key),
    )


def put_immutable(store: ObjectStore, key: str, data: bytes) -> bool:
    current = store.head(key)
    if current is not None:
        if store.get(key) != data:
            raise IntegrityError(f"immutable object collision: {key}")
        return True
    try:
        store.put(
            key,
            data,
            content_type="application/json",
            sha256=sha256_bytes(data),
            only_if_absent=True,
        )
        return False
    except ReleaseConflictError:
        if store.get(key) != data:
            raise IntegrityError(f"immutable object collision: {key}") from None
        return True


def _read(store: ObjectStore, key: str, expected: str, label: str) -> bytes:
    try:
        data = store.get(key)
    except FileNotFoundError as exc:
        raise CompilerFailure(
            "MISSING_OBJECT", "admit", f"missing {label}", key=key
        ) from exc
    if sha256_bytes(data) != expected:
        raise CompilerFailure(
            "HASH_MISMATCH", "admit", f"{label} hash mismatch", key=key
        )
    return data


def _object(data: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CompilerFailure("INVALID_JSON", "admit", f"invalid {label}") from exc
    if not isinstance(value, dict):
        raise CompilerFailure("INVALID_JSON", "admit", f"{label} must be an object")
    return value


def _policy(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    audience = snapshot.get("audience")
    access = snapshot.get("access_policy")
    if audience not in AUDIENCES or snapshot.get("acl_status") != "resolved":
        raise CompilerFailure(
            "POLICY_UNRESOLVED", "admit", "audience or ACL is unresolved"
        )
    if not isinstance(access, dict) or access.get("policy_type") == "unresolved":
        raise CompilerFailure("POLICY_UNRESOLVED", "admit", "access policy unresolved")
    principals = access.get("principals")
    if not isinstance(principals, list) or len(principals) != len(set(principals)):
        raise CompilerFailure("POLICY_INVALID", "admit", "access principals invalid")
    if audience == "public" and (
        access.get("policy_type") != "public" or principals
    ):
        raise CompilerFailure("POLICY_BROADENING", "admit", "public policy mismatch")
    for name in ("owner", "license"):
        evidence = snapshot.get(name)
        if not isinstance(evidence, dict) or evidence.get("status") != "resolved":
            raise CompilerFailure(
                "POLICY_UNRESOLVED", "admit", f"{name} is unresolved"
            )
        value = evidence.get("value")
        if not isinstance(value, str) or not value.strip():
            raise CompilerFailure("POLICY_INVALID", "admit", f"{name} value invalid")
    return {
        "audience": audience,
        "access_policy": access,
        "owner": snapshot["owner"],
        "license": snapshot["license"],
        "may_broaden": False,
    }


def _verify_events(store: ObjectStore, result: Mapping[str, Any]) -> None:
    keys = result.get("event_keys")
    if not isinstance(keys, list) or not keys:
        raise CompilerFailure(
            "ADMISSION_EVIDENCE_INVALID", "admit", "event chain missing"
        )
    previous = None
    final = None
    for key in keys:
        if not isinstance(key, str) or not key.startswith("intake/v1/attempts/"):
            raise CompilerFailure(
                "ADMISSION_EVIDENCE_INVALID", "admit", "event key invalid"
            )
        try:
            event = _object(store.get(key), "intake event")
        except FileNotFoundError as exc:
            raise CompilerFailure(
                "MISSING_OBJECT", "admit", "intake event missing"
            ) from exc
        if not verify_intake_event(event):
            raise CompilerFailure(
                "ADMISSION_EVIDENCE_INVALID", "admit", "event hash invalid"
            )
        if event.get("previous_event_sha256") != previous:
            raise CompilerFailure(
                "ADMISSION_EVIDENCE_INVALID", "admit", "event chain not adjacent"
            )
        digest = event.get("event_sha256")
        if not isinstance(digest, str) or not key.endswith(f"-{digest}.json"):
            raise CompilerFailure(
                "ADMISSION_EVIDENCE_INVALID", "admit", "event key hash mismatch"
            )
        previous, final = digest, event.get("to_state")
    if final != "accepted_for_compilation":
        raise CompilerFailure(
            "ADMISSION_NOT_ACCEPTED", "admit", "event chain not accepted"
        )


def admit(store: ObjectStore, request: LocalMarkdownCompilerRequest):
    snapshot = _object(
        _read(store, request.snapshot_key, request.snapshot_sha256, "snapshot"),
        "snapshot",
    )
    derivative = _object(
        _read(store, request.derivative_key, request.derivative_sha256, "derivative"),
        "derivative",
    )
    result = _object(
        _read(store, request.result_key, request.result_sha256, "result"), "result"
    )
    normalized = _read(
        store, request.normalized_key, request.normalized_sha256, "normalized"
    )
    if snapshot.get("schema_version") != "intake-snapshot/v1":
        raise CompilerFailure("UNSUPPORTED_SCHEMA", "admit", "snapshot unsupported")
    if derivative.get("schema_version") != "intake-derivative/v1":
        raise CompilerFailure("UNSUPPORTED_SCHEMA", "admit", "derivative unsupported")
    if result.get("status") != "accepted_for_compilation":
        raise CompilerFailure("ADMISSION_NOT_ACCEPTED", "admit", "result not accepted")
    _verify_events(store, result)
    connector = (snapshot.get("connector_type"), snapshot.get("connector_version"))
    if connector != ("local_file", "local-file/1.0.0"):
        raise CompilerFailure("UNSUPPORTED_CONNECTOR", "admit", "connector unsupported")
    normalizer = (
        derivative.get("normalizer_id"),
        derivative.get("normalizer_version"),
        derivative.get("mime_type"),
    )
    if normalizer != ("markdown", "1.0.0", "text/markdown"):
        raise CompilerFailure("UNSUPPORTED_NORMALIZER", "admit", "normalizer unsupported")
    identities = [
        (result.get("source_id"), snapshot.get("source_id")),
        (result.get("snapshot_id"), snapshot.get("snapshot_id")),
        (result.get("derivative_id"), derivative.get("derivative_id")),
        (derivative.get("snapshot_id"), snapshot.get("snapshot_id")),
        (result.get("snapshot_key"), request.snapshot_key),
        (result.get("derivative_key"), request.derivative_key),
        (result.get("normalized_key"), request.normalized_key),
        (derivative.get("normalized_key"), request.normalized_key),
    ]
    if any(left != right for left, right in identities):
        raise CompilerFailure("IDENTITY_MISMATCH", "admit", "intake identity mismatch")
    if derivative.get("normalized_content_hash") != request.normalized_sha256:
        raise CompilerFailure("IDENTITY_MISMATCH", "admit", "normalized hash mismatch")
    try:
        text = normalized.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CompilerFailure("INVALID_UTF8", "admit", "normalized text is not UTF-8") from exc
    return snapshot, derivative, result, text, _policy(snapshot)
