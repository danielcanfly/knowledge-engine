from __future__ import annotations

from collections.abc import Mapping, MutableMapping, MutableSequence, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from fastapi import APIRouter, FastAPI, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .m26_admin_contract import AdminAPIError, redact
from .m26_admin_control_plane import (
    actor_from,
    append_audit_event,
    build_audit_event,
    request_id_from,
    require_capability,
)

ADMIN_PREFIX = "/v1/admin"
CANONICAL_OPENAPI_VERSION = "1.1.1-gb05-repair"
GOLDEN_READ_CAPABILITY = "evaluation.golden.read"
RUNS_READ_CAPABILITY = "evaluation.runs.read"
RUN_START_CAPABILITY = "evaluation.run.start"
RUN_REQUEST_SCHEMA_REASON = "GOLDEN_RUN_REQUEST_SCHEMA_REQUIRED"
RUN_REQUEST_CONTRACT_UNAVAILABLE = "GOLDEN_RUN_REQUEST_CONTRACT_UNAVAILABLE"
RUNNER_UNAVAILABLE_REASON = "GOLDEN_EVALUATION_RUNNER_UNAVAILABLE"
_ALLOWED_FRESHNESS = frozenset({"live", "near_live", "delayed", "snapshot", "stale", "unknown"})
_ALLOWED_DATASET_STATES = frozenset({"draft", "active", "superseded"})
_ALLOWED_RUN_STATES = frozenset({"queued", "running", "pass", "warn", "fail", "cancelled"})
_ALLOWED_CASE_STATES = frozenset({"pass", "warn", "fail", "error", "not_run"})


class DatasetIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str = Field(min_length=1, max_length=256)
    version: str = Field(min_length=1, max_length=256)
    dataset_hash: str = Field(min_length=1, max_length=512)


class ScoringContractIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = Field(min_length=1, max_length=256)
    hash: str = Field(min_length=1, max_length=512)


class EvaluationReleaseIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    release_id: str = Field(min_length=1, max_length=256)
    index_identity: str = Field(min_length=1, max_length=1024)
    config_identity: str = Field(min_length=1, max_length=512)
    runtime_sha256: str = Field(min_length=1, max_length=512)
    collection: str = Field(min_length=1, max_length=512)
    manifest_sha256: str = Field(min_length=1, max_length=512)
    provider_id: str | None = Field(default=None, min_length=1, max_length=256)
    model_id: str | None = Field(default=None, min_length=1, max_length=512)
    provider_config_hash: str | None = Field(default=None, min_length=1, max_length=512)


class StartEvaluationRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["selected", "all", "retrieval_only"]
    dataset: DatasetIdentity
    case_ids: list[str] = Field(max_length=1000)
    release: EvaluationReleaseIdentity
    scoring_contract: ScoringContractIdentity

    @model_validator(mode="after")
    def validate_scope_and_provider_identity(self) -> StartEvaluationRunRequest:
        normalized = [case_id.strip() for case_id in self.case_ids if case_id.strip()]
        if len(normalized) != len(self.case_ids) or len(set(normalized)) != len(normalized):
            raise ValueError("case_ids must contain unique non-empty identifiers")
        if self.mode == "selected" and not normalized:
            raise ValueError("selected mode requires at least one explicit case_id")
        if self.mode == "all" and normalized:
            raise ValueError("all mode must not carry case_ids")
        if self.mode == "retrieval_only" and not normalized:
            raise ValueError("retrieval_only mode requires explicit case_ids")
        if self.mode != "retrieval_only" and not (
            self.release.provider_id and self.release.model_id and self.release.provider_config_hash
        ):
            raise ValueError(
                "provider_id, model_id, and provider_config_hash are required "
                "for model-bearing runs"
            )
        return self


class GoldenEvaluationProvider(Protocol):
    def list_golden_sets(self, request: Request) -> Mapping[str, Any]: ...

    def list_evaluation_runs(self, request: Request) -> Mapping[str, Any]: ...

    def record_evaluation_run(self, request: Request, run: Mapping[str, Any]) -> None: ...


class GoldenEvaluationRunner(Protocol):
    def start_run(
        self,
        request: Request,
        *,
        operation_id: str,
        run_request: Mapping[str, Any],
    ) -> Mapping[str, Any]: ...


