from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from .database_bundle import (
    DEFAULT_MAX_CHILD_OBJECTS,
    DEFAULT_MAX_COLUMNS,
    DEFAULT_MAX_METADATA_BYTES,
    DEFAULT_MAX_RELATIONS,
    DEFAULT_MAX_SCHEMAS,
    DatabaseAccess,
    DatabaseBundle,
    LocalDatabaseBundleReader,
    render_derivative,
)
from .intake_v1 import (
    AUDIENCES,
    SNAPSHOT_ID_RE,
    SOURCE_ID_RE,
    AccessPolicy,
    EvidenceValue,
    IntakeFailure,
    IntakeResult,
    _event,
    _event_keys,
    _pretty_json_bytes,
    _prompt_findings,
    _put_immutable,
    _reject,
    _secret_matches,
    _storage_location,
    _validate_utc,
    _write_event,
    _write_output,
    canonical_json_bytes,
    derivative_id_for,
    snapshot_id_for,
    stable_source_id,
)
from .storage import ObjectStore, sha256_bytes

CONNECTOR_TYPE = "database_metadata_export"
CONNECTOR_VERSION = "database-metadata-export/1.0.0"
NORMALIZER_ID = "database_metadata_markdown"
NORMALIZER_VERSION = "1.0.0"
AUDIENCE_RANK = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}
POLICY_RANK = {
    "public": 0,
    "authenticated": 1,
    "principal_set": 2,
    "restricted": 3,
    "unresolved": 4,
}


@dataclass(frozen=True)
class DatabaseMetadataRequest:
    locator: str
    retrieved_at: str
    owner: EvidenceValue
    license: EvidenceValue
    audience: str
    access_policy: AccessPolicy
    source_id: str | None = None
    parent_snapshot: str | None = None
    max_metadata_bytes: int = DEFAULT_MAX_METADATA_BYTES
    max_schemas: int = DEFAULT_MAX_SCHEMAS
    max_relations: int = DEFAULT_MAX_RELATIONS
    max_columns: int = DEFAULT_MAX_COLUMNS
    max_children: int = DEFAULT_MAX_CHILD_OBJECTS

    def validate(self) -> None:
        if not self.locator or self.locator.strip() != self.locator:
            raise IntakeFailure("INVALID_LOCATOR", "request", "database bundle locator is required")
        _validate_utc(self.retrieved_at)
        self.owner.validate("owner")
        self.license.validate("license")
        if self.audience not in AUDIENCES:
            raise IntakeFailure("INVALID_METADATA", "request", "invalid audience")
        self.access_policy.validate(audience=self.audience)
        if self.source_id is not None and SOURCE_ID_RE.fullmatch(self.source_id) is None:
            raise IntakeFailure("INVALID_METADATA", "request", "invalid source_id")
        if self.parent_snapshot is not None and SNAPSHOT_ID_RE.fullmatch(
            self.parent_snapshot
        ) is None:
            raise IntakeFailure("INVALID_METADATA", "request", "invalid parent_snapshot")
        if not 1 <= self.max_metadata_bytes <= DEFAULT_MAX_METADATA_BYTES:
            raise IntakeFailure("INVALID_METADATA", "request", "max_metadata_bytes is outside policy")
        if not 1 <= self.max_schemas <= 10_000:
            raise IntakeFailure("INVALID_METADATA", "request", "max_schemas is outside policy")
        if not 1 <= self.max_relations <= 100_000:
            raise IntakeFailure("INVALID_METADATA", "request", "max_relations is outside policy")
        if not 1 <= self.max_columns <= 1_000_000:
            raise IntakeFailure("INVALID_METADATA", "request", "max_columns is outside policy")
        if not 1 <= self.max_children <= 2_000_000:
            raise IntakeFailure("INVALID_METADATA", "request", "max_children is outside policy")

    def attempt_id(self) -> str:
        payload = {
            "schema_version": "intake-attempt/v1",
            "connector_type": CONNECTOR_TYPE,
            "locator": self.locator,
            "retrieved_at": self.retrieved_at,
            "owner": self.owner.to_dict(),
            "license": self.license.to_dict(),
            "audience": self.audience,
            "access_policy": self.access_policy.to_dict(),
            "source_id": self.source_id,
            "parent_snapshot": self.parent_snapshot,
            "max_metadata_bytes": self.max_metadata_bytes,
            "max_schemas": self.max_schemas,
            "max_relations": self.max_relations,
            "max_columns": self.max_columns,
            "max_children": self.max_children,
        }
        return "attempt_" + sha256_bytes(canonical_json_bytes(payload))[:32]


