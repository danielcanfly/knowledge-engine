from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from .m23_cloudflare_qdrant import (
    CLOUDFLARE_MODEL,
    QDRANT_VECTOR_NAME,
    CloudflareConfig,
    SectionInput,
    embed_sections,
)
from .m26_active_production_release import ActiveProductionRelease
from .m26_pa7_arbitrary_query_runtime import PA7ArbitraryQueryError
from .m26_production_answer_bundle import (
    ProductionAnswerBundle,
    ProductionAnswerBundleError,
)
from .m26_verified_answer_citation_gate import canonical_sha256


@dataclass(frozen=True)
class ProductionRemoteDenseConfig:
    cloudflare_account_id: str
    cloudflare_api_token: str
    qdrant_url: str
    qdrant_api_key: str
    timeout_seconds: float = 30.0


class ActiveProductionQdrantDenseChannel:
    """Read-only dense retrieval bound to the bundle's active production pointer."""

    def __init__(self, config: ProductionRemoteDenseConfig) -> None:
        self.config = config

    def search(
        self,
        *,
        question: str,
        bundle: ProductionAnswerBundle,
        top_k: int,
    ) -> dict[str, Any]:
        active = _active_release(bundle)
        vector = embed_sections(
            [SectionInput(section_id="m26-pa7-owner-query", text=question, payload={})],
            CloudflareConfig(
                account_id=self.config.cloudflare_account_id,
                api_token=self.config.cloudflare_api_token,
                timeout_seconds=self.config.timeout_seconds,
            ),
        )[0]
        identity_filter = _active_production_qdrant_filter(active)
        response = httpx.post(
            _qdrant_search_url(self.config.qdrant_url, active.qdrant_collection),
            headers={
                "api-key": self.config.qdrant_api_key,
                "Content-Type": "application/json",
            },
            json={
                "vector": {"name": QDRANT_VECTOR_NAME, "vector": vector},
                "limit": max(1, min(top_k, 20)),
                "filter": identity_filter,
                "with_payload": [
                    "concept_id",
                    "section_id",
                    "source_id",
                    "release_id",
                    "source_commit_sha",
                    "admission_sha256",
                    "candidate_release_eligible",
                    "production_authority",
                    "text_sha256",
                ],
                "with_vector": False,
            },
            timeout=self.config.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, Mapping) or not isinstance(payload.get("result"), list):
            raise PA7ArbitraryQueryError(
                "PA7_DENSE_BACKEND_INVALID",
                "Qdrant response shape is invalid",
            )

        candidates: list[dict[str, Any]] = []
        for raw in payload["result"]:
            if not isinstance(raw, Mapping):
                continue
            point_payload = raw.get("payload")
            if not isinstance(point_payload, Mapping):
                continue
            _validate_qdrant_payload_identity(point_payload, active)
            section_id = str(point_payload.get("section_id", "")).strip()
            if not section_id:
                continue
            score = raw.get("score", 0.0)
            if isinstance(score, bool) or not isinstance(score, (int, float)):
                continue
            candidates.append(
                {
                    "channel": "dense",
                    "section_id": section_id,
                    "concept_id": str(point_payload.get("concept_id", "")),
                    "score": round(float(score), 6),
                    "point_id_sha256": canonical_sha256(str(raw.get("id", ""))),
                    "payload_identity_sha256": canonical_sha256(
                        {
                            key: point_payload.get(key)
                            for key in (
                                "concept_id",
                                "section_id",
                                "source_id",
                                "release_id",
                                "source_commit_sha",
                                "admission_sha256",
                                "candidate_release_eligible",
                                "production_authority",
                                "text_sha256",
                            )
                            if key in point_payload
                        }
                    ),
                    "payload_release_id": str(point_payload.get("release_id", "")),
                    "payload_text_sha256": str(point_payload.get("text_sha256", "")),
                }
            )

        return {
            "backend_identity": {
                "backend": "qdrant_dense_read_only",
                "qdrant_collection": active.qdrant_collection,
                "qdrant_url_sha256": canonical_sha256(
                    self.config.qdrant_url.rstrip("/")
                ),
                "embedding_model": CLOUDFLARE_MODEL,
                "vector_name": QDRANT_VECTOR_NAME,
                "release_id": active.release_id,
                "manifest_sha256": bundle.manifest_sha256,
                "production_pointer_sha256": active.pointer_sha256,
                "semantic_point_count": active.semantic_point_count,
                "remote": True,
                "vectors_persisted": False,
                "identity_filter": identity_filter,
                "identity_checked": True,
            },
            "candidates": candidates[:top_k],
        }


