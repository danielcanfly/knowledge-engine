from __future__ import annotations

import hashlib
import os
import threading
from collections.abc import Callable
from typing import Any

STATIC_OWNER_EMAIL_SHA256_ALLOWLIST = frozenset({
    # Same owner email hash used by the protected console Worker.
    "9427ba8408d7bc179c5f2582b03675f2e0a704b3b95f03b1e07857755694337f",
})

import jwt
from jwt import PyJWKClient

from .m26_admin_contract import (
    DEFAULT_CONSOLE_ORIGIN,
    AdminActor,
    AdminAPIError,
    AdminConfigurationError,
)


class AdminAccessSettings:
    def __init__(
        self,
        team_domain: str,
        audience: str,
        owner_emails: frozenset[str] = frozenset(),
        owner_subjects: frozenset[str] = frozenset(),
        owner_email_hashes: frozenset[str] = STATIC_OWNER_EMAIL_SHA256_ALLOWLIST,
        console_origin: str = DEFAULT_CONSOLE_ORIGIN,
    ) -> None:
        self.team_domain = team_domain
        self.audience = audience
        self.owner_emails = owner_emails
        self.owner_subjects = owner_subjects
        self.owner_email_hashes = owner_email_hashes
        self.console_origin = console_origin

    @classmethod
    def from_env(cls) -> AdminAccessSettings:
        team = os.environ.get("M26_CONSOLE_ACCESS_TEAM_DOMAIN", "").strip().rstrip("/")
        audience = os.environ.get("M26_CONSOLE_ACCESS_AUD", "").strip()
        origin = os.environ.get("M26_CONSOLE_ORIGIN", DEFAULT_CONSOLE_ORIGIN).strip().rstrip("/")
        emails = frozenset(
            item.strip().casefold()
            for item in os.environ.get("M26_CONSOLE_OWNER_EMAILS", "").split(",")
            if item.strip()
        )
        subjects = frozenset(
            item.strip()
            for item in os.environ.get("M26_CONSOLE_OWNER_SUBJECTS", "").split(",")
            if item.strip()
        )
        owner_email_hashes = frozenset(
            item.strip().casefold()
            for item in os.environ.get("M26_CONSOLE_OWNER_EMAIL_SHA256_ALLOWLIST", "").split(",")
            if item.strip()
        ) | STATIC_OWNER_EMAIL_SHA256_ALLOWLIST
        if team and (not team.startswith("https://") or ".cloudflareaccess.com" not in team):
            raise AdminConfigurationError("Cloudflare Access team domain is not configured")
        if not emails and not subjects and not owner_email_hashes:
            raise AdminConfigurationError("Console owner allowlist is not configured")
        if origin != DEFAULT_CONSOLE_ORIGIN:
            raise AdminConfigurationError("Console origin must remain the frozen production origin")
        return cls(team, audience, emails, subjects, owner_email_hashes, origin)

    @property
    def certs_url(self) -> str:
        return f"{self.team_domain}/cdn-cgi/access/certs"


class AccessJWTAuthenticator:
    def __init__(self, settings: AdminAccessSettings, *, jwk_client: Any | None = None) -> None:
        self.settings = settings
        self._jwk_client_factory = lambda certs_url: PyJWKClient(
            certs_url,
            cache_keys=True,
            lifespan=3600,
            timeout=5,
        )
        self._jwks = jwk_client

    def authenticate(self, assertion: str | None) -> AdminActor:
        if not assertion or not assertion.strip():
            raise AdminAPIError(
                status_code=401,
                code="ADMIN_ACCESS_ASSERTION_MISSING",
                message="Cloudflare Access assertion is required",
            )
        try:
            token = assertion.strip()
            team_domain, audience = self._access_contract_from_token(token)
            jwks = self._jwks or self._jwk_client_factory(f"{team_domain}/cdn-cgi/access/certs")
            key = jwks.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                key.key,
                algorithms=["RS256"],
                audience=audience,
                issuer=team_domain,
                options={"require": ["exp", "iss", "sub", "aud"]},
            )
        except Exception as exc:
            raise AdminAPIError(
                status_code=403,
                code="ADMIN_ACCESS_ASSERTION_INVALID",
                message="Cloudflare Access assertion is invalid",
            ) from exc
        subject = str(claims.get("sub", "")).strip()
        email = str(claims["email"]).strip().casefold() if claims.get("email") else None
        email_hash = hashlib.sha256(email.encode()).hexdigest() if email is not None else None
        owner_match = (
            (email is not None and email in self.settings.owner_emails)
            or (email_hash is not None and email_hash in self.settings.owner_email_hashes)
            or subject in self.settings.owner_subjects
        )
        if not owner_match:
            raise AdminAPIError(
                status_code=403,
                code="ADMIN_ACTOR_NOT_OWNER",
                message="Authenticated Access identity is not authorized for owner console",
            )
        raw_audience = claims.get("aud")
        audience = (
            (raw_audience,)
            if isinstance(raw_audience, str)
            else tuple(map(str, raw_audience or []))
        )
        token_type = str(claims.get("type", "human")).casefold()
        return AdminActor(
            actor_id="cfaccess:" + hashlib.sha256(subject.encode()).hexdigest()[:24],
            subject=subject,
            email=email,
            actor_type="service" if token_type in {"app", "service"} else "human",
            issuer=str(claims.get("iss", "")),
            audience=audience,
        )

    def _access_contract_from_token(self, token: str) -> tuple[str, str]:
        team_domain = self.settings.team_domain
        audience = self.settings.audience
        if team_domain and audience:
            return team_domain, audience
        try:
            unverified = jwt.decode(
                token,
                options={
                    "verify_signature": False,
                    "verify_exp": False,
                    "verify_aud": False,
                    "verify_iss": False,
                },
            )
        except Exception as exc:
            raise AdminAPIError(
                status_code=403,
                code="ADMIN_ACCESS_ASSERTION_INVALID",
                message="Cloudflare Access assertion is invalid",
            ) from exc
        if not team_domain:
            team_domain = str(unverified.get("iss", "")).strip().rstrip("/")
        if not audience:
            raw_audience = unverified.get("aud")
            audiences = (
                [raw_audience]
                if isinstance(raw_audience, str)
                else list(raw_audience or [])
            )
            audiences = [str(item).strip() for item in audiences if str(item).strip()]
            if len(audiences) != 1:
                raise AdminAPIError(
                    status_code=403,
                    code="ADMIN_ACCESS_ASSERTION_INVALID",
                    message="Cloudflare Access assertion is invalid",
                )
            audience = audiences[0]
        if not team_domain.startswith("https://") or ".cloudflareaccess.com" not in team_domain:
            raise AdminAPIError(
                status_code=403,
                code="ADMIN_ACCESS_ASSERTION_INVALID",
                message="Cloudflare Access assertion is invalid",
            )
        return team_domain, audience


class LazyAccessJWTAuthenticator:
    def __init__(
        self,
        factory: Callable[[], AdminAccessSettings] = AdminAccessSettings.from_env,
    ) -> None:
        self.factory = factory
        self._auth: AccessJWTAuthenticator | None = None
        self._lock = threading.Lock()

    def authenticate(self, assertion: str | None) -> AdminActor:
        if self._auth is None:
            with self._lock:
                if self._auth is None:
                    try:
                        self._auth = AccessJWTAuthenticator(self.factory())
                    except AdminConfigurationError as exc:
                        raise AdminAPIError(
                            status_code=503,
                            code="ADMIN_AUTH_CONFIGURATION_MISSING",
                            message="Admin authentication is not configured",
                        ) from exc
        return self._auth.authenticate(assertion)
