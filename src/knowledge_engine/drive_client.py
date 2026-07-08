from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from .intake_v1 import IntakeFailure, canonical_json_bytes
from .storage import sha256_bytes

GOOGLE_DOC_MIME = "application/vnd.google-apps.document"
SHORTCUT_MIME = "application/vnd.google-apps.shortcut"
EXPORT_MIME = "text/plain"
FILE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{10,256}$")
REVISION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,256}$")
KNOWN_PERMISSION_TYPES = {"anyone", "domain", "group", "user"}
KNOWN_ROLES = {
    "owner",
    "organizer",
    "fileOrganizer",
    "writer",
    "commenter",
    "reader",
}


class DriveTransport(Protocol):
    """Credential-owning read-only transport implemented outside intake core."""

    def get_file(
        self,
        file_id: str,
        *,
        fields: str,
        supports_all_drives: bool,
    ) -> Mapping[str, Any]: ...

    def list_revisions(
        self,
        file_id: str,
        *,
        fields: str,
        page_size: int,
        page_token: str | None,
    ) -> Mapping[str, Any]: ...

    def list_permissions(
        self,
        file_id: str,
        *,
        fields: str,
        page_size: int,
        page_token: str | None,
        supports_all_drives: bool,
    ) -> Mapping[str, Any]: ...

    def export_file(
        self,
        file_id: str,
        *,
        mime_type: str,
        max_bytes: int,
    ) -> bytes: ...


@dataclass(frozen=True)
class DriveFileMetadata:
    file_id: str
    name_sha256: str
    mime_type: str
    modified_time: str
    version: str
    drive_id: str | None
    trashed: bool
    can_download: bool
    shortcut_target_id: str | None
    shortcut_target_mime: str | None


@dataclass(frozen=True)
class DriveRevisionState:
    latest_revision_id: str
    latest_modified_time: str | None
    observed_count: int
    digest: str


@dataclass(frozen=True)
class DrivePermissionState:
    policy_type: str
    minimum_audience: str
    principal_hashes: tuple[str, ...]
    permission_digest: str
    permission_count: int
    inherited_count: int
    direct_count: int
    type_counts: Mapping[str, int]
    role_counts: Mapping[str, int]
    unresolved: bool