def _validate_non_broadening(request: DatabaseMetadataRequest, access: DatabaseAccess) -> None:
    if POLICY_RANK[request.access_policy.policy_type] < POLICY_RANK[access.policy_type]:
        raise IntakeFailure(
            "DATABASE_ACL_BROADENING",
            "admission",
            "requested access policy is broader than database ACL evidence",
        )
    if AUDIENCE_RANK[request.audience] < AUDIENCE_RANK[access.minimum_audience]:
        raise IntakeFailure(
            "DATABASE_ACL_BROADENING",
            "admission",
            "requested audience is broader than database ACL evidence",
        )
    if access.policy_type == "unresolved":
        if request.access_policy.policy_type != "unresolved":
            raise IntakeFailure("ACL_UNRESOLVED", "admission", "database ACL evidence is unresolved")
        return
    if access.policy_type in {"authenticated", "principal_set"} and request.access_policy.policy_type in {
        "authenticated",
        "principal_set",
    }:
        requested = set(request.access_policy.principals)
        if not requested or not requested.issubset(set(access.principal_hashes)):
            raise IntakeFailure(
                "DATABASE_ACL_PRINCIPAL_MISMATCH",
                "admission",
                "requested principals are not proven by database ACL evidence",
            )


def _raw_keys(bundle: DatabaseBundle) -> tuple[str, str]:
    metadata_hash = bundle.manifest.metadata_sha256
    manifest_hash = bundle.manifest.manifest_sha256
    return (
        f"intake/v1/raw/sha256/{metadata_hash[:2]}/{metadata_hash}",
        f"intake/v1/raw/sha256/{manifest_hash[:2]}/{manifest_hash}",
    )


def _evidence(
    *,
    attempt_id: str,
    source_id: str,
    bundle: DatabaseBundle | None,
    failure: IntakeFailure | None,
) -> dict[str, Any]:
    manifest = bundle.manifest if bundle is not None else None
    metadata_raw_key = None
    manifest_raw_key = None
    counts = None
    if bundle is not None:
        metadata_raw_key, manifest_raw_key = _raw_keys(bundle)
        counts = bundle.metadata.counts
    return {
        "schema_version": "database-acquisition-evidence/v1",
        "attempt_id": attempt_id,
        "source_id": source_id,
        "connector_type": CONNECTOR_TYPE,
        "connector_version": CONNECTOR_VERSION,
        "source_uri_sha256": manifest.source_uri_sha256 if manifest else None,
        "database_id_sha256": manifest.database_id_sha256 if manifest else None,
        "database_name_sha256": manifest.database_name_sha256 if manifest else None,
        "engine": manifest.engine if manifest else None,
        "engine_version": manifest.engine_version if manifest else None,
        "migration_head_sha256": manifest.migration_head_sha256 if manifest else None,
        "collected_at": manifest.collected_at if manifest else None,
        "metadata": (
            {
                "sha256": manifest.metadata_sha256,
                "byte_size": manifest.metadata_byte_size,
                "raw_key": metadata_raw_key,
                "canonical_sha256": sha256_bytes(bundle.metadata.canonical_bytes),
            }
            if manifest and bundle
            else None
        ),
        "manifest": (
            {
                "sha256": manifest.manifest_sha256,
                "byte_size": len(bundle.manifest_bytes),
                "raw_key": manifest_raw_key,
            }
            if manifest and bundle
            else None
        ),
        "counts": counts,
        "access": (
            {
                "policy_type": manifest.access.policy_type,
                "minimum_audience": manifest.access.minimum_audience,
                "principal_count": len(manifest.access.principal_hashes),
                "observation_source": manifest.access.observation_source,
                "native_evidence_sha256": manifest.access.native_evidence_sha256,
                "digest": manifest.access.digest,
            }
            if manifest
            else None
        ),
        "collector": (
            {"tool": manifest.collector_tool, "version": manifest.collector_version}
            if manifest
            else None
        ),
        "bundle_policy": {
            "local_only": True,
            "network_enabled": False,
            "database_connection_enabled": False,
            "driver_import_enabled": False,
            "sql_execution_enabled": False,
            "migration_execution_enabled": False,
            "subprocess_enabled": False,
            "shell_enabled": False,
            "row_data_allowed": False,
            "sample_values_allowed": False,
            "row_counts_allowed": False,
            "sql_or_ddl_bodies_allowed": False,
            "connection_fields_allowed": False,
            "credential_fields_allowed": False,
            "symlinks_allowed": False,
            "hardlinks_allowed": False,
            "metadata_names_persisted_in_evidence": False,
        },
        "outcome": "accepted" if failure is None else "rejected",
        "failure_code": failure.code if failure else None,
        "safe_context": failure.safe_context if failure else {},
    }


