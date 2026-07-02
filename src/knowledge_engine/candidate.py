from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .errors import IntegrityError
from .publisher import publish_release
from .runtime import Runtime
from .source import build_source_release
from .storage import ObjectStore


@dataclass(frozen=True)
class CandidateGateResult:
    channel: str
    release_id: str
    manifest_key: str
    manifest_sha256: str
    source_repository: str
    source_sha: str
    foundation_sha: str
    source_snapshot_sha256: str
    release_tree_sha256: str
    internal_status: str
    internal_result_count: int
    internal_citation_count: int
    public_status: str
    public_result_count: int
    public_acl_filtered_count: int
    production_pointer_unchanged: bool
    reproducibility_passed: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _optional_get(store: ObjectStore, key: str) -> bytes | None:
    try:
        return store.get(key)
    except FileNotFoundError:
        return None


def _release_tree_digest(root: Path) -> str:
    records: list[dict[str, Any]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        data = path.read_bytes()
        records.append(
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    payload = (
        json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _assert_candidate_channel(channel: str) -> None:
    if channel == "production" or not channel.startswith("candidate-source-"):
        raise IntegrityError(
            "source candidate channels must start with candidate-source- and cannot be production"
        )


def _assert_internal_query(payload: dict[str, Any], release_id: str) -> tuple[int, int]:
    if payload.get("status") != "answered":
        raise IntegrityError(f"candidate internal query did not answer: {payload}")
    release = payload.get("release")
    if not isinstance(release, dict) or release.get("release_id") != release_id:
        raise IntegrityError("candidate internal query returned the wrong release")
    results = payload.get("results")
    if not isinstance(results, list) or not results:
        raise IntegrityError("candidate internal query returned no results")
    citation_count = 0
    for result in results:
        if not isinstance(result, dict):
            continue
        citations = result.get("citations")
        if isinstance(citations, list):
            citation_count += len(citations)
    if citation_count < 1:
        raise IntegrityError("candidate internal query returned no citations")
    return len(results), citation_count


def _assert_public_denial(payload: dict[str, Any], release_id: str) -> int:
    if payload.get("status") != "not_found":
        raise IntegrityError(f"candidate public query unexpectedly answered: {payload}")
    release = payload.get("release")
    if not isinstance(release, dict) or release.get("release_id") != release_id:
        raise IntegrityError("candidate public query returned the wrong release")
    results = payload.get("results")
    if results != []:
        raise IntegrityError("candidate public query exposed restricted results")
    retrieval = payload.get("retrieval")
    if not isinstance(retrieval, dict):
        raise IntegrityError("candidate public query omitted retrieval evidence")
    acl_filtered_count = int(retrieval.get("acl_filtered_count", 0))
    if acl_filtered_count < 1:
        raise IntegrityError("candidate public query did not prove ACL filtering")
    if retrieval.get("raw_fallback_used") is True:
        raise IntegrityError("candidate public query used raw fallback")
    return acl_filtered_count


def run_source_candidate_gate(
    *,
    store: ObjectStore,
    repository_url: str,
    repository: str,
    source_commit_sha: str,
    foundation_commit_sha: str,
    channel: str,
    release_time: datetime,
    query: str,
    work_root: Path,
) -> CandidateGateResult:
    _assert_candidate_channel(channel)
    normalized_time = release_time.astimezone(UTC).replace(microsecond=0)
    promoted_at = normalized_time.isoformat().replace("+00:00", "Z")
    production_before = _optional_get(store, "channels/production.json")

    first, first_snapshot = build_source_release(
        repository_url=repository_url,
        repository=repository,
        source_commit_sha=source_commit_sha,
        foundation_commit_sha=foundation_commit_sha,
        work_root=work_root / "first",
        release_time=normalized_time,
    )
    second, second_snapshot = build_source_release(
        repository_url=repository_url,
        repository=repository,
        source_commit_sha=source_commit_sha,
        foundation_commit_sha=foundation_commit_sha,
        work_root=work_root / "second",
        release_time=normalized_time,
    )

    first_tree = _release_tree_digest(first.release_root)
    second_tree = _release_tree_digest(second.release_root)
    reproducibility_passed = (
        first.release_id == second.release_id
        and first.manifest == second.manifest
        and first_snapshot == second_snapshot
        and first_tree == second_tree
    )
    if not reproducibility_passed:
        raise IntegrityError("candidate rebuild was not reproducible")

    publish_result = publish_release(
        store=store,
        compiled=first,
        channel=channel,
        promoted_at=promoted_at,
    )

    runtime = Runtime(store, work_root / "runtime-cache", channel)
    active = runtime.refresh()
    if active.release_id != first.release_id:
        raise IntegrityError("candidate runtime loaded the wrong release")

    internal = runtime.query(query, {"public", "internal"}, limit=10)
    internal_result_count, internal_citation_count = _assert_internal_query(
        internal,
        first.release_id,
    )
    public = runtime.query(query, {"public"}, limit=10)
    public_acl_filtered_count = _assert_public_denial(public, first.release_id)

    production_after = _optional_get(store, "channels/production.json")
    production_pointer_unchanged = production_after == production_before
    if not production_pointer_unchanged:
        raise IntegrityError("candidate gate changed the production channel pointer")

    return CandidateGateResult(
        channel=channel,
        release_id=publish_result.release_id,
        manifest_key=publish_result.manifest_key,
        manifest_sha256=publish_result.manifest_sha256,
        source_repository=repository,
        source_sha=source_commit_sha,
        foundation_sha=foundation_commit_sha,
        source_snapshot_sha256=first_snapshot["content_sha256"],
        release_tree_sha256=first_tree,
        internal_status=str(internal.get("status")),
        internal_result_count=internal_result_count,
        internal_citation_count=internal_citation_count,
        public_status=str(public.get("status")),
        public_result_count=len(public.get("results", [])),
        public_acl_filtered_count=public_acl_filtered_count,
        production_pointer_unchanged=production_pointer_unchanged,
        reproducibility_passed=reproducibility_passed,
    )
