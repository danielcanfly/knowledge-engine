from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Literal

from .compiler_contract_v1 import put_immutable
from .errors import IntegrityError
from .m13_contracts import (
    BATCH_ID_RE,
    CANDIDATE_CHANNEL_RE,
    ExpectedPreviousProduction,
    M13BatchRecord,
    M13OperationRequest,
    M13OperationResult,
    ProductionIdentity,
    assert_expected_previous_production,
    stable_json_bytes,
)
from .m13_release_inventory import (
    ARTIFACT_TYPES,
    LoadedRelease,
    M13ReleaseInventoryError,
    ReleaseReference,
    load_release,
)
from .m13_retention import RetentionArtifact
from .release_quality_gate import GOVERNANCE_NO_WRITE
from .storage import ObjectStore, sha256_bytes

COMPARISON_SCHEMA = "knowledge-engine-m13-release-comparison/v1"
AudienceChange = Literal["unchanged", "narrowed", "broadened"]
_IDS = {
    "concepts": "concept_id",
    "claims": "claim_id",
    "audience": "audience_id",
    "citations": "citation_id",
    "registry": "registry_id",
    "indexes": "index_id",
}
_RANK = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}


class M13ReleaseComparisonError(ValueError):
    def __init__(self, code: str, message: str, **context: Any) -> None:
        super().__init__(f"{code}: {message}")
        self.code, self.message, self.context = code, message, context


def _utc(value: str, name: str) -> None:
    if not value.endswith("Z"):
        raise M13ReleaseComparisonError(
            "M13_COMPARISON_TIME_INVALID", f"{name} must end with Z"
        )
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise M13ReleaseComparisonError(
            "M13_COMPARISON_TIME_INVALID", f"{name} must be valid ISO-8601"
        ) from exc


@dataclass(frozen=True)
class ReleaseComparisonRequest:
    batch_id: str
    base_release: ReleaseReference
    target_release: ReleaseReference
    expected_previous_production: ProductionIdentity
    requested_by: str
    requested_at: str
    generated_at: str
    candidate_channel: str | None = None

    def __post_init__(self) -> None:
        if not BATCH_ID_RE.fullmatch(self.batch_id):
            raise M13ReleaseComparisonError(
                "M13_COMPARISON_BATCH_INVALID", "batch_id is invalid"
            )
        if self.candidate_channel is not None and not CANDIDATE_CHANNEL_RE.fullmatch(
            self.candidate_channel
        ):
            raise M13ReleaseComparisonError(
                "M13_COMPARISON_CHANNEL_INVALID", "candidate_channel is invalid"
            )
        if not self.requested_by.strip():
            raise M13ReleaseComparisonError(
                "M13_COMPARISON_ACTOR_REQUIRED", "requested_by is required"
            )
        _utc(self.requested_at, "requested_at")
        _utc(self.generated_at, "generated_at")
        if (
            self.base_release.release_id == self.target_release.release_id
            and self.base_release.manifest_sha256 != self.target_release.manifest_sha256
        ):
            raise M13ReleaseComparisonError(
                "M13_COMPARISON_RELEASE_ID_COLLISION",
                "one release_id cannot identify divergent manifests",
            )

    def to_identity(self) -> dict[str, Any]:
        return {
            "schema_version": f"{COMPARISON_SCHEMA}/request",
            "batch_id": self.batch_id,
            "candidate_channel": self.candidate_channel,
            "base_release": self.base_release.to_identity(),
            "target_release": self.target_release.to_identity(),
            "expected_previous_production": self.expected_previous_production.to_identity(),
            "requested_by": self.requested_by,
            "requested_at": self.requested_at,
            "generated_at": self.generated_at,
        }


