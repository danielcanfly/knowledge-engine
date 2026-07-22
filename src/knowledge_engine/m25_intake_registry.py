from __future__ import annotations

from typing import Any

from .m25_intake_common import (
    ADAPTER_SCHEMA,
    AUTHORITY_SCHEMA,
    EXISTING_INTAKE_ADAPTER,
    FOUNDATION_SHA,
    LOCAL_MARKDOWN_ADAPTER,
    M25_2_ENGINE_BASE_SHA,
    NORMALIZED_OUTPUT_SCHEMA,
    SOURCE_SHA,
    _digest,
)

def build_adapter_registry() -> dict[str, Any]:
    pins = {
        "engine_sha": M25_2_ENGINE_BASE_SHA,
        "source_sha": SOURCE_SHA,
        "foundation_sha": FOUNDATION_SHA,
    }
    definitions = [
        {
            "schema_version": ADAPTER_SCHEMA,
            "adapter_id": LOCAL_MARKDOWN_ADAPTER,
            "adapter_version": "1.0.0",
            "classification": "adapter",
            "source_contract": "local-file/1.0.0 -> intake/v1",
            "target_contract": NORMALIZED_OUTPUT_SCHEMA,
            "pinned_repositories": pins,
            "may_read": ["explicit allowed_root local Markdown files"],
            "may_write": ["intake/v1/*", "admission/v1/*"],
            "must_not_write": [
                "knowledge-source/*",
                "channels/production.json",
                "production/*",
            ],
            "hidden_io_permitted": False,
        },
        {
            "schema_version": ADAPTER_SCHEMA,
            "adapter_id": EXISTING_INTAKE_ADAPTER,
            "adapter_version": "1.0.0",
            "classification": "direct_reuse",
            "source_contract": "accepted intake/v1 artifact references",
            "target_contract": NORMALIZED_OUTPUT_SCHEMA,
            "pinned_repositories": pins,
            "may_read": ["explicit intake/v1 object keys"],
            "may_write": ["admission/v1/*"],
            "must_not_write": [
                "intake/v1/raw/*",
                "knowledge-source/*",
                "channels/production.json",
            ],
            "hidden_io_permitted": False,
        },
    ]
    adapters = []
    for definition in definitions:
        adapter = dict(definition)
        adapter["adapter_sha256"] = _digest(adapter)
        adapters.append(adapter)
    registry = {
        "schema_version": "knowledge-engine-m25-adapter-registry/v1",
        "entry_engine_sha": M25_2_ENGINE_BASE_SHA,
        "authority": "candidate_only",
        "approved_adapter_count": len(adapters),
        "adapters": adapters,
    }
    registry["registry_sha256"] = _digest(registry)
    return registry

def build_authority_envelope() -> dict[str, Any]:
    body = {
        "schema_version": AUTHORITY_SCHEMA,
        "authority_class": "candidate_only",
        "decision_ref": None,
        "immutable_intake_write_permitted": True,
        "candidate_write_permitted": True,
        "review_decision_write_permitted": False,
        "source_branch_write_permitted": False,
        "source_pr_open_permitted": False,
        "source_pr_merge_permitted": False,
        "candidate_release_rebuild_permitted": False,
        "production_pointer_write_permitted": False,
        "semantic_or_hybrid_enable_permitted": False,
        "production_answer_serving_permitted": False,
        "large_scale_ingestion_permitted": False,
    }
    identity = _digest(body)
    envelope = {**body, "authority_id": "m25auth_" + identity}
    envelope["authority_sha256"] = _digest(envelope)
    return envelope

