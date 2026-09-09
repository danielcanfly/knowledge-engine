from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m25_blog_pilot import SERIES_META_PATH, TreeBlob, git_blob_sha
from knowledge_engine.m26_admin_ingestion import CAP_INGESTION_JOB_CONFIRM
from knowledge_engine.m26_admin_production import (
    ProductionAdminRuntime,
    QualifiedL3BCapabilityProvider,
    SqliteAdminControlStore,
)
from knowledge_engine.m26_ingestion_runtime import (
    CombinedCapabilityProvider,
    GitHubBlogSource,
    build_runtime_ingestion_adapter_from_env,
)
from knowledge_engine.m26_sqlite_ingestion import (
    SQLiteIngestionAdapter,
    SQLiteIngestionLedger,
    SQLiteIngestionReadAuthority,
)


class _GitHubFixture:
    commit = "a" * 40
    committed_at = "2026-09-10T01:02:03Z"

    def __init__(self) -> None:
        self.blobs = {
            SERIES_META_PATH: (
                b"export const series = [\n"
                b"  { slug: /series-.+/, key: 'series', order: 1, "
                b"labelZh: 'Series', labelEn: '1. Series' }\n"
                b"]\n"
            ),
            "src/content/blog/series-one/en.md": (
                b"---\ntitle: One\ndraft: false\nseries: Series\n---\n"
                b"## First heading\nFirst body.\n"
            ),
            "src/content/blog/series-two/en.md": (
                b"---\ntitle: Two\ndraft: false\nseries: Series\n---\n"
                b"## Second heading\nSecond body.\n"
            ),
        }
        self.by_sha = {git_blob_sha(value): value for value in self.blobs.values()}

    def resolve_commit(self, repository: str, ref: str) -> tuple[str, str]:
        assert repository == "danielcanfly/daniel-blog"
        assert ref in {"main", self.commit}
        return self.commit, self.committed_at

    def tree(self, repository: str, commit: str) -> list[TreeBlob]:
        assert repository == "danielcanfly/daniel-blog"
        assert commit == self.commit
        return [
            TreeBlob(path=path, sha=git_blob_sha(data), size=len(data))
            for path, data in sorted(self.blobs.items())
        ]

    def blob(self, repository: str, blob_sha: str) -> bytes:
        assert repository == "danielcanfly/daniel-blog"
        return self.by_sha[blob_sha]

    def archive_files(self, repository: str, commit: str, paths: Any) -> dict[str, bytes]:
        assert repository == "danielcanfly/daniel-blog"
        assert commit == self.commit
        return {path: self.blobs[path] for path in paths}


