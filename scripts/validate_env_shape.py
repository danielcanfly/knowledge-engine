#!/usr/bin/env python3
from __future__ import annotations

import os
from urllib.parse import urlparse


def value(name: str, *, strip_slash: bool = False) -> str:
    result = os.getenv(name, "").strip()
    if strip_slash:
        result = result.rstrip("/")
    if not result:
        raise SystemExit(f"MISSING_{name}")
    return result


def main() -> int:
    auth_mode = value("AUTH_MODE")
    issuer = value("JWT_ISSUER", strip_slash=True)
    jwks = value("JWT_JWKS_URL", strip_slash=True)
    audience = value("JWT_AUDIENCE")
    value("R2_ACCESS_KEY_ID")
    value("R2_SECRET_ACCESS_KEY")
    value("R2_BUCKET")
    endpoint = value("R2_ENDPOINT_URL", strip_slash=True)

    if auth_mode != "supabase_jwt":
        raise SystemExit("INVALID_AUTH_MODE_EXPECTED_SUPABASE_JWT")
    issuer_url = urlparse(issuer)
    jwks_url = urlparse(jwks)
    endpoint_url = urlparse(endpoint)
    if issuer_url.scheme != "https" or issuer_url.path.rstrip("/") != "/auth/v1":
        raise SystemExit("INVALID_JWT_ISSUER_FORMAT")
    if (
        jwks_url.scheme != "https"
        or jwks_url.path.rstrip("/") != "/auth/v1/.well-known/jwks.json"
    ):
        raise SystemExit("INVALID_JWT_JWKS_URL_FORMAT")
    if audience != "authenticated":
        raise SystemExit("INVALID_JWT_AUDIENCE_EXPECTED_AUTHENTICATED")
    if (
        endpoint_url.scheme != "https"
        or not endpoint_url.netloc.endswith("r2.cloudflarestorage.com")
    ):
        raise SystemExit("INVALID_R2_ENDPOINT_EXPECTED_S3_API_ENDPOINT")
    print("PRODUCTION_CONFIG_GATE_PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