class BoundedDriveClient:
    FILE_FIELDS = (
        "id,name,mimeType,modifiedTime,version,driveId,trashed,"
        "capabilities(canDownload),shortcutDetails(targetId,targetMimeType)"
    )
    REVISION_FIELDS = "nextPageToken,revisions(id,modifiedTime,mimeType)"
    PERMISSION_FIELDS = (
        "nextPageToken,permissions(id,type,role,allowFileDiscovery,deleted,"
        "pendingOwner,view,permissionDetails(permissionType,role,inherited,inheritedFrom))"
    )

    def __init__(self, transport: DriveTransport, *, max_pages: int = 20) -> None:
        if not 1 <= max_pages <= 100:
            raise ValueError("max_pages must be between 1 and 100")
        self.transport = transport
        self.max_pages = max_pages

    def file(self, file_id: str) -> DriveFileMetadata:
        if FILE_ID_RE.fullmatch(file_id) is None:
            raise IntakeFailure("INVALID_DRIVE_FILE_ID", "request", "invalid Drive file ID")
        payload = self.transport.get_file(
            file_id,
            fields=self.FILE_FIELDS,
            supports_all_drives=True,
        )
        return parse_file_metadata(payload, file_id)

    def revisions(self, file_id: str, *, max_items: int) -> DriveRevisionState:
        items = self._collect(
            file_id,
            collection="revisions",
            fields=self.REVISION_FIELDS,
            max_items=max_items,
        )
        return parse_revision_state(items)

    def permissions(self, file_id: str, *, max_items: int) -> DrivePermissionState:
        items = self._collect(
            file_id,
            collection="permissions",
            fields=self.PERMISSION_FIELDS,
            max_items=max_items,
        )
        return parse_permission_state(items)

    def export_text(self, file_id: str, *, max_bytes: int) -> bytes:
        data = self.transport.export_file(file_id, mime_type=EXPORT_MIME, max_bytes=max_bytes)
        if not isinstance(data, bytes):
            raise IntakeFailure("DRIVE_EXPORT_INVALID", "acquire", "Drive export must be bytes")
        if not data:
            raise IntakeFailure("EMPTY_SOURCE", "acquire", "Drive export is empty")
        if len(data) > max_bytes:
            raise IntakeFailure(
                "DRIVE_RESPONSE_TOO_LARGE",
                "acquire",
                "Drive export exceeds byte policy",
            )
        return data

    def _collect(
        self,
        file_id: str,
        *,
        collection: str,
        fields: str,
        max_items: int,
    ) -> list[Mapping[str, Any]]:
        items: list[Mapping[str, Any]] = []
        page_token: str | None = None
        seen_tokens: set[str] = set()
        for _page in range(self.max_pages):
            if collection == "revisions":
                payload = self.transport.list_revisions(
                    file_id,
                    fields=fields,
                    page_size=min(max_items, 1000),
                    page_token=page_token,
                )
            else:
                payload = self.transport.list_permissions(
                    file_id,
                    fields=fields,
                    page_size=min(max_items, 1000),
                    page_token=page_token,
                    supports_all_drives=True,
                )
            if not isinstance(payload, Mapping):
                raise IntakeFailure("DRIVE_JSON_INVALID", "acquire", "Drive page must be an object")
            page_items = payload.get(collection, [])
            if not isinstance(page_items, list) or any(
                not isinstance(item, Mapping) for item in page_items
            ):
                raise IntakeFailure(
                    "DRIVE_JSON_INVALID",
                    "acquire",
                    f"Drive {collection} payload is invalid",
                )
            items.extend(page_items)
            if len(items) > max_items:
                raise IntakeFailure(
                    "DRIVE_COLLECTION_LIMIT",
                    "acquire",
                    f"Drive {collection} exceeds item policy",
                )
            token = payload.get("nextPageToken")
            if token is None:
                return items
            if not isinstance(token, str) or not token or len(token) > 2048 or token in seen_tokens:
                raise IntakeFailure(
                    "DRIVE_PAGINATION_INVALID",
                    "acquire",
                    "Drive pagination token is invalid",
                )
            seen_tokens.add(token)
            page_token = token
        raise IntakeFailure(
            "DRIVE_PAGINATION_LIMIT",
            "acquire",
            f"Drive {collection} exceeded page policy",
        )


def required_text(mapping: Mapping[str, Any], field: str, *, code: str) -> str:
    value = mapping.get(field)
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise IntakeFailure(code, "acquire", f"Drive field {field} is invalid")
    return value


