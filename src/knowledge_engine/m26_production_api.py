from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from . import m26_ask_api
from . import m26_aq_semantic_runtime_patch_v3_lifecycle as aq_lifecycle_patch
from . import m26_pa7_arbitrary_query_runtime as legacy_runtime
from .m26_aq_semantic_runtime_patch_v3 import install as install_aq_semantic_runtime_patch
from .m26_aq_semantic_runtime_patch_v3_lifecycle import (
    install as install_aq_lifecycle_runtime_patch,
)
from .m26_aq_semantic_runtime_patch_v3_surface import (
    install as install_aq_surface_runtime_patch,
)
from .m26_intent_compat import classify_with_semantic_compat
from .m26_pa7_semantic_closure_runtime import run_owner_arbitrary_query

install_aq_semantic_runtime_patch()
install_aq_lifecycle_runtime_patch()
install_aq_surface_runtime_patch()

_production_question_contract = legacy_runtime._question_contract
_production_repair_guidance = aq_lifecycle_patch._repair_guidance


def _question_explicitly_requests_persisted_progress(question: str) -> bool:
    q = " ".join(str(question).casefold().split())
    return bool(
        re.search(r"\bpersist(?:ed|ence|ing)?\b", q)
        or any(
            marker in q
            for marker in (
                "durable",
                "disconnect",
                "recover",
                "resume",
                "saved state",
                "server-side state",
                "progress survives",
                "state survives",
            )
        )
    )


def _question_contract_without_progress_substring_false_positive(
    *, question: str, intent_class: str
) -> dict[str, Any]:
    """Do not treat ordinary in-progress wording as a persisted-progress request."""
    contract = dict(
        _production_question_contract(
            question=question,
            intent_class=intent_class,
        )
    )
    if _question_explicitly_requests_persisted_progress(question):
        return contract
    facets = contract.get("required_facets")
    if not isinstance(facets, list):
        return contract
    contract["required_facets"] = [
        item
        for item in facets
        if not isinstance(item, Mapping)
        or str(item.get("facet_id", "")) != "persisted_progress"
    ]
    return contract


def _production_variance_repair_guidance(code: str) -> str:
    if str(code) == "M26-PA7-ME-036":
        return (
            "The selected graph evidence records a precedes relation. State that exact "
            "ordering or sequence relationship explicitly, using comes before or precedes; "
            "do not replace it with dependency or causal semantics."
        )
    return _production_repair_guidance(str(code))


legacy_runtime._question_contract = (
    _question_contract_without_progress_substring_false_positive
)
aq_lifecycle_patch._repair_guidance = _production_variance_repair_guidance

_original_named_question_entities = legacy_runtime._named_question_entities
_original_intent_class = legacy_runtime._intent_class


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


def _intent_class_with_semantic_compat(question: str) -> str:
    return classify_with_semantic_compat(
        question,
        legacy_classifier=_original_intent_class,
    )


# Install semantic compatibility before the owner-only routes are registered.
legacy_runtime._named_question_entities = _named_question_entities_with_series_shorthand
legacy_runtime._intent_class = _intent_class_with_semantic_compat
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
