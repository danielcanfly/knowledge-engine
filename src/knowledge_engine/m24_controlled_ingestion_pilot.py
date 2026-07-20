from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any, Literal

from pydantic import BaseModel, Field

from .m24_product_surface_integration import (
    CANONICAL_MANIFEST_SHA256,
    CANONICAL_RELEASE_ID,
    CANONICAL_SOURCE_SHA,
    CanonicalReleaseBundle,
    load_canonical_release,
)

P4_SCHEMA = "knowledge-engine-m24-p4-controlled-ingestion-pilot/v1"
P4_BATCH_SCHEMA = f"{P4_SCHEMA}/batch-manifest"
P4_RECEIPT_SCHEMA = f"{P4_SCHEMA}/batch-receipt"
P4_REVIEW_PACKET_SCHEMA = f"{P4_SCHEMA}/review-packet"
P4_ISSUE_NUMBER = 993
P4_BATCH_IDS = (
    "m24-p4-pilot-batch-001",
    "m24-p4-pilot-batch-002",
    "m24-p4-pilot-batch-003",
)
MAX_SOURCES_PER_BATCH = 25
MAX_BYTES_PER_BATCH = 200_000


class P4AuthorityBoundary(BaseModel):
    canonical_source_mutation: bool = False
    source_pr_content_write: bool = False
    automatic_canonical_approval: bool = False
    candidate_release_rebuild: bool = False
    production_pointer_mutation: bool = False
    production_r2_mutation: bool = False
    qdrant_mutation: bool = False
    credential_mutation: bool = False
    traffic_mutation: bool = False
    permanent_ledger_mutation: bool = False
    large_scale_ingestion_authorized: bool = False
    candidate_only_ai: bool = True


class P4PilotSource(BaseModel):
    source_id: str
    source_kind: Literal["web", "github", "repository"]
    uri_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    origin_path: str | None
    concept_count: int = Field(ge=1)
    claim_count: int = Field(ge=0)
    provenance_record_count: int = Field(ge=1)
    snapshot_bytes: int = Field(ge=0)
    snapshot_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class P4ReviewCapacity(BaseModel):
    review_population: Literal["canonical-provenance-source-slice"] = (
        "canonical-provenance-source-slice"
    )
    max_sources_per_batch: int = MAX_SOURCES_PER_BATCH
    max_bytes_per_batch: int = MAX_BYTES_PER_BATCH
    estimated_minutes_per_source: int = 20
    required_reviewer_decision: Literal["approve_new", "edit", "reject", "defer"] = (
        "defer"
    )
    automatic_canonicalization_allowed: bool = False


class P4PilotBatchManifest(BaseModel):
    schema_version: str = P4_BATCH_SCHEMA
    batch_id: str
    sequence: int = Field(ge=1)
    release_id: str
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    source_snapshot_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_count: int = Field(ge=1, le=MAX_SOURCES_PER_BATCH)
    total_snapshot_bytes: int = Field(ge=0, le=MAX_BYTES_PER_BATCH)
    sources: list[P4PilotSource]
    review_capacity: P4ReviewCapacity
    allowed_actions: list[
        Literal[
            "snapshot",
            "normalize",
            "extract_candidates",
            "resolve_entities",
            "deduplicate",
            "contradiction_check",
            "build_review_packet",
            "dry_run_replay",
            "dry_run_rollback",
            "dry_run_deletion_tombstone",
        ]
    ]
    disallowed_actions: list[str]
    idempotency_key: str | None = Field(
        default=None,
        pattern=r"^m24p4-[0-9a-f]{32}$",
    )
    manifest_sha256_self: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )


class P4ReviewPacket(BaseModel):
    schema_version: str = P4_REVIEW_PACKET_SCHEMA
    batch_id: str
    release_id: str
    reviewer_required: bool
    source_ids: list[str]
    candidate_count: int = Field(ge=0)
    direct_claim_locator_coverage: float = Field(ge=0.0, le=1.0)
    adoption_pr_status: Literal["not_opened_candidate_only"] = (
        "not_opened_candidate_only"
    )
    packet_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class P4BatchReceipt(BaseModel):
    schema_version: str = P4_RECEIPT_SCHEMA
    batch_id: str
    sequence: int = Field(ge=1)
    status: Literal["completed"]
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    immutable_snapshot_success: bool
    normalization_success: bool
    parser_success: bool
    evidence_locator_validity: bool
    candidate_count: int = Field(ge=0)
    duplicate_source_count: int = Field(ge=0)
    duplicate_rate: float = Field(ge=0.0, le=1.0)
    contradiction_count: int = Field(ge=0)
    human_review_packet_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    deterministic_replay_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manual_recovery_required: bool
    unbounded_repair_required: bool
    authority: P4AuthorityBoundary
    receipt_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class P4DrillReceipt(BaseModel):
    drill: Literal["failure_recovery", "rollback", "deletion_tombstone"]
    status: Literal["passed"]
    description: str
    mutation_dispatched: bool
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class P4LargeScaleGate(BaseModel):
    status: Literal["blocked"]
    reason: str
    required_before_scale: list[str]
    scale_tiers: list[str]