@dataclass(frozen=True)
class ReleaseComparisonResult:
    comparison_id: str
    request: ReleaseComparisonRequest
    input_artifact_hashes: tuple[dict[str, str], ...]
    added_concepts: tuple[str, ...]
    removed_concepts: tuple[str, ...]
    changed_concepts: tuple[dict[str, Any], ...]
    added_claims: tuple[str, ...]
    removed_claims: tuple[str, ...]
    changed_claims: tuple[dict[str, Any], ...]
    audience_changes: tuple[dict[str, Any], ...]
    citation_changes: tuple[dict[str, Any], ...]
    registry_changes: tuple[dict[str, Any], ...]
    index_changes: tuple[dict[str, Any], ...]
    manifest_changes: tuple[dict[str, Any], ...]
    risk_summary: dict[str, Any]
    release_blockers: tuple[str, ...]
    generated_at: str
    artifact_key: str
    canonical_sha256: str
    governance: dict[str, bool]
    idempotent: bool = False

    def to_identity(self) -> dict[str, Any]:
        return {
            "schema_version": f"{COMPARISON_SCHEMA}/result",
            "comparison_id": self.comparison_id,
            "batch_id": self.request.batch_id,
            "candidate_channel": self.request.candidate_channel,
            "base_release": self.request.base_release.to_identity(),
            "target_release": self.request.target_release.to_identity(),
            "base_manifest_sha256": self.request.base_release.manifest_sha256,
            "target_manifest_sha256": self.request.target_release.manifest_sha256,
            "expected_previous_production": self.request.expected_previous_production.to_identity(),
            "input_artifact_hashes": list(self.input_artifact_hashes),
            "added_concepts": list(self.added_concepts),
            "removed_concepts": list(self.removed_concepts),
            "changed_concepts": list(self.changed_concepts),
            "added_claims": list(self.added_claims),
            "removed_claims": list(self.removed_claims),
            "changed_claims": list(self.changed_claims),
            "audience_changes": list(self.audience_changes),
            "citation_changes": list(self.citation_changes),
            "registry_changes": list(self.registry_changes),
            "index_changes": list(self.index_changes),
            "manifest_changes": list(self.manifest_changes),
            "risk_summary": self.risk_summary,
            "release_blockers": list(self.release_blockers),
            "governance": self.governance,
            "requested_by": self.request.requested_by,
            "requested_at": self.request.requested_at,
            "generated_at": self.generated_at,
            "artifact_key": self.artifact_key,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.to_identity(),
            "canonical_sha256": self.canonical_sha256,
            "idempotent": self.idempotent,
        }

    def canonical_bytes(self) -> bytes:
        return stable_json_bytes(self.to_identity())

    def operation_result(self) -> M13OperationResult:
        request = M13OperationRequest(
            kind="release_comparison",
            batch_id=self.request.batch_id,
            requested_by=self.request.requested_by,
            requested_at=self.request.requested_at,
            expected_previous_production=ExpectedPreviousProduction(
                production=self.request.expected_previous_production,
                checked_at=self.request.generated_at,
            ),
            artifact_names=(self.artifact_key,),
            planning_only=True,
            requires_production_slot=False,
        )
        return M13OperationResult(
            operation_id=request.operation_id(),
            request=request,
            state="completed",
            result_at=self.generated_at,
            evidence_refs=(self.artifact_key,),
        )

    def retention_artifact(self) -> RetentionArtifact:
        return RetentionArtifact(
            key=self.artifact_key,
            artifact_class="evidence",
            created_at=self.generated_at,
            sha256=self.canonical_sha256,
            batch_id=self.request.batch_id,
            candidate_channel=self.request.candidate_channel,
            reference_ids=(
                self.comparison_id,
                self.request.base_release.release_id,
                self.request.target_release.release_id,
            ),
        )


def _hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(stable_json_bytes(dict(value))).hexdigest()


def _entries(release: LoadedRelease, kind: str) -> dict[str, dict[str, Any]]:
    field = _IDS[kind]
    result: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for raw in release.artifact(kind)["entries"]:
        if not isinstance(raw, dict):
            raise M13ReleaseComparisonError(
                "M13_COMPARISON_ENTRY_INVALID",
                "release artifact entry must be an object",
                artifact_type=kind,
            )
        stable_id = raw.get(field)
        if not isinstance(stable_id, str) or not stable_id:
            raise M13ReleaseComparisonError(
                "M13_COMPARISON_STABLE_ID_MISSING",
                "entry lacks a stable identity",
                artifact_type=kind,
            )
        if stable_id in result:
            raise M13ReleaseComparisonError(
                "M13_COMPARISON_STABLE_ID_DUPLICATE",
                "duplicate stable identity",
                artifact_type=kind,
            )
        result[stable_id] = dict(raw)
        order.append(stable_id)
    if order != sorted(order):
        raise M13ReleaseComparisonError(
            "M13_COMPARISON_ENTRIES_UNSORTED",
            "entries must be sorted by stable identity",
            artifact_type=kind,
        )
    return result


