from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import m26_aq_semantic_runtime_patch_v2 as canonical_aq_runtime
from . import m26_ask_api

CANONICAL_RUNTIME_ENTRYPOINT = (
    "knowledge_engine.m26_pa7_semantic_closure_runtime.run_owner_arbitrary_query"
)

# Compose the canonical AQ runtime once before route registration. This keeps the
# production wrapper on one public serving path while restoring verified semantic
# repair behavior without installing the final universal recovery patch tower.
canonical_aq_runtime.install()

from .m26_pa7_semantic_closure_runtime import run_owner_arbitrary_query  # noqa: E402

m26_ask_api.run_owner_arbitrary_query = run_owner_arbitrary_query
m26_ask_api.RUNTIME_ENTRYPOINT = CANONICAL_RUNTIME_ENTRYPOINT

_original_build_web_query_dto = m26_ask_api.build_web_query_dto


def _build_web_query_dto_with_semantic_closure(
    runtime_response: Mapping[str, Any],
) -> dict[str, Any]:
    dto = _original_build_web_query_dto(runtime_response)
    dto["answer_source"] = str(runtime_response.get("answer_source", ""))
    dto["semantic_closure"] = dict(
        runtime_response.get("semantic_closure", {})
        if isinstance(runtime_response.get("semantic_closure"), Mapping)
        else {}
    )
    dto["evidence_utilization_trace"] = dict(
        runtime_response.get("evidence_utilization_trace", {})
        if isinstance(runtime_response.get("evidence_utilization_trace"), Mapping)
        else {}
    )
    dto["graph_observability"] = dict(
        runtime_response.get("graph_observability", {})
        if isinstance(runtime_response.get("graph_observability"), Mapping)
        else {}
    )
    dto["integrity"] = {
        "unsupported_accepted_claims": int(
            runtime_response.get("unsupported_accepted_claims", 0)
        ),
        "material_claim_support_verified": bool(
            runtime_response.get("material_claim_support_verified", True)
        ),
        "citation_locator_valid": bool(runtime_response.get("citation_locator_valid", True)),
    }
    return dto


m26_ask_api.build_web_query_dto = _build_web_query_dto_with_semantic_closure

from .api import app  # noqa: E402,F401
