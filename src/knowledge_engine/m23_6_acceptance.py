from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from .errors import IntegrityError

SOURCE_SHA = "a6ba738d910d01d2ae99b1968f0831989934c549"
FOUNDATION_SHA = "e5ef644053d34e89c70d2ceb37521e1c59234832"
FINAL_ENGINE_SHA = "66b3086145ff17700a4996a2bedc29c908faf349"

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

EXPECTED_SOURCE_PR = {
    "number": 19,
    "head_sha": "deb3ad1e631c2149183d10561fbceb0a1848a989",
    "state": "open",
    "draft": True,
    "merged": False,
    "canonical_write_permitted": False,
}

EXPECTED_QDRANT = {
    "collection": "llm_wiki_m23_pilot_bge_m3_1024",
    "vector_name": "default",
    "dimension": 1024,
    "distance": "Cosine",
    "points_count": 107,
    "preflight_points_count": 0,
    "postflight_points_count": 107,
    "ingestion_manifest_sha256": (
        "2814f138f2314779d77738f1e9bd3d0d0d7d388769244c3367232e5b278a0868"
    ),
    "qdrant_points_sha256": (
        "0f1178949a5eccd7dec6c41ad09da423d65ff88de3a2d91c4a01319bd964963b"
    ),
    "point_ids_sha256": (
        "907e3020819ac6fd1c50ff45a4e266f97494b1aee312a1adb00547955245d0d8"
    ),
    "aggregate_point_fingerprint_sha256": (
        "2b726f1b37ceb4b674752e25494abc9e4cb397b2d506452b9d7a94568d50bfd3"
    ),
    "pilot_release_id": "m23pilot-a07eb79e381ca7e635cc9139",
    "pilot_release_manifest_sha256": (
        "a07eb79e381ca7e635cc91397c322fd6ff57a62b5571a54866d26aefb734ebe9"
    ),
    "first_upsert_receipt_sha256": (
        "0e89d9971e6fd10505b5e36113e079629c444c371d01ac6d909d717270c7c21b"
    ),
    "all_expected_ids_present": True,
    "all_payloads_and_vectors_match": True,
    "canonical_knowledge": False,
    "candidate_release_eligible": False,
    "production_authority": False,
}

EXPECTED_WORKER = {
    "deployment_authorized": False,
    "queue_creation_authorized": False,
    "read_only_before_explicit_deployment": True,
    "max_messages_per_batch": 4,
    "max_sections_per_message": 25,
    "max_sections_per_run": 500,
    "max_sections_per_day": 2000,
    "max_concurrency": 2,
    "max_delivery_attempts": 3,
    "dlq_isolation": True,
    "idempotent_duplicate_skip": True,
    "optimistic_replace": True,
    "stale_event_rejection": True,
}

EXPECTED_RUNTIME = {
    "retrieval_mode": "lexical",
    "candidate_runtime_enabled": False,
    "shadow_semantic_enabled": False,
    "answer_generation_enabled": False,
    "multihop_mode": "off",
    "candidate_read_only": True,
    "lexical_output_authoritative": True,
    "semantic_output_served_to_production": False,
    "production_response_mutation_allowed": False,
}

EXPECTED_EXPLORER = {
    "graph_explorer_enabled": False,
    "internal_only": True,
    "read_only": True,
    "public_route_allowed": False,
    "browser_network_client_allowed": False,
    "browser_persistence_allowed": False,
    "write_back_allowed": False,
    "typed_graph_and_semantic_overlay_conflation_allowed": False,
    "graph_neural_retrieval_allowed": False,
}

EXPECTED_CANDIDATE = {
    "release_id": "m23cand-c7fbec7e945e79d05d3263b0",
    "manifest_sha256": (
        "3303a1d54d448c96c724178b482dc73daed2712ba8d09b0e34fa96eb8761e560"
    ),
    "graph_v2_sha256": (
        "9e87b4ee48ad6900d5b32d493ddaa3e2d05eca1dbfb4d52b87f4bc3ef15af380"
    ),
    "node_count": 15,
    "typed_edge_count": 12,
    "semantic_section_count": 107,
    "semantic_anchor_counts": {
        "pilot/harness-theory-part-01": 29,
        "pilot/harness-theory-part-02": 40,
        "pilot/harness-theory-part-03": 38,
    },
    "per_concept_section_attribution_available": False,
    "pending_human_review_count": 15,
    "canonical_knowledge": False,
    "candidate_release_eligible": False,
    "production_authority": False,
}


