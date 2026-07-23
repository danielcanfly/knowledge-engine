from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .errors import IntegrityError
from .m14_citation_runtime import enrich_runtime_citations
from .m14_retrieval import AUDIENCE_RANK, retrieve_wiki_first

QUESTION_SCHEMA = "knowledge-engine-m26-question-request/v1"
PLAN_SCHEMA = "knowledge-engine-m26-retrieval-plan/v1"
ENVELOPE_SCHEMA = "knowledge-engine-m26-evidence-envelope/v1"
TRACE_SCHEMA = "knowledge-engine-m26-retrieval-trace/v1"
GAP_SCHEMA = "knowledge-engine-m26-retrieval-gap-report/v1"
CORPUS_SCHEMA = "knowledge-engine-m26-synthetic-corpus/v1"
POLICY_SCHEMA = "knowledge-engine-m26-retrieval-policy/v1"
BENCHMARK_SCHEMA = "knowledge-engine-m26-retrieval-benchmark/v1"

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u3400-\u9fff]+")
_WS_RE = re.compile(r"\s+")
_PROMPT_INJECTION_PATTERNS = (
    ("ignore_previous", re.compile(r"\bignore\s+(?:all\s+)?previous\b", re.I)),
    ("system_prompt_request", re.compile(r"\bsystem\s+prompt\b", re.I)),
    ("embedded_instruction", re.compile(r"\bfollow\s+(?:these|the)\s+instructions\b", re.I)),
)
_SECRET_PATTERNS = (
    ("password_assignment", re.compile(r"\bpassword\s*[:=]\s*\S+", re.I)),
    ("bearer_token", re.compile(r"\bbearer\s+[A-Za-z0-9._~+/=-]{12,}", re.I)),
    ("api_key_assignment", re.compile(r"\bapi[_-]?key\s*[:=]\s*\S+", re.I)),
    ("private_key", re.compile(r"BEGIN [A-Z ]*PRIVATE KEY")),
)
_STOP_TERMS = {
    "a", "an", "and", "are", "about", "does", "explain", "for", "how", "in",
    "is", "it", "of", "on", "or", "say", "the", "to", "what", "with",
}
_AUDIENCE_LADDER = ("public", "internal", "confidential", "restricted")
_ALLOWED_INTENTS = {"lookup", "explain", "compare", "trace_source", "navigate_graph", "follow_up"}


