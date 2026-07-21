from __future__ import annotations

import json
import zipfile
from pathlib import Path

from scripts.m23_7_r3_8_remote_operator import canonical_sha256

from knowledge_engine.m24_14_obsidian_vault_zip import (
    P4_REPORT_PATH,
    build_p4_obsidian_vault_zip_report,
)
from knowledge_engine.m24_internal_product_deployment import (
    OBSIDIAN_VAULT_ZIP_RELATIVE,
    SITE_ROOT,
    ZIP_TIMESTAMP,
    build_p6_internal_product_deployment,
)
from knowledge_engine.storage import sha256_bytes


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_m24_14_4_report_is_digest_bound() -> None:
    report = _json(P4_REPORT_PATH)
    unsigned = dict(report)
    digest = unsigned.pop("self_sha256")

    assert canonical_sha256(unsigned) == digest


def test_m24_14_4_report_matches_generated_vault_zip_evidence() -> None:
    report = build_p4_obsidian_vault_zip_report()

    assert report.model_dump(mode="json") == _json(P4_REPORT_PATH)
    assert report.status == "m24_14_4_obsidian_vault_zip_candidate_complete"
    assert report.repeated_build_byte_identical is True
    assert report.app_shell_download_link is True
    assert report.download_href == OBSIDIAN_VAULT_ZIP_RELATIVE


def test_m24_14_4_zip_is_byte_identical_across_repeated_p6_builds() -> None:
    build_p6_internal_product_deployment()
    zip_path = SITE_ROOT / OBSIDIAN_VAULT_ZIP_RELATIVE
    first = zip_path.read_bytes()
    build_p6_internal_product_deployment()
    second = zip_path.read_bytes()

    assert first == second
    assert sha256_bytes(second) == _json(P4_REPORT_PATH)["vault_zip_sha256"]


def test_m24_14_4_zip_members_are_sorted_fixed_timestamp_and_vault_shaped() -> None:
    build_p4_obsidian_vault_zip_report()
    zip_path = SITE_ROOT / OBSIDIAN_VAULT_ZIP_RELATIVE

    with zipfile.ZipFile(zip_path, "r") as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        assert names == sorted(names)
        assert "README.md" in names
        assert "manifest.json" in names
        assert ".obsidian/app.json" in names
        assert any(name.startswith("concepts/") and name.endswith(".md") for name in names)
        assert any(name.startswith("sources/") and name.endswith(".md") for name in names)
        assert all(info.date_time == ZIP_TIMESTAMP for info in infos)
        assert all(info.compress_type == zipfile.ZIP_STORED for info in infos)


def test_m24_14_4_manifest_and_app_shell_link_to_downloadable_zip() -> None:
    build_p4_obsidian_vault_zip_report()
    manifest = _json(SITE_ROOT / "data/obsidian-export-manifest.json")
    app_js = SITE_ROOT.joinpath("app.js").read_text(encoding="utf-8")
    report = _json(P4_REPORT_PATH)

    assert manifest["vault_zip_path"] == OBSIDIAN_VAULT_ZIP_RELATIVE
    assert manifest["download_href"] == OBSIDIAN_VAULT_ZIP_RELATIVE
    assert manifest["vault_zip_sha256"] == report["vault_zip_sha256"]
    assert manifest["vault_zip_bytes"] == report["vault_zip_bytes"]
    assert "Download Vault ZIP" in app_js
    assert "vault_zip_sha256" in app_js


def test_m24_14_4_preserves_non_production_authority_boundary() -> None:
    report = build_p4_obsidian_vault_zip_report()

    assert report.write_back_authorized is False
    assert report.authority.product_audience == "authenticated_internal"
    assert report.authority.browser_authority == "read_only"
    assert report.authority.production_retrieval == "lexical"
    assert report.authority.semantic_promotion_enabled is False
    assert report.authority.semantic_serving_enabled is False
    assert report.authority.hybrid_retrieval_enabled is False
    assert report.authority.production_answer_serving_enabled is False
    assert report.authority.source_mutation is False
    assert report.authority.production_pointer_mutation is False
    assert report.authority.production_r2_mutation is False
    assert report.authority.qdrant_mutation is False
    assert report.authority.credential_mutation is False
    assert report.authority.traffic_mutation is False
