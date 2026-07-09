from __future__ import annotations

import json
import shutil
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .errors import IntegrityError
from .m14_citation_runtime import enrich_runtime_citations
from .m14_retrieval import retrieve_wiki_first
from .query_evaluation import evaluate_runtime_query
from .storage import ObjectStore, sha256_bytes


@dataclass(frozen=True)
class ActiveRelease:
    release_id: str
    manifest_sha256: str
    loaded_at: str
    manifest: dict[str, Any]
    lexical_index: dict[str, Any]
    graph: dict[str, Any]
    provenance: dict[str, Any]
    semantic_index: dict[str, Any] | None


def _load_json_file(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IntegrityError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise IntegrityError(f"{label} must be a JSON object")
    return value


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
        if not isinstance(manifest, dict):
            raise IntegrityError("release manifest must be a JSON object")
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
            artifact_paths: dict[str, Path] = {}
            for artifact in artifacts:
                if not isinstance(artifact, dict):
                    raise IntegrityError("release artifact entry must be an object")
                key = artifact.get("key")
                kind = artifact.get("kind")
                if not isinstance(key, str) or not key:
                    raise IntegrityError("release artifact key is missing")
                if not isinstance(kind, str) or not kind:
                    raise IntegrityError("release artifact kind is missing")
                if kind in artifact_paths:
                    raise IntegrityError(f"duplicate release artifact kind: {kind}")
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
                artifact_paths[kind] = destination

            pointer_after = self.store.get(pointer_key)
            if pointer_after != pointer_data:
                raise IntegrityError("channel pointer changed during refresh")

            required = {"lexical_index", "graph", "provenance"}
            missing = sorted(required - set(artifact_paths))
            if missing:
                raise IntegrityError(f"release is missing runtime artifacts: {missing}")
            lexical_index = _load_json_file(
                artifact_paths["lexical_index"],
                "lexical index",
            )
            graph = _load_json_file(artifact_paths["graph"], "wiki graph")
            provenance = _load_json_file(
                artifact_paths["provenance"],
                "provenance",
            )
            semantic_index = None
            semantic_path = artifact_paths.get("semantic_index")
            if semantic_path is not None:
                semantic_index = _load_json_file(semantic_path, "semantic index")

            if release_cache.exists():
                shutil.rmtree(release_cache)
            staging_cache.replace(release_cache)
            active = ActiveRelease(
                release_id=release_id,
                manifest_sha256=actual_manifest_sha,
                loaded_at=(
                    datetime.now(UTC)
                    .replace(microsecond=0)
                    .isoformat()
                    .replace("+00:00", "Z")
                ),
                manifest=manifest,
                lexical_index=lexical_index,
                graph=graph,
                provenance=provenance,
                semantic_index=semantic_index,
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
        retrieved = retrieve_wiki_first(
            query=query,
            allowed_audiences=allowed_audiences,
            lexical_index=active.lexical_index,
            graph=active.graph,
            provenance=active.provenance,
            semantic_index=active.semantic_index,
            limit=limit,
        )
        citation_metrics = enrich_runtime_citations(
            results=retrieved["results"],
            provenance=active.provenance,
            allowed_audiences=allowed_audiences,
        )
        retrieved["retrieval"].update(citation_metrics)
        release = {
            "release_id": active.release_id,
            "manifest_sha256": active.manifest_sha256,
            "loaded_at": active.loaded_at,
            "created_at": active.manifest.get("created_at"),
        }
        evaluation = evaluate_runtime_query(
            release=release,
            query=query,
            audiences=allowed_audiences,
            status=retrieved["status"],
            results=retrieved["results"],
            retrieval=retrieved["retrieval"],
            non_answer_reason=retrieved["not_found_reason"],
        )
        return {
            "status": retrieved["status"],
            "release": release,
            "query": query,
            "results": retrieved["results"],
            "retrieval": retrieved["retrieval"],
            "evaluation": evaluation,
            "not_found_reason": retrieved["not_found_reason"],
            "non_answer_reason": retrieved["not_found_reason"],
        }
