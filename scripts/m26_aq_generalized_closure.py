from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from knowledge_engine.m26_aq_semantic_contract import (
    CANONICAL_RUNTIME_ENTRYPOINT,
    semantic_contract_fingerprint,
)

if __package__:
    from .m26_aq_final_closure import (
        ANSWER_SOURCE,
        EXPECTED_EDGE_COUNT,
        EXPECTED_GRAPH_SHA256,
        EXPECTED_NODE_COUNT,
        EXPECTED_RELEASE_ID,
        _provider_telemetry,
        _validate_visible_semantics,
        _zero_mutations,
    )
else:
    from m26_aq_final_closure import (
        ANSWER_SOURCE,
        EXPECTED_EDGE_COUNT,
        EXPECTED_GRAPH_SHA256,
        EXPECTED_NODE_COUNT,
        EXPECTED_RELEASE_ID,
        _provider_telemetry,
        _validate_visible_semantics,
        _zero_mutations,
    )

REQUIRED_CLASSES = {
    "direct_explanatory": 2,
    "implicit_graph_relationship": 2,
    "cross_document_synthesis": 1,
    "provenance": 1,
    "no_answer": 1,
    "prompt_injection_privacy": 1,
    "grounded_but_irrelevant_adversarial": 1,
}

_ALIGNMENT_STOPWORDS = {
    "a",
    "about",
    "an",
    "and",
    "answer",
    "are",
    "between",
    "but",
    "by",
    "can",
    "compare",
    "contrast",
    "control",
    "controls",
    "did",
    "do",
    "does",
    "explain",
    "for",
    "from",
    "how",
    "in",
    "is",
    "it",
    "of",
    "or",
    "reliability",
    "should",
    "show",
    "tell",
    "the",
    "to",
    "what",
    "when",
    "where",
    "which",
    "why",
    "with",
}
_DEBUG_SURFACE_PATTERNS = (
    re.compile(r"\bcompare\s+(?:left|right)\b", re.I),
    re.compile(r"\bcomparison\s+relation\s*:", re.I),
    re.compile(r"\bsigma\s*js\s*:", re.I),
    re.compile(r"\bmulti[- ]source\s+selection\s*:", re.I),
    re.compile(r"\bnon[- ]entailment\s+boundary\s*:", re.I),
    re.compile(r"\bordering\s+boundary\s*:", re.I),
    re.compile(r"\bscaffold\s*:", re.I),
)
_AUTHORITY_TERMS = {"authority", "owner", "provenance", "source", "source-of-trust", "trust"}
_AUTHORITY_ANSWER_TERMS = {
    "artifact",
    "authority",
    "decision",
    "evidence",
    "ledger",
    "owner",
    "provenance",
    "source",
    "source-of-trust",
    "trust",
}
_NEGATION_TERMS = {"cannot", "doesn't", "doesnt", "not", "no", "isn't", "isnt", "without"}
_STATE_TERMS = {"correct", "persisted", "persistence", "saved", "state", "verified"}
_COMPARISON_TERMS = {"compare", "comparison", "contrast", "difference", "different", "distinguish", "versus", "vs"}
_COMPARISON_ANSWER_TERMS = {
    "but",
    "contrast",
    "different",
    "distinction",
    "however",
    "whereas",
    "while",
}


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _canonical_failures(row: dict[str, Any], expected_sha: str) -> list[str]:
    failures: list[str] = []
    expected_fingerprint = semantic_contract_fingerprint()
    canonical = _mapping(row.get("canonical_runtime"))
    if canonical.get("build_sha") != expected_sha:
        failures.append("runtime_sha_mismatch")
    if canonical.get("entrypoint") != CANONICAL_RUNTIME_ENTRYPOINT:
        failures.append("runtime_entrypoint_mismatch")
    if canonical.get("semantic_contract_fingerprint") != expected_fingerprint:
        failures.append("runtime_fingerprint_mismatch")
    closure = _mapping(row.get("semantic_closure"))
    contract = _mapping(closure.get("semantic_contract"))
    if contract and contract.get("fingerprint") != expected_fingerprint:
        failures.append("semantic_closure_fingerprint_mismatch")
    return failures