def _diff(
    base: Mapping[str, dict[str, Any]], target: Mapping[str, dict[str, Any]]
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[dict[str, Any], ...]]:
    base_ids, target_ids = set(base), set(target)
    changed = tuple(
        {
            "stable_id": stable_id,
            "before_sha256": _hash(base[stable_id]),
            "after_sha256": _hash(target[stable_id]),
            "changed_fields": sorted(
                field
                for field in set(base[stable_id]) | set(target[stable_id])
                if base[stable_id].get(field) != target[stable_id].get(field)
            ),
        }
        for stable_id in sorted(base_ids & target_ids)
        if base[stable_id] != target[stable_id]
    )
    return (
        tuple(sorted(target_ids - base_ids)),
        tuple(sorted(base_ids - target_ids)),
        changed,
    )


def _audience(
    before: Mapping[str, Any] | None, after: Mapping[str, Any] | None
) -> AudienceChange:
    if before == after:
        return "unchanged"
    if before is None:
        return "broadened"
    if after is None:
        return "narrowed"
    before_level, after_level = before.get("audience"), after.get("audience")
    before_people, after_people = (
        before.get("principals", []),
        after.get("principals", []),
    )

    def valid_people(value: Any) -> bool:
        return isinstance(value, list) and all(isinstance(item, str) for item in value)

    if (
        before_level not in _RANK
        or after_level not in _RANK
        or not valid_people(before_people)
        or not valid_people(after_people)
    ):
        raise M13ReleaseComparisonError(
            "M13_COMPARISON_AUDIENCE_INVALID", "audience entry is invalid"
        )
    if len(before_people) != len(set(before_people)) or len(after_people) != len(
        set(after_people)
    ):
        raise M13ReleaseComparisonError(
            "M13_COMPARISON_AUDIENCE_INVALID", "audience principals duplicate"
        )
    if _RANK[after_level] < _RANK[before_level] or set(after_people) < set(
        before_people
    ):
        return "broadened"
    return "narrowed"


def _audience_changes(
    base: Mapping[str, dict[str, Any]], target: Mapping[str, dict[str, Any]]
) -> tuple[dict[str, Any], ...]:
    values = []
    for stable_id in sorted(set(base) | set(target)):
        before, after = base.get(stable_id), target.get(stable_id)
        classification = _audience(before, after)
        if classification != "unchanged":
            values.append(
                {
                    "audience_id": stable_id,
                    "classification": classification,
                    "before_sha256": _hash(before) if before is not None else None,
                    "after_sha256": _hash(after) if after is not None else None,
                    "before": before,
                    "after": after,
                }
            )
    return tuple(values)


def _typed(
    kind: str, base: Mapping[str, dict[str, Any]], target: Mapping[str, dict[str, Any]]
) -> tuple[dict[str, Any], ...]:
    added, removed, changed = _diff(base, target)
    values = [
        *(
            {"stable_id": value, "change_type": "added", "artifact_type": kind}
            for value in added
        ),
        *(
            {"stable_id": value, "change_type": "removed", "artifact_type": kind}
            for value in removed
        ),
        *(
            {**value, "change_type": "changed", "artifact_type": kind}
            for value in changed
        ),
    ]
    return tuple(
        sorted(values, key=lambda item: (item["stable_id"], item["change_type"]))
    )


