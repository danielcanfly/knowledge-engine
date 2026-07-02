from pathlib import Path


def test_dispatch_candidate_runs_in_engine_production_job() -> None:
    workflow = Path(
        ".github/workflows/source-candidate-dispatch.yml"
    ).read_text(encoding="utf-8")

    publish = workflow.split("  publish-candidate:\n", 1)[1].split(
        "\n  record-evidence:\n", 1
    )[0]
    assert "runs-on: ubuntu-latest" in publish
    assert "environment: production" in publish
    assert "uses: ./.github/workflows/source-candidate-gate.yml" not in publish
    assert "R2_ACCESS_KEY_ID: ${{ secrets.R2_ACCESS_KEY_ID }}" in publish
    assert "R2_SECRET_ACCESS_KEY: ${{ secrets.R2_SECRET_ACCESS_KEY }}" in publish
    assert "KNOWLEDGE_SOURCE_READ_TOKEN" in publish
    assert "knowledge-engine gate-source-candidate" in publish
