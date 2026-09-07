from __future__ import annotations

import ast
import asyncio
import base64
import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request as URLRequest
from urllib.request import urlopen

from fastapi import APIRouter, FastAPI, Request
from pydantic import BaseModel, field_validator

from .config import Settings
from .errors import ReleaseConflictError
from .m26_admin_contract import utc_now
from .m26_admin_control_plane import (
    AdminAPIError,
    actor_from,
    append_audit_event,
    build_audit_event,
    request_id_from,
    require_capability,
)
from .m26_ask_api import DEFAULT_GATE_PATH, run_owner_query_for_web
from .m26_pa5_v8_live import MODEL, MiniMaxClient
from .storage import create_object_store
from .suggested_questions_promotion import (
    ObjectStoreSuggestedQuestionsPromotionStore,
    SuggestedQuestionsPromotionError,
    SuggestedQuestionsPromotionUnavailable,
    build_promotion_preview,
    publish_promotion,
    record_preview_evaluations,
)
from .suggested_questions_scoring import (
    ProviderSuggestedQuestionsEvaluator,
    UnavailableSuggestedQuestionsEvaluator,
)

DEFAULT_REPOSITORY = "danielcanfly/daniel-blog"
DEFAULT_SOURCE_PATH = "src/data/m26-home-suggested-questions.mjs"
DEFAULT_SOURCE_REF = "main"
SOURCE_TOKEN_ENV = "M26_SUGGESTED_QUESTIONS_GITHUB_TOKEN"
WRITE_TOKEN_ENV = "M26_SUGGESTED_QUESTIONS_GITHUB_WRITE_TOKEN"


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
                "Server-side GitHub read credential is not configured "
                "for the private publication source.",
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
                "write_authority": "governed_git_adapter",
            },
            "questions": [
                _question_record(text, index, snapshot)
                for index, text in enumerate(snapshot.questions)
            ],
        },
    }


