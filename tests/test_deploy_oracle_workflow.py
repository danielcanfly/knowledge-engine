from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/deploy-oracle.yml"


def test_r2_manifest_canary_precedes_checkout_and_production_mutation() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    canary = text.index("Fail closed on production R2 manifest credential canary")
    checkout = text.index("actions/checkout@v4")
    env_write = text.index(".env.next")
    deploy = text.index("Deploy exact requested revision")
    assert canary < checkout < env_write < deploy
    assert "s3api head-object" in text
    assert "FULL_PRODUCTION_MANIFEST_KEY" in text
    assert "credential_source=github_environment_production_primary" in text
    assert "read_variant_used=false" in text
    assert "R2_ACCESS_KEY_ID_READ" not in text
    assert ".env.pre-deploy-$stamp" in text