def parse_file_metadata(payload: Mapping[str, Any], expected_file_id: str) -> DriveFileMetadata:
    if not isinstance(payload, Mapping):
        raise IntakeFailure("DRIVE_METADATA_INVALID", "acquire", "Drive metadata is invalid")
    file_id = required_text(payload, "id", code="DRIVE_METADATA_INVALID")
    if file_id != expected_file_id or FILE_ID_RE.fullmatch(file_id) is None:
        raise IntakeFailure("DRIVE_FILE_ID_MISMATCH", "acquire", "Drive returned another file ID")
    name = required_text(payload, "name", code="DRIVE_METADATA_INVALID")
    mime_type = required_text(payload, "mimeType", code="DRIVE_METADATA_INVALID")
    modified_time = required_text(payload, "modifiedTime", code="DRIVE_METADATA_INVALID")
    version_value = payload.get("version")
    if isinstance(version_value, int):
        version = str(version_value)
    elif isinstance(version_value, str) and version_value.isdigit():
        version = version_value
    else:
        raise IntakeFailure("DRIVE_METADATA_INVALID", "acquire", "Drive version is invalid")
    drive_id_value = payload.get("driveId")
    drive_id = None
    if drive_id_value is not None:
        if not isinstance(drive_id_value, str) or FILE_ID_RE.fullmatch(drive_id_value) is None:
            raise IntakeFailure("DRIVE_METADATA_INVALID", "acquire", "Drive driveId is invalid")
        drive_id = drive_id_value
    trashed = payload.get("trashed")
    capabilities = payload.get("capabilities")
    if not isinstance(trashed, bool) or not isinstance(capabilities, Mapping):
        raise IntakeFailure("DRIVE_METADATA_INVALID", "acquire", "Drive metadata flags are invalid")
    can_download = capabilities.get("canDownload")
    if not isinstance(can_download, bool):
        raise IntakeFailure("DRIVE_METADATA_INVALID", "acquire", "Drive canDownload is invalid")
    target_id = None
    target_mime = None
    shortcut = payload.get("shortcutDetails")
    if shortcut is not None:
        if not isinstance(shortcut, Mapping):
            raise IntakeFailure("DRIVE_METADATA_INVALID", "acquire", "shortcutDetails is invalid")
        target_id = required_text(shortcut, "targetId", code="DRIVE_METADATA_INVALID")
        target_mime = required_text(shortcut, "targetMimeType", code="DRIVE_METADATA_INVALID")
        if FILE_ID_RE.fullmatch(target_id) is None:
            raise IntakeFailure("DRIVE_METADATA_INVALID", "acquire", "shortcut target is invalid")
    return DriveFileMetadata(
        file_id=file_id,
        name_sha256=sha256_bytes(name.encode("utf-8")),
        mime_type=mime_type,
        modified_time=modified_time,
        version=version,
        drive_id=drive_id,
        trashed=trashed,
        can_download=can_download,
        shortcut_target_id=target_id,
        shortcut_target_mime=target_mime,
    )


def parse_revision_state(items: Sequence[Mapping[str, Any]]) -> DriveRevisionState:
    if not items:
        raise IntakeFailure("DRIVE_REVISION_UNRESOLVED", "acquire", "Drive returned no revisions")
    records: list[dict[str, Any]] = []
    for item in items:
        revision_id = required_text(item, "id", code="DRIVE_REVISION_INVALID")
        if REVISION_ID_RE.fullmatch(revision_id) is None:
            raise IntakeFailure("DRIVE_REVISION_INVALID", "acquire", "revision ID is invalid")
        modified = item.get("modifiedTime")
        mime = item.get("mimeType")
        if modified is not None and (not isinstance(modified, str) or len(modified) > 128):
            raise IntakeFailure("DRIVE_REVISION_INVALID", "acquire", "modifiedTime is invalid")
        if mime is not None and (not isinstance(mime, str) or len(mime) > 256):
            raise IntakeFailure("DRIVE_REVISION_INVALID", "acquire", "revision MIME is invalid")
        records.append({"id": revision_id, "modifiedTime": modified, "mimeType": mime})
    latest = records[-1]
    return DriveRevisionState(
        latest_revision_id=latest["id"],
        latest_modified_time=latest["modifiedTime"],
        observed_count=len(records),
        digest=sha256_bytes(canonical_json_bytes(records)),
    )


def _principal_hash(value: str) -> str:
    return "drive-principal:" + sha256_bytes(value.encode("utf-8"))[:32]