def _manifest(base: LoadedRelease, target: LoadedRelease) -> tuple[dict[str, Any], ...]:
    values = [
        {
            "field": field,
            "before": base.manifest.get(field),
            "after": target.manifest.get(field),
        }
        for field in sorted(
            (set(base.manifest) | set(target.manifest)) - {"release_id", "artifacts"}
        )
        if base.manifest.get(field) != target.manifest.get(field)
    ]
    b = {item.artifact_type: item.to_identity() for item in base.artifacts}
    t = {item.artifact_type: item.to_identity() for item in target.artifacts}
    for kind in ARTIFACT_TYPES:
        if b[kind] != t[kind]:
            values.append(
                {
                    "field": f"artifacts.{kind}",
                    "before_sha256": b[kind]["sha256"],
                    "after_sha256": t[kind]["sha256"],
                    "before_bytes": b[kind]["bytes"],
                    "after_bytes": t[kind]["bytes"],
                    "before_schema_version": b[kind]["schema_version"],
                    "after_schema_version": t[kind]["schema_version"],
                }
            )
    return tuple(values)


def _ids(value: Any, name: str, stable_id: str) -> list[str]:
    if (
        not isinstance(value, list)
        or not all(isinstance(item, str) for item in value)
        or len(value) != len(set(value))
    ):
        raise M13ReleaseComparisonError(
            "M13_COMPARISON_SUPPORT_MAPPING_INVALID",
            f"{name} must be a unique string list",
            stable_id=stable_id,
        )
    return value


def _batch(request: ReleaseComparisonRequest, batch: M13BatchRecord | None) -> None:
    expected = request.expected_previous_production
    if (
        request.base_release.release_id != expected.release_id
        or request.base_release.manifest_sha256 != expected.manifest_sha256
    ):
        raise M13ReleaseComparisonError(
            "M13_COMPARISON_BASE_PRODUCTION_MISMATCH",
            "base release must equal expected production",
        )
    if batch is None:
        return
    if batch.batch_id != request.batch_id:
        raise M13ReleaseComparisonError(
            "M13_COMPARISON_BATCH_MISMATCH", "batch does not match"
        )
    if batch.state != "candidate_ready":
        raise M13ReleaseComparisonError(
            "M13_COMPARISON_BATCH_STATE_INVALID",
            "batch must be candidate_ready",
            state=batch.state,
        )
    if batch.seed.production != expected:
        raise M13ReleaseComparisonError(
            "M13_COMPARISON_BATCH_PRODUCTION_MISMATCH",
            "batch production does not match",
        )
    if (batch.seed.source_repository, batch.seed.source_commit_sha) != (
        request.target_release.source_repository,
        request.target_release.source_commit_sha,
    ):
        raise M13ReleaseComparisonError(
            "M13_COMPARISON_BATCH_SOURCE_MISMATCH", "target Source does not match batch"
        )
    if (
        batch.candidate_channel is not None
        and request.candidate_channel != batch.candidate_channel
    ):
        raise M13ReleaseComparisonError(
            "M13_COMPARISON_BATCH_CHANNEL_MISMATCH",
            "candidate channel does not match batch",
        )


