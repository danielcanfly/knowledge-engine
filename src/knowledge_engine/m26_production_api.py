from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from . import m26_ask_api
from . import m26_pa7_arbitrary_query_runtime as legacy_runtime
from .m26_pa7_semantic_closure_runtime import run_owner_arbitrary_query

_original_named_question_entities = legacy_runtime._named_question_entities


def _named_question_entities_with_series_shorthand(question: str) -> list[str]:
    entities = list(_original_named_question_entities(question))
    harness_parts = re.findall(r"Harness Theory Part (\d+)", question, flags=re.I)
    if harness_parts:
        existing = {item.casefold() for item in entities}
        for part in re.findall(r"\bPart (\d+)\b", question, flags=re.I):
            entity = f"Harness Theory Part {part}"
            if entity.casefold() not in existing:
                entities.append(entity)
                existing.add(entity.casefold())
    return entities


# Install the normalized entity parser before the owner-only routes are registered.
legacy_runtime._named_question_entities = _named_question_entities_with_series_shorthand
m26_ask_api.run_owner_arbitrary_query = run_owner_arbitrary_query
m26_ask_api.RUNTIME_ENTRYPOINT = (
    "knowledge_engine.m26_pa7_semantic_closure_runtime.run_owner_arbitrary_query"
)

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

# Import after patching so route registration sees the production closure runtime.
from .api import app  # noqa: E402,F401
