from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import jwt
from fastapi import Header
from jwt import PyJWKClient

from .config import Settings
from .errors import AuthorizationError

ALLOWED_AUDIENCES = {"public", "internal", "confidential", "restricted"}


@dataclass(frozen=True)
class Principal:
    subject: str
    audiences: frozenset[str]
    claims: dict[str, Any]


class Authenticator:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._jwks = (
            PyJWKClient(settings.jwt_jwks_url or "")
            if settings.auth_mode == "supabase_jwt"
            else None
        )

    def authenticate(self, authorization: str | None) -> Principal:
        if self.settings.auth_mode == "disabled":
            return Principal(
                subject="development-user",
                audiences=frozenset(self.settings.jwt_default_audiences),
                claims={"auth_mode": "disabled"},
            )
        if not authorization or not authorization.startswith("Bearer "):
            raise AuthorizationError("missing bearer token")
        token = authorization.removeprefix("Bearer ").strip()
        if not token:
            raise AuthorizationError("empty bearer token")
        try:
            assert self._jwks is not None
            signing_key = self._jwks.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256", "ES256"],
                audience=self.settings.jwt_audience,
                issuer=self.settings.jwt_issuer,
                options={"require": ["exp", "iss", "sub", "aud"]},
            )
        except Exception as exc:
            raise AuthorizationError("invalid bearer token") from exc
        claim_audiences = claims.get("knowledge_audiences")
        if isinstance(claim_audiences, list):
            audiences = {
                str(item) for item in claim_audiences if str(item) in ALLOWED_AUDIENCES
            }
        else:
            audiences = set(self.settings.jwt_default_audiences)
        audiences.add("public")
        return Principal(
            subject=str(claims["sub"]),
            audiences=frozenset(audiences),
            claims=claims,
        )


def authorization_header(
    authorization: str | None = Header(default=None),
) -> str | None:
    return authorization