def parse_permission_state(items: Sequence[Mapping[str, Any]]) -> DrivePermissionState:
    records: list[dict[str, Any]] = []
    principal_hashes: set[str] = set()
    type_counts: dict[str, int] = {}
    role_counts: dict[str, int] = {}
    inherited_count = 0
    direct_count = 0
    unresolved = False
    for item in items:
        permission_id = required_text(item, "id", code="DRIVE_PERMISSION_INVALID")
        permission_type = required_text(item, "type", code="DRIVE_PERMISSION_INVALID")
        role = required_text(item, "role", code="DRIVE_PERMISSION_INVALID")
        if permission_type not in KNOWN_PERMISSION_TYPES or role not in KNOWN_ROLES:
            unresolved = True
        deleted = item.get("deleted", False)
        pending_owner = item.get("pendingOwner", False)
        if not isinstance(deleted, bool) or not isinstance(pending_owner, bool):
            raise IntakeFailure("DRIVE_PERMISSION_INVALID", "acquire", "permission flags invalid")
        if deleted:
            continue
        allow_discovery = item.get("allowFileDiscovery")
        if allow_discovery is not None and not isinstance(allow_discovery, bool):
            raise IntakeFailure("DRIVE_PERMISSION_INVALID", "acquire", "discovery flag invalid")
        details_value = item.get("permissionDetails", [])
        if not isinstance(details_value, list):
            raise IntakeFailure("DRIVE_PERMISSION_INVALID", "acquire", "permission details invalid")
        details: list[dict[str, Any]] = []
        for detail in details_value:
            if not isinstance(detail, Mapping):
                raise IntakeFailure("DRIVE_PERMISSION_INVALID", "acquire", "permission detail invalid")
            inherited = detail.get("inherited")
            detail_role = detail.get("role")
            detail_type = detail.get("permissionType")
            if not isinstance(inherited, bool) or not isinstance(detail_role, str) or not isinstance(
                detail_type, str
            ):
                raise IntakeFailure("DRIVE_PERMISSION_INVALID", "acquire", "detail fields invalid")
            inherited_from = detail.get("inheritedFrom")
            inherited_hash = None
            if inherited_from is not None:
                if not isinstance(inherited_from, str) or len(inherited_from) > 256:
                    raise IntakeFailure("DRIVE_PERMISSION_INVALID", "acquire", "inheritance invalid")
                inherited_hash = sha256_bytes(inherited_from.encode("utf-8"))[:32]
            details.append(
                {
                    "permissionType": detail_type,
                    "role": detail_role,
                    "inherited": inherited,
                    "inheritedFromHash": inherited_hash,
                }
            )
            inherited_count += int(inherited)
            direct_count += int(not inherited)
        if not details:
            direct_count += 1
        principal = _principal_hash(permission_id)
        if permission_type in {"domain", "group", "user"}:
            principal_hashes.add(principal)
        type_counts[permission_type] = type_counts.get(permission_type, 0) + 1
        role_counts[role] = role_counts.get(role, 0) + 1
        records.append(
            {
                "principalHash": principal,
                "type": permission_type,
                "role": role,
                "allowFileDiscovery": allow_discovery,
                "pendingOwner": pending_owner,
                "permissionDetails": sorted(details, key=canonical_json_bytes),
            }
        )
    records.sort(key=canonical_json_bytes)
    if unresolved or not records:
        policy_type, minimum_audience = "unresolved", "restricted"
    elif type_counts.get("anyone", 0):
        policy_type, minimum_audience = "public", "public"
    elif type_counts.get("domain", 0):
        policy_type, minimum_audience = "authenticated", "internal"
    elif type_counts.get("user", 0) or type_counts.get("group", 0):
        policy_type, minimum_audience = "principal_set", "confidential"
    else:
        policy_type, minimum_audience = "restricted", "restricted"
    return DrivePermissionState(
        policy_type=policy_type,
        minimum_audience=minimum_audience,
        principal_hashes=tuple(sorted(principal_hashes)),
        permission_digest=sha256_bytes(canonical_json_bytes(records)),
        permission_count=len(records),
        inherited_count=inherited_count,
        direct_count=direct_count,
        type_counts=dict(sorted(type_counts.items())),
        role_counts=dict(sorted(role_counts.items())),
        unresolved=unresolved or not records,
    )
