from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from itertools import pairwise
from pathlib import Path
from typing import Any

from .errors import IntegrityError

SOURCE_SHA = "a6ba738d910d01d2ae99b1968f0831989934c549"
FOUNDATION_SHA = "e5ef644053d34e89c70d2ceb37521e1c59234832"
FINAL_ENGINE_SHA = "66b3086145ff17700a4996a2bedc29c908faf349"
EVIDENCE_SHA256 = "23060cf974e01da874b75d678b2a0e8de3c6885b681e46fcaf3621a5d1036bcb"
EVIDENCE_PATH = (
    Path(__file__).resolve().parents[2]
    / "pilot"
    / "m23"
    / "m23-6-7-acceptance-evidence.json"
)

PROTECTED_MUTATION_KEYS = (
    "access_application_creation",
    "cloudflare_inference",
    "credential_rotation",
    "delete",
    "graph_neural_retrieval",
    "permanent_ledger",
    "pointer",
    "production",
    "production_traffic",
    "public_graph_explorer",
    "qdrant_delete",
    "qdrant_write",
    "r2_write",
    "source",
    "source_pr_19_merge",
    "worker_or_pages_deployment",
)

CHAIN_FIELDS = {
    "milestone",
    "issue",
    "implementation_pr",
    "reconciliation_pr",
    "entry_base",
    "implementation_head",
    "implementation_merge",
    "reconciliation_head",
    "reconciliation_merge",
    "issue_completed",
    "implementation_merged",
    "reconciliation_merged",
    "implementation_expected_head_merge",
    "reconciliation_expected_head_merge",
    "workflows",
}


