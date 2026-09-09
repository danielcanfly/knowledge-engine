from __future__ import annotations

from pathlib import Path


QA_DATA_DIR = "/var/lib/knowledge-engine/public-api"
QA_DB_PATH = f"{QA_DATA_DIR}/qa-inbox.sqlite3"
COMBINED_APP = "knowledge_engine.m26_console_api:app"
PUBLIC_ONLY_APP = "knowledge_engine.m26_public_api:app"


def test_dockerfile_prepares_non_root_qa_data_directory() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    assert QA_DATA_DIR in dockerfile
    assert "chown -R knowledge:knowledge /var/lib/knowledge-engine /app" in dockerfile
    assert COMBINED_APP in dockerfile


def test_compose_runs_combined_console_app_not_public_only_app() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    assert f"      - {COMBINED_APP}" in compose
    assert PUBLIC_ONLY_APP not in compose
    assert "    read_only: true" in compose


def test_compose_binds_durable_qa_inbox_volume_and_db_path() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    assert f"      M26_QA_DB_PATH: {QA_DB_PATH}" in compose
    assert f"      - m26-qa-inbox-data:{QA_DATA_DIR}" in compose
    assert "  m26-qa-inbox-data:" in compose
