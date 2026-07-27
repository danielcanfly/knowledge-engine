from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "m26-pa-2-live-evidence-observer.yml"


def test_observer_is_exact_and_has_no_live_data_credentials() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "94b7d9d81ab3f56f62df25a6722bed5f2c038347" in text
    assert "M26.PA.2 Exact Live Read-Only Evidence" in text
    assert "[m26.pa2-observe-live]" in text
    assert "m26-pa-2-live-read-only-evidence-attempt-1" in text
    assert "TARGET_ISSUE: '1186'" in text
    assert "R2_ACCESS_KEY_ID" not in text
    assert "R2_SECRET_ACCESS_KEY" not in text
    assert "QDRANT_API_KEY" not in text
    assert "QDRANT_READ_ONLY_API_KEY" not in text
    assert "secrets." not in text


def test_observer_permissions_are_metadata_only() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "permissions:\n  contents: read" in text
    assert "actions: read" in text
    assert "issues: write" in text
    assert "contents: write" not in text
    for forbidden in (
        "/rerun",
        "put_object",
        "delete_object",
        "upsert",
        "workflow_dispatch",
        "production_pointer",
    ):
        assert forbidden not in text