def _unavailable_envelope(
    request: Request,
    source: GitHubSuggestedQuestionsSource,
    exc: SuggestedQuestionsSourceUnavailable,
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
                "write_authority": "governed_git_adapter",
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


class SuggestedQuestionsPromotionPreviewRequest(BaseModel):
    event_ids: list[str]

    @field_validator("event_ids")
    @classmethod
    def bounded_unique_event_ids(cls, value: list[str]) -> list[str]:
        normalized = [str(item).strip() for item in value]
        if not normalized or any(not item for item in normalized):
            raise ValueError("event_ids requires one or more non-empty IDs")
        if len(normalized) > 20:
            raise ValueError("at most 20 QA events may be previewed at once")
        if len(set(normalized)) != len(normalized):
            raise ValueError("event_ids must be unique")
        return normalized


class SuggestedQuestionsPromotionPublishRequest(BaseModel):
    base_revision: str
    selected_event_ids: list[str]

    @field_validator("selected_event_ids")
    @classmethod
    def bounded_unique_selected_ids(cls, value: list[str]) -> list[str]:
        normalized = [str(item).strip() for item in value]
        if not normalized or any(not item for item in normalized):
            raise ValueError("selected_event_ids requires one or more non-empty IDs")
        if len(normalized) > 20:
            raise ValueError("at most 20 candidates may be published at once")
        if len(set(normalized)) != len(normalized):
            raise ValueError("selected_event_ids must be unique")
        return normalized


def _append_questions_to_source(source: str, questions: Sequence[str]) -> str:
    marker = "M26_HOME_SUGGESTED_QUESTIONS"
    marker_index = source.find(marker)
    if marker_index < 0:
        raise ValueError("suggested-question source marker is missing")
    close_index = source.find("]);", marker_index)
    if close_index < marker_index:
        raise ValueError("suggested-question source closing marker is missing")
    addition = "".join(f"  {json.dumps(question, ensure_ascii=False)},\n" for question in questions)
    return source[:close_index] + addition + source[close_index:]


class GitHubSuggestedQuestionsPublisher:
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
        self.token = token if token is not None else os.getenv(WRITE_TOKEN_ENV)
        self.timeout_seconds = timeout_seconds

    def _request_json(
        self,
        url: str,
        *,
        method: str = "GET",
        payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.token:
            raise SuggestedQuestionsSourceUnavailable(
                "SUGGESTED_QUESTIONS_WRITE_CREDENTIAL_UNAVAILABLE",
                "Server-side GitHub write credential is not configured.",
            )
        body = json.dumps(payload).encode() if payload is not None else None
        request = URLRequest(
            url,
            data=body,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "m26-console-suggested-questions-governed-publisher",
                **({"Content-Type": "application/json"} if body is not None else {}),
            },
            method=method,
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code in {409, 412, 422}:
                raise ReleaseConflictError("Suggested Questions Git revision changed") from exc
            raise SuggestedQuestionsSourceUnavailable(
                "SUGGESTED_QUESTIONS_WRITE_HTTP_ERROR",
                f"GitHub publication mutation returned HTTP {exc.code}.",
            ) from exc
        except (URLError, TimeoutError) as exc:
            raise SuggestedQuestionsSourceUnavailable(
                "SUGGESTED_QUESTIONS_WRITE_NETWORK_ERROR",
                "GitHub publication mutation could not be completed.",
            ) from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SuggestedQuestionsSourceUnavailable(
                "SUGGESTED_QUESTIONS_WRITE_INVALID_RESPONSE",
                "GitHub publication mutation response was invalid.",
            ) from exc
        if not isinstance(result, dict):
            raise SuggestedQuestionsSourceUnavailable(
                "SUGGESTED_QUESTIONS_WRITE_INVALID_RESPONSE",
                "GitHub publication mutation response was not an object.",
            )
        return result

    def publish(
        self,
        *,
        base_revision: str,
        questions: Sequence[str],
        operation_id: str,
    ) -> Mapping[str, Any]:
        expected_prefix = "github-blob:"
        if not base_revision.startswith(expected_prefix):
            raise ValueError("base_revision must be a github-blob revision")
        expected_blob = base_revision[len(expected_prefix) :]
        owner, separator, repo = self.repository.partition("/")
        if not separator or not owner or not repo:
            raise ValueError("publication repository must use owner/repository form")
        contents_url = (
            f"https://api.github.com/repos/{quote(owner)}/{quote(repo)}/contents/"
            f"{quote(self.source_path, safe='/')}"
        )
        current = self._request_json(
            f"{contents_url}?ref={quote(self.source_ref, safe='')}", method="GET"
        )
        current_blob = str(current.get("sha") or "")
        if current_blob != expected_blob:
            raise ReleaseConflictError("Suggested Questions base revision changed")
        if current.get("encoding") != "base64" or not isinstance(current.get("content"), str):
            raise SuggestedQuestionsSourceUnavailable(
                "SUGGESTED_QUESTIONS_SOURCE_ENCODING_UNSUPPORTED",
                "GitHub publication source did not return base64 file content.",
            )
        source = base64.b64decode(current["content"]).decode("utf-8")
        existing = parse_homepage_question_source(source)
        existing_normalized = {" ".join(item.casefold().split()) for item in existing}
        additions: list[str] = []
        for raw in questions:
            question = " ".join(str(raw).split())
            if not question:
                raise ValueError("published question must not be empty")
            normalized = " ".join(question.casefold().split())
            if normalized in existing_normalized:
                raise ValueError("published question already exists")
            if normalized not in {" ".join(item.casefold().split()) for item in additions}:
                additions.append(question)
        if not additions:
            raise ValueError("publication requires at least one new question")
        updated_source = _append_questions_to_source(source, additions)
        result = self._request_json(
            contents_url,
            method="PUT",
            payload={
                "message": f"chore: publish governed suggested questions ({operation_id})",
                "content": base64.b64encode(updated_source.encode()).decode(),
                "sha": current_blob,
                "branch": self.source_ref,
            },
        )
        content = result.get("content") if isinstance(result.get("content"), Mapping) else {}
        commit = result.get("commit") if isinstance(result.get("commit"), Mapping) else {}
        new_blob = str(content.get("sha") or "")
        if not new_blob:
            raise SuggestedQuestionsSourceUnavailable(
                "SUGGESTED_QUESTIONS_WRITE_REVISION_MISSING",
                "GitHub mutation did not return a content revision.",
            )
        readback_payload = self._request_json(
            f"{contents_url}?ref={quote(self.source_ref, safe='')}", method="GET"
        )
        if readback_payload.get("encoding") != "base64" or not isinstance(
            readback_payload.get("content"), str
        ):
            raise SuggestedQuestionsSourceUnavailable(
                "SUGGESTED_QUESTIONS_READBACK_INVALID",
                "Published source could not be read back.",
            )
        readback_source = base64.b64decode(readback_payload["content"]).decode("utf-8")
        readback_questions = parse_homepage_question_source(readback_source)
        readback_normalized = {" ".join(item.casefold().split()) for item in readback_questions}
        verified = all(" ".join(item.casefold().split()) in readback_normalized for item in additions)
        if not verified or str(readback_payload.get("sha") or "") != new_blob:
            raise SuggestedQuestionsSourceUnavailable(
                "SUGGESTED_QUESTIONS_READBACK_MISMATCH",
                "Published questions failed Git readback verification.",
            )
        return {
            "revision": f"github-blob:{new_blob}",
            "content_blob_sha": new_blob,
            "commit_sha": str(commit.get("sha") or "") or None,
            "question_count": len(readback_questions),
            "added_questions": additions,
            "readback_verified": True,
        }


class CanonicalSuggestedQuestionRerunner:
    def __init__(
        self,
        *,
        root: Path | None = None,
        gate_path: Path | None = None,
    ) -> None:
        self.root = root or Path(os.environ.get("M26_QUERY_ROOT", "."))
        self.gate_path = gate_path or Path(os.environ.get("M26_QUERY_GATE_PATH", str(DEFAULT_GATE_PATH)))

    def run(self, question: str) -> Mapping[str, Any]:
        owner_hash = ""
        for name in (
            "STAGING_M26_OWNER_SUBJECT_HASH",
            "KNOWLEDGE_ENGINE_OWNER_SUBJECT_HASH",
            "M26_OWNER_SUBJECT_HASH",
        ):
            owner_hash = os.environ.get(name, "").strip().lower()
            if owner_hash:
                break
        if not owner_hash:
            raise SuggestedQuestionsPromotionUnavailable(
                "qualified runtime owner hash is not configured"
            )
        try:
            return run_owner_query_for_web(
                root=self.root,
                gate_path=self.gate_path,
                request_payload={"question": question},
                owner_subject_hash=owner_hash,
                public_request=True,
            )
        except Exception as exc:
            raise SuggestedQuestionsPromotionUnavailable(
                "canonical Suggested Questions promotion rerun failed"
            ) from exc


@lru_cache(maxsize=1)
def _promotion_store_from_env() -> ObjectStoreSuggestedQuestionsPromotionStore:
    return ObjectStoreSuggestedQuestionsPromotionStore(create_object_store(Settings.from_env()))


@lru_cache(maxsize=1)
def _suggested_questions_evaluator_from_env() -> Any:
    api_key = os.environ.get("MINIMAX_API_KEY", "").strip()
    if not api_key:
        return UnavailableSuggestedQuestionsEvaluator()
    client = MiniMaxClient(api_key, max_calls=500, max_cost=Decimal("10"))
    return ProviderSuggestedQuestionsEvaluator(
        client,
        provider_name="minimax",
        model=MODEL,
    )


def _dependency(request: Request, name: str, factory: Any) -> Any:
    value = getattr(request.app.state, name, None)
    return value if value is not None else factory()


def _qa_repository(request: Request) -> Any:
    value = getattr(request.app.state, "suggested_questions_qa_repository", None)
    if value is not None:
        return value
    from .m26_qa_inbox_integration import qa_repository_from_env

    return qa_repository_from_env()


def _aq_evaluator(request: Request) -> Any:
    value = getattr(request.app.state, "suggested_questions_aq_evaluator", None)
    if value is not None:
        return value
    from .m26_qa_inbox_integration import qa_evaluator_from_env

    return qa_evaluator_from_env()


def _audit_promotion(
    request: Request,
    *,
    action: str,
    outcome: str,
    reason_code: str,
    operation_id: str | None,
    object_id: str | None,
    metadata: Mapping[str, Any] | None = None,
) -> None:
    append_audit_event(
        request,
        build_audit_event(
            actor=actor_from(request),
            action=action,
            object_type="suggested_questions_promotion",
            object_id=object_id,
            request_id=request_id_from(request),
            operation_id=operation_id,
            outcome=outcome,
            reason_code=reason_code,
            metadata=metadata or {},
        ),
    )


def _promotion_response(
    request: Request,
    record: Mapping[str, Any],
    *,
    replayed: bool,
    operation_id: str | None = None,
) -> dict[str, Any]:
    return {
        "request_id": request_id_from(request),
        "operation_id": operation_id or str(record["promotion_id"]),
        "replayed": replayed,
        "data": dict(record),
    }


def _begin_idempotent_operation(
    request: Request,
    payload: Mapping[str, Any],
) -> tuple[str, bool]:
    actor = actor_from(request)
    return request.app.state.admin_idempotency.begin(
        actor_id=actor.actor_id,
        method=request.method,
        path=request.url.path,
        idempotency_key=request.headers.get("idempotency-key", ""),
        request_payload=dict(payload),
    )


def _candidate_questions_for_ids(
    record: Mapping[str, Any], selected_event_ids: Sequence[str]
) -> list[str]:
    by_id = {
        str(item.get("event_id")): item
        for item in record.get("candidates", [])
        if isinstance(item, Mapping)
    }
    result: list[str] = []
    for event_id in selected_event_ids:
        item = by_id.get(str(event_id))
        if item is None:
            raise SuggestedQuestionsPromotionError("selected event is not part of the preview")
        if item.get("status") != "eligible":
            raise SuggestedQuestionsPromotionError(
                "only preview-eligible candidates may be published"
            )
        result.append(str(item.get("question") or ""))
    return result


def _mark_published_from_readback(
    *,
    record: Mapping[str, Any],
    selected_event_ids: Sequence[str],
    snapshot: SuggestedQuestionsSnapshot,
    publish_operation_id: str,
    qa_repository: Any,
) -> dict[str, Any] | None:
    questions = _candidate_questions_for_ids(record, selected_event_ids)
    present = {" ".join(item.casefold().split()) for item in snapshot.questions}
    if not all(" ".join(question.casefold().split()) in present for question in questions):
        return None
    updated = dict(record)
    updated["status"] = "published"
    updated["publication"] = {
        "revision": snapshot.revision,
        "content_blob_sha": snapshot.content_blob_sha,
        "commit_sha": snapshot.observed_repo_commit,
        "question_count": len(snapshot.questions),
        "added_questions": questions,
        "readback_verified": True,
        "selected_event_ids": list(selected_event_ids),
        "publish_operation_id": publish_operation_id,
        "reconciled_from_readback": True,
    }
    for event_id in selected_event_ids:
        item = next(
            (
                candidate
                for candidate in record.get("candidates", [])
                if isinstance(candidate, Mapping)
                and str(candidate.get("event_id")) == str(event_id)
            ),
            None,
        )
        sq_payload = (
            item.get("suggested_questions_evaluation")
            if isinstance(item, Mapping)
            and isinstance(item.get("suggested_questions_evaluation"), Mapping)
            else {}
        )
        try:
            qa_repository.record_suggested_questions_evaluation(
                str(event_id),
                status="published",
                score=int(sq_payload.get("score"))
                if isinstance(sq_payload.get("score"), int)
                else None,
                result=str(sq_payload.get("result") or "pass"),
                rubric_version=str(
                    sq_payload.get("rubric_version")
                    or "SUGGESTED_QUESTIONS_OWNER_RUBRIC_v1"
                ),
                promotion_id=str(record["promotion_id"]),
                production_published=True,
                publication_revision=snapshot.revision,
            )
        except (KeyError, AttributeError):
            pass
    return updated


def _promotion_error(exc: Exception) -> AdminAPIError:
    if isinstance(exc, ReleaseConflictError):
        return AdminAPIError(
            status_code=409,
            code="SUGGESTED_QUESTIONS_REVISION_CONFLICT",
            message=str(exc),
        )
    if isinstance(exc, SuggestedQuestionsPromotionUnavailable):
        return AdminAPIError(
            status_code=503,
            code="SUGGESTED_QUESTIONS_PROMOTION_UNAVAILABLE",
            message=str(exc),
            retryable=True,
        )
    if isinstance(exc, SuggestedQuestionsSourceUnavailable):
        return AdminAPIError(
            status_code=503,
            code=exc.reason_code,
            message=exc.detail,
            retryable=True,
        )
    if isinstance(exc, (SuggestedQuestionsPromotionError, ValueError)):
        return AdminAPIError(
            status_code=422,
            code="SUGGESTED_QUESTIONS_PROMOTION_INVALID",
            message=str(exc),
        )
    return AdminAPIError(
        status_code=500,
        code="SUGGESTED_QUESTIONS_PROMOTION_FAILED",
        message="Suggested Questions promotion failed",
    )


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

    @router.post(
        "/suggested-questions/promotions/preview",
        operation_id="previewSuggestedQuestionsPromotion",
    )
    async def preview_suggested_questions_promotion(
        request: Request, payload: SuggestedQuestionsPromotionPreviewRequest
    ) -> dict[str, Any]:
        require_capability(request, "suggested_questions.publish", mutation=True)
        canonical_request = {"event_ids": list(payload.event_ids)}
        operation_id, replayed = _begin_idempotent_operation(request, canonical_request)
        store = _dependency(
            request,
            "suggested_questions_promotion_store",
            _promotion_store_from_env,
        )
        if replayed:
            try:
                record = store.get(operation_id)
            except KeyError as exc:
                raise AdminAPIError(
                    status_code=409,
                    code="SUGGESTED_QUESTIONS_PREVIEW_REPLAY_RESULT_UNAVAILABLE",
                    message="The preview operation exists but its durable result is unavailable.",
                ) from exc
            _audit_promotion(
                request,
                action="suggested_questions.promotion.preview.replayed",
                outcome="accepted",
                reason_code="SUGGESTED_QUESTIONS_PREVIEW_REPLAYED",
                operation_id=operation_id,
                object_id=operation_id,
                metadata={"event_count": len(payload.event_ids)},
            )
            return _promotion_response(
                request, record, replayed=True, operation_id=operation_id
            )

        source = request.app.state.suggested_questions_source
        try:
            snapshot = await asyncio.to_thread(source.read)
            record = await asyncio.to_thread(
                build_promotion_preview,
                promotion_id=operation_id,
                event_ids=payload.event_ids,
                qa_repository=_qa_repository(request),
                rerunner=_dependency(
                    request,
                    "suggested_questions_rerunner",
                    CanonicalSuggestedQuestionRerunner,
                ),
                aq_evaluator=_aq_evaluator(request),
                sq_evaluator=_dependency(
                    request,
                    "suggested_questions_sq_evaluator",
                    _suggested_questions_evaluator_from_env,
                ),
                existing_questions=snapshot.questions,
                source_revision=snapshot.revision,
                source_evidence_digest=snapshot.evidence_digest,
                observed_at=utc_now(),
            )
            record = store.create(operation_id, record)
            record_preview_evaluations(record, _qa_repository(request))
        except AdminAPIError:
            raise
        except Exception as exc:
            error = _promotion_error(exc)
            _audit_promotion(
                request,
                action="suggested_questions.promotion.preview.rejected",
                outcome="rejected",
                reason_code=error.code,
                operation_id=operation_id,
                object_id=operation_id,
                metadata={"event_count": len(payload.event_ids)},
            )
            raise error from exc
        _audit_promotion(
            request,
            action="suggested_questions.promotion.preview.accepted",
            outcome="accepted",
            reason_code="SUGGESTED_QUESTIONS_PREVIEW_READY",
            operation_id=operation_id,
            object_id=operation_id,
            metadata={"summary": record.get("summary", {})},
        )
        return _promotion_response(
            request, record, replayed=False, operation_id=operation_id
        )

    @router.get(
        "/suggested-questions/promotions/{promotion_id}",
        operation_id="getSuggestedQuestionsPromotion",
    )
    async def get_suggested_questions_promotion(
        request: Request, promotion_id: str
    ) -> dict[str, Any]:
        store = _dependency(
            request,
            "suggested_questions_promotion_store",
            _promotion_store_from_env,
        )
        try:
            record = store.get(promotion_id)
        except KeyError as exc:
            raise AdminAPIError(
                status_code=404,
                code="SUGGESTED_QUESTIONS_PROMOTION_NOT_FOUND",
                message="Suggested Questions promotion preview was not found.",
            ) from exc
        return _promotion_response(request, record, replayed=False)

    @router.post(
        "/suggested-questions/promotions/{promotion_id}/publish",
        operation_id="publishSuggestedQuestionsPromotion",
    )
    async def publish_suggested_questions_promotion(
        request: Request,
        promotion_id: str,
        payload: SuggestedQuestionsPromotionPublishRequest,
    ) -> dict[str, Any]:
        require_capability(request, "suggested_questions.publish", mutation=True)
        store = _dependency(
            request,
            "suggested_questions_promotion_store",
            _promotion_store_from_env,
        )
        try:
            record = store.get(promotion_id)
        except KeyError as exc:
            raise AdminAPIError(
                status_code=404,
                code="SUGGESTED_QUESTIONS_PROMOTION_NOT_FOUND",
                message="Suggested Questions promotion preview was not found.",
            ) from exc
        if str(payload.base_revision) != str(record.get("base_revision")):
            raise AdminAPIError(
                status_code=409,
                code="SUGGESTED_QUESTIONS_REVISION_CONFLICT",
                message="Publish request base_revision does not match the preview revision.",
            )
        canonical_request = {
            "promotion_id": promotion_id,
            "base_revision": payload.base_revision,
            "selected_event_ids": list(payload.selected_event_ids),
        }
        operation_id, replayed = _begin_idempotent_operation(request, canonical_request)

        if record.get("status") == "published":
            try:
                published = publish_promotion(
                    record=record,
                    selected_event_ids=payload.selected_event_ids,
                    current_source_revision=str(record.get("base_revision")),
                    publisher=_dependency(
                        request,
                        "suggested_questions_publisher",
                        GitHubSuggestedQuestionsPublisher,
                    ),
                    publish_operation_id=operation_id,
                    qa_repository=_qa_repository(request),
                )
            except Exception as exc:
                raise _promotion_error(exc) from exc
            return _promotion_response(
                request, published, replayed=True, operation_id=operation_id
            )

        source = request.app.state.suggested_questions_source
        try:
            snapshot = await asyncio.to_thread(source.read)
            if replayed:
                reconciled = _mark_published_from_readback(
                    record=record,
                    selected_event_ids=payload.selected_event_ids,
                    snapshot=snapshot,
                    publish_operation_id=operation_id,
                    qa_repository=_qa_repository(request),
                )
                if reconciled is not None:
                    try:
                        record = store.replace(promotion_id, reconciled)
                    except ReleaseConflictError:
                        latest = store.get(promotion_id)
                        if latest.get("status") != "published":
                            raise
                        record = latest
                    _audit_promotion(
                        request,
                        action="suggested_questions.promotion.publish.reconciled",
                        outcome="accepted",
                        reason_code="SUGGESTED_QUESTIONS_PUBLISH_READBACK_RECONCILED",
                        operation_id=operation_id,
                        object_id=promotion_id,
                        metadata={"selected_event_ids": list(payload.selected_event_ids)},
                    )
                    return _promotion_response(
                        request, record, replayed=True, operation_id=operation_id
                    )
            updated = await asyncio.to_thread(
                publish_promotion,
                record=record,
                selected_event_ids=payload.selected_event_ids,
                current_source_revision=snapshot.revision,
                publisher=_dependency(
                    request,
                    "suggested_questions_publisher",
                    GitHubSuggestedQuestionsPublisher,
                ),
                publish_operation_id=operation_id,
                qa_repository=_qa_repository(request),
            )
            try:
                record = store.replace(promotion_id, updated)
            except ReleaseConflictError:
                latest = store.get(promotion_id)
                if latest.get("status") != "published":
                    raise
                record = latest
        except AdminAPIError:
            raise
        except Exception as exc:
            error = _promotion_error(exc)
            _audit_promotion(
                request,
                action="suggested_questions.promotion.publish.rejected",
                outcome="rejected",
                reason_code=error.code,
                operation_id=operation_id,
                object_id=promotion_id,
                metadata={"selected_event_ids": list(payload.selected_event_ids)},
            )
            raise error from exc
        _audit_promotion(
            request,
            action="suggested_questions.promotion.publish.accepted",
            outcome="accepted",
            reason_code="SUGGESTED_QUESTIONS_PUBLISH_VERIFIED",
            operation_id=operation_id,
            object_id=promotion_id,
            metadata={
                "selected_event_ids": list(payload.selected_event_ids),
                "publication_revision": (record.get("publication") or {}).get("revision")
                if isinstance(record.get("publication"), Mapping)
                else None,
            },
        )
        return _promotion_response(
            request, record, replayed=replayed, operation_id=operation_id
        )

    @router.put("/suggested-questions", operation_id="updateSuggestedQuestions", status_code=202)
    async def update_suggested_questions(
        request: Request, payload: SuggestedQuestionsUpdate
    ) -> dict[str, Any]:
        del payload
        require_capability(request, "suggested_questions.publish", mutation=True)
        raise AdminAPIError(
            status_code=409,
            code="SUGGESTED_QUESTIONS_GOVERNED_PROMOTION_REQUIRED",
            message=(
                "Direct Suggested Questions mutation is disabled. Use the governed "
                "promotion preview and explicit publish endpoints."
            ),
            details={
                "publication_authority": "daniel-blog Git source",
                "preview_endpoint": "/v1/admin/suggested-questions/promotions/preview",
                "publish_endpoint": (
                    "/v1/admin/suggested-questions/promotions/{promotion_id}/publish"
                ),
                "requirements": [
                    "fresh canonical answer rerun",
                    "current Answer Quality PASS",
                    "independent Suggested Questions score >= 85",
                    "semantic dedupe",
                    "base_revision compare-and-swap",
                    "durable idempotency and audit",
                    "homepage readback proof",
                ],
            },
        )

    return router


def install_suggested_questions_admin(
    app: FastAPI,
    *,
    source: GitHubSuggestedQuestionsSource | Any | None = None,
    promotion_store: Any | None = None,
    rerunner: Any | None = None,
    aq_evaluator: Any | None = None,
    sq_evaluator: Any | None = None,
    publisher: Any | None = None,
) -> FastAPI:
    if getattr(app.state, "suggested_questions_admin_installed", False):
        return app
    app.state.suggested_questions_source = source or GitHubSuggestedQuestionsSource()
    if promotion_store is not None:
        app.state.suggested_questions_promotion_store = promotion_store
    if rerunner is not None:
        app.state.suggested_questions_rerunner = rerunner
    if aq_evaluator is not None:
        app.state.suggested_questions_aq_evaluator = aq_evaluator
    if sq_evaluator is not None:
        app.state.suggested_questions_sq_evaluator = sq_evaluator
    if publisher is not None:
        app.state.suggested_questions_publisher = publisher
    registry = getattr(app.state, "admin_mutation_registry", None)
    if registry is not None:
        registry.register("POST", "/v1/admin/suggested-questions/promotions/preview")
        registry.register(
            "POST", "/v1/admin/suggested-questions/promotions/{promotion_id}/publish"
        )
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
