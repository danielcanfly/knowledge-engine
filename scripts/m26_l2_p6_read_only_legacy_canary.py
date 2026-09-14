from __future__ import annotations

import json
import os
from dataclasses import asdict
from typing import Any

from knowledge_engine.config import Settings
from knowledge_engine.errors import ConfigurationError, IntegrityError
from knowledge_engine.m26_active_production_release import resolve_active_production_release
from knowledge_engine.m26_ingestion_qdrant_qualification import (
    QdrantQualificationConfig,
    QdrantReadOnlyQualificationObserver,
)
from knowledge_engine.m26_production_promotion import (
    LEGACY_M25_COMBINED_IDENTITY_SHA256,
    LEGACY_M25_NORMALIZED_IDENTITY_SHA256,
    LEGACY_M25_POINT_COUNT,
    LEGACY_M25_RAW_IDENTITY_SHA256,
    LEGACY_M25_RAW_TEXT_WITH_DERIVED_NORMALIZED_EMBEDDING_V1,
)
from knowledge_engine.storage import ObjectMetadata, create_object_store


class ReadOnlyStore:
    def __init__(self, store: Any) -> None:
        self._store = store
        self.get_count = 0
        self.head_count = 0

    def get(self, key: str) -> bytes:
        self.get_count += 1
        return self._store.get(key)

    def head(self, key: str) -> ObjectMetadata | None:
        self.head_count += 1
        return self._store.head(key)


def _use_distinct_read_credentials() -> str:
    mappings = (
        ("R2_ACCESS_KEY_ID", "R2_ACCESS_KEY_ID_READ"),
        ("R2_SECRET_ACCESS_KEY", "R2_SECRET_ACCESS_KEY_READ"),
    )
    for runtime_name, read_name in mappings:
        read_value = os.environ.get(read_name, "").strip()
        if not read_value:
            raise ConfigurationError(f"missing required read credential: {read_name}")
        os.environ[runtime_name] = read_value
    read_key = os.environ.get("QDRANT_API_KEY_READ", "").strip()
    if not read_key:
        raise ConfigurationError("missing required read credential: QDRANT_API_KEY_READ")
    write_key = os.environ.get("QDRANT_API_KEY", "").strip()
    if write_key and read_key == write_key:
        raise ConfigurationError("QDRANT_API_KEY_READ is not distinct from write credential")
    return read_key


def main() -> int:
    read_key = _use_distinct_read_credentials()
    settings = Settings.from_env()
    store = ReadOnlyStore(create_object_store(settings))
    active = resolve_active_production_release(store)
    observer = QdrantReadOnlyQualificationObserver(
        QdrantQualificationConfig(
            url=os.environ.get("QDRANT_URL", ""),
            api_key=read_key,
            page_size=100,
        ),
        store=store,
    )
    qualification = observer.qualify_production(active)
    if (
        qualification.identity_profile != LEGACY_M25_RAW_TEXT_WITH_DERIVED_NORMALIZED_EMBEDDING_V1
        or qualification.full_identity_count != LEGACY_M25_POINT_COUNT
        or qualification.legacy_payload_text_identity_sha256 != LEGACY_M25_RAW_IDENTITY_SHA256
        or qualification.derived_embedding_input_identity_sha256
        != LEGACY_M25_NORMALIZED_IDENTITY_SHA256
        or qualification.historical_identity_evidence_sha256 != LEGACY_M25_COMBINED_IDENTITY_SHA256
    ):
        raise IntegrityError("L2-P6 live legacy qualification mismatch")
    allowed_calls = {"GET", "POST"}
    if any(method not in allowed_calls for method, _ in observer.calls):
        raise IntegrityError("L2-P6 non-read Qdrant call detected")

    value = asdict(qualification)
    report = {
        "schema_version": "knowledge-engine-m26-l2-p6-read-only-canary/v1",
        "status": "PASS",
        "release_id": active.release_id,
        "collection": qualification.collection,
        "identity_profile": qualification.identity_profile,
        "points_count": qualification.points_count,
        "full_identity_count": qualification.full_identity_count,
        "derived_embedding_input_count": qualification.derived_embedding_input_count,
        "legacy_payload_text_identity_sha256": value["legacy_payload_text_identity_sha256"],
        "derived_embedding_input_identity_sha256": value["derived_embedding_input_identity_sha256"],
        "historical_identity_evidence_sha256": value["historical_identity_evidence_sha256"],
        "qdrant_read_key_distinct": "PASS",
        "qdrant_read_requests": len(observer.calls),
        "qdrant_mutations": 0,
        "r2_get_requests": store.get_count,
        "r2_head_requests": store.head_count,
        "r2_mutations": 0,
        "production_pointer_mutations": 0,
        "backfill_mutations": 0,
    }
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
