from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from .drive_client import (
    EXPORT_MIME,
    FILE_ID_RE,
    GOOGLE_DOC_MIME,
    REVISION_ID_RE,
    SHORTCUT_MIME,
    BoundedDriveClient,
    DriveFileMetadata,
    DrivePermissionState,
    DriveRevisionState,
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

CONNECTOR_TYPE = "google_drive_document"
CONNECTOR_VERSION = "google-drive-document/1.0.0"
NORMALIZER_ID = "google_docs_text_to_markdown"
NORMALIZER_VERSION = "1.0.0"
DEFAULT_MAX_BYTES = 10 * 1024 * 1024
DEFAULT_MAX_PERMISSIONS = 2_000
DEFAULT_MAX_REVISIONS = 2_000
AUDIENCE_RANK = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}
POLICY_RANK = {
    "public": 0,
    "authenticated": 1,
    "principal_set": 2,
    "restricted": 3,
    "unresolved": 4,
}
SAFE_REVISION_REF = re.compile(r"^[A-Za-z0-9_-]{1,256}$")


@dataclass(frozen=True)
class DriveDocumentRequest:
    file_id: str
    expected_revision_id: str
    retrieved_at: str
    owner: EvidenceValue
    license: EvidenceValue
    audience: str
    access_policy: AccessPolicy
    allow_shortcut: bool = False
    source_id: str | None = None
    parent_snapshot: str | None = None
    max_bytes: int = DEFAULT_MAX_BYTES
    max_permissions: int = DEFAULT_MAX_PERMISSIONS
    max_revisions: int = DEFAULT_MAX_REVISIONS

    def validate(self) -> None:
        if FILE_ID_RE.fullmatch(self.file_id) is None:
            raise IntakeFailure("INVALID_DRIVE_FILE_ID", "request", "invalid Drive file ID")
        if REVISION_ID_RE.fullmatch(self.expected_revision_id) is None:
            raise IntakeFailure(
                "INVALID_DRIVE_REVISION_ID",
                "request",
                "invalid Drive revision ID",
            )
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
        if not 1 <= self.max_bytes <= DEFAULT_MAX_BYTES:
            raise IntakeFailure(
                "INVALID_METADATA",
                "request",
                "max_bytes must be between 1 and 10485760",
            )
        if not 1 <= self.max_permissions <= 10_000:
            raise IntakeFailure(
                "INVALID_METADATA",
                "request",
                "max_permissions must be between 1 and 10000",
            )
        if not 1 <= self.max_revisions <= 10_000:
            raise IntakeFailure(
                "INVALID_METADATA",
                "request",
                "max_revisions must be between 1 and 10000",
            )

    def attempt_id(self) -> str:
        payload = {
            "schema_version": "intake-attempt/v1",
            "connector_type": CONNECTOR_TYPE,
            "file_id": self.file_id,
            "expected_revision_id": self.expected_revision_id,
            "retrieved_at": self.retrieved_at,
            "owner": self.owner.to_dict(),
            "license": self.license.to_dict(),
            "audience": self.audience,
            "access_policy": self.access_policy.to_dict(),
            "allow_shortcut": self.allow_shortcut,
            "source_id": self.source_id,
            "parent_snapshot": self.parent_snapshot,
            "max_bytes": self.max_bytes,
            "max_permissions": self.max_permissions,
            "max_revisions": self.max_revisions,
        }
        return "attempt_" + sha256_bytes(canonical_json_bytes(payload))[:32]


@dataclass(frozen=True)
class DriveAcquisition:
    requested_file: DriveFileMetadata
    target_file: DriveFileMetadata
    shortcut_permissions: DrivePermissionState | None
    target_permissions: DrivePermissionState
    pre_revision: DriveRevisionState
    post_revision: DriveRevisionState
    exported_bytes: bytes

    @property
    def canonical_locator(self) -> str:
        if self.requested_file.file_id == self.target_file.file_id:
            return f"gdrive://file/{self.target_file.file_id}"
        return (
            f"gdrive://shortcut/{self.requested_file.file_id}/target/"
            f"{self.target_file.file_id}"
        )