def _decode_artifacts(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {kind: json.loads(data) for kind, data in result["artifact_bytes"].items()}


def test_dynamic_source_build_is_immutable_deterministic_and_candidate_only() -> None:
    fixture = _GitHubFixture()
    source = GitHubBlogSource(
        repository="danielcanfly/daniel-blog",
        ref="main",
        client=fixture,  # type: ignore[arg-type]
    )
    observed = source.observe()
    builder = source.artifact_builder("b" * 40)

    first = builder({"source": observed})
    second = builder({"source": observed})
    artifacts = _decode_artifacts(first)

    assert first == second
    assert first["source_count"] == 2
    assert first["release_id"].startswith("m26blog-aaaaaaaaaaaa-")
    assert set(artifacts) == {
        "document_pack_admission",
        "document_source_index",
        "graph",
        "graph_v2",
        "lexical_index",
        "provenance",
        "semantic_inputs",
        "source_documents",
    }
    lexical_ids = {row["section_id"] for row in artifacts["lexical_index"]["documents"]}
    semantic = artifacts["semantic_inputs"]["documents"]
    assert lexical_ids == {row["section_id"] for row in semantic}
    assert len(semantic) == 4
    assert all(
        row["payload"]["text_sha256"] == hashlib.sha256(row["text"].encode()).hexdigest()
        for row in semantic
    )
    assert all(row["payload"]["candidate_release_eligible"] is True for row in semantic)
    assert all(row["payload"]["production_authority"] is False for row in semantic)
    assert artifacts["document_pack_admission"]["production_pointer_authorized_by_source"] is False


def test_dynamic_source_revalidation_fails_before_build_on_identity_drift() -> None:
    fixture = _GitHubFixture()
    source = GitHubBlogSource(
        repository="danielcanfly/daniel-blog",
        ref="main",
        client=fixture,  # type: ignore[arg-type]
    )
    observed = dict(source.observe())
    observed["source_identity_digest"] = "f" * 64

    with pytest.raises(IntegrityError, match="changed after plan revalidation"):
        source.artifact_builder("b" * 40)({"source": observed})


def _runtime_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    values = {
        "M26_INGESTION_ENABLED": "true",
        "M26_INGESTION_STATE_DB": str(tmp_path / "state" / "ingestion.sqlite3"),
        "M26_SOURCE_ROOT": str(tmp_path / "source"),
        "M26_QUERY_BUILD_SHA": "c" * 40,
        "QDRANT_URL": "https://qdrant.example.test",
        "QDRANT_API_KEY": "qdrant-test-token",
        "CLOUDFLARE_ACCOUNT_ID": "account-test",
        "CLOUDFLARE_AI_TOKEN": "provider-test-token",
        "OBJECT_STORE_BACKEND": "filesystem",
        "FILESYSTEM_STORE_ROOT": str(tmp_path / "objects"),
        "APP_ENV": "test",
        "AUTH_MODE": "disabled",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def test_runtime_factory_wires_all_candidate_seams_or_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _runtime_env(monkeypatch, tmp_path)

    qualified = build_runtime_ingestion_adapter_from_env()
    assert isinstance(qualified, SQLiteIngestionAdapter)
    assert qualified.source_observer is not None
    assert qualified.active_manifest_observer is not None
    assert qualified.candidate_executor is not None

    monkeypatch.delenv("CLOUDFLARE_AI_TOKEN")
    blocked = build_runtime_ingestion_adapter_from_env()
    assert isinstance(blocked, SQLiteIngestionReadAuthority)
    assert "candidate_executor" in blocked.missing_seams


def test_combined_capabilities_preserve_l3b_and_only_enable_qualified_ingestion(
    tmp_path: Path,
) -> None:
    primary = QualifiedL3BCapabilityProvider()
    adapter = SQLiteIngestionAdapter(SQLiteIngestionLedger(tmp_path / "ingestion.sqlite3"))
    combined = CombinedCapabilityProvider(primary, adapter)

    for gate in primary.list_capabilities():
        assert combined.get_capability(gate.capability_id) == gate
    ingestion = combined.get_capability(CAP_INGESTION_JOB_CONFIRM)
    assert ingestion is not None
    assert ingestion.effective_state == "enabled"
    assert ingestion.mutation_authorized is True
    assert ingestion.resource_identity == {
        "mode": "candidate_only",
        "production_pointer_authorized": False,
    }

    blocked = SQLiteIngestionReadAuthority(
        SQLiteIngestionLedger(tmp_path / "blocked.sqlite3"), ["candidate_executor"]
    )
    assert (
        CombinedCapabilityProvider(primary, blocked).get_capability(CAP_INGESTION_JOB_CONFIRM)
        is None
    )


def test_console_composes_durable_ingestion_without_weakening_l3b(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from knowledge_engine import m26_console_api as module

    primary = QualifiedL3BCapabilityProvider()
    production = ProductionAdminRuntime(
        primary,
        SqliteAdminControlStore(tmp_path / "admin.sqlite3"),
    )
    adapter = SQLiteIngestionAdapter(SQLiteIngestionLedger(tmp_path / "ingestion.sqlite3"))
    captured: dict[str, Any] = {}

    monkeypatch.setattr(module, "create_public_app", FastAPI)
    monkeypatch.setattr(module, "production_admin_runtime_from_env", lambda: production)
    monkeypatch.setattr(module, "build_runtime_ingestion_adapter_from_env", lambda: adapter)

    def install_control(_app: FastAPI, **kwargs: Any) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(module, "install_admin_control_plane", install_control)
    for name in (
        "install_admin_overview",
        "install_admin_ingestion_routes",
        "install_admin_corpus",
        "install_qa_inbox",
        "install_suggested_questions_admin",
        "install_admin_usage",
        "install_admin_health",
        "install_jobs_rollback_routes",
        "install_golden_questions_admin",
        "install_admin_settings",
        "install_admin_audit",
    ):
        monkeypatch.setattr(module, name, lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "playground_router", lambda: object())
    monkeypatch.setattr(FastAPI, "include_router", lambda *_args, **_kwargs: None)

    app = module.create_app()

    assert app.state.m26_durable_ingestion_adapter is adapter
    assert captured["idempotency_store"] is adapter.ledger
    provider = captured["capability_provider"]
    for gate in primary.list_capabilities():
        assert provider.get_capability(gate.capability_id) == gate
    assert provider.get_capability(CAP_INGESTION_JOB_CONFIRM) is not None


def test_deploy_contract_preserves_exact_predecessor_and_wires_runtime() -> None:
    workflow = Path(".github/workflows/deploy-oracle.yml").read_text(encoding="utf-8")
    rollback = Path("deploy/rollback.sh").read_text(encoding="utf-8")
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    for name in (
        "M26_INGESTION_ENABLED=true",
        "M26_INGESTION_STATE_DB=/var/lib/knowledge-engine/ingestion/ingestion.sqlite3",
        "KNOWLEDGE_SOURCE_READ_TOKEN=",
        "QDRANT_URL=",
        "QDRANT_API_KEY=",
        "CLOUDFLARE_ACCOUNT_ID=",
        "CLOUDFLARE_AI_TOKEN=",
    ):
        assert name in workflow
    assert 'rollback_tag="knowledge-engine-rollback:$runtime_sha"' in workflow
    assert 'docker image tag "$image_id" "$rollback_tag"' in workflow
    assert ': "${ROLLBACK_IMAGE_ID:?ROLLBACK_IMAGE_ID is required}"' in rollback
    assert ': "${ROLLBACK_ENV_SHA256:?ROLLBACK_ENV_SHA256 is required}"' in rollback
    assert "docker compose up -d --no-build --remove-orphans" in rollback
    assert "running_image_id" in rollback
    assert "Restore exact predecessor after failed deployment" in workflow
    assert "steps.deploy.outcome == 'failure'" in workflow
    assert "/var/lib/knowledge-engine/ingestion" in dockerfile
    assert "chown -R knowledge:knowledge /var/lib/knowledge-engine" in dockerfile
    assert "knowledge-engine-volume-init:" in compose
    assert "condition: service_completed_successfully" in compose
    assert "chown 10001:10001 /var/lib/knowledge-engine/ingestion" in compose


def _executable(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


def _rollback_fixture(tmp_path: Path) -> tuple[dict[str, str], Path, str]:
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    backup = deploy / ".env.pre-deploy-20260910T010203Z"
    backup.write_text("MODE=predecessor\n", encoding="utf-8")
    (deploy / ".env").write_text("MODE=failed-candidate\n", encoding="utf-8")
    binary = tmp_path / "bin"
    binary.mkdir()
    log = tmp_path / "commands.log"
    rollback_sha = "d" * 40
    image_id = "sha256:" + "e" * 64
    _executable(
        binary / "git",
        "#!/usr/bin/env bash\n"
        'printf \'git %s\\n\' "$*" >> "$FIXTURE_LOG"\n'
        "if [[ \"$1 $2\" == 'rev-parse HEAD' ]]; then printf '%s\\n' \"$ROLLBACK_SHA\"; fi\n",
    )
    _executable(
        binary / "docker",
        "#!/usr/bin/env bash\n"
        'printf \'docker %s\\n\' "$*" >> "$FIXTURE_LOG"\n'
        "if [[ \"$1 $2\" == 'image inspect' ]]; then\n"
        "  printf '%s\\n' \"$FAKE_IMAGE_ID\"\n"
        "  exit 0\n"
        "fi\n"
        "if [[ \"$1 $2 $3\" == 'compose ps -q' ]]; then printf 'fixture-container\\n'; exit 0; fi\n"
        "if [[ \"$1\" == 'inspect' ]]; then printf '%s\\n' \"$FAKE_IMAGE_ID\"; exit 0; fi\n"
        "exit 0\n",
    )
    _executable(
        binary / "curl",
        "#!/usr/bin/env bash\n"
        'printf \'{"ok":true,"backend":{"build_sha":"%s"}}\\n\' "$ROLLBACK_SHA"\n',
    )
    _executable(binary / "flock", "#!/usr/bin/env bash\nexit 0\n")
    env = {
        **os.environ,
        "PATH": f"{binary}:{os.environ['PATH']}",
        "DEPLOY_PATH": str(deploy),
        "ROLLBACK_SHA": rollback_sha,
        "ROLLBACK_IMAGE_ID": image_id,
        "ROLLBACK_ENV_FILE": str(backup),
        "ROLLBACK_ENV_SHA256": hashlib.sha256(backup.read_bytes()).hexdigest(),
        "KNOWLEDGE_ENGINE_DEPLOY_LOCK_FILE": str(tmp_path / "deploy.lock"),
        "FIXTURE_LOG": str(log),
        "FAKE_IMAGE_ID": image_id,
    }
    return env, log, image_id


def test_exact_image_rollback_restores_predecessor_without_build(tmp_path: Path) -> None:
    env, log, image_id = _rollback_fixture(tmp_path)

    completed = subprocess.run(
        ["bash", "deploy/rollback.sh"],
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "ROLLBACK_EXACT_IMAGE_PASSED" in completed.stdout
    assert f"ROLLBACK_IMAGE_ID={image_id}" in completed.stdout
    assert (tmp_path / "deploy" / ".env").read_text() == "MODE=predecessor\n"
    commands = log.read_text()
    assert "docker compose up -d --no-build --remove-orphans" in commands
    assert "compose build" not in commands


def test_exact_image_rollback_fails_closed_on_identity_drift(tmp_path: Path) -> None:
    env, log, _image_id = _rollback_fixture(tmp_path)
    env["ROLLBACK_IMAGE_ID"] = "sha256:" + "f" * 64

    completed = subprocess.run(
        ["bash", "deploy/rollback.sh"],
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 1
    assert "ROLLBACK_IMAGE_ID_MISMATCH" in completed.stderr
    assert (tmp_path / "deploy" / ".env").read_text() == "MODE=failed-candidate\n"
    assert "docker compose up" not in log.read_text()