def create_release_comparison(
    store: ObjectStore,
    request: ReleaseComparisonRequest,
    *,
    observed_production: ProductionIdentity,
    batch: M13BatchRecord | None = None,
) -> ReleaseComparisonResult:
    try:
        assert_expected_previous_production(
            expected=request.expected_previous_production, observed=observed_production
        )
    except ValueError as exc:
        raise M13ReleaseComparisonError(
            "M13_COMPARISON_EXPECTED_PRODUCTION_STALE", "expected production is stale"
        ) from exc
    _batch(request, batch)
    try:
        base, target = (
            load_release(store, request.base_release),
            load_release(store, request.target_release),
        )
    except M13ReleaseInventoryError as exc:
        raise M13ReleaseComparisonError(exc.code, exc.message, **exc.context) from exc

    entries = {
        kind: (_entries(base, kind), _entries(target, kind)) for kind in ARTIFACT_TYPES
    }
    added_concepts, removed_concepts, changed_concepts = _diff(*entries["concepts"])
    added_claims, removed_claims, changed_claims = _diff(*entries["claims"])
    audience_changes = _audience_changes(*entries["audience"])
    citation_changes = _typed("citations", *entries["citations"])
    registry_changes = _typed("registry", *entries["registry"])
    index_changes = _typed("indexes", *entries["indexes"])
    manifest_changes = _manifest(base, target)

    blockers = [
        f"audience_broadening:{change['audience_id']}"
        for change in audience_changes
        if change["classification"] == "broadened"
    ]
    claims_base, claims_target = entries["claims"]
    citations_base, citations_target = entries["citations"]
    for stable_id in added_claims:
        if not _ids(
            claims_target[stable_id].get("citation_ids"), "citation_ids", stable_id
        ):
            blockers.append(f"uncited_claim:{stable_id}")
    for stable_id in sorted(set(claims_base) & set(claims_target)):
        if set(
            _ids(
                claims_base[stable_id].get("citation_ids", []),
                "citation_ids",
                stable_id,
            )
        ) - set(
            _ids(
                claims_target[stable_id].get("citation_ids", []),
                "citation_ids",
                stable_id,
            )
        ):
            blockers.append(f"claim_support_removed:{stable_id}")
    for stable_id in sorted(set(citations_base) & set(citations_target)):
        if set(
            _ids(
                citations_base[stable_id].get("supports_claim_ids", []),
                "supports_claim_ids",
                stable_id,
            )
        ) - set(
            _ids(
                citations_target[stable_id].get("supports_claim_ids", []),
                "supports_claim_ids",
                stable_id,
            )
        ):
            blockers.append(f"citation_support_removed:{stable_id}")

    hash_values = [
        {"side": side, "key": key, "sha256": digest}
        for side, release in (("base", base), ("target", target))
        for key, digest in release.input_artifact_hashes
    ]
    input_hashes = tuple(
        sorted(hash_values, key=lambda item: (item["side"], item["key"]))
    )
    identity = {
        "schema_version": f"{COMPARISON_SCHEMA}/identity",
        "request": request.to_identity(),
        "input_artifact_hashes": list(input_hashes),
    }
    comparison_id = (
        "mcompare_" + hashlib.sha256(stable_json_bytes(identity)).hexdigest()[:32]
    )
    artifact_key = f"m13/v1/release-comparisons/{comparison_id}/result.json"
    risk = {
        "added_concepts": len(added_concepts),
        "removed_concepts": len(removed_concepts),
        "changed_concepts": len(changed_concepts),
        "added_claims": len(added_claims),
        "removed_claims": len(removed_claims),
        "changed_claims": len(changed_claims),
        "audience_broadened": sum(
            c["classification"] == "broadened" for c in audience_changes
        ),
        "audience_narrowed": sum(
            c["classification"] == "narrowed" for c in audience_changes
        ),
        "citation_changes": len(citation_changes),
        "registry_changes": len(registry_changes),
        "index_changes": len(index_changes),
        "manifest_changes": len(manifest_changes),
        "release_blocked": bool(blockers),
    }
    result = ReleaseComparisonResult(
        comparison_id=comparison_id,
        request=request,
        input_artifact_hashes=input_hashes,
        added_concepts=added_concepts,
        removed_concepts=removed_concepts,
        changed_concepts=changed_concepts,
        added_claims=added_claims,
        removed_claims=removed_claims,
        changed_claims=changed_claims,
        audience_changes=audience_changes,
        citation_changes=citation_changes,
        registry_changes=registry_changes,
        index_changes=index_changes,
        manifest_changes=manifest_changes,
        risk_summary=risk,
        release_blockers=tuple(sorted(set(blockers))),
        generated_at=request.generated_at,
        artifact_key=artifact_key,
        canonical_sha256="0" * 64,
        governance=dict(GOVERNANCE_NO_WRITE),
    )
    data = result.canonical_bytes()
    result = replace(result, canonical_sha256=sha256_bytes(data))
    try:
        replay = put_immutable(store, artifact_key, data)
    except IntegrityError as exc:
        raise M13ReleaseComparisonError(
            "M13_COMPARISON_IMMUTABLE_COLLISION",
            "comparison identity has divergent bytes",
            comparison_id=comparison_id,
            artifact_key=artifact_key,
        ) from exc
    return replace(result, idempotent=replay)