def _safety_text(bundle: DatabaseBundle) -> str:
    return bundle.manifest_bytes.decode("utf-8") + "\n" + bundle.metadata_bytes.decode("utf-8")


def intake_database_metadata(
    *,
    store: ObjectStore,
    request: DatabaseMetadataRequest,
    allowed_root: Path,
    output_dir: Path | None = None,
) -> IntakeResult:
    """Acquire one bounded offline database metadata evidence bundle."""

    attempt_id = request.attempt_id()
    events: list[dict[str, Any]] = []
    object_states: list[bool] = []
    artifacts: dict[str, Any] = {}
    current_state: str | None = None
    bundle: DatabaseBundle | None = None
    evidence_key: str | None = None
    evidence_written = False

    try:
        request.validate()
        reader = LocalDatabaseBundleReader(allowed_root)
        bundle = reader.read(
            request.locator,
            max_metadata_bytes=request.max_metadata_bytes,
            max_schemas=request.max_schemas,
            max_relations=request.max_relations,
            max_columns=request.max_columns,
            max_children=request.max_children,
        )
        manifest = bundle.manifest
        _validate_non_broadening(request, manifest.access)
        canonical_locator = f"database-metadata://{manifest.engine}/{manifest.database_id_sha256}"
        source_id = request.source_id or stable_source_id(CONNECTOR_TYPE, canonical_locator)
        artifacts["source_id"] = source_id
        evidence_key = f"intake/v1/attempts/{attempt_id}/database-acquisition.json"
        artifacts["database_evidence_key"] = evidence_key

        discovered = _event(
            attempt_id=attempt_id,
            sequence=1,
            occurred_at=request.retrieved_at,
            from_state=None,
            to_state="discovered",
            reason_code="SOURCE_DISCOVERED",
            evidence_refs=[
                f"database_id_sha256:{manifest.database_id_sha256}",
                f"manifest_sha256:{manifest.manifest_sha256}",
            ],
            previous_event_sha256=None,
        )
        _, reused = _write_event(store, discovered)
        events.append(discovered)
        object_states.append(reused)
        current_state = "discovered"

        acquired = _event(
            attempt_id=attempt_id,
            sequence=2,
            occurred_at=request.retrieved_at,
            from_state="discovered",
            to_state="acquired",
            reason_code="SOURCE_ACQUIRED",
            evidence_refs=[
                f"metadata_sha256:{manifest.metadata_sha256}",
                f"canonical_sha256:{sha256_bytes(bundle.metadata.canonical_bytes)}",
                f"access_digest:{manifest.access.digest}",
            ],
            previous_event_sha256=events[-1]["event_sha256"],
        )
        _, reused = _write_event(store, acquired)
        events.append(acquired)
        object_states.append(reused)
        current_state = "acquired"

        safety_text = _safety_text(bundle)
        secret_matches = _secret_matches(safety_text)
        if secret_matches:
            raise IntakeFailure(
                "SECRET_LIKE_CONTENT",
                "safety_gate",
                "database metadata evidence contains secret-like content",
                safe_context={
                    "patterns": secret_matches,
                    "metadata_sha256": manifest.metadata_sha256,
                    "manifest_sha256": manifest.manifest_sha256,
                },
            )
        normalized = render_derivative(manifest, bundle.metadata)
        warnings = _prompt_findings(safety_text)

        evidence = _evidence(
            attempt_id=attempt_id,
            source_id=source_id,
            bundle=bundle,
            failure=None,
        )
        evidence_bytes = _pretty_json_bytes(evidence)
        object_states.append(
            _put_immutable(store, evidence_key, evidence_bytes, content_type="application/json")
        )
        evidence_written = True

        metadata_raw_key, manifest_raw_key = _raw_keys(bundle)
        metadata_reused = _put_immutable(
            store,
            metadata_raw_key,
            bundle.metadata_bytes,
            content_type="application/json",
        )
        manifest_reused = _put_immutable(
            store,
            manifest_raw_key,
            bundle.manifest_bytes,
            content_type="application/json",
        )
        object_states.extend([metadata_reused, manifest_reused])
        artifacts.update(
            raw_blob_key=metadata_raw_key,
            raw_blob_reused=metadata_reused,
            manifest_raw_key=manifest_raw_key,
            manifest_raw_reused=manifest_reused,
        )

        acl_status = (
            "unresolved"
            if request.access_policy.policy_type == "unresolved"
            or request.access_policy.observation_source == "unresolved"
            or manifest.access.policy_type == "unresolved"
            else "resolved"
        )
        identity = {
            "schema_version": "intake-snapshot/v1",
            "source_id": source_id,
            "original_uri": canonical_locator,
            "connector_type": CONNECTOR_TYPE,
            "connector_version": CONNECTOR_VERSION,
            "retrieved_at": request.retrieved_at,
            "content_hash": manifest.metadata_sha256,
            "byte_size": manifest.metadata_byte_size,
            "mime_type": "application/json",
            "encoding": "utf-8",
            "license": request.license.to_dict(),
            "owner": request.owner.to_dict(),
            "audience": request.audience,
            "access_policy": request.access_policy.to_dict(),
            "source_version": (
                f"database:{manifest.database_id_sha256}:{manifest.metadata_sha256}:"
                f"{manifest.manifest_sha256}:{manifest.migration_head_sha256}:"
                f"{manifest.collected_at}:{manifest.access.digest}"
            ),
            "parent_snapshot": request.parent_snapshot,
        }
        snapshot_id = snapshot_id_for(identity)
        snapshot_key = f"intake/v1/snapshots/{source_id}/{snapshot_id}/snapshot.json"
        snapshot = {
            **identity,
            "snapshot_id": snapshot_id,
            "acl_status": acl_status,
            "storage_location": _storage_location(
                store,
                metadata_raw_key,
                manifest.metadata_sha256,
            ),
        }
        snapshot_bytes = _pretty_json_bytes(snapshot)
        object_states.append(
            _put_immutable(store, snapshot_key, snapshot_bytes, content_type="application/json")
        )
        artifacts.update(snapshot_id=snapshot_id, snapshot_key=snapshot_key)

        snapshotted = _event(
            attempt_id=attempt_id,
            sequence=3,
            occurred_at=request.retrieved_at,
            from_state="acquired",
            to_state="snapshotted",
            reason_code="SNAPSHOT_WRITTEN",
            evidence_refs=[metadata_raw_key, manifest_raw_key, snapshot_key, evidence_key],
            previous_event_sha256=events[-1]["event_sha256"],
        )
        _, reused = _write_event(store, snapshotted)
        events.append(snapshotted)
        object_states.append(reused)
        current_state = "snapshotted"

        normalized_hash = sha256_bytes(normalized)
        derivative_id = derivative_id_for(
            snapshot_id=snapshot_id,
            normalizer_id=NORMALIZER_ID,
            normalizer_version=NORMALIZER_VERSION,
            normalized_content_hash=normalized_hash,
        )
        normalized_key = (
            f"intake/v1/normalized/{snapshot_id}/{NORMALIZER_ID}/"
            f"{NORMALIZER_VERSION}/{normalized_hash}.md"
        )
        derivative_key = (
            f"intake/v1/normalized/{snapshot_id}/{NORMALIZER_ID}/"
            f"{NORMALIZER_VERSION}/derivative.json"
        )
        object_states.append(
            _put_immutable(store, normalized_key, normalized, content_type="text/markdown")
        )
        derivative = {
            "schema_version": "intake-derivative/v1",
            "derivative_id": derivative_id,
            "snapshot_id": snapshot_id,
            "normalizer_id": NORMALIZER_ID,
            "normalizer_version": NORMALIZER_VERSION,
            "normalized_content_hash": normalized_hash,
            "normalized_key": normalized_key,
            "byte_size": len(normalized),
            "mime_type": "text/markdown",
            "warnings": warnings,
            "database_evidence_key": evidence_key,
            "metadata_raw_key": metadata_raw_key,
            "manifest_raw_key": manifest_raw_key,
            "manifest_sha256": manifest.manifest_sha256,
            "database_id_sha256": manifest.database_id_sha256,
            "engine": manifest.engine,
            "engine_version": manifest.engine_version,
            "migration_head_sha256": manifest.migration_head_sha256,
            "counts": bundle.metadata.counts,
            "content_policy": "schema_metadata_only_no_rows_no_sql_bodies_no_credentials",
        }
        derivative_bytes = _pretty_json_bytes(derivative)
        object_states.append(
            _put_immutable(store, derivative_key, derivative_bytes, content_type="application/json")
        )
        artifacts.update(
            derivative_id=derivative_id,
            normalized_key=normalized_key,
            derivative_key=derivative_key,
        )

        normalized_event = _event(
            attempt_id=attempt_id,
            sequence=4,
            occurred_at=request.retrieved_at,
            from_state="snapshotted",
            to_state="normalized",
            reason_code="DERIVATIVE_WRITTEN",
            evidence_refs=[normalized_key, derivative_key, evidence_key],
            previous_event_sha256=events[-1]["event_sha256"],
        )
        _, reused = _write_event(store, normalized_event)
        events.append(normalized_event)
        object_states.append(reused)
        current_state = "normalized"

        if acl_status != "resolved" or request.owner.status != "resolved":
            raise IntakeFailure(
                "ACL_UNRESOLVED",
                "admission",
                "ACL or ownership is unresolved",
                safe_context={"snapshot_id": snapshot_id},
            )
        if request.license.status != "resolved":
            raise IntakeFailure(
                "LICENSE_UNRESOLVED",
                "admission",
                "license is unresolved",
                safe_context={"snapshot_id": snapshot_id},
            )

        accepted = _event(
            attempt_id=attempt_id,
            sequence=5,
            occurred_at=request.retrieved_at,
            from_state="normalized",
            to_state="accepted_for_compilation",
            reason_code="COMPILATION_ADMISSION_ACCEPTED",
            evidence_refs=[snapshot_key, derivative_key, evidence_key],
            previous_event_sha256=events[-1]["event_sha256"],
        )
        _, reused = _write_event(store, accepted)
        events.append(accepted)
        object_states.append(reused)

        result_key = f"intake/v1/attempts/{attempt_id}/result.json"
        result = IntakeResult(
            attempt_id=attempt_id,
            status="accepted_for_compilation",
            source_id=source_id,
            snapshot_id=snapshot_id,
            derivative_id=derivative_id,
            raw_blob_key=metadata_raw_key,
            snapshot_key=snapshot_key,
            normalized_key=normalized_key,
            derivative_key=derivative_key,
            result_key=result_key,
            rejection_key=None,
            idempotent=False,
            raw_blob_reused=metadata_reused,
            event_keys=_event_keys(attempt_id, events),
        )
        object_states.append(
            _put_immutable(
                store,
                result_key,
                _pretty_json_bytes(result.evidence_dict()),
                content_type="application/json",
            )
        )
        result = replace(result, idempotent=all(object_states))
        _write_output(output_dir, "database-acquisition.json", evidence_bytes)
        _write_output(output_dir, "snapshot.json", snapshot_bytes)
        _write_output(output_dir, "normalized.md", normalized)
        _write_output(output_dir, "derivative.json", derivative_bytes)
        _write_output(output_dir, "intake-result.json", _pretty_json_bytes(result.to_dict()))
        return result
    except IntakeFailure as failure:
        if not evidence_written and evidence_key and artifacts.get("source_id"):
            evidence = _evidence(
                attempt_id=attempt_id,
                source_id=str(artifacts["source_id"]),
                bundle=bundle,
                failure=failure,
            )
            object_states.append(
                _put_immutable(
                    store,
                    evidence_key,
                    _pretty_json_bytes(evidence),
                    content_type="application/json",
                )
            )
        return _reject(
            store=store,
            request=request,
            attempt_id=attempt_id,
            failure=failure,
            current_state=current_state,
            events=events,
            object_states=object_states,
            artifacts=artifacts,
            output_dir=output_dir,
        )
