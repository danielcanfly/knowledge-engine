from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import quote

import httpx

from .m23_7_5_live_shadow import (
    COLLECTION,
    VECTOR_NAME,
    HttpLiveShadowClient,
    ShadowFailure,
)


class StrictModeSafeHttpLiveShadowClient(HttpLiveShadowClient):
    """Read the isolated pilot without relying on unindexed payload filters.

    Qdrant Cloud strict mode may reject filtering on payload fields that do not
    have payload indexes. The collection, vector and point count are verified
    separately, and every returned point is validated by the M23.7.5 core before
    it can contribute to observation evidence.
    """

    def _post_points(self, endpoint: str, body: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        url = (
            f"{self.qdrant.base_url.rstrip('/')}/collections/"
            f"{quote(COLLECTION, safe='')}/points/{endpoint}"
        )
        try:
            with httpx.Client(timeout=self.qdrant.timeout_seconds) as client:
                response = client.post(
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
