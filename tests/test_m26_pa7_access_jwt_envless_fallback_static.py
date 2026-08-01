from __future__ import annotations

from pathlib import Path


def test_m26_pa7_worker_supports_envless_access_jwt_contract() -> None:
    worker_path = Path("pilot/m24/internal-product-deployment/site/_worker.js")
    worker = worker_path.read_text(encoding="utf-8")

    assert "resolveAccessJwtContract" in worker
    assert "verified_cloudflare_access_jwt_email_inferred_contract" in worker
    assert "M26_OWNER_ACCESS_JWT_CONFIG_MISSING" in worker
    assert "isCloudflareAccessIssuer" in worker
    assert "hostname === \"cloudflareaccess.com\"" in worker
    assert "hostname.endsWith(\".cloudflareaccess.com\")" in worker
    assert worker.index("const contract = resolveAccessJwtContract") < worker.index(
        "payload = await verifyAccessJwt(token, contract.issuer, contract.audience)"
    )
    assert worker.index("payload = await verifyAccessJwt") < worker.index(
        "const email = String(payload.email"
    )
    assert "cf-access-authenticated-user-email" not in worker
    assert "M26_ALLOW_LOCAL_OWNER_HEADER" in worker
    assert "llm-wiki-m24-internal.pages.dev" in worker
