from __future__ import annotations

import ast
import importlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from knowledge_engine.storage import sha256_bytes
from scripts.m10_verify_production_baseline import (
    PRODUCTION_POINTER_KEY,
    BaselineExpectation,
    verify_production_baseline,
)

ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = ROOT / "docs/architecture/m10/connector-inventory-v1.json"
SNAPSHOT_SCHEMA_PATH = ROOT / "schemas/intake-snapshot-v1.schema.json"
CONNECTOR_MODULES = {
    "local_file": "knowledge_engine.intake_v1",
    "web_url": "knowledge_engine.web_intake_v1",
    "local_pdf": "knowledge_engine.pdf_intake",
    "git_repository_path": "knowledge_engine.git_intake",
    "google_drive_document": "knowledge_engine.drive_intake",
    "media_derived_markdown": "knowledge_engine.media_intake",
    "meeting_transcript": "knowledge_engine.meeting_intake",
    "database_metadata_export": "knowledge_engine.database_intake",
}
EXPECTED_VERSIONS = {
    "local_file": "local-file/1.0.0",
    "web_url": "bounded-https/1.0.0",
    "local_pdf": "local-pdf/1.0.0",
    "git_repository_path": "git-path/1.0.0",
    "google_drive_document": "google-drive-document/1.0.0",
    "media_derived_markdown": "media-derived-markdown/1.0.0",
    "meeting_transcript": "meeting-transcript/1.0.0",
    "database_metadata_export": "database-metadata-export/1.0.0",
}
FORBIDDEN_CONNECTOR_TOKENS = {
    "channels/production.json",
    "publish_release",
    "review_decision",
    "candidate_build",
    "permanent_ledger",
}


def inventory() -> dict[str, Any]:
    return json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))


def source_for(module_name: str) -> str:
    relative = Path(*module_name.split("."))
    return (ROOT / "src" / relative.with_suffix(".py")).read_text(encoding="utf-8")


def test_capability_and_connector_inventory_is_reconciled() -> None:
    value = inventory()
    assert value["schema_version"] == "m10-connector-inventory/v1"
    assert value["initial_source_capability_count"] == 9
    assert value["implemented_connector_type_count"] == 8
    assert value["capability_reconciliation"]["markdown"].startswith(
        "implemented as the Markdown content mode of local_file"
    )
    records = {item["connector_type"]: item for item in value["connectors"]}
    assert set(records) == set(CONNECTOR_MODULES)
    assert records["local_file"]["source_capabilities"] == ["local file", "Markdown"]


@pytest.mark.parametrize(("connector_type", "module_name"), CONNECTOR_MODULES.items())
def test_inventory_matches_runtime_identity(connector_type: str, module_name: str) -> None:
    record = {
        item["connector_type"]: item for item in inventory()["connectors"]
    }[connector_type]
    module = importlib.import_module(module_name)
    assert record["module"] == module_name
    assert module.CONNECTOR_TYPE == connector_type
    assert module.CONNECTOR_VERSION == EXPECTED_VERSIONS[connector_type]
    assert record["connector_version"] == module.CONNECTOR_VERSION


def test_normalizer_identities_match_runtime() -> None:
    from knowledge_engine import drive_intake, git_intake, intake_v1, media_intake
    from knowledge_engine import meeting_intake, database_intake, pdf_intake, web_intake_v1

    records = {item["connector_type"]: item for item in inventory()["connectors"]}
    assert records["local_file"]["normalizers"] == [
        f"{intake_v1.NORMALIZER_ID}/{intake_v1.NORMALIZER_VERSION}"
    ]
    assert records["local_pdf"]["normalizers"] == [
        f"{pdf_intake.PARSER_ID}/{pdf_intake.PARSER_VERSION}"
    ]
    assert records["git_repository_path"]["normalizers"] == [
        f"{git_intake.MARKDOWN_NORMALIZER_ID}/{git_intake.NORMALIZER_VERSION}",
        f"{git_intake.TEXT_NORMALIZER_ID}/{git_intake.NORMALIZER_VERSION}",
    ]
    for connector_type, module in {
        "google_drive_document": drive_intake,
        "media_derived_markdown": media_intake,
        "meeting_transcript": meeting_intake,
        "database_metadata_export": database_intake,
    }.items():
        assert records[connector_type]["normalizers"] == [
            f"{module.NORMALIZER_ID}/{module.NORMALIZER_VERSION}"
        ]
    web_normalizers = {
        "/".join(web_intake_v1._normalize_web_content(b"<p>x</p>", "text/html")[1:]),
        "/".join(web_intake_v1._normalize_web_content(b"# x\n", "text/markdown")[1:]),
        "/".join(web_intake_v1._normalize_web_content(b"x\n", "text/plain")[1:]),
    }
    assert web_normalizers == set(records["web_url"]["normalizers"])


