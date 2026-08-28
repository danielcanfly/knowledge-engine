from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

GOOGLE_TRANSLATION_PROVIDER_SCHEMA = "m26-google-translation-provider/v1"
DEFAULT_TRANSLATION_LOCATION = "us-central1"
DEFAULT_TRANSLATION_MODEL = "general/translation-llm"
DEFAULT_TRANSLATION_TIMEOUT_SECONDS = 20.0


@dataclass(frozen=True)
class TranslationProviderConfig:
    project_id: str
    location: str = DEFAULT_TRANSLATION_LOCATION
    model: str = DEFAULT_TRANSLATION_MODEL
    timeout_seconds: float = DEFAULT_TRANSLATION_TIMEOUT_SECONDS

    @property
    def model_resource(self) -> str:
        return (
            f"projects/{self.project_id}/locations/{self.location}/models/"
            f"{self.model}"
        )

    @classmethod
    def from_env(cls) -> TranslationProviderConfig:
        project_id = (
            os.environ.get("M26_TRANSLATION_GOOGLE_PROJECT_ID")
            or os.environ.get("GOOGLE_CLOUD_PROJECT")
            or os.environ.get("GCLOUD_PROJECT")
            or ""
        ).strip()
        if not project_id:
            raise TranslationProviderError(
                "TRANSLATION_PROVIDER_CONFIG_MISSING",
                "Google translation project id is not configured",
            )
        location = os.environ.get("M26_TRANSLATION_GOOGLE_LOCATION", DEFAULT_TRANSLATION_LOCATION)
        model = os.environ.get("M26_TRANSLATION_GOOGLE_MODEL", DEFAULT_TRANSLATION_MODEL)
        timeout_raw = os.environ.get(
            "M26_TRANSLATION_TIMEOUT_SECONDS",
            str(DEFAULT_TRANSLATION_TIMEOUT_SECONDS),
        )
        try:
            timeout_seconds = float(timeout_raw)
        except ValueError as exc:
            raise TranslationProviderError(
                "TRANSLATION_PROVIDER_CONFIG_MISSING",
                "Google translation timeout is invalid",
            ) from exc
        if model != DEFAULT_TRANSLATION_MODEL:
            raise TranslationProviderError(
                "TRANSLATION_PROVIDER_CONFIG_MISSING",
                "Google translation model must be the configured Translation LLM",
            )
        return cls(
            project_id=project_id,
            location=location,
            model=model,
            timeout_seconds=timeout_seconds,
        )


@dataclass(frozen=True)
class TranslationRequest:
    text: str
    source_language: str
    target_language: str = "en"
    mime_type: str = "text/plain"


@dataclass(frozen=True)
class TranslationProviderResult:
    ok: bool
    translated_text: str = ""
    failure_code: str = ""
    failure_detail: str = ""
    provider: str = "google-cloud-translation-v3"
    model_resource: str = ""
    location: str = ""
    latency_ms: int = 0


class TranslationProvider(Protocol):
    calls: int

    def translate(self, request: TranslationRequest) -> TranslationProviderResult: ...


class TranslationProviderError(RuntimeError):
    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


class GoogleTranslationLLMProvider:
    def __init__(
        self,
        config: TranslationProviderConfig,
        *,
        access_token: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.config = config
        self._access_token = access_token
        self._client = client
        self.calls = 0

    def translate(self, request: TranslationRequest) -> TranslationProviderResult:
        self.calls += 1
        start = time.monotonic()
        if request.target_language != "en" or request.mime_type != "text/plain":
            return self._failed(
                "TRANSLATION_PROVIDER_CONFIG_MISSING",
                "translation target or MIME type is invalid",
                start,
            )
        token = self._access_token or _adc_access_token()
        endpoint = (
            f"https://translation.googleapis.com/v3/projects/{self.config.project_id}"
            f"/locations/{self.config.location}:translateText"
        )
        body: dict[str, Any] = {
            "contents": [request.text],
            "mimeType": request.mime_type,
            "targetLanguageCode": request.target_language,
            "model": self.config.model_resource,
        }
        if request.source_language:
            body["sourceLanguageCode"] = request.source_language
        try:
            if self._client is not None:
                response = self._client.post(
                    endpoint,
                    json=body,
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=self.config.timeout_seconds,
                )
            else:
                with httpx.Client(timeout=self.config.timeout_seconds) as client:
                    response = client.post(
                        endpoint,
                        json=body,
                        headers={"Authorization": f"Bearer {token}"},
                    )
        except httpx.TimeoutException:
            return self._failed("TRANSLATION_TIMEOUT", "translation request timed out", start)
        except httpx.HTTPError:
            return self._failed(
                "TRANSLATION_PROVIDER_FAILED",
                "translation transport failed",
                start,
            )
        if response.status_code < 200 or response.status_code >= 300:
            return self._failed(
                "TRANSLATION_PROVIDER_FAILED",
                f"translation provider returned HTTP {response.status_code}",
                start,
            )
        try:
            payload = response.json()
            translations = payload["translations"]
            translated_text = translations[0]["translatedText"]
        except (KeyError, IndexError, TypeError, ValueError):
            return self._failed(
                "TRANSLATION_OUTPUT_INVALID",
                "translation provider response was malformed",
                start,
            )
        if not isinstance(translated_text, str) or not translated_text.strip():
            return self._failed(
                "TRANSLATION_OUTPUT_INVALID",
                "translation provider returned empty text",
                start,
            )
        return TranslationProviderResult(
            ok=True,
            translated_text=translated_text,
            provider="google-cloud-translation-v3",
            model_resource=self.config.model_resource,
            location=self.config.location,
            latency_ms=_latency_ms(start),
        )

    def _failed(self, code: str, detail: str, start: float) -> TranslationProviderResult:
        return TranslationProviderResult(
            ok=False,
            failure_code=code,
            failure_detail=detail,
            model_resource=self.config.model_resource,
            location=self.config.location,
            latency_ms=_latency_ms(start),
        )


def _adc_access_token() -> str:
    try:
        import google.auth
        import google.auth.transport.requests
    except ImportError as exc:
        raise TranslationProviderError(
            "TRANSLATION_PROVIDER_CONFIG_MISSING",
            "google-auth is required for Application Default Credentials",
        ) from exc
    credentials, _project = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    request = google.auth.transport.requests.Request()
    credentials.refresh(request)
    token = getattr(credentials, "token", "")
    if not token:
        raise TranslationProviderError(
            "TRANSLATION_PROVIDER_CONFIG_MISSING",
            "Application Default Credentials did not provide an access token",
        )
    return str(token)


def _latency_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