def _resolve_files(
    client: BoundedDriveClient,
    request: DriveDocumentRequest,
) -> tuple[DriveFileMetadata, DriveFileMetadata]:
    requested = client.file(request.file_id)
    if requested.trashed:
        raise IntakeFailure("DRIVE_FILE_TRASHED", "discover", "Drive file is trashed")
    if requested.mime_type != SHORTCUT_MIME:
        return requested, requested
    if not request.allow_shortcut:
        raise IntakeFailure("DRIVE_SHORTCUT_DISABLED", "discover", "Drive shortcut is disabled")
    target_id = requested.shortcut_target_id
    target_mime = requested.shortcut_target_mime
    if target_id is None or target_mime is None:
        raise IntakeFailure("DRIVE_SHORTCUT_INVALID", "discover", "shortcut target is missing")
    if target_id == requested.file_id:
        raise IntakeFailure("DRIVE_SHORTCUT_LOOP", "discover", "shortcut targets itself")
    if target_mime == SHORTCUT_MIME:
        raise IntakeFailure("DRIVE_SHORTCUT_DEPTH", "discover", "nested shortcuts are forbidden")
    target = client.file(target_id)
    if target.mime_type == SHORTCUT_MIME:
        raise IntakeFailure("DRIVE_SHORTCUT_DEPTH", "discover", "nested shortcuts are forbidden")
    return requested, target


def _metadata_signature(value: DriveFileMetadata) -> tuple[Any, ...]:
    return (
        value.file_id,
        value.mime_type,
        value.modified_time,
        value.version,
        value.drive_id,
        value.trashed,
        value.can_download,
        value.shortcut_target_id,
        value.shortcut_target_mime,
    )


def _validate_non_broadening(
    request: DriveDocumentRequest,
    states: Sequence[DrivePermissionState],
) -> None:
    requested_policy_rank = POLICY_RANK[request.access_policy.policy_type]
    requested_audience_rank = AUDIENCE_RANK[request.audience]
    requested_principals = set(request.access_policy.principals)
    for state in states:
        if requested_policy_rank < POLICY_RANK[state.policy_type]:
            raise IntakeFailure(
                "DRIVE_ACL_BROADENING",
                "admission",
                "requested access policy is broader than Drive ACL",
            )
        if requested_audience_rank < AUDIENCE_RANK[state.minimum_audience]:
            raise IntakeFailure(
                "DRIVE_ACL_BROADENING",
                "admission",
                "requested audience is broader than Drive ACL",
            )
        if state.unresolved:
            if request.access_policy.policy_type != "unresolved":
                raise IntakeFailure(
                    "ACL_UNRESOLVED",
                    "admission",
                    "Drive ACL evidence is unresolved",
                )
            continue
        if state.policy_type in {"authenticated", "principal_set"} and request.access_policy.policy_type in {
            "authenticated",
            "principal_set",
        }:
            if not requested_principals or not requested_principals.issubset(
                set(state.principal_hashes)
            ):
                raise IntakeFailure(
                    "DRIVE_ACL_PRINCIPAL_MISMATCH",
                    "admission",
                    "requested principals are not proven by Drive ACL",
                )


def _normalise_export(data: bytes) -> bytes:
    if b"\x00" in data:
        raise IntakeFailure("DRIVE_BINARY_EXPORT", "safety_gate", "Drive export has NUL bytes")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise IntakeFailure(
            "DRIVE_EXPORT_INVALID_UTF8",
            "safety_gate",
            "Drive export must be UTF-8",
        ) from exc
    text = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    if not text.strip():
        raise IntakeFailure("EMPTY_SOURCE", "normalize", "Drive export is empty")
    return ("# Google Docs Export\n\n" + text.rstrip("\n") + "\n").encode("utf-8")