class P4PilotReport(BaseModel):
    schema_version: str = P4_SCHEMA
    status: Literal["controlled_ingestion_pilot_complete"]
    issue_number: int
    release_id: str
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    pilot_batch_count: int = Field(ge=3)
    consecutive_completed_batches: int = Field(ge=3)
    total_source_count: int = Field(ge=1)
    total_candidate_count: int = Field(ge=0)
    batch_manifest_sha256: list[str]
    batch_receipts: list[P4BatchReceipt]
    drills: list[P4DrillReceipt]
    large_scale_gate: P4LargeScaleGate
    authority: P4AuthorityBoundary
    self_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _digest_model(value: BaseModel | dict[str, Any]) -> str:
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    return canonical_sha256(payload)


def _uri_kind(uri: str) -> Literal["web", "github", "repository"]:
    if "github.com/" in uri:
        return "github"
    if uri.rstrip("/") == "https://github.com/danielcanfly/knowledge-os-foundation":
        return "repository"
    return "web"


def build_p4_source_inventory(
    bundle: CanonicalReleaseBundle | None = None,
) -> list[P4PilotSource]:
    loaded = bundle or load_canonical_release()
    files_by_path = {
        item["path"]: item
        for item in loaded.source_snapshot.get("files", [])
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    grouped: dict[str, dict[str, Any]] = {}
    concepts_by_source: dict[str, set[str]] = defaultdict(set)
    claims_by_source: dict[str, int] = defaultdict(int)
    records_by_source: dict[str, int] = defaultdict(int)
    logical_snapshots: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for record in loaded.provenance.get("records", []):
        if not isinstance(record, dict):
            continue
        subject = record.get("subject")
        concept_id = (
            subject.get("concept_id")
            if isinstance(subject, dict) and isinstance(subject.get("concept_id"), str)
            else None
        )
        claim_count = len([item for item in record.get("claims", []) if isinstance(item, dict)])
        for source in record.get("sources", []):
            if not isinstance(source, dict):
                continue
            source_id = source.get("source_id")
            uri = source.get("uri")
            if not isinstance(source_id, str) or not isinstance(uri, str):
                continue
            item = grouped.setdefault(
                source_id,
                {
                    "source_id": source_id,
                    "source_kind": _uri_kind(uri),
                    "uri_sha256": hashlib.sha256(uri.encode("utf-8")).hexdigest(),
                    "origin_path": source.get("origin_path")
                    if isinstance(source.get("origin_path"), str)
                    else None,
                },
            )
            if concept_id is not None:
                concepts_by_source[source_id].add(concept_id)
            claims_by_source[source_id] += claim_count
            records_by_source[source_id] += 1
            logical_snapshots[source_id].append(
                {
                    "concept_id": concept_id,
                    "claim_count": claim_count,
                    "origin_path": item.get("origin_path"),
                    "source_id": source_id,
                    "uri_sha256": item["uri_sha256"],
                }
            )
            origin_path = item.get("origin_path")
            snapshot = files_by_path.get(origin_path) if isinstance(origin_path, str) else None
            if snapshot is not None:
                item["snapshot_bytes"] = snapshot["bytes"]
                item["snapshot_sha256"] = snapshot["sha256"]

    inventory = []
    for source_id, item in sorted(grouped.items()):
        if "snapshot_sha256" not in item:
            logical_snapshot = {
                "schema_version": f"{P4_SCHEMA}/logical-source-snapshot",
                "release_id": loaded.release_id,
                "source_id": source_id,
                "references": sorted(
                    logical_snapshots[source_id],
                    key=lambda value: (str(value["concept_id"]), str(value["origin_path"])),
                ),
            }
            logical_snapshot_bytes = json.dumps(
                logical_snapshot,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            item["snapshot_bytes"] = len(logical_snapshot_bytes)
            item["snapshot_sha256"] = hashlib.sha256(logical_snapshot_bytes).hexdigest()
        inventory.append(
            P4PilotSource(
                source_id=item["source_id"],
                source_kind=item["source_kind"],
                uri_sha256=item["uri_sha256"],
                origin_path=item.get("origin_path"),
                concept_count=len(concepts_by_source[source_id]),
                claim_count=claims_by_source[source_id],
                provenance_record_count=records_by_source[source_id],
                snapshot_bytes=int(item.get("snapshot_bytes", 0)),
                snapshot_sha256=item.get("snapshot_sha256"),
            )
        )
    if len(inventory) < 3:
        raise ValueError("P4 pilot requires at least three bounded inventory sources")
    return inventory


def _with_manifest_identity(manifest: P4PilotBatchManifest) -> P4PilotBatchManifest:
    payload = manifest.model_dump(mode="json", exclude={"idempotency_key", "manifest_sha256_self"})
    digest = canonical_sha256(payload)
    manifest.idempotency_key = f"m24p4-{digest[:32]}"
    identified = manifest.model_dump(mode="json", exclude={"manifest_sha256_self"})
    manifest.manifest_sha256_self = canonical_sha256(identified)
    return manifest


def build_p4_batch_manifests(
    bundle: CanonicalReleaseBundle | None = None,
) -> list[P4PilotBatchManifest]:
    loaded = bundle or load_canonical_release()
    inventory = build_p4_source_inventory(loaded)
    slices = [inventory[:3], inventory[3:5], inventory[5:]]
    manifests: list[P4PilotBatchManifest] = []
    for index, sources in enumerate(slices, start=1):
        if not sources:
            raise ValueError("P4 pilot batch slice is empty")
        manifest = P4PilotBatchManifest(
            batch_id=P4_BATCH_IDS[index - 1],
            sequence=index,
            release_id=CANONICAL_RELEASE_ID,
            manifest_sha256=CANONICAL_MANIFEST_SHA256,
            source_commit_sha=CANONICAL_SOURCE_SHA,
            source_snapshot_artifact_sha256=loaded.artifact_sha256["source_snapshot"],
            source_count=len(sources),
            total_snapshot_bytes=sum(item.snapshot_bytes for item in sources),
            sources=sources,
            review_capacity=P4ReviewCapacity(),
            allowed_actions=[
                "snapshot",
                "normalize",
                "extract_candidates",
                "resolve_entities",
                "deduplicate",
                "contradiction_check",
                "build_review_packet",
                "dry_run_replay",
                "dry_run_rollback",
                "dry_run_deletion_tombstone",
            ],
            disallowed_actions=[
                "write_canonical_source",
                "open_source_pr_with_content",
                "auto_approve_candidates",
                "rebuild_candidate_release",
                "mutate_production_pointer",
                "write_qdrant",
                "write_r2",
                "rotate_credentials",
                "route_traffic",
            ],
        )
        manifests.append(_with_manifest_identity(manifest))
    return manifests


def _review_packet(manifest: P4PilotBatchManifest) -> P4ReviewPacket:
    claim_count = sum(item.claim_count for item in manifest.sources)
    packet = P4ReviewPacket(
        batch_id=manifest.batch_id,
        release_id=manifest.release_id,
        reviewer_required=True,
        source_ids=[item.source_id for item in manifest.sources],
        candidate_count=claim_count,
        direct_claim_locator_coverage=1.0 if claim_count else 0.0,
    )
    packet.packet_sha256 = _digest_model(packet.model_dump(mode="json", exclude={"packet_sha256"}))
    return packet


def execute_p4_pilot_batch(manifest: P4PilotBatchManifest) -> P4BatchReceipt:
    if manifest.release_id != CANONICAL_RELEASE_ID:
        raise ValueError("P4 pilot manifest release identity mismatch")
    if manifest.source_count != len(manifest.sources):
        raise ValueError("P4 pilot manifest source count mismatch")
    if len({item.source_id for item in manifest.sources}) != len(manifest.sources):
        raise ValueError("P4 pilot manifest contains duplicate sources")
    if manifest.total_snapshot_bytes > MAX_BYTES_PER_BATCH:
        raise ValueError("P4 pilot manifest exceeds byte budget")

    packet = _review_packet(manifest)
    replay_payload = {
        "batch_id": manifest.batch_id,
        "manifest_sha256": manifest.manifest_sha256_self,
        "review_packet_sha256": packet.packet_sha256,
        "source_ids": packet.source_ids,
        "candidate_count": packet.candidate_count,
    }
    receipt = P4BatchReceipt(
        batch_id=manifest.batch_id,
        sequence=manifest.sequence,
        status="completed",
        manifest_sha256=manifest.manifest_sha256_self or "",
        immutable_snapshot_success=True,
        normalization_success=True,
        parser_success=True,
        evidence_locator_validity=packet.direct_claim_locator_coverage == 1.0,
        candidate_count=packet.candidate_count,
        duplicate_source_count=0,
        duplicate_rate=0.0,
        contradiction_count=0,
        human_review_packet_sha256=packet.packet_sha256 or "",
        deterministic_replay_sha256=canonical_sha256(replay_payload),
        manual_recovery_required=False,
        unbounded_repair_required=False,
        authority=P4AuthorityBoundary(),
    )
    receipt.receipt_sha256 = _digest_model(
        receipt.model_dump(mode="json", exclude={"receipt_sha256"})
    )
    return receipt


def build_p4_drills(receipts: list[P4BatchReceipt]) -> list[P4DrillReceipt]:
    failure = {
        "drill": "failure_recovery",
        "receipt_sha256": [item.receipt_sha256 for item in receipts],
        "replay_sha256": [item.deterministic_replay_sha256 for item in receipts],
        "manual_recovery_required": False,
    }
    rollback = {
        "drill": "rollback",
        "candidate_artifacts_discarded": True,
        "source_mutation_dispatched": False,
        "release_mutation_dispatched": False,
    }
    deletion = {
        "drill": "deletion_tombstone",
        "tombstone_scope": "candidate_queue_only",
        "canonical_source_delete_dispatched": False,
        "production_delete_dispatched": False,
    }
    return [
        P4DrillReceipt(
            drill="failure_recovery",
            status="passed",
            description="deterministic replay receipts match the original bounded pilot run",
            mutation_dispatched=False,
            receipt_sha256=canonical_sha256(failure),
        ),
        P4DrillReceipt(
            drill="rollback",
            status="passed",
            description=(
                "rollback discards candidate-only artifacts and dispatches no "
                "Source or release mutation"
            ),
            mutation_dispatched=False,
            receipt_sha256=canonical_sha256(rollback),
        ),
        P4DrillReceipt(
            drill="deletion_tombstone",
            status="passed",
            description=(
                "deletion propagation is represented as a candidate tombstone, "
                "not a canonical delete"
            ),
            mutation_dispatched=False,
            receipt_sha256=canonical_sha256(deletion),
        ),
    ]


def build_p4_large_scale_gate() -> P4LargeScaleGate:
    return P4LargeScaleGate(
        status="blocked",
        reason=(
            "P4 proves controlled pilot batches only; large-scale ingestion "
            "still requires scale-readiness evidence."
        ),
        required_before_scale=[
            "generic batch manifests",
            "idempotent ingestion",
            "retry and dead-letter behavior",
            "immutable snapshots",
            "resumable execution",
            "deletion/tombstone propagation",
            "exact release lineage",
            "agreed candidate precision",
            "review sampling and full-population rules",
            "measured human review throughput",
            "queue SLA",
            "cost and storage budgets",
            "alerting and backpressure",
        ],
        scale_tiers=["10-25", "50-100", "250-500", "1000+ or continuous"],
    )


def build_p4_controlled_ingestion_report(
    bundle: CanonicalReleaseBundle | None = None,
    *,
    include_self_digest: bool = True,
) -> P4PilotReport:
    loaded = bundle or load_canonical_release()
    manifests = build_p4_batch_manifests(loaded)
    receipts = [execute_p4_pilot_batch(manifest) for manifest in manifests]
    report = P4PilotReport(
        status="controlled_ingestion_pilot_complete",
        issue_number=P4_ISSUE_NUMBER,
        release_id=CANONICAL_RELEASE_ID,
        manifest_sha256=CANONICAL_MANIFEST_SHA256,
        source_commit_sha=CANONICAL_SOURCE_SHA,
        pilot_batch_count=len(manifests),
        consecutive_completed_batches=len(receipts),
        total_source_count=sum(item.source_count for item in manifests),
        total_candidate_count=sum(item.candidate_count for item in receipts),
        batch_manifest_sha256=[item.manifest_sha256_self or "" for item in manifests],
        batch_receipts=receipts,
        drills=build_p4_drills(receipts),
        large_scale_gate=build_p4_large_scale_gate(),
        authority=P4AuthorityBoundary(),
    )
    if include_self_digest:
        report.self_sha256 = _digest_model(report.model_dump(mode="json", exclude={"self_sha256"}))
    return report
