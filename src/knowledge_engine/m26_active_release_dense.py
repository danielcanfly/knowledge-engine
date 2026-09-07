from __future__ import annotations

import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from .m23_cloudflare_qdrant import (
    QDRANT_VECTOR_NAME,
    CloudflareConfig,
    SectionInput,
    embed_sections,
)
from .m26_pa7_arbitrary_query_runtime import (
    DenseChannel,
    LocalDenseProjectionChannel,
    PA7ArbitraryQueryError,
)
from .m26_production_answer_bundle import ProductionAnswerBundle
from .m26_verified_answer_citation_gate import canonical_sha256


@dataclass(frozen=True)
class ActiveReleaseDenseConfig:
    cloudflare_account_id: str
    cloudflare_api_token: str
    qdrant_url: str
    qdrant_api_key: str
    timeout_seconds: float = 30.0


EmbeddingFunction = Callable[
    [Sequence[SectionInput]],
    Sequence[Sequence[float]],
]


class ActiveReleaseQdrantDenseChannel:
    """Read-only dense retrieval whose identity comes only from the active pointer chain."""

    def __init__(
        self,
        config: ActiveReleaseDenseConfig,
        *,
        qdrant_client: httpx.Client | None = None,
        embedding_function: EmbeddingFunction | None = None,
    ) -> None:
        self.config = config
        self._qdrant_client = qdrant_client
        self._embedding_function = embedding_function

    def _client(self) -> tuple[httpx.Client, bool]:
        if self._qdrant_client is not None:
            return self._qdrant_client, False
        return httpx.Client(timeout=self.config.timeout_seconds), True

    def _embed(self, question: str) -> Sequence[float]:
        sections = (
            SectionInput(
                section_id="m26-active-release-owner-query",
                text=question,
                payload={},
            ),
        )
        if self._embedding_function is not None:
            vectors = self._embedding_function(sections)
        else:
            vectors = embed_sections(
                sections,
                CloudflareConfig(
                    account_id=self.config.cloudflare_account_id,
                    api_token=self.config.cloudflare_api_token,
                    timeout_seconds=self.config.timeout_seconds,
                ),
            )
        if len(vectors) != 1:
            raise PA7ArbitraryQueryError(
                "PA7_ACTIVE_RELEASE_EMBEDDING_INVALID",
                "active-release dense query did not produce exactly one vector",
            )
        return vectors[0]

    @staticmethod
    def _active_filter(bundle: ProductionAnswerBundle) -> dict[str, Any]:
        active = bundle.active_release
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
                {
                    "key": "candidate_release_eligible",
                    "match": {"value": True},
                },
                {
                    "key": "production_authority",
                    "match": {"value": False},
                },
            ]
        }

    @staticmethod
    def _semantic_section_ids(bundle: ProductionAnswerBundle) -> set[str]:
        semantic = bundle.semantic_inputs
        if not isinstance(semantic, Mapping):
            raise PA7ArbitraryQueryError(
                "PA7_ACTIVE_RELEASE_SEMANTIC_INPUTS_MISSING",
                "active production bundle has no semantic_inputs artifact",
            )
        documents = semantic.get("documents")
        if not isinstance(documents, list) or not documents:
            raise PA7ArbitraryQueryError(
                "PA7_ACTIVE_RELEASE_SEMANTIC_INPUTS_INVALID",
                "active semantic_inputs documents are missing",
            )
        section_ids: set[str] = set()
        for document in documents:
            if not isinstance(document, Mapping):
                raise PA7ArbitraryQueryError(
                    "PA7_ACTIVE_RELEASE_SEMANTIC_INPUTS_INVALID",
                    "active semantic_inputs contains a non-object document",
                )
            section_id = document.get("section_id")
            if not isinstance(section_id, str) or not section_id:
                raise PA7ArbitraryQueryError(
                    "PA7_ACTIVE_RELEASE_SEMANTIC_INPUTS_INVALID",
                    "active semantic_inputs document is missing section_id",
                )
            if section_id in section_ids:
                raise PA7ArbitraryQueryError(
                    "PA7_ACTIVE_RELEASE_SEMANTIC_INPUTS_INVALID",
                    "active semantic_inputs contains duplicate section_id",
                )
            section_ids.add(section_id)
        if len(section_ids) != bundle.active_release.semantic_point_count:
            raise PA7ArbitraryQueryError(
                "PA7_ACTIVE_RELEASE_SEMANTIC_COUNT_MISMATCH",
                "active semantic_inputs count does not match pointer-bound Qdrant count",
            )
        return section_ids

    @staticmethod
    def _validate_payload(
        payload: Mapping[str, Any],
        *,
        bundle: ProductionAnswerBundle,
        allowed_section_ids: set[str],
    ) -> str:
        active = bundle.active_release
        expected = {
            "release_id": active.release_id,
            "source_commit_sha": active.source_commit_sha,
            "admission_sha256": active.admission_sha256,
            "candidate_release_eligible": True,
            "production_authority": False,
        }
        for key, value in expected.items():
            if payload.get(key) != value:
                raise PA7ArbitraryQueryError(
                    "PA7_ACTIVE_RELEASE_QDRANT_PAYLOAD_MISMATCH",
                    f"Qdrant payload {key} does not match active production identity",
                )
        section_id = payload.get("section_id")
        if not isinstance(section_id, str) or section_id not in allowed_section_ids:
            raise PA7ArbitraryQueryError(
                "PA7_ACTIVE_RELEASE_QDRANT_SECTION_MISMATCH",
                "Qdrant payload section_id is outside the active semantic artifact",
            )
        return section_id

    def search(
        self,
        *,
        question: str,
        bundle: ProductionAnswerBundle,
        top_k: int,
    ) -> dict[str, Any]:
        active = bundle.active_release
        if bundle.release_id != active.release_id:
            raise PA7ArbitraryQueryError(
                "PA7_ACTIVE_RELEASE_BUNDLE_MISMATCH",
                "answer bundle release_id does not match resolved production pointer",
            )
        if not self.config.qdrant_url.startswith("https://"):
            raise PA7ArbitraryQueryError(
                "PA7_ACTIVE_RELEASE_QDRANT_URL_INVALID",
                "Qdrant URL must use https",
            )
        if not self.config.qdrant_api_key:
            raise PA7ArbitraryQueryError(
                "PA7_ACTIVE_RELEASE_QDRANT_AUTH_MISSING",
                "Qdrant read credential is missing",
            )

        allowed_section_ids = self._semantic_section_ids(bundle)
        vector = self._embed(question)
        identity_filter = self._active_filter(bundle)
        collection = active.qdrant_collection
        url = (
            self.config.qdrant_url.rstrip("/")
            + "/collections/"
            + quote(collection, safe="")
            + "/points/search"
        )
        client, owned = self._client()
        try:
            response = client.post(
                url,
                headers={
                    "api-key": self.config.qdrant_api_key,
                    "Content-Type": "application/json",
                },
                json={
                    "vector": {"name": QDRANT_VECTOR_NAME, "vector": list(vector)},
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
            )
            response.raise_for_status()
            body = response.json()
        finally:
            if owned:
                client.close()

        raw_results = body.get("result") if isinstance(body, Mapping) else None
        if not isinstance(raw_results, list):
            raise PA7ArbitraryQueryError(
                "PA7_ACTIVE_RELEASE_DENSE_BACKEND_INVALID",
                "Qdrant response shape is invalid",
            )

        candidates: list[dict[str, Any]] = []
        for raw in raw_results:
            if not isinstance(raw, Mapping):
                raise PA7ArbitraryQueryError(
                    "PA7_ACTIVE_RELEASE_DENSE_BACKEND_INVALID",
                    "Qdrant result entry is not an object",
                )
            payload = raw.get("payload")
            if not isinstance(payload, Mapping):
                raise PA7ArbitraryQueryError(
                    "PA7_ACTIVE_RELEASE_DENSE_BACKEND_INVALID",
                    "Qdrant result payload is missing",
                )
            section_id = self._validate_payload(
                payload,
                bundle=bundle,
                allowed_section_ids=allowed_section_ids,
            )
            score = raw.get("score")
            if isinstance(score, bool) or not isinstance(score, (int, float)):
                raise PA7ArbitraryQueryError(
                    "PA7_ACTIVE_RELEASE_DENSE_BACKEND_INVALID",
                    "Qdrant result score is invalid",
                )
            candidates.append(
                {
                    "channel": "dense",
                    "section_id": section_id,
                    "concept_id": str(payload.get("concept_id", "")),
                    "score": round(float(score), 6),
                    "point_id_sha256": canonical_sha256(str(raw.get("id", ""))),
                    "payload_identity_sha256": canonical_sha256(
                        {
                            key: payload.get(key)
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
                            if key in payload
                        }
                    ),
                    "payload_release_id": str(payload.get("release_id", "")),
                    "payload_text_sha256": str(payload.get("text_sha256", "")),
                }
            )
        candidates.sort(key=lambda item: (-float(item["score"]), item["section_id"]))
        return {
            "backend_identity": {
                "backend": "active_release_qdrant_dense_read_only",
                "qdrant_collection": collection,
                "qdrant_url_sha256": canonical_sha256(
                    self.config.qdrant_url.rstrip("/")
                ),
                "vector_name": QDRANT_VECTOR_NAME,
                "release_id": active.release_id,
                "source_commit_sha": active.source_commit_sha,
                "admission_sha256": active.admission_sha256,
                "candidate_manifest_sha256": active.candidate_manifest_sha256,
                "production_manifest_sha256": active.production_manifest_sha256,
                "production_pointer_sha256": active.pointer_sha256,
                "remote": True,
                "vectors_persisted": False,
                "read_only": True,
                "identity_filter": identity_filter,
                "identity_checked": True,
                "authority_source": "resolved_production_pointer_chain",
            },
            "candidates": candidates[:top_k],
        }


def active_release_dense_channel_from_env(
    *,
    require_remote: bool = False,
) -> DenseChannel:
    api_key = (
        os.environ.get("QDRANT_API_KEY_READ")
        or os.environ.get("QDRANT_READ_ONLY_API_KEY")
        or os.environ.get("QDRANT_API_KEY")
        or ""
    )
    values = {
        "cloudflare_account_id": os.environ.get("CLOUDFLARE_ACCOUNT_ID", ""),
        "cloudflare_api_token": os.environ.get("CLOUDFLARE_AI_TOKEN")
        or os.environ.get("CLOUDFLARE_API_TOKEN", ""),
        "qdrant_url": os.environ.get("QDRANT_URL", ""),
        "qdrant_api_key": api_key,
    }
    present = {key for key, value in values.items() if value}
    if present and len(present) != len(values):
        missing = sorted(set(values) - present)
        raise PA7ArbitraryQueryError(
            "PA7_ACTIVE_RELEASE_REMOTE_DENSE_CONFIG_PARTIAL",
            "partial remote dense configuration: " + ",".join(missing),
        )
    if len(present) == len(values):
        return ActiveReleaseQdrantDenseChannel(
            ActiveReleaseDenseConfig(**values)
        )
    if require_remote:
        raise PA7ArbitraryQueryError(
            "PA7_ACTIVE_RELEASE_REMOTE_DENSE_CONFIG_MISSING",
            "remote dense configuration is required",
        )
    return LocalDenseProjectionChannel()


__all__ = [
    "ActiveReleaseDenseConfig",
    "ActiveReleaseQdrantDenseChannel",
    "active_release_dense_channel_from_env",
]