def _permission_summary(state: DrivePermissionState) -> dict[str, Any]:
    return {
        "policy_type": state.policy_type,
        "minimum_audience": state.minimum_audience,
        "permission_count": state.permission_count,
        "inherited_count": state.inherited_count,
        "direct_count": state.direct_count,
        "type_counts": state.type_counts,
        "role_counts": state.role_counts,
        "unresolved": state.unresolved,
    }


def _evidence(
    *,
    attempt_id: str,
    source_id: str,
    request: DriveDocumentRequest,
    acquisition: DriveAcquisition | None,
    raw_hash: str | None,
    failure: IntakeFailure | None,
) -> dict[str, Any]:
    requested = acquisition.requested_file if acquisition else None
    target = acquisition.target_file if acquisition else None
    target_permissions = acquisition.target_permissions if acquisition else None
    shortcut_permissions = acquisition.shortcut_permissions if acquisition else None
    revision = acquisition.pre_revision if acquisition else None
    return {
        "schema_version": "drive-acquisition-evidence/v1",
        "attempt_id": attempt_id,
        "source_id": source_id,
        "connector_type": CONNECTOR_TYPE,
        "connector_version": CONNECTOR_VERSION,
        "requested_file_id": request.file_id,
        "target_file_id": target.file_id if target else None,
        "shortcut_used": bool(requested and target and requested.file_id != target.file_id),
        "requested_name_sha256": requested.name_sha256 if requested else None,
        "target_name_sha256": target.name_sha256 if target else None,
        "mime_type": target.mime_type if target else None,
        "modified_time": target.modified_time if target else None,
        "file_version": target.version if target else None,
        "shared_drive": target.drive_id is not None if target else None,
        "drive_id_sha256": (
            sha256_bytes(target.drive_id.encode("utf-8")) if target and target.drive_id else None
        ),
        "expected_revision_id": request.expected_revision_id,
        "pre_revision_id": revision.latest_revision_id if revision else None,
        "post_revision_id": acquisition.post_revision.latest_revision_id if acquisition else None,
        "revision_digest": revision.digest if revision else None,
        "revision_count_observed": revision.observed_count if revision else None,
        "target_permission_digest": (
            target_permissions.permission_digest if target_permissions else None
        ),
        "target_permission_summary": (
            _permission_summary(target_permissions) if target_permissions else None
        ),
        "shortcut_permission_digest": (
            shortcut_permissions.permission_digest if shortcut_permissions else None
        ),
        "export_mime_type": EXPORT_MIME,
        "byte_size": len(acquisition.exported_bytes) if acquisition else None,
        "raw_sha256": raw_hash,
        "client_policy": {
            "read_only": True,
            "credential_ownership": "external_transport",
            "supports_all_drives": True,
            "raw_permissions_persisted": False,
            "credential_material_persisted": False,
            "fixed_export_mime": EXPORT_MIME,
            "shortcut_max_hops": 1,
        },
        "outcome": "accepted" if failure is None else "rejected",
        "failure_code": failure.code if failure else None,
        "safe_context": failure.safe_context if failure else {},
    }


