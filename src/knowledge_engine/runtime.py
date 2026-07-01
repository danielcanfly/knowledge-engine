from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .errors import IntegrityError
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

    def refresh(self) -> ActiveRelease:
        pointer_key = f"channels/{self.channel}.json"
        pointer_data = self.store.get(pointer_key)
        pointer = json.loads(pointer_data)
        manifest_data = self.store.get(pointer["manifest_key"])
        actual_manifest_sha = sha256_bytes(manifest_data)
        if actual_manifest_sha != pointer["manifest_sha256"]:
            raise IntegrityError("channel manifest hash mismatch")
        manifest = json.loads(manifest_data)
        if manifest.get("release_id") != pointer.get("release_id"):
            raise IntegrityError("channel and manifest release IDs differ")
        release_cache = self.cache_dir / manifest["release_id"]
        staging_cache = self.cache_dir / f".{manifest['release_id']}.staging"
        if staging_cache.exists():
            import shutil

            shutil.rmtree(staging_cache)
        staging_cache.mkdir(parents=True)
        for artifact in manifest["artifacts"]:
            data = self.store.get(artifact["key"])
            if len(data) != artifact["bytes"] or sha256_bytes(data) != artifact["sha256"]:
                raise IntegrityError(f"artifact integrity failure: {artifact['key']}")
            relative = artifact["key"].split(
                f"releases/{manifest['release_id']}/", 1
            )[1]
            destination = staging_cache / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
        if release_cache.exists():
            import shutil

            shutil.rmtree(release_cache)
        staging_cache.replace(release_cache)
        lexical_path = release_cache / "artifacts/lexical-index.json"
        provenance_path = release_cache / "artifacts/provenance.json"
        active = ActiveRelease(
            release_id=manifest["release_id"],
            manifest_sha256=actual_manifest_sha,
            loaded_at=datetime.now(UTC)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
            manifest=manifest,
            lexical_index=json.loads(lexical_path.read_text(encoding="utf-8")),
            provenance=json.loads(provenance_path.read_text(encoding="utf-8")),
        )
        with self._lock:
            self._active = active
        return active

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
                            "uri": source["uri"],
                            "retrieved_at": source["retrieved_at"],
                        }
                        for source in record.get("sources", [])
                    ],
                }
            )
        return {
            "status": "answered" if results else "not_found",
            "release": {
                "release_id": active.release_id,
                "manifest_sha256": active.manifest_sha256,
                "loaded_at": active.loaded_at,
            },
            "query": query,
            "results": results,
            "retrieval": {
                "strategy": "wiki_first_lexical",
                "candidate_count": len(scored),
                "selected_count": len(results),
                "acl_filtered_count": filtered,
                "raw_fallback_used": False,
            },
            "non_answer_reason": None if results else "no_authorized_match",
        }