class UnavailableGoldenEvaluationProvider:
    def list_golden_sets(self, request: Request) -> Mapping[str, Any]:
        del request
        return {}

    def list_evaluation_runs(self, request: Request) -> Mapping[str, Any]:
        del request
        return {}

    def record_evaluation_run(self, request: Request, run: Mapping[str, Any]) -> None:
        del request, run
        raise AdminAPIError(
            status_code=503,
            code="GOLDEN_RUN_PERSISTENCE_UNAVAILABLE",
            message="No qualified immutable evaluation-run persistence target is wired.",
        )


class UnavailableGoldenEvaluationRunner:
    def start_run(
        self,
        request: Request,
        *,
        operation_id: str,
        run_request: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        del request, operation_id, run_request
        raise AdminAPIError(
            status_code=503,
            code=RUNNER_UNAVAILABLE_REASON,
            message="No qualified Golden evaluation execution adapter is wired.",
        )


@dataclass
class StaticGoldenEvaluationProvider:
    golden: Mapping[str, Any]
    runs: Mapping[str, Any]

    def list_golden_sets(self, request: Request) -> Mapping[str, Any]:
        del request
        return self.golden

    def list_evaluation_runs(self, request: Request) -> Mapping[str, Any]:
        del request
        return self.runs

    def record_evaluation_run(self, request: Request, run: Mapping[str, Any]) -> None:
        del request
        if not isinstance(self.runs, MutableMapping):
            raise AdminAPIError(
                status_code=503,
                code="GOLDEN_RUN_PERSISTENCE_UNAVAILABLE",
                message="The configured evaluation-run ledger is immutable.",
            )
        raw_runs = self.runs.get("runs")
        if not isinstance(raw_runs, MutableSequence):
            raise AdminAPIError(
                status_code=503,
                code="GOLDEN_RUN_PERSISTENCE_UNAVAILABLE",
                message="The configured evaluation-run ledger cannot accept records.",
            )
        raw_runs.append(dict(run))


def _availability(status: str, reason_code: str | None, detail: str) -> dict[str, Any]:
    return {"status": status, "reason_code": reason_code, "detail": detail}


def _provenance(
    source: str,
    *,
    observed_at: str | None,
    resource_identity: Mapping[str, Any] | None = None,
    evidence_digest: str | None = None,
) -> dict[str, Any]:
    return {
        "source": source,
        "resource_identity": redact(resource_identity),
        "evidence_digest": evidence_digest,
        "source_observed_at": observed_at,
    }


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _freshness(value: Any) -> str:
    return value if isinstance(value, str) and value in _ALLOWED_FRESHNESS else "unknown"


def _scoring_contract(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    version = _text(raw.get("version"))
    contract_hash = _text(raw.get("hash"))
    if version is None or contract_hash is None:
        return None
    metrics = _string_list(raw.get("metrics"))
    return {"version": version, "hash": contract_hash, "metrics": metrics}


def _normalize_case(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    case_id = _text(raw.get("case_id"))
    question = _text(raw.get("question"))
    expectation_hash = _text(raw.get("expectation_hash"))
    if case_id is None or question is None or expectation_hash is None:
        return None
    return {
        "case_id": case_id,
        "question": question,
        "expectation_hash": expectation_hash,
        "expected_source_ids": _string_list(raw.get("expected_source_ids")),
        "expected_traits": _string_list(raw.get("expected_traits")),
        "tags": _string_list(raw.get("tags")),
    }


def _normalize_set(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    dataset_id = _text(raw.get("dataset_id"))
    version = _text(raw.get("version"))
    dataset_hash = _text(raw.get("dataset_hash"))
    state = raw.get("state")
    scoring = _scoring_contract(raw.get("scoring_contract"))
    if (
        dataset_id is None
        or version is None
        or dataset_hash is None
        or state not in _ALLOWED_DATASET_STATES
        or scoring is None
    ):
        return None
    raw_cases = raw.get("cases")
    cases = []
    if isinstance(raw_cases, Sequence) and not isinstance(raw_cases, (str, bytes)):
        for item in raw_cases:
            normalized = _normalize_case(item)
            if normalized is not None:
                cases.append(normalized)
    return {
        "dataset_id": dataset_id,
        "version": version,
        "dataset_hash": dataset_hash,
        "state": state,
        "scoring_contract": scoring,
        "cases": cases,
    }


def _identity(raw: Any, required: Sequence[str]) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    value: dict[str, Any] = {}
    for key in required:
        item = _text(raw.get(key))
        if item is None:
            return None
        value[key] = item
    for key in (
        "provider_id",
        "model_id",
        "provider_config_hash",
        "runtime_sha256",
        "collection",
        "manifest_sha256",
    ):
        item = _text(raw.get(key))
        if item is not None:
            value[key] = item
    return value


def _normalize_run_request_contract(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping) or raw.get("status") != "available":
        return {
            "status": "blocked",
            "reason_code": (_text(raw.get("reason_code")) if isinstance(raw, Mapping) else None)
            or RUN_REQUEST_SCHEMA_REASON,
            "canonical_openapi_version": CANONICAL_OPENAPI_VERSION,
        }
    release = _identity(
        raw.get("release"),
        (
            "release_id",
            "index_identity",
            "config_identity",
            "runtime_sha256",
            "collection",
            "manifest_sha256",
        ),
    )
    if release is None:
        return {
            "status": "blocked",
            "reason_code": RUN_REQUEST_CONTRACT_UNAVAILABLE,
            "canonical_openapi_version": CANONICAL_OPENAPI_VERSION,
        }
    return {
        "status": "available",
        "reason_code": None,
        "canonical_openapi_version": CANONICAL_OPENAPI_VERSION,
        "release": release,
    }


def _normalize_case_result(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    case_id = _text(raw.get("case_id"))
    state = raw.get("state")
    if case_id is None or state not in _ALLOWED_CASE_STATES:
        return None
    metrics = raw.get("metrics") if isinstance(raw.get("metrics"), Mapping) else {}
    safe_metrics: dict[str, Any] = {}
    for key in (
        "faithfulness",
        "completeness",
        "unsupported",
        "contradiction",
        "unknown",
        "stability",
        "latency_ms",
    ):
        value = metrics.get(key)
        if isinstance(value, (int, float, bool, str)) or value is None:
            safe_metrics[key] = value
    error = raw.get("error") if isinstance(raw.get("error"), Mapping) else None
    return {
        "case_id": case_id,
        "state": state,
        "answer": _text(raw.get("answer")),
        "retrieval": redact(raw.get("retrieval")),
        "evidence": redact(raw.get("evidence")),
        "metrics": safe_metrics,
        "trace_id": _text(raw.get("trace_id")),
        "error": redact(error),
    }


def _normalize_run(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    run_id = _text(raw.get("run_id"))
    state = raw.get("state")
    mode = raw.get("mode")
    dataset = _identity(raw.get("dataset"), ("dataset_id", "version", "dataset_hash"))
    release = _identity(raw.get("release"), ("release_id", "index_identity", "config_identity"))
    scoring = _scoring_contract(raw.get("scoring_contract"))
    created_at = _text(raw.get("created_at"))
    if (
        run_id is None
        or state not in _ALLOWED_RUN_STATES
        or mode not in {"selected", "all", "retrieval_only"}
        or dataset is None
        or release is None
        or scoring is None
        or created_at is None
    ):
        return None
    raw_results = raw.get("case_results")
    results = []
    if isinstance(raw_results, Sequence) and not isinstance(raw_results, (str, bytes)):
        for item in raw_results:
            normalized = _normalize_case_result(item)
            if normalized is not None:
                results.append(normalized)
    progress = raw.get("progress") if isinstance(raw.get("progress"), Mapping) else {}
    summary = raw.get("summary") if isinstance(raw.get("summary"), Mapping) else {}
    return {
        "run_id": run_id,
        "state": state,
        "mode": mode,
        "dataset": dataset,
        "release": release,
        "scoring_contract": scoring,
        "created_at": created_at,
        "completed_at": _text(raw.get("completed_at")),
        "progress": redact(progress),
        "summary": redact(summary),
        "case_results": results,
    }


def _read_payload(
    request: Request,
    *,
    raw: Mapping[str, Any],
    collection_key: str,
    normalizer: Any,
    unavailable_reason: str,
    unavailable_detail: str,
) -> dict[str, Any]:
    observed_at = _text(raw.get("observed_at"))
    source = _text(raw.get("source"))
    freshness = _freshness(raw.get("freshness"))
    evidence_digest = _text(raw.get("evidence_digest"))
    resource_identity = raw.get("resource_identity")
    raw_items = raw.get(collection_key)
    contract = _normalize_run_request_contract(raw.get("run_request_contract"))
    if source is None or not isinstance(raw_items, Sequence) or isinstance(raw_items, (str, bytes)):
        return {
            "request_id": request_id_from(request),
            "availability": _availability("unavailable", unavailable_reason, unavailable_detail),
            "provenance": _provenance("golden_evaluation_source_unavailable", observed_at=None),
            "observed_at": None,
            "freshness": "unknown",
            "data": {collection_key: [], "run_request_contract": contract},
        }
    normalized = [item for item in (normalizer(value) for value in raw_items) if item is not None]
    status = "available"
    reason_code = None
    detail = "Qualified immutable evaluation metadata."
    if len(normalized) != len(raw_items) or observed_at is None or freshness == "unknown":
        status = "partial"
        reason_code = "GOLDEN_EVALUATION_PARTIAL_EVIDENCE"
        detail = "Some evaluation records or observation metadata were rejected as incomplete."
    return {
        "request_id": request_id_from(request),
        "availability": _availability(status, reason_code, detail),
        "provenance": _provenance(
            source,
            observed_at=observed_at,
            resource_identity=resource_identity if isinstance(resource_identity, Mapping) else None,
            evidence_digest=evidence_digest,
        ),
        "observed_at": observed_at,
        "freshness": freshness,
        "data": {collection_key: normalized, "run_request_contract": contract},
    }


def _canonical_request(run_request: StartEvaluationRunRequest) -> dict[str, Any]:
    payload = run_request.model_dump(mode="json", exclude_none=True)
    if payload["mode"] != "all":
        payload["case_ids"] = sorted(payload.get("case_ids", []))
    return payload


def _audit_start(
    request: Request,
    *,
    action: str,
    outcome: str,
    reason_code: str,
    operation_id: str | None,
    object_id: str | None,
    metadata: Mapping[str, Any],
) -> None:
    append_audit_event(
        request,
        build_audit_event(
            actor=actor_from(request),
            action=action,
            object_type="evaluation_run",
            object_id=object_id,
            request_id=request_id_from(request),
            operation_id=operation_id,
            outcome=outcome,
            reason_code=reason_code,
            metadata=redact(metadata),
        ),
    )


def _request_contract_and_dataset(
    request: Request,
    provider: GoldenEvaluationProvider,
    payload: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        raw = provider.list_golden_sets(request)
    except Exception as exc:
        raise AdminAPIError(
            status_code=503,
            code="GOLDEN_DATASET_SOURCE_UNAVAILABLE",
            message="The Golden dataset registry could not be read.",
        ) from exc
    if not isinstance(raw, Mapping):
        raise AdminAPIError(
            status_code=503,
            code="GOLDEN_DATASET_SOURCE_UNAVAILABLE",
            message="The Golden dataset registry is unavailable.",
        )
    contract = _normalize_run_request_contract(raw.get("run_request_contract"))
    if contract.get("status") != "available":
        raise AdminAPIError(
            status_code=409,
            code=str(contract.get("reason_code") or RUN_REQUEST_CONTRACT_UNAVAILABLE),
            message="No qualified immutable Golden run request target is available.",
        )
    requested_dataset = payload["dataset"]
    requested_scoring = payload["scoring_contract"]
    candidate: dict[str, Any] | None = None
    raw_sets = raw.get("sets")
    if isinstance(raw_sets, Sequence) and not isinstance(raw_sets, (str, bytes)):
        for item in raw_sets:
            normalized = _normalize_set(item)
            if normalized is None:
                continue
            if (
                normalized["dataset_id"] == requested_dataset["dataset_id"]
                and normalized["version"] == requested_dataset["version"]
                and normalized["dataset_hash"] == requested_dataset["dataset_hash"]
            ):
                candidate = normalized
                break
    if candidate is None:
        raise AdminAPIError(
            status_code=409,
            code="GOLDEN_DATASET_IDENTITY_MISMATCH",
            message="Requested Golden dataset identity is not the qualified immutable dataset.",
        )
    scoring = candidate["scoring_contract"]
    if (
        scoring["version"] != requested_scoring["version"]
        or scoring["hash"] != requested_scoring["hash"]
    ):
        raise AdminAPIError(
            status_code=409,
            code="GOLDEN_SCORING_CONTRACT_MISMATCH",
            message="Requested scoring contract does not match the immutable Golden dataset.",
        )
    if payload["release"] != contract["release"]:
        raise AdminAPIError(
            status_code=409,
            code="GOLDEN_RELEASE_IDENTITY_MISMATCH",
            message=(
                "Requested release/index/config identity is not the qualified execution target."
            ),
        )
    known_case_ids = {item["case_id"] for item in candidate["cases"]}
    requested_case_ids = set(payload.get("case_ids", []))
    if not requested_case_ids.issubset(known_case_ids):
        raise AdminAPIError(
            status_code=409,
            code="GOLDEN_CASE_SELECTION_MISMATCH",
            message="Requested case selection contains case IDs outside the immutable dataset.",
        )
    return contract, candidate


def _find_existing_run(
    request: Request, provider: GoldenEvaluationProvider, operation_id: str
) -> dict[str, Any] | None:
    try:
        raw = provider.list_evaluation_runs(request)
    except Exception:
        return None
    raw_runs = raw.get("runs") if isinstance(raw, Mapping) else None
    if not isinstance(raw_runs, Sequence) or isinstance(raw_runs, (str, bytes)):
        return None
    for item in raw_runs:
        normalized = _normalize_run(item)
        if normalized is not None and normalized["run_id"] == operation_id:
            return normalized
    return None


def _validate_runner_result(
    operation_id: str, payload: Mapping[str, Any], raw_run: Mapping[str, Any]
) -> dict[str, Any]:
    run = _normalize_run(raw_run)
    if run is None:
        raise AdminAPIError(
            status_code=503,
            code="GOLDEN_RUNNER_RESULT_INVALID",
            message="The Golden evaluation runner returned an invalid immutable run record.",
        )
    if run["run_id"] != operation_id:
        raise AdminAPIError(
            status_code=503,
            code="GOLDEN_RUNNER_OPERATION_ID_MISMATCH",
            message="The runner did not bind run_id to the accepted operation identity.",
        )
    if (
        run["mode"] != payload["mode"]
        or run["dataset"] != payload["dataset"]
        or run["release"] != payload["release"]
        or run["scoring_contract"]["version"] != payload["scoring_contract"]["version"]
        or run["scoring_contract"]["hash"] != payload["scoring_contract"]["hash"]
    ):
        raise AdminAPIError(
            status_code=503,
            code="GOLDEN_RUNNER_IDENTITY_MISMATCH",
            message="The runner result does not preserve the exact immutable run request identity.",
        )
    return run


def golden_router() -> APIRouter:
    router = APIRouter(prefix=ADMIN_PREFIX, tags=["Evaluation"])

    @router.get("/evaluations/golden", operation_id="listGoldenSets")
    async def list_golden_sets(request: Request) -> dict[str, Any]:
        require_capability(request, GOLDEN_READ_CAPABILITY)
        provider = getattr(
            request.app.state,
            "admin_golden_evaluation_provider",
            UnavailableGoldenEvaluationProvider(),
        )
        try:
            raw = provider.list_golden_sets(request)
        except Exception:
            raw = {}
        return _read_payload(
            request,
            raw=raw if isinstance(raw, Mapping) else {},
            collection_key="sets",
            normalizer=_normalize_set,
            unavailable_reason="GOLDEN_DATASET_SOURCE_UNAVAILABLE",
            unavailable_detail="No qualified Golden dataset registry is wired.",
        )

    @router.get("/evaluations/runs", operation_id="listEvaluationRuns")
    async def list_evaluation_runs(request: Request) -> dict[str, Any]:
        require_capability(request, RUNS_READ_CAPABILITY)
        provider = getattr(
            request.app.state,
            "admin_golden_evaluation_provider",
            UnavailableGoldenEvaluationProvider(),
        )
        try:
            raw = provider.list_evaluation_runs(request)
        except Exception:
            raw = {}
        return _read_payload(
            request,
            raw=raw if isinstance(raw, Mapping) else {},
            collection_key="runs",
            normalizer=_normalize_run,
            unavailable_reason="GOLDEN_RUN_HISTORY_SOURCE_UNAVAILABLE",
            unavailable_detail="No qualified immutable evaluation-run history source is wired.",
        )

    @router.post("/evaluations/runs", operation_id="startEvaluationRun", status_code=202)
    async def start_evaluation_run(
        request: Request, body: StartEvaluationRunRequest
    ) -> dict[str, Any]:
        require_capability(request, RUN_START_CAPABILITY, mutation=True)
        actor = actor_from(request)
        provider = getattr(
            request.app.state,
            "admin_golden_evaluation_provider",
            UnavailableGoldenEvaluationProvider(),
        )
        runner = getattr(
            request.app.state, "admin_golden_evaluation_runner", UnavailableGoldenEvaluationRunner()
        )
        payload = _canonical_request(body)
        try:
            _request_contract_and_dataset(request, provider, payload)
        except AdminAPIError as exc:
            _audit_start(
                request,
                action="evaluation.run.start.rejected",
                outcome="rejected",
                reason_code=exc.code,
                operation_id=None,
                object_id=None,
                metadata={"request": payload},
            )
            raise
        try:
            operation_id, replayed = request.app.state.admin_idempotency.begin(
                actor_id=actor.actor_id,
                method=request.method,
                path=request.url.path,
                idempotency_key=request.headers.get("idempotency-key", ""),
                request_payload=payload,
            )
        except AdminAPIError as exc:
            _audit_start(
                request,
                action="evaluation.run.start.rejected",
                outcome="rejected",
                reason_code=exc.code,
                operation_id=None,
                object_id=None,
                metadata={"request": payload},
            )
            raise
        if replayed:
            existing = _find_existing_run(request, provider, operation_id)
            if existing is None:
                _audit_start(
                    request,
                    action="evaluation.run.start.blocked",
                    outcome="blocked",
                    reason_code="GOLDEN_RUN_REPLAY_RESULT_UNAVAILABLE",
                    operation_id=operation_id,
                    object_id=None,
                    metadata={"request": payload, "replayed": True},
                )
                raise AdminAPIError(
                    status_code=409,
                    code="GOLDEN_RUN_REPLAY_RESULT_UNAVAILABLE",
                    message=(
                        "The idempotent operation exists but no accepted immutable "
                        "run can be read back."
                    ),
                )
            _audit_start(
                request,
                action="evaluation.run.start.replayed",
                outcome="accepted",
                reason_code="GOLDEN_RUN_REPLAYED",
                operation_id=operation_id,
                object_id=operation_id,
                metadata={"request": payload, "replayed": True},
            )
            return {
                "request_id": request_id_from(request),
                "operation_id": operation_id,
                "status": "accepted",
                "replayed": True,
            }
        try:
            raw_run = runner.start_run(request, operation_id=operation_id, run_request=payload)
            run = _validate_runner_result(operation_id, payload, raw_run)
            provider.record_evaluation_run(request, run)
        except AdminAPIError as exc:
            _audit_start(
                request,
                action="evaluation.run.start.blocked",
                outcome="blocked",
                reason_code=exc.code,
                operation_id=operation_id,
                object_id=None,
                metadata={"request": payload, "replayed": False},
            )
            raise
        except Exception as exc:
            _audit_start(
                request,
                action="evaluation.run.start.failed",
                outcome="failed",
                reason_code="GOLDEN_RUN_EXECUTION_FAILED",
                operation_id=operation_id,
                object_id=None,
                metadata={"request": payload, "replayed": False},
            )
            raise AdminAPIError(
                status_code=503,
                code="GOLDEN_RUN_EXECUTION_FAILED",
                message="Golden evaluation execution failed before a durable run was accepted.",
                retryable=False,
            ) from exc
        _audit_start(
            request,
            action="evaluation.run.start.accepted",
            outcome="accepted",
            reason_code="GOLDEN_RUN_ACCEPTED",
            operation_id=operation_id,
            object_id=operation_id,
            metadata={"request": payload, "replayed": False},
        )
        return {
            "request_id": request_id_from(request),
            "operation_id": operation_id,
            "status": "accepted",
            "replayed": False,
        }

    return router


def install_golden_questions_admin(
    app: FastAPI,
    *,
    provider: GoldenEvaluationProvider | None = None,
    runner: GoldenEvaluationRunner | None = None,
) -> FastAPI:
    if getattr(app.state, "admin_golden_questions_installed", False):
        return app
    app.state.admin_golden_evaluation_provider = provider or UnavailableGoldenEvaluationProvider()
    app.state.admin_golden_evaluation_runner = runner or UnavailableGoldenEvaluationRunner()
    app.include_router(golden_router())
    app.state.admin_golden_questions_installed = True
    return app


__all__ = [
    "CANONICAL_OPENAPI_VERSION",
    "GOLDEN_READ_CAPABILITY",
    "RUNS_READ_CAPABILITY",
    "RUN_START_CAPABILITY",
    "RUN_REQUEST_SCHEMA_REASON",
    "RUN_REQUEST_CONTRACT_UNAVAILABLE",
    "RUNNER_UNAVAILABLE_REASON",
    "DatasetIdentity",
    "EvaluationReleaseIdentity",
    "GoldenEvaluationRunner",
    "ScoringContractIdentity",
    "StartEvaluationRunRequest",
    "StaticGoldenEvaluationProvider",
    "UnavailableGoldenEvaluationProvider",
    "UnavailableGoldenEvaluationRunner",
    "golden_router",
    "install_golden_questions_admin",
]