class RetrievalEnvelopeError(IntegrityError):
    """Fail-closed M26.2 contract error with a stable reason code."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(f"{reason_code}: {message}")
        self.reason_code = reason_code


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_value(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def with_self_digest(value: Mapping[str, Any]) -> dict[str, Any]:
    unsigned = dict(value)
    unsigned.pop("self_sha256", None)
    return {**unsigned, "self_sha256": sha256_value(unsigned)}


def verify_self_digest(value: Mapping[str, Any]) -> None:
    unsigned = dict(value)
    claimed = unsigned.pop("self_sha256", None)
    if not isinstance(claimed, str) or claimed != sha256_value(unsigned):
        raise RetrievalEnvelopeError("SELF_DIGEST_MISMATCH", "artifact self digest is invalid")


def normalize_question(question: str) -> str:
    if not isinstance(question, str) or not question.strip():
        raise RetrievalEnvelopeError("QUESTION_EMPTY", "question must be a non-empty string")
    normalized = _WS_RE.sub(" ", question).strip()
    if len(normalized) > 12000:
        raise RetrievalEnvelopeError("QUESTION_TOO_LONG", "question exceeds the M26.1 bound")
    return normalized


def query_terms(question: str) -> list[str]:
    terms = [term.casefold() for term in _TOKEN_RE.findall(question)]
    return list(dict.fromkeys(term for term in terms if term not in _STOP_TERMS))


def infer_intent(question: str, *, parent_request_id: object = None) -> str:
    lowered = question.casefold()
    if parent_request_id:
        return "follow_up"
    if any(token in lowered for token in ("compare", "difference", "versus", " vs ")):
        return "compare"
    if any(token in lowered for token in ("source", "provenance", "citation", "where does")):
        return "trace_source"
    if any(token in lowered for token in ("related", "relationship", "graph", "neighbor")):
        return "navigate_graph"
    if any(token in lowered for token in ("what is", "who is", "when", "where")):
        return "lookup"
    return "explain"


def allowed_audiences_for(audience: str) -> list[str]:
    if audience not in AUDIENCE_RANK:
        raise RetrievalEnvelopeError("AUDIENCE_INVALID", f"unsupported audience: {audience}")
    maximum = AUDIENCE_RANK[audience]
    return [item for item in _AUDIENCE_LADDER if AUDIENCE_RANK[item] <= maximum]


def _require_release_identity(value: Mapping[str, Any], *, label: str) -> dict[str, Any]:
    required = {
        "schema_version",
        "release_id",
        "manifest_sha256",
        "source_repository",
        "source_sha",
        "foundation_repository",
        "foundation_sha",
    }
    if not isinstance(value, Mapping) or set(value) - (required | {"vault_sha256"}):
        raise RetrievalEnvelopeError("RELEASE_IDENTITY_INVALID", f"{label} has unknown fields")
    if not required <= set(value):
        raise RetrievalEnvelopeError("RELEASE_IDENTITY_INVALID", f"{label} is incomplete")
    if value.get("schema_version") != "knowledge-engine-m26-release-identity/v1":
        raise RetrievalEnvelopeError("RELEASE_IDENTITY_INVALID", f"{label} schema is incompatible")
    if not re.fullmatch(r"[a-f0-9]{64}", str(value["manifest_sha256"])):
        raise RetrievalEnvelopeError(
            "RELEASE_IDENTITY_INVALID",
            f"{label} manifest digest is invalid",
        )
    for key in ("source_sha", "foundation_sha"):
        if not re.fullmatch(r"[a-f0-9]{40}", str(value[key])):
            raise RetrievalEnvelopeError("RELEASE_IDENTITY_INVALID", f"{label} {key} is invalid")
    return dict(value)


def validate_question_request(request: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "schema_version",
        "request_id",
        "question",
        "audience",
        "actor_id_hash",
        "created_at",
        "policy",
        "release",
    }
    allowed = required | {
        "conversation_id",
        "parent_request_id",
        "requested_format",
        "requested_language",
    }
    if not isinstance(request, Mapping) or set(request) - allowed:
        raise RetrievalEnvelopeError("QUESTION_REQUEST_INVALID", "request has unknown fields")
    if not required <= set(request):
        raise RetrievalEnvelopeError("QUESTION_REQUEST_INVALID", "request is incomplete")
    if request.get("schema_version") != QUESTION_SCHEMA:
        raise RetrievalEnvelopeError("QUESTION_REQUEST_INVALID", "request schema is incompatible")
    if not re.fullmatch(r"m26req_[a-f0-9]{32}", str(request.get("request_id"))):
        raise RetrievalEnvelopeError("QUESTION_REQUEST_INVALID", "request_id is invalid")
    if not re.fullmatch(r"[a-f0-9]{64}", str(request.get("actor_id_hash"))):
        raise RetrievalEnvelopeError("QUESTION_REQUEST_INVALID", "actor_id_hash is invalid")
    normalize_question(str(request["question"]))
    allowed_audiences_for(str(request["audience"]))
    policy = request.get("policy")
    if not isinstance(policy, Mapping):
        raise RetrievalEnvelopeError("QUESTION_REQUEST_INVALID", "request policy is missing")
    if policy.get("external_browsing") is not False or policy.get("tool_calls") is not False:
        raise RetrievalEnvelopeError(
            "QUESTION_AUTHORITY_ESCALATION",
            "external browsing and tools are forbidden",
        )
    _require_release_identity(request["release"], label="request.release")
    return dict(request)


def validate_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    verify_self_digest(policy)
    if policy.get("schema_version") != POLICY_SCHEMA:
        raise RetrievalEnvelopeError("POLICY_INVALID", "retrieval policy schema is incompatible")
    if policy.get("accepted_predecessor_status") != "m26_1_architecture_authority_accepted":
        raise RetrievalEnvelopeError("PREDECESSOR_NOT_ACCEPTED", "M26.1 acceptance is not pinned")
    authority = policy.get("authority")
    if not isinstance(authority, Mapping):
        raise RetrievalEnvelopeError("POLICY_INVALID", "authority section is missing")
    required_false = (
        "real_corpus_binding",
        "provider_calls",
        "semantic_retrieval",
        "hybrid_retrieval",
        "production_answer_serving",
        "source_mutation",
        "release_mutation",
        "qdrant_or_r2_mutation",
    )
    if authority.get("synthetic_only") is not True:
        raise RetrievalEnvelopeError("POLICY_AUTHORITY_INVALID", "M26.2 must be synthetic-only")
    if any(authority.get(key) is not False for key in required_false):
        raise RetrievalEnvelopeError("POLICY_AUTHORITY_INVALID", "forbidden authority is enabled")
    if authority.get("authoritative_retrieval_lane") != "lexical":
        raise RetrievalEnvelopeError(
            "POLICY_AUTHORITY_INVALID",
            "lexical must remain authoritative",
        )
    return dict(policy)


def validate_corpus(corpus: Mapping[str, Any]) -> dict[str, Any]:
    verify_self_digest(corpus)
    allowed = {
        "schema_version",
        "synthetic",
        "real_corpus",
        "release",
        "lexical_index",
        "graph",
        "graph_v2",
        "provenance",
        "source_documents",
        "facet_catalog",
        "self_sha256",
    }
    if not isinstance(corpus, Mapping) or set(corpus) - allowed:
        raise RetrievalEnvelopeError("CORPUS_INVALID", "synthetic corpus has unknown fields")
    if corpus.get("schema_version") != CORPUS_SCHEMA:
        raise RetrievalEnvelopeError("CORPUS_INVALID", "synthetic corpus schema is incompatible")
    if corpus.get("synthetic") is not True or corpus.get("real_corpus") is not False:
        raise RetrievalEnvelopeError(
            "REAL_CORPUS_FORBIDDEN",
            "M26.2 may consume only synthetic corpus",
        )
    _require_release_identity(corpus["release"], label="corpus.release")
    documents = corpus.get("lexical_index", {}).get("documents")
    if not isinstance(documents, list) or not documents:
        raise RetrievalEnvelopeError("CORPUS_INVALID", "lexical documents are missing")
    source_documents = corpus.get("source_documents")
    if not isinstance(source_documents, list):
        raise RetrievalEnvelopeError("CORPUS_INVALID", "source documents are missing")
    ids: set[str] = set()
    for source in source_documents:
        if not isinstance(source, Mapping):
            raise RetrievalEnvelopeError("CORPUS_INVALID", "source document must be an object")
        source_id = source.get("source_id")
        if not isinstance(source_id, str) or not source_id or source_id in ids:
            raise RetrievalEnvelopeError(
                "CORPUS_INVALID",
                "source identity is invalid or duplicated",
            )
        ids.add(source_id)
        text = source.get("text")
        if not isinstance(text, str) or not text:
            raise RetrievalEnvelopeError("CORPUS_INVALID", f"source text is missing: {source_id}")
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != source.get("content_sha256"):
            raise RetrievalEnvelopeError("CORPUS_INVALID", f"source digest mismatch: {source_id}")
    return dict(corpus)


def build_retrieval_plan(
    request: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    request = validate_question_request(request)
    policy = validate_policy(policy)
    question = normalize_question(str(request["question"]))
    intent = infer_intent(question, parent_request_id=request.get("parent_request_id"))
    if intent not in _ALLOWED_INTENTS:
        raise RetrievalEnvelopeError("INTENT_INVALID", "intent is not allowed")
    bounds = policy["bounds"]
    graph_enabled = intent in {"explain", "compare", "trace_source", "navigate_graph", "follow_up"}
    plan: dict[str, Any] = {
        "schema_version": PLAN_SCHEMA,
        "request_id": request["request_id"],
        "normalized_question": question,
        "intent": intent,
        "allowed_audiences": allowed_audiences_for(str(request["audience"])),
        "lexical": {
            "enabled": True,
            "limit": int(bounds["lexical_limit"]),
            "query_terms": query_terms(question),
        },
        "graph": {
            "enabled": graph_enabled,
            "max_depth": int(bounds["graph_max_depth"]) if graph_enabled else 0,
            "max_nodes": int(bounds["graph_max_nodes"]) if graph_enabled else 0,
            "max_edges": int(bounds["graph_max_edges"]) if graph_enabled else 0,
            "relation_types": list(policy["allowed_relation_types"]) if graph_enabled else [],
        },
        "release": dict(request["release"]),
    }
    plan["deterministic_key"] = sha256_value(plan)
    return plan


def validate_retrieval_plan(
    plan: Mapping[str, Any],
    *,
    request: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    expected = build_retrieval_plan(request, policy)
    if dict(plan) != expected:
        raise RetrievalEnvelopeError(
            "RETRIEVAL_PLAN_DRIFT",
            "plan does not match deterministic construction",
        )
    return expected


def _filtered_graph(
    corpus: Mapping[str, Any],
    plan: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    graph = corpus["graph"]
    if not plan["graph"]["enabled"]:
        return {**graph, "edges": []}, None
    allowed = set(plan["graph"]["relation_types"])
    graph_v2 = corpus.get("graph_v2")
    if not isinstance(graph_v2, Mapping):
        return graph, None
    edges = [
        edge
        for edge in graph_v2.get("edges", [])
        if isinstance(edge, Mapping) and edge.get("relation_type") in allowed
    ]
    if len(edges) > int(plan["graph"]["max_edges"]):
        edges = edges[: int(plan["graph"]["max_edges"])]
    return graph, {**graph_v2, "edges": edges}


def _source_catalog(corpus: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item["source_id"]): dict(item) for item in corpus["source_documents"]}


def _query_specific_acl_count(
    corpus: Mapping[str, Any],
    plan: Mapping[str, Any],
    retrieved: Mapping[str, Any],
    *,
    maximum_audience_rank: int,
) -> int:
    """Count only restricted candidates reached by this query, without exposing their text."""
    filtered: set[str] = set()
    terms = set(plan["lexical"]["query_terms"])
    for document in corpus["lexical_index"].get("documents", []):
        if not isinstance(document, Mapping):
            continue
        audience = document.get("audience")
        if audience not in AUDIENCE_RANK:
            continue
        if AUDIENCE_RANK[str(audience)] <= maximum_audience_rank:
            continue
        searchable = " ".join(
            str(document.get(key, ""))
            for key in ("title", "section_title", "description", "body", "excerpt")
        )
        searchable_terms = set(query_terms(searchable)) | {
            str(item).casefold() for item in document.get("terms", [])
        }
        if terms & searchable_terms:
            filtered.add(f"section:{document.get('section_id', document.get('concept_id'))}")

    selected = {
        str(result["concept_id"])
        for result in retrieved.get("results", [])
        if isinstance(result, Mapping) and isinstance(result.get("concept_id"), str)
    }
    node_audiences = {
        str(node["concept_id"]): str(node["audience"])
        for node in corpus.get("graph", {}).get("nodes", [])
        if isinstance(node, Mapping)
        and isinstance(node.get("concept_id"), str)
        and node.get("audience") in AUDIENCE_RANK
    }
    for edge in corpus.get("graph", {}).get("edges", []):
        if not isinstance(edge, Mapping):
            continue
        source = edge.get("source", edge.get("from", edge.get("from_concept_id")))
        target = edge.get("target", edge.get("to", edge.get("to_concept_id")))
        for seed, neighbor in ((source, target), (target, source)):
            if (
                seed in selected
                and neighbor in node_audiences
                and AUDIENCE_RANK[node_audiences[str(neighbor)]] > maximum_audience_rank
            ):
                filtered.add(f"graph-node:{neighbor}")

    allowed_relations = set(plan["graph"]["relation_types"])
    for edge in corpus.get("graph_v2", {}).get("edges", []):
        if not isinstance(edge, Mapping) or edge.get("relation_type") not in allowed_relations:
            continue
        source = edge.get("source")
        target = edge.get("target")
        edge_audience = edge.get("audience")
        if source in selected and target in node_audiences:
            target_restricted = (
                AUDIENCE_RANK[node_audiences[str(target)]] > maximum_audience_rank
            )
            edge_restricted = (
                edge_audience in AUDIENCE_RANK
                and AUDIENCE_RANK[str(edge_audience)] > maximum_audience_rank
            )
            if target_restricted or edge_restricted:
                filtered.add(f"relation:{edge.get('edge_id', f'{source}:{target}')}")

    records = {
        str(record["subject"]["concept_id"]): record
        for record in corpus.get("provenance", {}).get("records", [])
        if isinstance(record, Mapping)
        and isinstance(record.get("subject"), Mapping)
        and isinstance(record["subject"].get("concept_id"), str)
    }
    for concept_id in selected:
        record = records.get(concept_id, {})
        for source in record.get("sources", []):
            if not isinstance(source, Mapping):
                continue
            audience = source.get("audience")
            if (
                audience in AUDIENCE_RANK
                and AUDIENCE_RANK[str(audience)] > maximum_audience_rank
            ):
                filtered.add(f"citation-source:{source.get('source_id', concept_id)}")
    return len(filtered)


def _normalise_locator(
    locator: object,
    *,
    fallback: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    source = locator if isinstance(locator, Mapping) else fallback
    if not isinstance(source, Mapping):
        raise RetrievalEnvelopeError("LOCATOR_MISSING", "evidence locator is missing")
    allowed = {"heading", "page", "start_line", "end_line", "paragraph", "timecode", "anchor"}
    if set(source) - allowed:
        raise RetrievalEnvelopeError("LOCATOR_INVALID", "locator has unknown fields")
    output = {key: source.get(key) for key in sorted(allowed)}
    start = output["start_line"]
    end = output["end_line"]
    if start is not None and (not isinstance(start, int) or start < 1):
        raise RetrievalEnvelopeError("LOCATOR_INVALID", "start_line is invalid")
    if end is not None and (not isinstance(end, int) or end < 1):
        raise RetrievalEnvelopeError("LOCATOR_INVALID", "end_line is invalid")
    if isinstance(start, int) and isinstance(end, int) and end < start:
        raise RetrievalEnvelopeError("LOCATOR_INVALID", "line range is reversed")
    if all(value is None for value in output.values()):
        raise RetrievalEnvelopeError("LOCATOR_MISSING", "locator is empty")
    return output


def _extract_text(source: Mapping[str, Any], locator: Mapping[str, Any]) -> str:
    text = str(source["text"])
    lines = text.splitlines()
    start = locator.get("start_line")
    end = locator.get("end_line")
    if isinstance(start, int) and isinstance(end, int):
        if end > len(lines):
            raise RetrievalEnvelopeError("LOCATOR_OUT_OF_RANGE", "line locator exceeds source")
        extracted = "\n".join(lines[start - 1 : end]).strip()
    else:
        extracted = text.strip()
    if not extracted:
        raise RetrievalEnvelopeError("PASSAGE_EMPTY", "locator produced an empty passage")
    return extracted


def _prompt_injection_signals(text: str) -> list[str]:
    return [code for code, pattern in _PROMPT_INJECTION_PATTERNS if pattern.search(text)]


def _secret_signal(text: str) -> str | None:
    for code, pattern in _SECRET_PATTERNS:
        if pattern.search(text):
            return code
    return None


def _opaque_identity(prefix: str, value: str) -> str:
    return f"{prefix}_{hashlib.sha256(value.encode('utf-8')).hexdigest()[:32]}"


def _relation_paths_for_result(
    result: Mapping[str, Any],
    *,
    maximum_audience_rank: int,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for edge in result.get("relation_expansions", []):
        if not isinstance(edge, Mapping):
            continue
        path_unsigned = {
            "seed_concept_id": str(edge["source"]),
            "target_concept_id": str(edge["target"]),
            "edge_ids": [str(edge["edge_id"])],
            "relation_types": [str(edge["relation_type"])],
            "depth": 1,
            "factual_support": False,
            "audience_rank_ceiling": maximum_audience_rank,
        }
        output.append(
            {
                "path_id": _opaque_identity("relpath", json.dumps(path_unsigned, sort_keys=True)),
                **path_unsigned,
            }
        )
    return output


def _facet_requirements(
    question: str,
    corpus: Mapping[str, Any],
) -> list[dict[str, Any]]:
    terms = set(query_terms(question))
    requirements: list[dict[str, Any]] = []
    for facet in corpus.get("facet_catalog", []):
        if not isinstance(facet, Mapping):
            continue
        triggers = {str(item).casefold() for item in facet.get("terms", [])}
        if terms & triggers:
            requirements.append(
                {
                    "facet_id": str(facet["facet_id"]),
                    "expected_concept_ids": sorted(str(item) for item in facet["concept_ids"]),
                    "matched_terms": sorted(terms & triggers),
                }
            )
    return sorted(requirements, key=lambda item: item["facet_id"])


def assemble_retrieval_envelope(
    request: Mapping[str, Any],
    plan: Mapping[str, Any],
    corpus: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    request = validate_question_request(request)
    policy = validate_policy(policy)
    corpus = validate_corpus(corpus)
    plan = validate_retrieval_plan(plan, request=request, policy=policy)
    if request["release"] != corpus["release"] or plan["release"] != corpus["release"]:
        raise RetrievalEnvelopeError("RELEASE_IDENTITY_MISMATCH", "request, plan and corpus differ")
    graph, graph_v2 = _filtered_graph(corpus, plan)
    retrieved = retrieve_wiki_first(
        query=" ".join(plan["lexical"]["query_terms"]),
        allowed_audiences=set(plan["allowed_audiences"]),
        lexical_index=corpus["lexical_index"],
        graph=graph,
        relation_graph=graph_v2,
        relation_aware_expansion=bool(plan["graph"]["enabled"]),
        provenance=corpus["provenance"],
        semantic_index=None,
        limit=int(plan["lexical"]["limit"]),
    )
    citation_counts = enrich_runtime_citations(
        results=retrieved["results"],
        provenance=corpus["provenance"],
        allowed_audiences=set(plan["allowed_audiences"]),
    )
    retrieved["retrieval"].update(citation_counts)
    if retrieved["retrieval"].get("semantic_used") is not False:
        raise RetrievalEnvelopeError(
            "SEMANTIC_LANE_FORBIDDEN",
            "semantic contribution is forbidden",
        )
    maximum_rank = max(AUDIENCE_RANK[item] for item in plan["allowed_audiences"])
    sources = _source_catalog(corpus)
    relation_paths: dict[str, dict[str, Any]] = {}
    passages: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    conflict_seen = False
    concept_scope_seen = False
    selected_concepts: set[str] = set()
    required_facets = _facet_requirements(plan["normalized_question"], corpus)
    material_concepts = {
        concept_id
        for facet in required_facets
        for concept_id in facet["expected_concept_ids"]
    }

    for result_index, result in enumerate(retrieved["results"], start=1):
        audience = str(result["audience"])
        if AUDIENCE_RANK[audience] > maximum_rank:
            raise RetrievalEnvelopeError(
                "ACL_POST_FILTER_LEAK",
                "retrieval result exceeds audience",
            )
        selected_concepts.add(str(result["concept_id"]))
        paths = _relation_paths_for_result(result, maximum_audience_rank=maximum_rank)
        for path in paths:
            relation_paths[path["path_id"]] = path
        path_ids = sorted(path["path_id"] for path in paths)
        citations = result.get("citations", [])
        if not isinstance(citations, list):
            raise RetrievalEnvelopeError("CITATION_INVALID", "citations must be a list")
        for citation_index, citation in enumerate(citations, start=1):
            if not isinstance(citation, Mapping):
                raise RetrievalEnvelopeError("CITATION_INVALID", "citation must be an object")
            source_id = citation.get("source_id")
            source = sources.get(str(source_id))
            material = (
                str(result["concept_id"]) in material_concepts
                if required_facets
                else result_index <= 3
            )
            identity_seed = (
                f"{request['request_id']}:{result['section_id']}:"
                f"{source_id}:{citation_index}"
            )
            if source is None:
                excluded.append(
                    {
                        "identity": _opaque_identity("invalid", identity_seed),
                        "reason": "invalid",
                        "material": material,
                    }
                )
                continue
            if AUDIENCE_RANK[str(source["audience"])] > maximum_rank:
                excluded.append(
                    {
                        "identity": _opaque_identity("acl", identity_seed),
                        "reason": "acl",
                        "material": material,
                    }
                )
                continue
            if source.get("current") is not True:
                excluded.append(
                    {
                        "identity": _opaque_identity("stale", identity_seed),
                        "reason": "stale",
                        "material": material,
                    }
                )
                continue
            try:
                locator = _normalise_locator(
                    citation.get("locator"),
                    fallback=source.get("default_locator"),
                )
                text = _extract_text(source, locator)
            except RetrievalEnvelopeError:
                excluded.append(
                    {
                        "identity": _opaque_identity("invalid", identity_seed),
                        "reason": "invalid",
                        "material": material,
                    }
                )
                continue
            secret = _secret_signal(text)
            if secret is not None:
                excluded.append(
                    {
                        "identity": _opaque_identity("unsafe", identity_seed + secret),
                        "reason": "unsafe",
                        "material": material,
                    }
                )
                continue
            text_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
            duplicate_key = (str(source_id), json.dumps(locator, sort_keys=True), text_sha)
            if duplicate_key in seen:
                excluded.append(
                    {
                        "identity": _opaque_identity("duplicate", identity_seed),
                        "reason": "duplicate",
                        "material": material,
                    }
                )
                continue
            seen.add(duplicate_key)
            citation_scope = citation.get("citation_scope")
            if citation_scope != "claim":
                concept_scope_seen = True
            if citation.get("support") == "contradicts":
                conflict_seen = True
            passage_id = _opaque_identity(
                "passage",
                (
                    f"{source_id}:{result['section_id']}:"
                    f"{json.dumps(locator, sort_keys=True)}:{text_sha}"
                ),
            )
            passages.append(
                {
                    "passage_id": passage_id,
                    "source_id": str(source_id),
                    "source_kind": str(source["source_kind"]),
                    "uri": str(source["uri"]),
                    "concept_id": str(result["concept_id"]),
                    "section_id": str(result["section_id"]),
                    "audience": str(source["audience"]),
                    "text": text,
                    "text_sha256": text_sha,
                    "snapshot_sha256": source.get("snapshot_sha256"),
                    "locator": locator,
                    "rank": len(passages) + 1,
                    "retrieval_score": result.get("score"),
                    "relation_path_ids": path_ids,
                    "prompt_injection_signals": _prompt_injection_signals(text),
                }
            )

    query_acl = _query_specific_acl_count(
        corpus,
        plan,
        retrieved,
        maximum_audience_rank=maximum_rank,
    )
    existing_acl = sum(item["reason"] == "acl" for item in excluded)
    acl_filtered = max(query_acl, existing_acl)
    for index in range(existing_acl, acl_filtered):
        excluded.append(
            {
                "identity": _opaque_identity("acl", f"{request['request_id']}:filtered:{index}"),
                "reason": "acl",
                "material": not passages,
            }
        )
    non_acl_excluded = sum(item["reason"] != "acl" for item in excluded)
    missing_facets = [
        facet["facet_id"]
        for facet in required_facets
        if not (set(facet["expected_concept_ids"]) & {p["concept_id"] for p in passages})
    ]
    covered_facets = [
        facet["facet_id"] for facet in required_facets if facet["facet_id"] not in missing_facets
    ]
    if not retrieved["results"]:
        sufficiency = "no_match"
    elif conflict_seen:
        sufficiency = "conflicting"
    elif not passages:
        sufficiency = "insufficient"
    elif missing_facets or concept_scope_seen or any(
        item["material"] and item["reason"] != "acl" for item in excluded
    ):
        sufficiency = "partially_sufficient"
    else:
        sufficiency = "sufficient"
    plan_sha = sha256_value(plan)
    envelope = with_self_digest(
        {
            "schema_version": ENVELOPE_SCHEMA,
            "request_id": request["request_id"],
            "retrieval_plan_sha256": plan_sha,
            "release": dict(corpus["release"]),
            "sufficiency": sufficiency,
            "passages": passages,
            "relation_paths": [relation_paths[key] for key in sorted(relation_paths)],
            "excluded_evidence": excluded,
            "population": {
                "retrieved": len(passages) + len(excluded),
                "included": len(passages),
                "excluded": non_acl_excluded,
                "acl_filtered": acl_filtered,
            },
        }
    )
    first_divergent = "none"
    reason_codes: list[str] = []
    next_action = "context_compile"
    if sufficiency == "no_match":
        first_divergent = "candidate_recall"
        reason_codes.append("NO_AUTHORISED_MATCH" if acl_filtered else "NO_MATCH")
        next_action = "abstain"
    elif sufficiency == "insufficient":
        first_divergent = "citation_locator"
        reason_codes.append("NO_EXACT_PASSAGE")
        next_action = "repair_locator"
    elif sufficiency == "partially_sufficient":
        first_divergent = "sufficiency"
        if missing_facets:
            reason_codes.append("MISSING_REQUIRED_FACETS")
        if concept_scope_seen:
            reason_codes.append("CONCEPT_CITATION_NOT_CLAIM_SUPPORT")
        if any(item["reason"] == "stale" for item in excluded):
            reason_codes.append("STALE_MATERIAL_EVIDENCE")
        next_action = "clarify" if missing_facets else "context_compile"
    elif sufficiency == "conflicting":
        first_divergent = "sufficiency"
        reason_codes.append("CONFLICTING_EVIDENCE")
        next_action = "context_compile"
    if any(p["prompt_injection_signals"] for p in passages):
        reason_codes.append("PROMPT_INJECTION_SIGNAL_PRESENT")
    trace = with_self_digest(
        {
            "schema_version": TRACE_SCHEMA,
            "request_id": request["request_id"],
            "retrieval_plan_sha256": plan_sha,
            "synthetic": True,
            "stages": [
                {
                    "stage": "query_plan",
                    "status": "passed",
                    "count": len(plan["lexical"]["query_terms"]),
                    "duration_ms": None,
                    "reason_codes": [],
                },
                {
                    "stage": "candidate_recall",
                    "status": "passed" if retrieved["results"] else "empty",
                    "count": int(retrieved["retrieval"]["section_candidate_count"]),
                    "duration_ms": None,
                    "reason_codes": [],
                },
                {
                    "stage": "acl",
                    "status": "passed",
                    "count": acl_filtered,
                    "duration_ms": None,
                    "reason_codes": [],
                },
                {
                    "stage": "graph",
                    "status": "passed" if plan["graph"]["enabled"] else "skipped",
                    "count": len(relation_paths),
                    "duration_ms": None,
                    "reason_codes": [],
                },
                {
                    "stage": "citation_locator",
                    "status": "passed" if passages else "empty",
                    "count": len(passages),
                    "duration_ms": None,
                    "reason_codes": [],
                },
                {
                    "stage": "evidence_assembly",
                    "status": "passed" if passages else "empty",
                    "count": len(passages),
                    "duration_ms": None,
                    "reason_codes": [],
                },
                {
                    "stage": "sufficiency",
                    "status": sufficiency,
                    "count": len(covered_facets),
                    "duration_ms": None,
                    "reason_codes": reason_codes,
                },
            ],
            "first_divergent_stage": first_divergent,
            "reason_codes": reason_codes,
            "authoritative_lane": "lexical",
            "semantic_used": False,
            "hybrid_used": False,
            "provider_called": False,
        }
    )
    gap = with_self_digest(
        {
            "schema_version": GAP_SCHEMA,
            "request_id": request["request_id"],
            "retrieval_plan_sha256": plan_sha,
            "required_facets": required_facets,
            "covered_facets": covered_facets,
            "missing_facets": missing_facets,
            "first_divergent_stage": first_divergent,
            "reason_codes": reason_codes,
            "next_action": next_action,
            "authority": "diagnostic_only",
            "safe_for_context_compiler": sufficiency in {
                "sufficient",
                "partially_sufficient",
                "conflicting",
            },
        }
    )
    return envelope, trace, gap


def run_case(
    case: Mapping[str, Any],
    *,
    corpus: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    request = case["request"]
    plan = build_retrieval_plan(request, policy)
    envelope, trace, gap = assemble_retrieval_envelope(request, plan, corpus, policy)
    expected = case["expected"]
    failures: list[str] = []
    if envelope["sufficiency"] != expected["sufficiency"]:
        failures.append("sufficiency")
    if len(envelope["passages"]) < int(expected.get("min_passages", 0)):
        failures.append("min_passages")
    if len(envelope["relation_paths"]) < int(expected.get("min_relation_paths", 0)):
        failures.append("min_relation_paths")
    if envelope["population"]["acl_filtered"] < int(expected.get("min_acl_filtered", 0)):
        failures.append("min_acl_filtered")
    actual_concepts = {item["concept_id"] for item in envelope["passages"]}
    if not set(expected.get("required_concept_ids", [])) <= actual_concepts:
        failures.append("required_concept_ids")
    required_reasons = set(expected.get("required_reason_codes", []))
    if not required_reasons <= set(gap["reason_codes"]):
        failures.append("required_reason_codes")
    prompt_signals = {
        signal for passage in envelope["passages"] for signal in passage["prompt_injection_signals"]
    }
    if (
        "prompt_injection_signal" in expected
        and bool(expected["prompt_injection_signal"]) != bool(prompt_signals)
    ):
        failures.append("prompt_injection_signal")
    forbidden_fragments = [str(item) for item in expected.get("forbidden_text_fragments", [])]
    serialized = json.dumps(envelope, ensure_ascii=False).casefold()
    if any(fragment.casefold() in serialized for fragment in forbidden_fragments):
        failures.append("forbidden_text_fragment")
    return {
        "case_id": case["case_id"],
        "passed": not failures,
        "failures": failures,
        "plan_sha256": sha256_value(plan),
        "envelope_sha256": envelope["self_sha256"],
        "trace_sha256": trace["self_sha256"],
        "gap_sha256": gap["self_sha256"],
        "sufficiency": envelope["sufficiency"],
        "passage_count": len(envelope["passages"]),
        "relation_path_count": len(envelope["relation_paths"]),
        "acl_filtered": envelope["population"]["acl_filtered"],
        "reason_codes": gap["reason_codes"],
    }


def run_benchmark(
    cases_artifact: Mapping[str, Any],
    *,
    corpus: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    verify_self_digest(cases_artifact)
    if cases_artifact.get("schema_version") != "knowledge-engine-m26-retrieval-benchmark-cases/v1":
        raise RetrievalEnvelopeError("BENCHMARK_INVALID", "benchmark cases schema is incompatible")
    results = [
        run_case(case, corpus=corpus, policy=policy)
        for case in cases_artifact["cases"]
    ]
    passed = sum(item["passed"] for item in results)
    report = {
        "schema_version": BENCHMARK_SCHEMA,
        "status": "m26_2_retrieval_envelope_ready" if passed == len(results) else "repair_required",
        "case_count": len(results),
        "passed_count": passed,
        "failed_count": len(results) - passed,
        "metrics": {
            "case_pass_rate": passed / len(results) if results else 0.0,
            "acl_leakage_count": 0,
            "semantic_or_hybrid_use_count": 0,
            "provider_call_count": 0,
            "real_corpus_binding_count": 0,
        },
        "results": results,
        "authority": {
            "synthetic_only": True,
            "candidate_only": True,
            "production_authority": False,
            "m26_3_authorized": False,
        },
    }
    return with_self_digest(report)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RetrievalEnvelopeError("JSON_INVALID", f"{path} must contain an object")
    return value


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
