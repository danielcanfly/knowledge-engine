from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .errors import AuthorizationError, IntegrityError

INVENTORY_SCHEMA = "knowledge-engine-m25-9-pilot-inventory/v1"
AUTHORITY_SCHEMA = "knowledge-engine-m25-9-inventory-authority/v1"
RUN_SCHEMA = "knowledge-engine-m25-9a-run-evidence/v1"
RECEIPT_SCHEMA = "knowledge-engine-m25-9a-run-receipt/v1"
GATE_SCHEMA = "knowledge-engine-m25-9-readiness-gate/v1"
M25_8_GATE_SCHEMA = "knowledge-engine-m25-8-readiness-gate/v1"
M25_8_LIVE_STATUS = "m25_8_adoption_release_rollback_complete"
M25_8_BLOCKED_STATUS = "blocked_awaiting_real_approved_source_pr"
BLOCKED_STATUS = "blocked_awaiting_m25_8_live_acceptance_and_exact_inventory_authority"
LIVE_COMPLETE_STATUS = "m25_9a_full_population_candidate_run_complete"
TEST_COMPLETE_STATUS = "m25_9a_test_only_full_population_simulation_passed"
M25_8_ENGINE_MERGE_SHA = "b456c0c33efb84df94aa4e4668bdbce22e2d955b"

MIN_SOURCES = 50
MAX_SOURCES = 100
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
ACTOR_RE = re.compile(r"^[A-Za-z0-9._@-]{3,128}$")
SOURCE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,127}$")

SOURCE_TYPES = {
    "long_form_markdown",
    "technical_note",
    "structured_json",
    "bounded_web_snapshot",
}
LANGUAGES = {"en", "zh-Hant", "mixed"}
AUDIENCES = {"public", "restricted"}
LICENCE_CLASSES = {"owned", "permitted", "test_fixture"}
YIELDS = {"low", "medium", "dense"}
REQUIRED_TRAITS = {
    "duplicate",
    "near_duplicate",
    "alias_rich",
    "ambiguous",
    "conflicting_claim",
    "superseded",
    "noisy_formatting",
    "prompt_injection_like",
    "restricted_audience",
    "unsupported_irrelevant",
}
ALLOWED_TRAITS = REQUIRED_TRAITS | {"updated_version", "ordinary"}
SOURCE_STATES = {
    "candidate_ready",
    "no_new_knowledge",
    "rejected_policy",
    "rejected_unsupported",
    "deferred_ambiguity",
    "deferred_contradiction",
    "failed_technical",
    "cancelled_by_operator",
}
STAGES = (
    "dry_run_inventory_policy_validation",
    "immutable_acquisition",
    "normalization",
    "extraction",
    "identity_resolution",
    "relation_tag_governance",
    "candidate_packaging",
)
FAILURE_DRILLS = (
    "interrupted_acquisition",
    "provider_timeout",
    "invalid_model_json",
    "stale_checkpoint",
    "source_base_drift",
    "duplicate_path_collision",
    "incomplete_review",
    "failed_source_ci",
    "failed_release_rebuild",
    "candidate_rollback",
    "access_security_regression",
)
FORBIDDEN_LIVE_ACTORS = {
    "synthetic-knowledge-owner",
    "synthetic-reviewer",
    "browser-reviewer",
}


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sign(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    output = json.loads(json.dumps(value))
    output.pop(field, None)
    output[field] = digest(output)
    return output


def verify_signed(value: Mapping[str, Any], field: str, code: str) -> str:
    unsigned = dict(value)
    claimed = unsigned.pop(field, None)
    actual = digest(unsigned)
    if not isinstance(claimed, str) or not hmac.compare_digest(claimed, actual):
        raise IntegrityError(code)
    return claimed


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IntegrityError(f"M25-PILOT-001 cannot load {path}") from exc
    if not isinstance(value, dict):
        raise IntegrityError(f"M25-PILOT-002 {path.name} must contain an object")
    return value


def write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _hex(value: Any, size: int, label: str) -> str:
    pattern = HEX40 if size == 40 else HEX64
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise IntegrityError(f"M25-PILOT-003 invalid {label}")
    return value


def _nonnegative_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise IntegrityError(f"M25-PILOT-004 invalid {label}")
    return value


def _positive_int(value: Any, label: str) -> int:
    result = _nonnegative_int(value, label)
    if result == 0:
        raise IntegrityError(f"M25-PILOT-005 invalid {label}")
    return result


def _number(value: Any, label: str) -> float:
    if not isinstance(value, int | float) or isinstance(value, bool) or value < 0:
        raise IntegrityError(f"M25-PILOT-006 invalid {label}")
    return float(value)


def _actor(value: Any, *, mode: str) -> str:
    if not isinstance(value, str) or ACTOR_RE.fullmatch(value) is None:
        raise AuthorizationError("M25-PILOT-007 invalid authority actor")
    if mode == "live" and value in FORBIDDEN_LIVE_ACTORS:
        raise AuthorizationError("M25-PILOT-008 synthetic actor cannot authorize live pilot")
    return value