def intake_google_drive_document(
    *,
    store: ObjectStore,
    request: DriveDocumentRequest,
    client: BoundedDriveClient,
    output_dir: Path | None = None,
) -> IntakeResult:
    """Acquire one revision-stable native Google Docs text export."""

    attempt_id = request.attempt_id()
    events: list[dict[str, Any]] = []
    object_states: list[bool] = []
    artifacts: dict[str, Any] = {}
    current_state: str | None = None
    acquisition: DriveAcquisition | None = None
    raw_hash: str | None = None
    evidence_key: str | None = None
    evidence_written = False

    try:
        request.validate()
        requested_file, target_file = _resolve_files(client, request)
        if target_file.trashed:
            raise IntakeFailure("DRIVE_FILE_TRASHED", "discover", "Drive target is trashed")
        if target_file.mime_type != GOOGLE_DOC_MIME:
            raise IntakeFailure(
                "DRIVE_MIME_UNSUPPORTED",
                "discover",
                "only native Google Docs documents are supported",
            )
        if not target_file.can_download:
            raise IntakeFailure(
                "DRIVE_DOWNLOAD_RESTRICTED",
                "discover",
                "Drive document cannot be exported",
            )
        canonical_locator = (
            f"gdrive://file/{target_file.file_id}"
            if requested_file.file_id == target_file.file_id
            else f"gdrive://shortcut/{requested_file.file_id}/target/{target_file.file_id}"
        )
        source_id = request.source_id or stable_source_id(CONNECTOR_TYPE, canonical_locator)
        artifacts["source_id"] = source_id

        discovered = _event(
            attempt_id=attempt_id,
            sequence=1,
            occurred_at=request.retrieved_at,
            from_state=None,
            to_state="discovered",
            reason_code="SOURCE_DISCOVERED",
            evidence_refs=[
                f"file_id_sha256:{sha256_bytes(request.file_id.encode('utf-8'))}",
                f"revision_sha256:{sha256_bytes(request.expected_revision_id.encode('utf-8'))}",
            ],
            previous_event_sha256=None,
        )
        _, reused = _write_event(store, discovered)
        events.append(discovered)
        object_states.append(reused)
        current_state = "discovered"
        evidence_key = f"intake/v1/attempts/{attempt_id}/drive-acquisition.json"
        artifacts["drive_evidence_key"] = evidence_key

        pre_revision = client.revisions(target_file.file_id, max_items=request.max_revisions)
        if pre_revision.latest_revision_id != request.expected_revision_id:
            raise IntakeFailure(
                "DRIVE_REVISION_MISMATCH",
                "acquire",
                "Drive head revision differs from expected revision",
            )
        target_permissions = client.permissions(
            target_file.file_id,
            max_items=request.max_permissions,
        )
        shortcut_permissions = None
        permission_states = [target_permissions]
        if requested_file.file_id != target_file.file_id:
            shortcut_permissions = client.permissions(
                requested_file.file_id,
                max_items=request.max_permissions,
            )
            permission_states.append(shortcut_permissions)
        _validate_non_broadening(request, permission_states)

        exported = client.export_text(target_file.file_id, max_bytes=request.max_bytes)
        requested_after, target_after = _resolve_files(client, request)
        if _metadata_signature(requested_file) != _metadata_signature(requested_after):
            raise IntakeFailure("DRIVE_FILE_DRIFT", "acquire", "Drive source changed during export")
        if _metadata_signature(target_file) != _metadata_signature(target_after):
            raise IntakeFailure("DRIVE_FILE_DRIFT", "acquire", "Drive target changed during export")
        post_revision = client.revisions(target_file.file_id, max_items=request.max_revisions)
        if post_revision.latest_revision_id != pre_revision.latest_revision_id:
            raise IntakeFailure("DRIVE_REVISION_DRIFT", "acquire", "Drive revision changed")
        target_permissions_after = client.permissions(
            target_file.file_id,
            max_items=request.max_permissions,
        )
        if target_permissions_after.permission_digest != target_permissions.permission_digest:
            raise IntakeFailure("DRIVE_ACL_DRIFT", "acquire", "Drive target ACL changed")
        if shortcut_permissions is not None:
            shortcut_permissions_after = client.permissions(
                requested_file.file_id,
                max_items=request.max_permissions,
            )
            if shortcut_permissions_after.permission_digest != shortcut_permissions.permission_digest:
                raise IntakeFailure("DRIVE_ACL_DRIFT", "acquire", "Drive shortcut ACL changed")

        acquisition = DriveAcquisition(
            requested_file=requested_file,
            target_file=target_file,
            shortcut_permissions=shortcut_permissions,
            target_permissions=target_permissions,
            pre_revision=pre_revision,
            post_revision=post_revision,
            exported_bytes=exported,
        )
        raw_hash = sha256_bytes(exported)
        acquired = _event(
            attempt_id=attempt_id,
            sequence=2,
            occurred_at=request.retrieved_at,
            from_state="discovered",
            to_state="acquired",
            reason_code="SOURCE_ACQUIRED",
            evidence_refs=[
                f"revision:{pre_revision.latest_revision_id}",
                f"sha256:{raw_hash}",
                f"bytes:{len(exported)}",
            ],
            previous_event_sha256=events[-1]["event_sha256"],
        )
        _, reused = _write_event(store, acquired)
        events.append(acquired)
        object_states.append(reused)
        current_state = "acquired"

        normalized = _normalise_export(exported)
        extracted_text = normalized.decode("utf-8")
        secret_matches = _secret_matches(extracted_text)
        if secret_matches:
            raise IntakeFailure(
                "SECRET_LIKE_CONTENT",
                "safety_gate",
                "Drive export contains secret-like content",
                safe_context={
                    "patterns": secret_matches,
                    "observed_sha256": raw_hash,
                    "observed_bytes": len(exported),
                },
            )

        evidence = _evidence(
            attempt_id=attempt_id,
            source_id=source_id,
            request=request,
            acquisition=acquisition,
            raw_hash=raw_hash,
            failure=None,
        )
        evidence_bytes = _pretty_json_bytes(evidence)
        object_states.append(
            _put_immutable(store, evidence_key, evidence_bytes, content_type="application/json")
        )
        evidence_written = True

        raw_blob_key = f"intake/v1/raw/sha256/{raw_hash[:2]}/{raw_hash}"
        raw_reused = _put_immutable(store, raw_blob_key, exported, content_type=EXPORT_MIME)
        object_states.append(raw_reused)
        artifacts.update(raw_blob_key=raw_blob_key, raw_blob_reused=raw_reused)

        acl_status = (
            "unresolved"
            if request.access_policy.policy_type == "unresolved"
            or request.access_policy.observation_source == "unresolved"
            else "resolved"
        )
        identity = {
            "schema_version": "intake-snapshot/v1",
            "source_id": source_id,
            "original_uri": acquisition.canonical_locator,
            "connector_type": CONNECTOR_TYPE,
            "connector_version": CONNECTOR_VERSION,
            "retrieved_at": request.retrieved_at,
            "content_hash": raw_hash,
            "byte_size": len(exported),
            "mime_type": EXPORT_MIME,
            "encoding": "utf-8",
            "license": request.license.to_dict(),
            "owner": request.owner.to_dict(),
            "audience": request.audience,
            "access_policy": request.access_policy.to_dict(),
            "source_version": (
                f"drive:{target_file.file_id}:{pre_revision.latest_revision_id}:"
                f"{target_file.version}:{target_permissions.permission_digest}"
            ),
            "parent_snapshot": request.parent_snapshot,
        }
        snapshot_id = snapshot_id_for(identity)
        snapshot_key = f"intake/v1/snapshots/{source_id}/{snapshot_id}/snapshot.json"
        snapshot = {
            **identity,
            "snapshot_id": snapshot_id,
            "acl_status": acl_status,
            "storage_location": _storage_location(store, raw_blob_key, raw_hash),
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
            evidence_refs=[raw_blob_key, snapshot_key, evidence_key],
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
            "warnings": _prompt_findings(extracted_text),
            "drive_evidence_key": evidence_key,
            "file_id": target_file.file_id,
            "revision_id": pre_revision.latest_revision_id,
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
            raw_blob_key=raw_blob_key,
            snapshot_key=snapshot_key,
            normalized_key=normalized_key,
            derivative_key=derivative_key,
            result_key=result_key,
            rejection_key=None,
            idempotent=False,
            raw_blob_reused=raw_reused,
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
        _write_output(output_dir, "drive-acquisition.json", evidence_bytes)
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
                request=request,
                acquisition=acquisition,
                raw_hash=raw_hash,
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
