from __future__ import annotations

import json
import re
import shutil
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .errors import IntegrityError
from .query_evaluation import evaluate_runtime_query
from .storage import ObjectStore, sha256_bytes

AUDIENCE_RANK = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}
TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u3400-\u9fff]+")


@dataclass(frozen=True)
class ActiveRelease:
    release_id: str
    manifest_sha256: str
    loaded_at: str
    manifest: dict[str, Any]
    lexical_index: dict[str, Any]
    provenance: dict[str, Any]


def _citation_uri(source: dict[str, Any]) -> str:
    uri = source.get("uri") or source.get("locator")
    if not uri:
        raise IntegrityError(
            f"provenance source is missing uri: {source.get('source_id', 'unknown')}"
        )
    return str(uri)


class Runtime:
    def __init__(self, store: ObjectStore, cache_dir: Path, channel: str) -> None:
        self.store = store
        self.cache_dir = cache_dir.resolve()
        self.channel = channel
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._active: ActiveRelease | None = None
        self._lock = threading.RLock()

    @property
    def active(self) -> ActiveRelease | None:
        with self._lock:
            return self._active

    def refresh(
        self,
        *,
        expected_release_id: str | None = None,
        expected_manifest_sha256: str | None = None,
    ) -> ActiveRelease:
        pointer_key = f"channels/{self.channel}.json"
        pointer_data = self.store.get(pointer_key)
        try:
            pointer = json.loads(pointer_data)
        except json.JSONDecodeError as exc:
            raise IntegrityError("channel pointer is invalid JSON") from exc
        if not isinstance(pointer, dict):
            raise IntegrityError("channel pointer must be a JSON object")

        release_id = pointer.get("release_id")
        manifest_key = pointer.get("manifest_key")
        manifest_sha256 = pointer.get("manifest_sha256")
        identity = (release_id, manifest_key, manifest_sha256)
        if not all(isinstance(item, str) and item for item in identity):
            raise IntegrityError("channel pointer is missing release identity")
        if expected_release_id is not None and release_id != expected_release_id:
            raise IntegrityError(
                f"expected release {expected_release_id}, channel points to {release_id}"
            )
        if (
            expected_manifest_sha256 is not None
            and manifest_sha256 != expected_manifest_sha256
        ):
            raise IntegrityError("channel manifest hash does not match expected identity")

        manifest_data = self.store.get(manifest_key)
        actual_manifest_sha = sha256_bytes(manifest_data)
        if actual_manifest_sha != manifest_sha256:
            raise IntegrityError("channel manifest hash mismatch")
        try:
            manifest = json.loads(manifest_data)
        except json.JSONDecodeError as exc:
            raise IntegrityError("release manifest is invalid JSON") from exc
        if manifest.get("release_id") != release_id:
            raise IntegrityError("channel and manifest release IDs differ")

        release_cache = self.cache_dir / release_id
        staging_cache = self.cache_dir / f".{release_id}.staging"
        if staging_cache.exists():
            shutil.rmtree(staging_cache)
        staging_cache.mkdir(parents=True)
        try:
            artifacts = manifest.get("artifacts")
            if not isinstance(artifacts, list):
                raise IntegrityError("release manifest artifacts must be a list")
            for artifact in artifacts:
                if not isinstance(artifact, dict):
                    raise IntegrityError("release artifact entry must be an object")
                key = artifact.get("key")
                if not isinstance(key, str) or not key:
                    raise IntegrityError("release artifact key is missing")
                data = self.store.get(key)
                if len(data) != artifact.get("bytes") or sha256_bytes(data) != artifact.get(
                    "sha256"
                ):
                    raise IntegrityError(f"artifact integrity failure: {key}")
                prefix = f"releases/{release_id}/"
                if not key.startswith(prefix):
                    raise IntegrityError(f"artifact key escapes release prefix: {key}")
                relative = key[len(prefix) :]
                destination = (staging_cache / relative).resolve()
                try:
                    destination.relative_to(staging_cache.resolve())
                except ValueError as exc:
                    raise IntegrityError(f"unsafe artifact path: {key}") from exc
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)

            pointer_after = self.store.get(pointer_key)
            if pointer_after != pointer_data:
                raise IntegrityError("channel pointer changed during refresh")

            lexical_path = staging_cache / "artifacts/lexical-index.json"
            provenance_path = staging_cache / "artifacts/provenance.json"
            lexical_index = json.loads(lexical_path.read_text(encoding="utf-8"))
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))

            if release_cache.exists():
                shutil.rmtree(release_cache)
            staging_cache.replace(release_cache)
            active = ActiveRelease(
                release_id=release_id,
                manifest_sha256=actual_manifest_sha,
                loaded_at=datetime.now(UTC)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z"),
                manifest=manifest,
                lexical_index=lexical_index,
                provenance=provenance,
            )
            with self._lock:
                self._active = active
            return active
        except Exception:
            if staging_cache.exists():
                shutil.rmtree(staging_cache)
            raise

    def ensure_loaded(self) -> ActiveRelease:
        active = self.active
        if active is not None:
            return active
        return self.refresh()

    def query(
        self,
        query: str,
        allowed_audiences: set[str],
        *,
        limit: int = 10,
    ) -> dict[str, Any]:
        active = self.ensure_loaded()
        allowed = {item for item in allowed_audiences if item in AUDIENCE_RANK}
        if not allowed:
            allowed = {"public"}
        maximum_rank = max(AUDIENCE_RANK[item] for item in allowed)
        query_terms = [part.lower() for part in TOKEN_RE.findall(query)]
        records = {
            record["subject"]["concept_id"]: record
            for record in active.provenance.get("records", [])
        }
        scored: list[tuple[int, dict[str, Any]]] = []
        filtered = 0
        for document in active.lexical_index.get("documents", []):
            if AUDIENCE_RANK[document["audience"]] > maximum_rank:
                filtered += 1
                continue
            terms = document.get("terms", [])
            score = sum(terms.count(term) for term in query_terms)
            title_terms = [
                part.lower() for part in TOKEN_RE.findall(document.get("title", ""))
            ]
            score += 4 * sum(title_terms.count(term) for term in query_terms)
            if score > 0:
                scored.append((score, document))
        scored.sort(key=lambda item: (-item[0], item[1]["concept_id"]))
        results = []
        for score, document in scored[:limit]:
            record = records.get(document["concept_id"], {})
            results.append(
                {
                    "concept_id": document["concept_id"],
                    "x_kos_id": document["x_kos_id"],
                    "title": document["title"],
                    "description": document["description"],
                    "score": score,
                    "citations": [
                        {
                            "source_id": source["source_id"],
                            "uri": _citation_uri(source),
                            "retrieved_at": source["retrieved_at"],
                        }
                        for source in record.get("sources", [])
                    ],
                }
            )
        status = "answered" if results else "not_found"
        release = {
            "release_id": active.release_id,
            "manifest_sha256": active.manifest_sha256,
            "loaded_at": active.loaded_at,
        }
        retrieval = {
            "strategy": "wiki_first_lexical",
            "candidate_count": len(scored),
            "selected_count": len(results),
            "acl_filtered_count": filtered,
            "raw_fallback_used": False,
        }
        non_answer_reason = None if results else "no_authorized_match"
        evaluation = evaluate_runtime_query(
            release=release,
            query=query,
            audiences=allowed,
            status=status,
            results=results,
            retrieval=retrieval,
            non_answer_reason=non_answer_reason,
        )
        return {
            "status": status,
            "release": release,
            "query": query,
            "results": results,
            "retrieval": retrieval,
            "evaluation": evaluation,
            "non_answer_reason": non_answer_reason,
        }