def _chain(
    milestone: str,
    issue: int,
    implementation_pr: int,
    reconciliation_pr: int,
    entry_base: str,
    implementation_head: str,
    implementation_merge: str,
    reconciliation_head: str,
    reconciliation_merge: str,
    workflows: tuple[tuple[str, int, int], ...],
) -> dict[str, Any]:
    return {
        "milestone": milestone,
        "issue": issue,
        "implementation_pr": implementation_pr,
        "reconciliation_pr": reconciliation_pr,
        "entry_base": entry_base,
        "implementation_head": implementation_head,
        "implementation_merge": implementation_merge,
        "reconciliation_head": reconciliation_head,
        "reconciliation_merge": reconciliation_merge,
        "workflows": workflows,
    }


EXPECTED_CHAINS = (
    _chain(
        "M23.6.1",
        384,
        385,
        386,
        "e6557ff8b3f6eb8ce7cd206df5bf0a4794ae34fb",
        "2a284811d36128ec44a16c694930e620b7ee485d",
        "620d0dba184d5bbda7e32a86fb7fb388017778fc",
        "832565fc6de72286c6c0d6c26a8707c26a0e62c8",
        "913c8cbb19dd6c7b89b753aecd61afd943e373fc",
        (
            ("M23.6.1 Pilot Authority Contract", 2, 29382687615),
            ("CI", 777, 29382687591),
            ("R2 Release Integration", 520, 29382687626),
            ("M17 Architecture Canon Acceptance", 125, 29382687589),
            ("M18 Graph v2 acceptance", 213, 29382687598),
        ),
    ),
    _chain(
        "M23.6.2",
        387,
        388,
        389,
        "913c8cbb19dd6c7b89b753aecd61afd943e373fc",
        "f9de0b5d7b351b2551f9cf68a36a31f5674acbfa",
        "f9c17811bc23f7af171686805c9c93e0ca7c78bd",
        "4a4bc3dc451566a33236a16e1d0de593fc7661b9",
        "8fd1e00632aebb2ab5af487fbcd626e9f8f3305f",
        (
            ("M23.6.2 Qdrant Ingestion Manifest", 2, 29384126418),
            ("CI", 782, 29384126447),
            ("R2 Release Integration", 523, 29384126419),
            ("M17 Architecture Canon Acceptance", 128, 29384126422),
            ("M18 Graph v2 acceptance", 218, 29384126491),
        ),
    ),
    _chain(
        "M23.6.2a",
        390,
        391,
        392,
        "8fd1e00632aebb2ab5af487fbcd626e9f8f3305f",
        "78cc20e1c076ce388a80553b0162f178a27d90bb",
        "067e5d70c8204d0976a917ef0ff2b2b9a0e8d932",
        "f19834c23878514aafc8f5e88e4a9ab04c102703",
        "43b6f2b0dd39ae0e7a19fbcce81272071a279dcf",
        (
            ("M23.6.2 Qdrant Ingestion Manifest", 8, 29388319749),
            ("CI", 790, 29388319797),
            ("R2 Release Integration", 529, 29388319742),
            ("M18 Graph v2 acceptance", 226, 29388319741),
        ),
    ),
    _chain(
        "M23.6.3",
        393,
        394,
        395,
        "43b6f2b0dd39ae0e7a19fbcce81272071a279dcf",
        "ae9dee012b0dcd12f4844c995a6b71cb5c2e5754",
        "152f8b41b4dc5aedd7e96b77a86a0ea6d60e93ab",
        "4f7ef218e5eaf9ba2f01edccbe18e91d86c5b578",
        "baa0fb9bf89bb216dbc34d3fb633b6eee706f029",
        (
            ("M23.6.2 Qdrant Ingestion Manifest", 9, 29389501188),
            ("CI", 795, 29389501184),
            ("R2 Release Integration", 532, 29389501190),
            ("M18 Graph v2 acceptance", 231, 29389501176),
        ),
    ),
    _chain(
        "M23.6.4",
        396,
        397,
        398,
        "baa0fb9bf89bb216dbc34d3fb633b6eee706f029",
        "2a5ce95d105484a77df5e5d7151c2c5e7238cd7d",
        "343bd53057868536b47179b97b32008e60ef00e3",
        "2b398db89d8bfbbc713681932fd7923778427c9c",
        "d0fb8b1b799d91b15520fd0bf8dacd093cf91e0d",
        (
            ("M23.6.4 Worker Queue Incremental Ingestion", 9, 29390704331),
            ("CI", 807, 29390704328),
            ("R2 Release Integration", 542, 29390704326),
            ("M17 Architecture Canon Acceptance", 140, 29390704361),
            ("M18 Graph v2 acceptance", 243, 29390704412),
        ),
    ),
    _chain(
        "M23.6.5",
        399,
        400,
        401,
        "d0fb8b1b799d91b15520fd0bf8dacd093cf91e0d",
        "26344362436f69c041723885aced788e5de007e3",
        "daafeb7d0a295e1434e1487dc2b5e0ab1e5bad24",
        "f1aa162d916199b1add01bbc39bac11882787e8f",
        "0eecc89bb711e7df8976a79d46bcd2d1072be44a",
        (
            ("M23.6.5 Candidate Semantic Runtime", 2, 29391633413),
            ("CI", 812, 29391633387),
            ("R2 Release Integration", 545, 29391633375),
            ("M17 Architecture Canon Acceptance", 143, 29391633403),
            ("M18 Graph v2 acceptance", 248, 29391633399),
        ),
    ),
    _chain(
        "M23.6.6",
        402,
        403,
        404,
        "0eecc89bb711e7df8976a79d46bcd2d1072be44a",
        "2a5a9ea181d0ed35f9e46b89139e2d2103b96804",
        "22cc6c51dac5c21251ed6350b40c94e452143e10",
        "3e53ad6dd6c2ba6b79dfc56c72ab3377e8dd5ce9",
        FINAL_ENGINE_SHA,
        (
            ("M23.6.6 Candidate Release and Internal Explorer", 1, 29392785481),
            ("CI", 816, 29392785495),
            ("R2 Release Integration", 547, 29392785435),
            ("M17 Architecture Canon Acceptance", 145, 29392785470),
            ("M18 Graph v2 acceptance", 252, 29392785456),
            ("M19.3 Sigma explorer shell", 13, 29392785472),
            ("M19.4 graph explorer interactions", 11, 29392785457),
            ("M19.5 detail provenance panels", 9, 29392785443),
            ("M19.6 large graph strategy", 7, 29392785449),
            ("M19.7 Phase B acceptance", 5, 29392785460),
        ),
    ),
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


def _exact_mapping(
    value: Any, expected: Mapping[str, Any], label: str
) -> dict[str, Any]:
    item = _mapping(value, label)
    if dict(item) != dict(expected):
        raise IntegrityError(f"M23.6-ACCEPT-103 {label} identity mismatch")
    return dict(item)


def _workflow_rows(expected: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "run_number": run_number,
            "run_id": run_id,
            "head_sha": expected["implementation_head"],
            "conclusion": "success",
        }
        for name, run_number, run_id in expected["workflows"]
    ]


