from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .m26_admin_contract import AdminAPIError, canonical_json_bytes

_GOLDEN_RELATIVE_PATH = Path("pilot/m23/m23-1-golden-queries.json")
_SCORING_CONTRACT = {
    "version": "m23-retrieval-expectation/v1",
    "metrics": ["retrieval_match", "policy_expectation"],
}
_SCORING_HASH = hashlib.sha256(
    canonical_json_bytes(
        {
            "version": _SCORING_CONTRACT["version"],
            "metrics": _SCORING_CONTRACT["metrics"],
            "expectation_fields": [
                "expected_logical_articles",
                "expected_policy",
                "should_match",
                "class",
            ],
        }
    )
).hexdigest()


def _candidate_paths() -> tuple[Path, ...]:
    return (
        Path.cwd() / _GOLDEN_RELATIVE_PATH,
        Path(__file__).resolve().parents[2] / _GOLDEN_RELATIVE_PATH,
        Path("/app") / _GOLDEN_RELATIVE_PATH,
    )


def _asset_path() -> Path | None:
    for candidate in _candidate_paths():
        if candidate.is_file():
            return candidate
    return None


def _observed_at(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat().replace("+00:00", "Z")
    except OSError:
        return None


def _expectation_hash(query: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        canonical_json_bytes(
            {
                "expected_logical_articles": query.get("expected_logical_articles", []),
                "expected_policy": query.get("expected_policy"),
                "should_match": query.get("should_match"),
                "class": query.get("class"),
            }
        )
    ).hexdigest()


class PackagedGoldenEvaluationProvider:
    """Read-only adapter over the immutable Golden query asset shipped with the runtime."""

    def __init__(self, path: Path, raw: Mapping[str, Any]) -> None:
        self.path = path
        self.raw = dict(raw)

    def list_golden_sets(self, request: Any) -> Mapping[str, Any]:
        del request
        queries = self.raw.get("queries")
        if not isinstance(queries, list):
            return {}
        cases: list[dict[str, Any]] = []
        for item in queries:
            if not isinstance(item, Mapping):
                continue
            case_id = str(item.get("query_id") or "").strip()
            question = str(item.get("text") or "").strip()
            if not case_id or not question:
                continue
            expected_sources = [
                str(value)
                for value in item.get("expected_logical_articles", [])
                if isinstance(value, str) and value.strip()
            ]
            traits = [
                f"class:{str(item.get('class') or 'unknown')}",
                f"policy:{str(item.get('expected_policy') or 'unknown')}",
                f"should_match:{str(bool(item.get('should_match'))).lower()}",
            ]
            tags = [
                value
                for value in (
                    str(item.get("language") or "").strip(),
                    str(item.get("class") or "").strip(),
                )
                if value
            ]
            cases.append(
                {
                    "case_id": case_id,
                    "question": question,
                    "expectation_hash": _expectation_hash(item),
                    "expected_source_ids": expected_sources,
                    "expected_traits": traits,
                    "tags": tags,
                }
            )

        dataset_hash = str(self.raw.get("golden_query_digest") or "").strip()
        if not dataset_hash:
            dataset_hash = hashlib.sha256(self.path.read_bytes()).hexdigest()
        observed_at = _observed_at(self.path)
        schema_version = str(self.raw.get("schema_version") or "unknown")
        return {
            "source": "packaged_m23_golden_query_registry",
            "observed_at": observed_at,
            "freshness": "snapshot",
            "evidence_digest": dataset_hash,
            "resource_identity": {
                "artifact": _GOLDEN_RELATIVE_PATH.as_posix(),
                "schema_version": schema_version,
            },
            "run_request_contract": {
                "status": "blocked",
                "reason_code": "GOLDEN_RUN_START_NOT_AUTHORIZED",
            },
            "sets": [
                {
                    "dataset_id": "m23-golden-queries",
                    "version": schema_version,
                    "dataset_hash": dataset_hash,
                    "state": "active",
                    "scoring_contract": {
                        **_SCORING_CONTRACT,
                        "hash": _SCORING_HASH,
                    },
                    "cases": cases,
                }
            ],
        }

    def list_evaluation_runs(self, request: Any) -> Mapping[str, Any]:
        del request
        # There is no qualified durable evaluation-run ledger in production.
        # Returning an empty authoritative list would fabricate evidence.
        return {}

    def record_evaluation_run(self, request: Any, run: Mapping[str, Any]) -> None:
        del request, run
        raise AdminAPIError(
            status_code=503,
            code="GOLDEN_RUN_PERSISTENCE_UNAVAILABLE",
            message="The packaged Golden registry is immutable and has no run ledger.",
        )


def packaged_golden_evaluation_provider() -> PackagedGoldenEvaluationProvider | None:
    path = _asset_path()
    if path is None:
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(raw, Mapping):
        return None
    return PackagedGoldenEvaluationProvider(path, raw)


__all__ = ["PackagedGoldenEvaluationProvider", "packaged_golden_evaluation_provider"]
