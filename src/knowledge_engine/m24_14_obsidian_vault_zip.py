from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from .m24_internal_product_deployment import (
    OBSIDIAN_VAULT_ZIP_RELATIVE,
    SITE_ROOT,
    P6AuthorityBoundary,
    build_p6_internal_product_deployment,
)
from .m24_product_surface_integration import (
    CANONICAL_MANIFEST_SHA256,
    CANONICAL_RELEASE_ID,
    CANONICAL_SOURCE_SHA,
)
from .storage import sha256_bytes

P4_SCHEMA = "knowledge-engine-m24-14-4-obsidian-vault-zip/v1"
P4_ISSUE_NUMBER = 1013
P4_ROOT = Path("pilot/m24/m24-14/obsidian-vault-zip")
P4_REPORT_PATH = P4_ROOT / "m24-14-4-obsidian-vault-zip.json"


class P4ZipMemberEvidence(BaseModel):
    path: str
    bytes: int = Field(ge=0)
    crc: int = Field(ge=0)
    timestamp: tuple[int, int, int, int, int, int]


class P4ObsidianVaultZipReport(BaseModel):
    schema_version: str = P4_SCHEMA
    status: Literal["m24_14_4_obsidian_vault_zip_candidate_complete"]
    issue_number: int
    release_id: str
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    vault_zip_path: str
    vault_zip_bytes: int = Field(ge=1)
    vault_zip_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    download_href: str
    member_count: int = Field(ge=1)
    member_paths_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    members: list[P4ZipMemberEvidence]
    deterministic_policy: list[str]
    repeated_build_byte_identical: bool
    app_shell_download_link: bool
    write_back_authorized: bool
    authority: P6AuthorityBoundary
    self_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _zip_members(path: Path) -> list[P4ZipMemberEvidence]:
    with zipfile.ZipFile(path, "r") as archive:
        return [
            P4ZipMemberEvidence(
                path=info.filename,
                bytes=info.file_size,
                crc=info.CRC,
                timestamp=info.date_time,
            )
            for info in sorted(archive.infolist(), key=lambda item: item.filename)
        ]


def build_p4_obsidian_vault_zip_report(
    *,
    output_path: Path = P4_REPORT_PATH,
    include_self_digest: bool = True,
) -> P4ObsidianVaultZipReport:
    build_p6_internal_product_deployment()
    zip_path = SITE_ROOT / OBSIDIAN_VAULT_ZIP_RELATIVE
    first_bytes = zip_path.read_bytes()
    build_p6_internal_product_deployment()
    second_bytes = zip_path.read_bytes()
    manifest = json.loads(
        SITE_ROOT.joinpath("data/obsidian-export-manifest.json").read_text(encoding="utf-8")
    )
    app_js = SITE_ROOT.joinpath("app.js").read_text(encoding="utf-8")
    members = _zip_members(zip_path)
    report = P4ObsidianVaultZipReport(
        status="m24_14_4_obsidian_vault_zip_candidate_complete",
        issue_number=P4_ISSUE_NUMBER,
        release_id=CANONICAL_RELEASE_ID,
        manifest_sha256=CANONICAL_MANIFEST_SHA256,
        source_commit_sha=CANONICAL_SOURCE_SHA,
        vault_zip_path=zip_path.as_posix(),
        vault_zip_bytes=len(second_bytes),
        vault_zip_sha256=sha256_bytes(second_bytes),
        download_href=manifest["download_href"],
        member_count=len(members),
        member_paths_sha256=canonical_sha256([member.path for member in members]),
        members=members,
        deterministic_policy=[
            "zip_stored_no_compression",
            "lexicographic_member_order",
            "fixed_1980_01_01_timestamp",
            "fixed_0644_file_permissions",
            "utf8_text_content_from_release_pinned_export",
        ],
        repeated_build_byte_identical=first_bytes == second_bytes,
        app_shell_download_link=(
            "Download Vault ZIP" in app_js and "obsidian.download_href" in app_js
        ),
        write_back_authorized=manifest["write_back_authorized"],
        authority=P6AuthorityBoundary(),
    )
    if include_self_digest:
        report.self_sha256 = canonical_sha256(
            report.model_dump(mode="json", exclude={"self_sha256"})
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_json(report.model_dump(mode="json")), encoding="utf-8")
    return report
