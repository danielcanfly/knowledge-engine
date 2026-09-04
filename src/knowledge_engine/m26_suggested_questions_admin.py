from __future__ import annotations

import asyncio
import ast
import base64
import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request as URLRequest, urlopen

from fastapi import APIRouter, FastAPI, Request
from pydantic import BaseModel, field_validator

from .m26_admin_control_plane import AdminAPIError, request_id_from, require_capability
from .m26_admin_contract import utc_now

DEFAULT_REPOSITORY = "danielcanfly/daniel-blog"
DEFAULT_SOURCE_PATH = "src/data/m26-home-suggested-questions.mjs"
DEFAULT_SOURCE_REF = "main"
SOURCE_TOKEN_ENV = "M26_SUGGESTED_QUESTIONS_GITHUB_TOKEN"


@dataclass(frozen=True)
class SuggestedQuestionsSnapshot:
    repository: str
    source_path: str
    source_ref: str
    content_blob_sha: str
    observed_repo_commit: str | None
    questions: tuple[str, ...]
    observed_at: str

    @property
    def revision(self) -> str:
        return f"github-blob:{self.content_blob_sha}"

    @property
    def evidence_digest(self) -> str:
        payload = json.dumps(
            {
                "repository": self.repository,
                "source_path": self.source_path,
                "source_ref": self.source_ref,
                "content_blob_sha": self.content_blob_sha,
                "questions": self.questions,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(payload).hexdigest()


class SuggestedQuestionsSourceUnavailable(RuntimeError):
    def __init__(self, reason_code: str, detail: str) -> None:
        super().__init__(detail)
        self.reason_code = reason_code
        self.detail = detail


def parse_homepage_question_source(source: str) -> tuple[str, ...]:
    marker = "M26_HOME_SUGGESTED_QUESTIONS"
    if marker not in source or "Object.freeze([" not in source:
        raise ValueError("suggested-question source marker is missing")
    questions: list[str] = []
    inside = False
    for raw_line in source.splitlines():
        line = raw_line.strip()
        if not inside:
            if "Object.freeze([" in line:
                inside = True
            continue
        if line.startswith("])") or line.startswith("];") or line == "]);":
            break
        if not line or line.startswith("//"):
            continue
        literal = line[:-1] if line.endswith(",") else line
        value = ast.literal_eval(literal)
        if not isinstance(value, str) or not value.strip():
            raise ValueError("question pool contains a non-string or empty item")
        questions.append(value)
    if not questions:
        raise ValueError("suggested-question source yielded no questions")
    if len(set(questions)) != len(questions):
        raise ValueError("suggested-question source contains an exact duplicate")
    return tuple(questions)


class GitHubSuggestedQuestionsSource:
    def __init__(
        self,
        *,
        repository: str = DEFAULT_REPOSITORY,
        source_path: str = DEFAULT_SOURCE_PATH,
        source_ref: str = DEFAULT_SOURCE_REF,
        token: str | None = None,
        timeout_seconds: float = 8.0,
    ) -> None:
        self.repository = repository
        self.source_path = source_path
        self.source_ref = source_ref
        self.token = token if token is not None else os.getenv(SOURCE_TOKEN_ENV)
        self.timeout_seconds = timeout_seconds

    def _json(self, url: str) -> dict[str, Any]:
        if not self.token:
            raise SuggestedQuestionsSourceUnavailable(
                "SUGGESTED_QUESTIONS_SOURCE_CREDENTIAL_UNAVAILABLE",
                "Server-side GitHub read credential is not configured for the private publication source.",
            )
        request = URLRequest(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "m26-console-suggested-questions-read-model",
            },
            method="GET",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise SuggestedQuestionsSourceUnavailable(
                "SUGGESTED_QUESTIONS_SOURCE_HTTP_ERROR",
                f"GitHub publication source returned HTTP {exc.code}.",
            ) from exc
        except (URLError, TimeoutError) as exc:
            raise SuggestedQuestionsSourceUnavailable(
                "SUGGESTED_QUESTIONS_SOURCE_NETWORK_ERROR",
                "GitHub publication source could not be observed.",
            ) from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SuggestedQuestionsSourceUnavailable(
                "SUGGESTED_QUESTIONS_SOURCE_INVALID_RESPONSE",
                "GitHub publication source response was not valid JSON.",
            ) from exc

    def read(self) -> SuggestedQuestionsSnapshot:
        owner, separator, repo = self.repository.partition("/")
        if not separator or not owner or not repo:
            raise SuggestedQuestionsSourceUnavailable(
                "SUGGESTED_QUESTIONS_SOURCE_CONFIG_INVALID",
                "Publication repository must use owner/repository form.",
            )
        contents_url = (
            f"https://api.github.com/repos/{quote(owner)}/{quote(repo)}/contents/"
            f"{quote(self.source_path, safe='/')}?ref={quote(self.source_ref, safe='')}"
        )
        payload = self._json(contents_url)
        if payload.get("encoding") != "base64" or not isinstance(payload.get("content"), str):
            raise SuggestedQuestionsSourceUnavailable(
                "SUGGESTED_QUESTIONS_SOURCE_ENCODING_UNSUPPORTED",
                "GitHub publication source did not return base64 file content.",
            )
        try:
            source = base64.b64decode(payload["content"]).decode("utf-8")
            questions = parse_homepage_question_source(source)
        except (ValueError, UnicodeDecodeError) as exc:
            raise SuggestedQuestionsSourceUnavailable(
                "SUGGESTED_QUESTIONS_SOURCE_PARSE_FAILED",
                "Homepage Suggested Questions source could not be parsed safely.",
            ) from exc

        blob_sha = payload.get("sha")
        if not isinstance(blob_sha, str) or not blob_sha:
            raise SuggestedQuestionsSourceUnavailable(
                "SUGGESTED_QUESTIONS_SOURCE_REVISION_MISSING",
                "GitHub publication source did not expose a content blob revision.",
            )

        commit_sha: str | None = None
        try:
            commit_payload = self._json(
                f"https://api.github.com/repos/{quote(owner)}/{quote(repo)}/commits/"
                f"{quote(self.source_ref, safe='')}"
            )
            if isinstance(commit_payload.get("sha"), str):
                commit_sha = commit_payload["sha"]
        except SuggestedQuestionsSourceUnavailable:
            commit_sha = None

        return SuggestedQuestionsSnapshot(
            repository=self.repository,
            source_path=self.source_path,
            source_ref=self.source_ref,
            content_blob_sha=blob_sha,
            observed_repo_commit=commit_sha,
            questions=questions,
            observed_at=utc_now(),
        )


def _question_record(text: str, index: int, snapshot: SuggestedQuestionsSnapshot) -> dict[str, Any]:
    stable_id = "sq_" + hashlib.sha256(text.encode()).hexdigest()[:16]
    return {
        "id": stable_id,
        "text": text,
        "state": "published",
        "locale": "en",
        "category": None,
        "tags": [],
        "display_order": index + 1,
        "enabled": True,
        "source": f"{snapshot.repository}:{snapshot.source_path}@{snapshot.content_blob_sha}",
        "duplicate_of": None,
        "latest_test": None,
    }


def _available_envelope(request: Request, snapshot: SuggestedQuestionsSnapshot) -> dict[str, Any]:
    return {
        "request_id": request_id_from(request),
        "availability": {"status": "available", "reason_code": None, "detail": None},
        "provenance": {
            "source": "github_repository_read_projection",
            "resource_identity": {
                "repository": snapshot.repository,
                "source_path": snapshot.source_path,
                "source_ref": snapshot.source_ref,
                "content_blob_sha": snapshot.content_blob_sha,
                "observed_repo_commit": snapshot.observed_repo_commit,
            },
            "evidence_digest": snapshot.evidence_digest,
            "source_observed_at": snapshot.observed_at,
        },
        "observed_at": snapshot.observed_at,
        "freshness": "live",
        "data": {
            "publication": {
                "authority": "git_source",
                "repository": snapshot.repository,
                "source_path": snapshot.source_path,
                "source_ref": snapshot.source_ref,
                "observed_repo_commit": snapshot.observed_repo_commit,
                "revision": snapshot.revision,
                "content_blob_sha": snapshot.content_blob_sha,
                "question_count": len(snapshot.questions),
                "sampler_count": 3,
                "write_authority": "unselected",
            },
            "questions": [
                _question_record(text, index, snapshot)
                for index, text in enumerate(snapshot.questions)
            ],
        },
    }


def _unavailable_envelope(
    request: Request, source: GitHubSuggestedQuestionsSource, exc: SuggestedQuestionsSourceUnavailable
) -> dict[str, Any]:
    return {
        "request_id": request_id_from(request),
        "availability": {
            "status": "unavailable",
            "reason_code": exc.reason_code,
            "detail": exc.detail,
        },
        "provenance": {
            "source": "github_repository_read_projection",
            "resource_identity": {
                "repository": source.repository,
                "source_path": source.source_path,
                "source_ref": source.source_ref,
            },
            "evidence_digest": None,
            "source_observed_at": None,
        },
        "observed_at": None,
        "freshness": "unknown",
        "data": {
            "publication": {
                "authority": "git_source",
                "repository": source.repository,
                "source_path": source.source_path,
                "source_ref": source.source_ref,
                "observed_repo_commit": None,
                "revision": None,
                "content_blob_sha": None,
                "question_count": None,
                "sampler_count": 3,
                "write_authority": "unselected",
            },
            "questions": [],
        },
    }


class SuggestedQuestionsUpdate(BaseModel):
    base_revision: str
    operations: list[dict[str, Any]]

    @field_validator("operations")
    @classmethod
    def bounded_operations(cls, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if len(value) > 100:
            raise ValueError("operations may contain at most 100 items")
        return value


def _router() -> APIRouter:
    router = APIRouter(prefix="/v1/admin", tags=["SuggestedQuestions"])

    @router.get("/suggested-questions", operation_id="listSuggestedQuestions")
    async def list_suggested_questions(request: Request) -> dict[str, Any]:
        source = request.app.state.suggested_questions_source
        try:
            snapshot = await asyncio.to_thread(source.read)
        except SuggestedQuestionsSourceUnavailable as exc:
            return _unavailable_envelope(request, source, exc)
        return _available_envelope(request, snapshot)

    @router.put("/suggested-questions", operation_id="updateSuggestedQuestions", status_code=202)
    async def update_suggested_questions(
        request: Request, payload: SuggestedQuestionsUpdate
    ) -> dict[str, Any]:
        del payload
        require_capability(request, "suggested_questions.publish", mutation=True)
        raise AdminAPIError(
            status_code=409,
            code="SUGGESTED_QUESTIONS_WRITE_AUTHORITY_UNSELECTED",
            message="No governed homepage publication write adapter has been selected.",
            details={
                "publication_authority": "daniel-blog Git source",
                "required_before_enablement": [
                    "governed server-side write adapter",
                    "base_revision compare-and-swap",
                    "durable idempotency and audit",
                    "homepage readback proof",
                ],
            },
        )

    return router


def install_suggested_questions_admin(
    app: FastAPI, *, source: GitHubSuggestedQuestionsSource | Any | None = None
) -> FastAPI:
    if getattr(app.state, "suggested_questions_admin_installed", False):
        return app
    app.state.suggested_questions_source = source or GitHubSuggestedQuestionsSource()
    app.include_router(_router())
    app.state.suggested_questions_admin_installed = True
    return app


__all__ = [
    "DEFAULT_REPOSITORY",
    "DEFAULT_SOURCE_PATH",
    "DEFAULT_SOURCE_REF",
    "GitHubSuggestedQuestionsSource",
    "SuggestedQuestionsSnapshot",
    "SuggestedQuestionsSourceUnavailable",
    "install_suggested_questions_admin",
    "parse_homepage_question_source",
]
