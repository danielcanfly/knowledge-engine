from __future__ import annotations

import hashlib
import os
import threading
from collections.abc import Callable
from typing import Any

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
        console_origin: str = DEFAULT_CONSOLE_ORIGIN,
    ) -> None:
        self.team_domain = team_domain
        self.audience = audience
        self.owner_emails = owner_emails
        self.owner_subjects = owner_subjects
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
        if not team.startswith("https://") or ".cloudflareaccess.com" not in team:
            raise AdminConfigurationError("Cloudflare Access team domain is not configured")
        if not audience:
            raise AdminConfigurationError("Cloudflare Access application AUD is not configured")
        if not emails and not subjects:
            raise AdminConfigurationError("Console owner allowlist is not configured")
        if origin != DEFAULT_CONSOLE_ORIGIN:
            raise AdminConfigurationError("Console origin must remain the frozen production origin")
        return cls(team, audience, emails, subjects, origin)

    @property
    def certs_url(self) -> str:
        return f"{self.team_domain}/cdn-cgi/access/certs"


class AccessJWTAuthenticator:
    def __init__(self, settings: AdminAccessSettings, *, jwk_client: Any | None = None) -> None:
        self.settings = settings
        self._jwks = jwk_client or PyJWKClient(settings.certs_url, cache_keys=True)

    def authenticate(self, assertion: str | None) -> AdminActor:
        if not assertion or not assertion.strip():
            raise AdminAPIError(
                status_code=401,
                code="ADMIN_ACCESS_ASSERTION_MISSING",
                message="Cloudflare Access assertion is required",
            )
        try:
            token = assertion.strip()
            key = self._jwks.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                key.key,
                algorithms=["RS256"],
                audience=self.settings.audience,
                issuer=self.settings.team_domain,
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
        owner_match = (
            (email is not None and email in self.settings.owner_emails)
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
