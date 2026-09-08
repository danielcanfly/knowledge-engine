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


def test_deploy_requires_exact_sha_and_defers_public_identity_gate_by_default() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    deploy = (WORKFLOW.parents[2] / "deploy/deploy.sh").read_text(encoding="utf-8")

    assert "git_sha must be an exact 40-character lowercase commit SHA" in text
    assert "require_public_identity" in text
    assert "Optional public identity gate" in text
    assert "PUBLIC_RUNTIME_SHA_MISMATCH" in text
    assert "RELEASE_SHA must be an exact 40-character lowercase commit SHA" in deploy
    assert "DEPLOYMENT_HEALTH_CONTRACT_MISMATCH" in deploy
    assert "/v1/answers/health" in deploy


def test_standard_compose_uses_canonical_public_runtime_contract() -> None:
    compose = (WORKFLOW.parents[2] / "docker-compose.yml").read_text(encoding="utf-8")
    dockerfile = (WORKFLOW.parents[2] / "Dockerfile").read_text(encoding="utf-8")

    assert "knowledge_engine.m26_public_api:app" in compose
    assert "M26_PUBLIC_QUOTA_DB" in compose
    assert "m26-daily-ip-rate-limit-data" in compose
    assert "knowledge_engine.m26_public_api:app" in dockerfile
    assert "/v1/answers/health" in dockerfile