def canonical_acceptance_evidence() -> dict[str, Any]:
    chain_identity_fields = (
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
    return {
        "schema_version": "knowledge-engine-m23-6-acceptance-evidence/v1",
        "engine_sha": FINAL_ENGINE_SHA,
        "source_sha": SOURCE_SHA,
        "foundation_sha": FOUNDATION_SHA,
        "source_pr": dict(EXPECTED_SOURCE_PR),
        "qdrant": dict(EXPECTED_QDRANT),
        "worker": dict(EXPECTED_WORKER),
        "runtime": dict(EXPECTED_RUNTIME),
        "candidate_release": {
            **EXPECTED_CANDIDATE,
            "semantic_anchor_counts": dict(
                EXPECTED_CANDIDATE["semantic_anchor_counts"]
            ),
        },
        "explorer": dict(EXPECTED_EXPLORER),
        "chains": [
            {
                **{key: expected[key] for key in chain_identity_fields},
                "issue_completed": True,
                "implementation_merged": True,
                "reconciliation_merged": True,
                "implementation_expected_head_merge": True,
                "reconciliation_expected_head_merge": True,
                "workflows": _workflow_rows(expected),
            }
            for expected in EXPECTED_CHAINS
        ],
        "protected_state": {key: False for key in PROTECTED_MUTATION_KEYS},
    }


def _validate_workflows(
    value: Any, expected: Mapping[str, Any]
) -> list[dict[str, Any]]:
    rows = _sequence(value, f"{expected['milestone']}.workflows")
    wanted = _workflow_rows(expected)
    if len(rows) != len(wanted):
        raise IntegrityError(
            f"M23.6-ACCEPT-104 {expected['milestone']} workflow count mismatch"
        )
    normalized: list[dict[str, Any]] = []
    required_keys = {"name", "run_number", "run_id", "head_sha", "conclusion"}
    for actual, required in zip(rows, wanted, strict=True):
        item = _mapping(actual, "workflow")
        if set(item) != required_keys:
            raise IntegrityError("M23.6-ACCEPT-105 workflow shape mismatch")
        if dict(item) != required:
            raise IntegrityError("M23.6-ACCEPT-106 workflow evidence mismatch")
        normalized.append(dict(item))
    identities = {
        (item["name"], item["run_number"], item["run_id"])
        for item in normalized
    }
    if len(identities) != len(normalized):
        raise IntegrityError("M23.6-ACCEPT-107 duplicate workflow evidence")
    return normalized


def _validate_chain(value: Any, expected: Mapping[str, Any]) -> dict[str, Any]:
    item = _mapping(value, "chain")
    if set(item) != CHAIN_FIELDS:
        raise IntegrityError("M23.6-ACCEPT-108 chain shape mismatch")
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
                f"M23.6-ACCEPT-109 {expected['milestone']} {key} mismatch"
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
                f"M23.6-ACCEPT-110 {expected['milestone']} incomplete state: {key}"
            )
    return {
        **{key: item[key] for key in item if key != "workflows"},
        "workflows": _validate_workflows(item["workflows"], expected),
    }