def _sha(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise IntegrityError(f"M23.6-ACCEPT-101 {label} must be an object")
    return value


def _sequence(value: Any, label: str) -> tuple[Any, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise IntegrityError(f"M23.6-ACCEPT-102 {label} must be a list")
    return tuple(value)


def _load_expected() -> dict[str, Any]:
    try:
        raw = EVIDENCE_PATH.read_bytes()
    except OSError as exc:
        raise IntegrityError("M23.6-ACCEPT-103 evidence matrix is unavailable") from exc
    if hashlib.sha256(raw).hexdigest() != EVIDENCE_SHA256:
        raise IntegrityError("M23.6-ACCEPT-104 evidence matrix digest mismatch")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise IntegrityError("M23.6-ACCEPT-105 evidence matrix is invalid JSON") from exc
    return dict(_mapping(value, "evidence matrix"))


def canonical_acceptance_evidence() -> dict[str, Any]:
    return json.loads(json.dumps(_load_expected(), sort_keys=True))


def _exact_mapping(
    value: Any,
    expected: Mapping[str, Any],
    label: str,
) -> dict[str, Any]:
    item = _mapping(value, label)
    if dict(item) != dict(expected):
        raise IntegrityError(f"M23.6-ACCEPT-106 {label} identity mismatch")
    return dict(item)


def _validate_workflows(
    value: Any,
    expected: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows = _sequence(value, "workflows")
    if len(rows) != len(expected):
        raise IntegrityError("M23.6-ACCEPT-107 workflow count mismatch")
    normalized: list[dict[str, Any]] = []
    required = {"name", "run_number", "run_id", "head_sha", "conclusion"}
    for actual, wanted in zip(rows, expected, strict=True):
        item = _mapping(actual, "workflow")
        if set(item) != required:
            raise IntegrityError("M23.6-ACCEPT-108 workflow shape mismatch")
        if dict(item) != dict(wanted):
            raise IntegrityError("M23.6-ACCEPT-109 workflow evidence mismatch")
        normalized.append(dict(item))
    identities = {
        (item["name"], item["run_number"], item["run_id"])
        for item in normalized
    }
    if len(identities) != len(normalized):
        raise IntegrityError("M23.6-ACCEPT-110 duplicate workflow evidence")
    return normalized


def _validate_chain(value: Any, expected: Mapping[str, Any]) -> dict[str, Any]:
    item = _mapping(value, "chain")
    if set(item) != CHAIN_FIELDS:
        raise IntegrityError("M23.6-ACCEPT-111 chain shape mismatch")
    identity_fields = (
        "milestone",
        "issue",
        "implementation_pr",
        "reconciliation_pr",
        "entry_base",
        "implementation_head",
        "implementation_merge",
        "reconciliation_head",
        "reconciliation_merge",
    )
    for key in identity_fields:
        if item[key] != expected[key]:
            raise IntegrityError(
                f"M23.6-ACCEPT-112 {expected['milestone']} {key} mismatch"
            )
    completion_fields = (
        "issue_completed",
        "implementation_merged",
        "reconciliation_merged",
        "implementation_expected_head_merge",
        "reconciliation_expected_head_merge",
    )
    for key in completion_fields:
        if item[key] is not True:
            raise IntegrityError(
                f"M23.6-ACCEPT-113 {expected['milestone']} incomplete state: {key}"
            )
    return {
        **{key: item[key] for key in item if key != "workflows"},
        "workflows": _validate_workflows(item["workflows"], expected["workflows"]),
    }


def validate_m23_6_acceptance(payload: Mapping[str, Any]) -> dict[str, Any]:
    expected = _load_expected()
    root = _mapping(payload, "acceptance")
    if set(root) != set(expected):
        raise IntegrityError("M23.6-ACCEPT-114 root shape mismatch")
    for key, wanted in (
        ("schema_version", "knowledge-engine-m23-6-acceptance-evidence/v1"),
        ("engine_sha", FINAL_ENGINE_SHA),
        ("source_sha", SOURCE_SHA),
        ("foundation_sha", FOUNDATION_SHA),
    ):
        if root[key] != wanted:
            raise IntegrityError(f"M23.6-ACCEPT-115 {key} mismatch")

    source_pr = _exact_mapping(root["source_pr"], expected["source_pr"], "source_pr")
    qdrant = _exact_mapping(root["qdrant"], expected["qdrant"], "qdrant")
    worker = _exact_mapping(root["worker"], expected["worker"], "worker")
    runtime = _exact_mapping(root["runtime"], expected["runtime"], "runtime")
    candidate = _exact_mapping(
        root["candidate_release"], expected["candidate_release"], "candidate_release"
    )
    explorer = _exact_mapping(root["explorer"], expected["explorer"], "explorer")

    if sum(candidate["semantic_anchor_counts"].values()) != qdrant["points_count"]:
        raise IntegrityError("M23.6-ACCEPT-116 semantic anchors do not cover 107 points")
    if candidate["per_concept_section_attribution_available"] is not False:
        raise IntegrityError("M23.6-ACCEPT-117 invented per-concept attribution")
    if runtime["retrieval_mode"] != "lexical":
        raise IntegrityError("M23.6-ACCEPT-118 lexical rollback is not preserved")
    if runtime["lexical_output_authoritative"] is not True:
        raise IntegrityError("M23.6-ACCEPT-119 lexical output is not authoritative")
    if explorer["typed_graph_and_semantic_overlay_conflation_allowed"] is not False:
        raise IntegrityError("M23.6-ACCEPT-120 graph and semantic layers were conflated")

    protected = _mapping(root["protected_state"], "protected_state")
    if set(protected) != set(PROTECTED_MUTATION_KEYS):
        raise IntegrityError("M23.6-ACCEPT-121 protected state is incomplete")
    if any(protected[key] is not False for key in PROTECTED_MUTATION_KEYS):
        raise IntegrityError("M23.6-ACCEPT-122 protected mutation was dispatched")

    rows = _sequence(root["chains"], "chains")
    wanted_chains = _sequence(expected["chains"], "expected chains")
    if len(rows) != len(wanted_chains):
        raise IntegrityError("M23.6-ACCEPT-123 seven evidence chains are required")
    normalized = [
        _validate_chain(row, wanted)
        for row, wanted in zip(rows, wanted_chains, strict=True)
    ]
    expected_order = [
        "M23.6.1",
        "M23.6.2",
        "M23.6.2a",
        "M23.6.3",
        "M23.6.4",
        "M23.6.5",
        "M23.6.6",
    ]
    if [row["milestone"] for row in normalized] != expected_order:
        raise IntegrityError("M23.6-ACCEPT-124 repair chain is missing or misordered")
    for previous, current in pairwise(normalized):
        if previous["reconciliation_merge"] != current["entry_base"]:
            raise IntegrityError("M23.6-ACCEPT-125 reconciliation chain is broken")
    if normalized[-1]["reconciliation_merge"] != FINAL_ENGINE_SHA:
        raise IntegrityError("M23.6-ACCEPT-126 final reconciliation mismatch")
    for key in ("issue", "implementation_pr", "reconciliation_pr"):
        if len({row[key] for row in normalized}) != len(normalized):
            raise IntegrityError(f"M23.6-ACCEPT-127 duplicate chain identity: {key}")

    return {
        **{key: root[key] for key in root if key != "chains"},
        "source_pr": source_pr,
        "qdrant": qdrant,
        "worker": worker,
        "runtime": runtime,
        "candidate_release": candidate,
        "explorer": explorer,
        "protected_state": dict(protected),
        "chains": normalized,
    }


def build_m23_6_acceptance_report(payload: Mapping[str, Any]) -> dict[str, Any]:
    normalized = validate_m23_6_acceptance(payload)
    return {
        "schema_version": "knowledge-engine-m23-6-acceptance-report/v1",
        "milestone": "M23.6.7",
        "status": "pass",
        "accepted_engine_sha": FINAL_ENGINE_SHA,
        "source_sha": SOURCE_SHA,
        "foundation_sha": FOUNDATION_SHA,
        "evidence_sha256": _sha(normalized),
        "chain_count": len(normalized["chains"]),
        "qdrant_point_count": normalized["qdrant"]["points_count"],
        "candidate_release_id": normalized["candidate_release"]["release_id"],
        "candidate_manifest_sha256": normalized["candidate_release"][
            "manifest_sha256"
        ],
        "rollback": {
            "mode": "lexical-only",
            "candidate_dependency_required": False,
            "immediate": True,
        },
        "production_authority": False,
        "protected_mutations_dispatched": False,
    }