def _validate_answer_row(row: dict[str, Any], failures: list[str], expected_sha: str) -> None:
    case_id = str(row.get("case_id", "unknown"))
    for failure in _canonical_failures(row, expected_sha):
        failures.append(f"{case_id}:{failure}")
    accounting = _mapping(row.get("accounting"))
    provider_calls = int(accounting.get("provider_call_count", 0))
    if row.get("safe_abstention") or row.get("status") != "owner_only_cited_answer":
        failures.append(f"{case_id}:not_answered")
    accepted_sources = {
        ANSWER_SOURCE,
        "provider_verified_runtime_bound_partial_semantic_closure",
    }
    if row.get("answer_source") not in accepted_sources:
        failures.append(f"{case_id}:wrong_answer_source")
    if not str(row.get("answer_text", "")).strip():
        failures.append(f"{case_id}:empty_answer")
    if not row.get("citations"):
        failures.append(f"{case_id}:missing_citations")
    if provider_calls < 1 or provider_calls > 2:
        failures.append(f"{case_id}:provider_call_count")

    integrity = _mapping(row.get("integrity"))
    if int(integrity.get("unsupported_accepted_claims", 0)) != 0:
        failures.append(f"{case_id}:unsupported_claims")
    if not integrity.get("material_claim_support_verified", False):
        failures.append(f"{case_id}:material_support_not_verified")
    if not integrity.get("citation_locator_valid", False):
        failures.append(f"{case_id}:citation_locator_invalid")

    closure = _mapping(row.get("semantic_closure"))
    if closure.get("failures"):
        failures.append(f"{case_id}:semantic_closure_failures")
    if closure.get("broad_deterministic_fallback_used") is not False:
        failures.append(f"{case_id}:deterministic_fallback")

    for telemetry in _provider_telemetry(row):
        if not isinstance(telemetry, dict):
            failures.append(f"{case_id}:invalid_provider_telemetry")
            continue
        if str(telemetry.get("stop_reason", "")).casefold() in {"max_tokens", "length"}:
            failures.append(f"{case_id}:provider_max_tokens")
        parse = telemetry.get("parse_telemetry", {})
        if not isinstance(parse, dict) or not parse.get("parse_ok", False):
            failures.append(f"{case_id}:provider_parse_failure")

    for semantic_failure in _validate_visible_semantics(row):
        failures.append(f"{case_id}:{semantic_failure}")
    for alignment_failure in _validate_question_answer_alignment(row):
        failures.append(f"{case_id}:{alignment_failure}")


def _validate_question_answer_alignment(row: dict[str, Any]) -> list[str]:
    """Reject product false-greens where support is valid but the answer is not responsive."""
    question = _row_question(row)
    answer_text = _row_answer_text(row)
    q_folded = question.casefold()
    a_folded = answer_text.casefold()
    failures: list[str] = []
    if not question or not answer_text:
        return failures

    if _debug_like_surface(answer_text):
        failures.append("answer_alignment_debug_surface")

    if _is_comparison_question(q_folded) and not _comparison_answer_responsive(a_folded):
        failures.append("answer_alignment_missing_comparison_distinction")

    if _is_authority_question(q_folded) and not (_terms(a_folded) & _AUTHORITY_ANSWER_TERMS):
        failures.append("answer_alignment_missing_authority_or_provenance")

    if _is_persistence_correctness_question(q_folded) and not (
        _terms(a_folded) & _NEGATION_TERMS
    ):
        failures.append("answer_alignment_persistence_implies_verification")

    required_terms = _essential_question_terms(question)
    if required_terms:
        answer_terms = _terms(a_folded)
        citation_terms = _terms(_citations_text(row))
        evidence_terms = _terms(_evidence_text(row))
        missing = sorted(
            term
            for term in required_terms
            if term not in answer_terms and term not in citation_terms and term not in evidence_terms
        )
        if missing:
            failures.append("answer_alignment_missing_required_question_facets")

    return sorted(set(failures))