def production_dense_channel_from_env(
    *,
    require_remote: bool = False,
) -> ActiveProductionQdrantDenseChannel | None:
    """Build remote dense access without accepting collection identity from env."""

    config_values = {
        "cloudflare_account_id": os.environ.get("CLOUDFLARE_ACCOUNT_ID", ""),
        "cloudflare_api_token": os.environ.get("CLOUDFLARE_AI_TOKEN")
        or os.environ.get("CLOUDFLARE_API_TOKEN", ""),
        "qdrant_url": os.environ.get("QDRANT_URL", ""),
        "qdrant_api_key": os.environ.get("QDRANT_API_KEY_READ")
        or os.environ.get("QDRANT_READ_ONLY_API_KEY")
        or os.environ.get("QDRANT_API_KEY", ""),
    }
    if all(config_values.values()):
        return ActiveProductionQdrantDenseChannel(
            ProductionRemoteDenseConfig(**config_values)
        )
    if require_remote:
        missing = sorted(key for key, value in config_values.items() if not value)
        raise PA7ArbitraryQueryError(
            "PA7_REMOTE_DENSE_CONFIG_MISSING",
            "missing remote dense configuration: " + ",".join(missing),
        )
    return None


def _active_release(bundle: ProductionAnswerBundle) -> ActiveProductionRelease:
    try:
        active = bundle.active_release
    except ProductionAnswerBundleError as exc:
        raise PA7ArbitraryQueryError(
            "PA7_ACTIVE_PRODUCTION_RELEASE_MISSING",
            "dense query bundle is missing resolved active production authority",
        ) from exc
    if bundle.release_id != active.release_id:
        raise PA7ArbitraryQueryError(
            "PA7_PRODUCTION_BUNDLE_RELEASE_MISMATCH",
            "dense query bundle does not match its resolved active production release",
        )
    if not active.qdrant_collection:
        raise PA7ArbitraryQueryError(
            "PA7_ACTIVE_QDRANT_COLLECTION_MISSING",
            "active production release is missing its Qdrant collection",
        )
    return active


def _active_production_qdrant_filter(
    active: ActiveProductionRelease,
) -> dict[str, Any]:
    return {
        "must": [
            {"key": "release_id", "match": {"value": active.release_id}},
            {
                "key": "source_commit_sha",
                "match": {"value": active.source_commit_sha},
            },
            {
                "key": "admission_sha256",
                "match": {"value": active.admission_sha256},
            },
            {"key": "candidate_release_eligible", "match": {"value": True}},
            {"key": "production_authority", "match": {"value": True}},
        ]
    }


def _validate_qdrant_payload_identity(
    payload: Mapping[str, Any],
    active: ActiveProductionRelease,
) -> None:
    expected = {
        "release_id": active.release_id,
        "source_commit_sha": active.source_commit_sha,
        "admission_sha256": active.admission_sha256,
        "candidate_release_eligible": True,
        "production_authority": True,
    }
    mismatches = [
        key for key, value in expected.items() if payload.get(key) != value
    ]
    if mismatches:
        raise PA7ArbitraryQueryError(
            "PA7_QDRANT_PAYLOAD_IDENTITY_MISMATCH",
            "dense point identity does not match active production authority: "
            + ",".join(sorted(mismatches)),
        )


def _qdrant_search_url(base_url: str, collection: str) -> str:
    return (
        f"{base_url.rstrip('/')}/collections/"
        f"{quote(collection, safe='')}/points/search"
    )