def validate_m23_6_acceptance(payload: Mapping[str, Any]) -> dict[str, Any]:
    root = _mapping(payload, "acceptance")
    expected_keys = {
        "schema_version",
        "engine_sha",
        "source_sha",
        "foundation_sha",
        "source_pr",
        "qdrant",
        "worker",
        "runtime",
        "candidate_release",
        "explorer",
        "chains",
        "protected_state",
    }
    if set(root) != expected_keys:
        raise IntegrityError("M23.6-ACCEPT-111 root shape mismatch")
    if root["schema_version"] != "knowledge-engine-m23-6-acceptance-evidence/v1":
        raise IntegrityError("M23.6-ACCEPT-112 unsupported schema")
    if root["engine_sha"] != FINAL_ENGINE_SHA:
        raise IntegrityError("M23.6-ACCEPT-113 final Engine identity mismatch")
    if root["source_sha"] != SOURCE_SHA or root["foundation_sha"] != FOUNDATION_SHA:
        raise IntegrityError("M23.6-ACCEPT-114 governed identity mismatch")

    source_pr = _exact_mapping(root["source_pr"], EXPECTED_SOURCE_PR, "source_pr")
    qdrant = _exact_mapping(root["qdrant"], EXPECTED_QDRANT, "qdrant")
    worker = _exact_mapping(root["worker"], EXPECTED_WORKER, "worker")
    runtime = _exact_mapping(root["runtime"], EXPECTED_RUNTIME, "runtime")
    candidate = _exact_mapping(
        root["candidate_release"], EXPECTED_CANDIDATE, "candidate_release"
    )
    explorer = _exact_mapping(root["explorer"], EXPECTED_EXPLORER, "explorer")

    if sum(candidate["semantic_anchor_counts"].values()) != qdrant["points_count"]:
        raise IntegrityError("M23.6-ACCEPT-115 semantic anchors do not cover 107 points")
    if candidate["per_concept_section_attribution_available"] is not False:
        raise IntegrityError("M23.6-ACCEPT-116 invented per-concept attribution")
    if runtime["retrieval_mode"] != "lexical":
        raise IntegrityError("M23.6-ACCEPT-117 lexical rollback is not preserved")
    if runtime["lexical_output_authoritative"] is not True:
        raise IntegrityError("M23.6-ACCEPT-118 lexical output is not authoritative")
    if explorer["typed_graph_and_semantic_overlay_conflation_allowed"] is not False:
        raise IntegrityError("M23.6-ACCEPT-119 graph and semantic layers were conflated")

    protected = _mapping(root["protected_state"], "protected_state")
    if set(protected) != set(PROTECTED_MUTATION_KEYS):
        raise IntegrityError("M23.6-ACCEPT-120 protected state is incomplete")
    if any(protected[key] is not False for key in PROTECTED_MUTATION_KEYS):
        raise IntegrityError("M23.6-ACCEPT-121 protected mutation was dispatched")

    rows = _sequence(root["chains"], "chains")
    if len(rows) != len(EXPECTED_CHAINS):
        raise IntegrityError("M23.6-ACCEPT-122 seven evidence chains are required")
    normalized = [
        _validate_chain(row, expected)
        for row, expected in zip(rows, EXPECTED_CHAINS, strict=True)
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
        raise IntegrityError("M23.6-ACCEPT-123 repair chain is missing or misordered")
    for previous, current in zip(normalized, normalized[1:], strict=True):
        if previous["reconciliation_merge"] != current["entry_base"]:
            raise IntegrityError("M23.6-ACCEPT-124 reconciliation chain is broken")
    if normalized[-1]["reconciliation_merge"] != FINAL_ENGINE_SHA:
        raise IntegrityError("M23.6-ACCEPT-125 final reconciliation mismatch")
    for key in ("issue", "implementation_pr", "reconciliation_pr"):
        if len({row[key] for row in normalized}) != len(normalized):
            raise IntegrityError(f"M23.6-ACCEPT-126 duplicate chain identity: {key}")

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