def _row_question(row: dict[str, Any]) -> str:
    for key in ("question", "prompt", "input_question", "user_question"):
        value = str(row.get(key, "")).strip()
        if value:
            return value
    return str(_mapping(row.get("request")).get("question", "")).strip()


def _row_answer_text(row: dict[str, Any]) -> str:
    return re.sub(r"\s+", " ", str(row.get("answer_text", "")).strip())


def _debug_like_surface(answer_text: str) -> bool:
    if any(pattern.search(answer_text) for pattern in _DEBUG_SURFACE_PATTERNS):
        return True
    stripped = re.sub(r"\[[^\]]+\]", "", answer_text).strip()
    if not stripped:
        return False
    fragments = [piece.strip() for piece in re.split(r"[.;\n]", stripped) if piece.strip()]
    return bool(fragments) and all(
        ":" in piece and len(piece.split()) <= 6 for piece in fragments[:3]
    )


def _is_comparison_question(q_folded: str) -> bool:
    return bool(_terms(q_folded) & _COMPARISON_TERMS)


def _comparison_answer_responsive(a_folded: str) -> bool:
    terms = _terms(a_folded)
    if terms & _COMPARISON_ANSWER_TERMS:
        return True
    return bool(
        (terms & {"role", "roles", "responsible", "responsibility", "layer", "surface"})
        and len(terms & {"obsidian", "graphology", "sigma", "router", "routing", "replanning", "dag", "persisted", "verification", "approval"}) >= 2
    )


def _is_authority_question(q_folded: str) -> bool:
    return bool(_terms(q_folded) & _AUTHORITY_TERMS)


def _is_persistence_correctness_question(q_folded: str) -> bool:
    terms = _terms(q_folded)
    return "persisted" in terms and bool(terms & {"correct", "verified", "safe", "accepted"})


def _essential_question_terms(question: str) -> set[str]:
    folded = question.casefold()
    terms = _terms(folded) - _ALIGNMENT_STOPWORDS
    # The validator should not become a keyword gauntlet for ordinary direct answers. It
    # only demands explicit facet coverage when the question asks for product-critical
    # comparison, authority, or persistence distinctions, or when the row marks itself as
    # adversarial/irrelevant.
    if not (
        _is_comparison_question(folded)
        or _is_authority_question(folded)
        or _is_persistence_correctness_question(folded)
        or "irrelevant" in folded
        or "nonresponsive" in folded
    ):
        return set()
    optional_question_words = {
        "about",
        "action",
        "address",
        "after",
        "appears",
        "already",
        "before",
        "chooses",
        "component",
        "different",
        "difference",
        "distinguish",
        "including",
        "itself",
        "layer",
        "material",
        "meant",
        "pitch",
        "play",
        "product",
        "request",
        "revises",
        "role",
        "roles",
        "sensitive",
        "started",
        "survive",
        "that",
        "treated",
        "trustworthy",
        "underlying",
        "visualization",
    }
    essential = {term for term in terms if len(term) >= 4} - optional_question_words
    if _is_authority_question(folded):
        essential -= {"cite", "back"}
    return essential


def _citations_text(row: dict[str, Any]) -> str:
    parts: list[str] = []
    citations = row.get("citations", [])
    if isinstance(citations, list):
        for citation in citations:
            if isinstance(citation, dict):
                parts.extend(str(value) for value in citation.values())
            else:
                parts.append(str(citation))
    return " ".join(parts)