@pytest.mark.parametrize("module_name", CONNECTOR_MODULES.values())
def test_connectors_do_not_import_or_name_production_mutation_surfaces(module_name: str) -> None:
    source = source_for(module_name)
    tree = ast.parse(source)
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imports.update(
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    )
    assert not any(name.endswith(("publisher", "review", "resolution")) for name in imports)
    assert not (FORBIDDEN_CONNECTOR_TOKENS & {token for token in FORBIDDEN_CONNECTOR_TOKENS if token in source})


def test_offline_connectors_do_not_gain_network_or_database_execution_imports() -> None:
    offline = {
        "knowledge_engine.intake_v1",
        "knowledge_engine.media_intake",
        "knowledge_engine.meeting_intake",
        "knowledge_engine.database_intake",
    }
    forbidden = {"socket", "http.client", "requests", "urllib.request", "subprocess", "sqlite3", "psycopg", "pymysql", "pyodbc", "sqlalchemy"}
    for module_name in offline:
        tree = ast.parse(source_for(module_name))
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imports.update(
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        )
        assert not {name for name in imports if name in forbidden}


def test_snapshot_schema_remains_closed_and_versioned() -> None:
    schema = json.loads(SNAPSHOT_SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["$id"].endswith("intake-snapshot-v1.schema.json")
    assert schema["additionalProperties"] is False
    assert schema["properties"]["schema_version"]["const"] == "intake-snapshot/v1"
    required = set(schema["required"])
    assert {"snapshot_id", "source_id", "content_hash", "storage_location", "access_policy"} <= required


def test_closure_documents_reference_inventory_and_read_only_verification() -> None:
    readme = (ROOT / "docs/architecture/m10/README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "docs/architecture/m10/operator-runbook.md").read_text(encoding="utf-8")
    closure = (ROOT / "docs/architecture/m10/closure-report.md").read_text(encoding="utf-8")
    assert "Status: implemented" in readme
    assert "connector-inventory-v1.json" in readme
    assert "m10_verify_production_baseline.py" in runbook
    assert "read-only" in runbook.lower()
    assert "9 source capabilities" in closure
    assert "8 runtime connector types" in closure
    assert "#30" in closure and "remain open" in closure


class ReadOnlyFakeStore:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects
        self.get_calls: list[str] = []

    def get(self, key: str) -> bytes:
        self.get_calls.append(key)
        return self.objects[key]

    def put(self, *_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("read-only verifier attempted put")

    def delete(self, *_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("read-only verifier attempted delete")


def test_production_baseline_verifier_reads_only_and_checks_both_hashes() -> None:
    release_id = "test-release"
    manifest_key = f"releases/{release_id}/manifest.json"
    manifest_bytes = b'{"schema_version":"1.0"}\n'
    manifest_hash = sha256_bytes(manifest_bytes)
    pointer_bytes = (
        json.dumps(
            {
                "schema_version": "1.0",
                "channel": "production",
                "release_id": release_id,
                "manifest_key": manifest_key,
                "manifest_sha256": manifest_hash,
                "promoted_at": "2026-01-01T00:00:00Z",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode()
    expectation = BaselineExpectation(
        pointer_sha256=sha256_bytes(pointer_bytes),
        release_id=release_id,
        manifest_sha256=manifest_hash,
        manifest_key=manifest_key,
    )
    store = ReadOnlyFakeStore(
        {PRODUCTION_POINTER_KEY: pointer_bytes, manifest_key: manifest_bytes}
    )
    result = verify_production_baseline(store, expectation)
    assert result["status"] == "passed"
    assert result["mode"] == "read_only"
    assert store.get_calls == [PRODUCTION_POINTER_KEY, manifest_key]

    changed = replace(expectation, pointer_sha256="0" * 64)
    with pytest.raises(RuntimeError, match="production pointer bytes changed"):
        verify_production_baseline(store, changed)
