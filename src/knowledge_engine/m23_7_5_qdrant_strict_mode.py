from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import quote

import httpx

from .errors import IntegrityError
from .m23_7_5_live_shadow import (
    COLLECTION,
    VECTOR_NAME,
    HttpLiveShadowClient,
    ShadowFailure,
)
from .m23_cloudflare_qdrant import (
    CloudflareConfig,
    QdrantConfig,
    SectionInput,
    embed_sections,
    validate_qdrant_collection_response,
)


class StrictModeSafeHttpLiveShadowClient(HttpLiveShadowClient):
    """Reuse two bounded sessions while preserving strict read-only validation.

    Qdrant Cloud strict mode may reject filtering on payload fields that do not
    have payload indexes. The collection, vector and point count are verified
    separately, and every returned point is validated by the M23.7.5 core before
    it can contribute to observation evidence.

    One Cloudflare client and one Qdrant client are created for an observation.
    Reusing them removes repeated TLS/proxy handshakes without changing the
    provider, model, request payloads, collection, authority or privacy boundary.
    """

    def __init__(self, cloudflare: CloudflareConfig, qdrant: QdrantConfig) -> None:
        super().__init__(cloudflare, qdrant)
        object.__setattr__(
            self,
            "_cloudflare_http",
            httpx.Client(timeout=cloudflare.timeout_seconds),
        )
        object.__setattr__(
            self,
            "_qdrant_http",
            httpx.Client(timeout=qdrant.timeout_seconds),
        )
        object.__setattr__(self, "_closed", False)

    def __enter__(self) -> StrictModeSafeHttpLiveShadowClient:
        self._ensure_open()
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _ensure_open(self) -> None:
        if self._closed:
            raise ShadowFailure("response-shape-drift")

    def close(self) -> None:
        if self._closed:
            return
        self._cloudflare_http.close()
        self._qdrant_http.close()
        object.__setattr__(self, "_closed", True)

    def collection_snapshot(self) -> Mapping[str, Any]:
        self._ensure_open()
        url = (
            f"{self.qdrant.base_url.rstrip('/')}/collections/"
            f"{quote(COLLECTION, safe='')}"
        )
        try:
            response = self._qdrant_http.get(
                url,
                headers={"api-key": self.qdrant.api_key},
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException as exc:
            raise ShadowFailure("qdrant-timeout") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise ShadowFailure("qdrant-unavailable") from exc
        if not isinstance(payload, Mapping):
            raise ShadowFailure("response-shape-drift")
        try:
            return validate_qdrant_collection_response(payload)
        except IntegrityError as exc:
            raise ShadowFailure("collection-identity-drift") from exc

    def _post_points(self, endpoint: str, body: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        self._ensure_open()
        url = (
            f"{self.qdrant.base_url.rstrip('/')}/collections/"
            f"{quote(COLLECTION, safe='')}/points/{endpoint}"
        )
        try:
            response = self._qdrant_http.post(
                url,
                headers={"api-key": self.qdrant.api_key},
                json=dict(body),
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException as exc:
            raise ShadowFailure("qdrant-timeout") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise ShadowFailure("qdrant-unavailable") from exc
        if not isinstance(payload, Mapping):
            raise ShadowFailure("response-shape-drift")
        result = payload.get("result")
        points = result.get("points") if isinstance(result, Mapping) else None
        if not isinstance(points, list) or any(not isinstance(item, Mapping) for item in points):
            raise ShadowFailure("response-shape-drift")
        return points

    def sample_points(self, limit: int) -> Sequence[Mapping[str, Any]]:
        return self._post_points(
            "scroll",
            {
                "limit": limit,
                "with_payload": True,
                "with_vector": False,
            },
        )

    def embed(self, text: str) -> Sequence[float]:
        self._ensure_open()
        section = SectionInput(section_id="m23-7-5-live-probe", text=text, payload={})
        try:
            rows = embed_sections(
                [section],
                self.cloudflare,
                client=self._cloudflare_http,
            )
        except httpx.TimeoutException as exc:
            raise ShadowFailure("cloudflare-timeout") from exc
        except (httpx.HTTPError, IntegrityError) as exc:
            raise ShadowFailure("cloudflare-unavailable") from exc
        if len(rows) != 1:
            raise ShadowFailure("response-shape-drift")
        return rows[0]

    def query(self, vector: Sequence[float], top_k: int) -> Sequence[Mapping[str, Any]]:
        return self._post_points(
            "query",
            {
                "query": list(vector),
                "using": VECTOR_NAME,
                "limit": top_k,
                "with_payload": True,
                "with_vector": False,
            },
        )