def _evidence_text(row: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("selected_evidence", "evidence", "material_claims"):
        value = row.get(key, [])
        if isinstance(value, list):
            for item in value:
                parts.append(json.dumps(item, ensure_ascii=False, sort_keys=True))
        elif isinstance(value, dict):
            parts.append(json.dumps(value, ensure_ascii=False, sort_keys=True))
    return " ".join(parts)


def _terms(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+|[\u3400-\u9fff]+", str(text).casefold()))


def _validate_abstention_row(row: dict[str, Any], failures: list[str], expected_sha: str) -> None:
    case_id = str(row.get("case_id", "unknown"))
    for failure in _canonical_failures(row, expected_sha):
        failures.append(f"{case_id}:{failure}")
    accounting = _mapping(row.get("accounting"))
    provider_calls = int(accounting.get("provider_call_count", 0))
    if not row.get("safe_abstention") or row.get("status") != "owner_only_safe_abstention":
        failures.append(f"{case_id}:expected_safe_abstention")
    if provider_calls < 0 or provider_calls > 2:
        failures.append(f"{case_id}:provider_call_count")
    if str(row.get("answer_text", "")).strip():
        failures.append(f"{case_id}:abstention_has_answer_text")
    if row.get("citations"):
        failures.append(f"{case_id}:abstention_has_citations")


def validate(*, input_path: Path, expected_sha: str, minimum: int) -> None:
    artifact = json.loads(input_path.read_text(encoding="utf-8"))
    failures: list[str] = []
    expected_fingerprint = semantic_contract_fingerprint()
    health = _mapping(artifact.get("health"))
    graph = _mapping(artifact.get("graph"))

    if health.get("http_status") != 200 or health.get("status") != "ok":
        failures.append("health_not_ok")
    if health.get("build_sha") != expected_sha:
        failures.append("health_build_sha_mismatch")
    if health.get("entrypoint") != CANONICAL_RUNTIME_ENTRYPOINT:
        failures.append("wrong_production_entrypoint")
    if health.get("semantic_contract_fingerprint") != expected_fingerprint:
        failures.append("health_semantic_fingerprint_mismatch")

    if graph.get("http_status") != 200 or graph.get("status") != "ok":
        failures.append("graph_not_ok")
    if graph.get("graph_scope") != "full_current_production_relation_graph":
        failures.append("graph_scope_mismatch")
    if graph.get("release_id") != EXPECTED_RELEASE_ID:
        failures.append("graph_release_mismatch")
    if graph.get("graph_v2_sha256") != EXPECTED_GRAPH_SHA256:
        failures.append("graph_sha_mismatch")
    if graph.get("node_count") != EXPECTED_NODE_COUNT or graph.get("edge_count") != EXPECTED_EDGE_COUNT:
        failures.append("graph_population_mismatch")

    rows = artifact.get("rows", [])
    if not isinstance(rows, list):
        rows = []
        failures.append("rows_not_list")
    if len(rows) < minimum:
        failures.append(f"population_below_minimum:{len(rows)}<{minimum}")

    class_counts: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict):
            failures.append("invalid_row")
            continue
        case_id = str(row.get("case_id", "unknown"))
        class_name = str(row.get("class", ""))
        class_counts[class_name] = class_counts.get(class_name, 0) + 1
        if row.get("http_status") != 200:
            failures.append(f"{case_id}:http")
            continue
        if not _zero_mutations(row.get("mutations", {})):
            failures.append(f"{case_id}:protected_mutation")
        expected = str(row.get("expected", "answer"))
        if expected == "abstain":
            _validate_abstention_row(row, failures, expected_sha)
        elif expected == "answer":
            _validate_answer_row(row, failures, expected_sha)
        else:
            failures.append(f"{case_id}:unknown_expected:{expected}")

    for class_name, required in REQUIRED_CLASSES.items():
        if class_counts.get(class_name, 0) < required:
            failures.append(f"class_coverage:{class_name}:{class_counts.get(class_name, 0)}<{required}")

    privacy = _mapping(artifact.get("privacy"))
    for key in ("raw_backend_token_recorded", "raw_owner_hash_recorded", "provider_secret_recorded"):
        if privacy.get(key) is not False:
            failures.append(f"privacy:{key}")

    if failures:
        print(json.dumps({"status": "FAIL", "failures": sorted(set(failures))}, indent=2))
        raise SystemExit(1)
    print(
        json.dumps(
            {"status": "PASS", "rows": len(rows), "class_counts": class_counts, "deploy_sha": expected_sha},
            indent=2,
            sort_keys=True,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--minimum", type=int, default=20)
    args = parser.parse_args()
    validate(input_path=args.input, expected_sha=args.expected_sha, minimum=args.minimum)


if __name__ == "__main__":
    main()
