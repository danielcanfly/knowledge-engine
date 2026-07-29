from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from knowledge_engine.m26_verified_answer_citation_gate import (
    canonical_sha256,
    sha256_bytes,
    verify_provider_output,
)

POPULATION_PATH = Path("pilot/m26/m26-pa-5-frozen-population.json")
LEXICAL_PATH = Path("pilot/m24/canonical-release/artifacts/lexical-index.json")
PROVENANCE_PATH = Path("pilot/m24/canonical-release/artifacts/provenance.json")
GRAPH_PATH = Path("pilot/m24/canonical-release/artifacts/graph-v2.json")
POPULATION_SHA256 = "101fb166147195013ede721c68ac2dc2cef9445865436c8cf130a0dd2addd580"
STRATA = (
    "direct_grounded_factual",
    "provenance_and_source_trace",
    "cross_document_comparison",
    "graph_navigation",
    "conflict_and_temporal_freshness",
    "abstention_no_answer",
    "prompt_injection_privacy_adversarial",
)
RELATIONS = ("contrasts_with", "complements", "overlaps", "insufficient_basis")
ABSTENTION_CODES = (
    "NO_ANSWER_IN_ACCEPTED_ARTIFACT",
    "PROMPT_INJECTION_OR_PRIVACY_BOUNDARY",
    "UNRESOLVED_CONFLICT",
    "STALE_TEMPORAL_EVIDENCE",
    "INSUFFICIENT_SUPPORT",
)
PA4_POLICY = {
    "verification": {"max_claims_per_item": 2},
    "budget": {"max_repair_attempts": 1},
}


class PA5V8Error(ValueError):
    pass


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PA5V8Error(f"{path} must contain an object")
    return value


def _sentence(text: str) -> str:
    text = " ".join(text.split())
    if not text:
        raise PA5V8Error("empty evidence")
    match = re.search(r"(?<=[.!?])\s+", text)
    candidate = text[: match.start()] if match else text
    return candidate[:512].strip()


def _span_id(question_id: str, evidence_id: str, text: str) -> str:
    return "span_" + canonical_sha256(
        {
            "question_id": question_id,
            "evidence_id": evidence_id,
            "text_sha256": sha256_bytes(text.encode()),
        }
    )[:24]


def _locator_id(question_id: str, identity: Mapping[str, Any], evidence_id: str) -> str:
    return "loc_" + canonical_sha256(
        {"question_id": question_id, "identity": dict(identity), "evidence_id": evidence_id}
    )[:24]


def _evidence(
    *,
    question: Mapping[str, Any],
    identity: Mapping[str, Any],
    evidence_id: str,
    text: str,
    source_id: str,
    section_id: str,
) -> dict[str, Any]:
    text = _sentence(text)
    text_sha256 = sha256_bytes(text.encode("utf-8"))
    return {
        "evidence_id": evidence_id,
        "span_id": _span_id(str(question["question_id"]), evidence_id, text),
        "span_text": text,
        "span_text_sha256": text_sha256,
        "locator": {
            "locator_id": _locator_id(str(question["question_id"]), identity, evidence_id),
            "source_id": source_id,
            "section_id": section_id,
            "text_sha256": text_sha256,
            "artifact_key": str(identity["artifact_path"]),
            "artifact_sha256": str(identity["artifact_sha256"]),
            "release_id": str(identity["release_id"]),
        },
    }


def compile_grounding_plans(root: Path) -> list[dict[str, Any]]:
    population = _load(root / POPULATION_PATH)
    if population.get("population_sha256") != POPULATION_SHA256:
        raise PA5V8Error("frozen population digest drift")
    questions = population.get("questions")
    if not isinstance(questions, list) or len(questions) != 200:
        raise PA5V8Error("frozen population denominator drift")

    lexical = _load(root / LEXICAL_PATH)
    provenance = _load(root / PROVENANCE_PATH)
    graph = _load(root / GRAPH_PATH)
    sections = {str(x["section_id"]): x for x in lexical["documents"]}
    records = list(provenance["records"])
    edges = {str(x["edge_id"]): x for x in graph["edges"]}
    plans: list[dict[str, Any]] = []

    for question in questions:
        identity = dict(question["construction_source_identity"])
        stratum = str(question["stratum"])
        qid = str(question["question_id"])
        abstention_policy = None
        candidates: list[dict[str, Any]] = []
        relation_enum: list[str] = []

        if stratum == "direct_grounded_factual":
            section = sections.get(str(identity.get("section_id")))
            if section is None:
                raise PA5V8Error(f"{qid}: section does not resolve")
            candidates.append(
                _evidence(
                    question=question,
                    identity=identity,
                    evidence_id="evidence_primary",
                    text=str(section["body"]),
                    source_id=str(identity["concept_id"]),
                    section_id=str(identity["section_id"]),
                )
            )
        elif stratum == "provenance_and_source_trace":
            record = next(
                (
                    r
                    for r in records
                    if str(r.get("synthesis_id", "")) == str(identity.get("synthesis_id", ""))
                    or str(r.get("subject", {}).get("concept_id", ""))
                    == str(identity.get("concept_id", ""))
                ),
                None,
            )
            if record is None:
                raise PA5V8Error(f"{qid}: provenance record does not resolve")
            claim_match = re.search(r'claim "([^"]+)"', str(question["question"]))
            claims = list(record.get("claims", []))
            claim = next(
                (
                    c
                    for c in claims
                    if claim_match and c.get("claim_id") == claim_match.group(1)
                ),
                claims[0] if claims else None,
            )
            if claim is None:
                raise PA5V8Error(f"{qid}: provenance claim does not resolve")
            candidates.append(
                _evidence(
                    question=question,
                    identity=identity,
                    evidence_id=str(claim["claim_id"]),
                    text=str(claim["text"]),
                    source_id=str(identity.get("source_id", identity["concept_id"])),
                    section_id=str(identity.get("provenance_id", identity["concept_id"])),
                )
            )
        elif stratum == "cross_document_comparison":
            left = sections.get(str(identity.get("section_id")))
            right = sections.get(str(identity.get("comparison_section_id")))
            if left is None or right is None:
                raise PA5V8Error(f"{qid}: comparison section does not resolve")
            candidates.extend(
                [
                    _evidence(
                        question=question,
                        identity=identity,
                        evidence_id="evidence_left",
                        text=str(left["body"]),
                        source_id=str(left["concept_id"]),
                        section_id=str(left["section_id"]),
                    ),
                    _evidence(
                        question=question,
                        identity=identity,
                        evidence_id="evidence_right",
                        text=str(right["body"]),
                        source_id=str(right["concept_id"]),
                        section_id=str(right["section_id"]),
                    ),
                ]
            )
            relation_enum = list(RELATIONS)
        elif stratum == "graph_navigation":
            edge = edges.get(str(identity.get("edge_id")))
            if edge is None:
                raise PA5V8Error(f"{qid}: graph edge does not resolve")
            text = (
                f'{edge["source"]} {edge["relation_type"]} {edge["target"]}; '
                f'edge {edge["edge_id"]} has review status {edge["review_status"]}.'
            )
            candidates.append(
                _evidence(
                    question=question,
                    identity=identity,
                    evidence_id=str(edge["edge_id"]),
                    text=text,
                    source_id=str(edge["source"]),
                    section_id=str(edge["edge_id"]),
                )
            )
        elif stratum == "conflict_and_temporal_freshness":
            record = next(
                (
                    r
                    for r in records
                    if str(r.get("subject", {}).get("concept_id", ""))
                    == str(identity.get("concept_id", ""))
                ),
                None,
            )
            if record is None or not record.get("sources"):
                raise PA5V8Error(f"{qid}: temporal provenance does not resolve")
            source = next(
                (
                    s
                    for s in record["sources"]
                    if s.get("source_id") == identity.get("source_id")
                ),
                record["sources"][0],
            )
            origin = source.get("origin_commit", identity.get("source_commit_sha", "unknown"))
            text = (
                f'Source {source["source_id"]} was retrieved at {source["retrieved_at"]} '
                f'from origin commit {origin}; accepted release is {identity["release_id"]}.'
            )
            candidates.append(
                _evidence(
                    question=question,
                    identity=identity,
                    evidence_id=str(source["source_id"]),
                    text=text,
                    source_id=str(source["source_id"]),
                    section_id=str(identity.get("provenance_id", identity["concept_id"])),
                )
            )
        elif stratum == "abstention_no_answer":
            abstention_policy = "NO_ANSWER_IN_ACCEPTED_ARTIFACT"
        elif stratum == "prompt_injection_privacy_adversarial":
            abstention_policy = "PROMPT_INJECTION_OR_PRIVACY_BOUNDARY"
        else:
            raise PA5V8Error(f"{qid}: unknown stratum")

        if abstention_policy is None and not candidates:
            raise PA5V8Error(f"{qid}: answerable plan has no evidence")
        plan = {
            "question_id": qid,
            "question_digest": question["question_digest"],
            "stratum": stratum,
            "adapter": stratum,
            "artifact_identity": identity,
            "candidate_evidence": candidates,
            "allowed_relation_enums": relation_enum,
            "abstention_policy": abstention_policy,
            "max_provider_calls": 2,
            "rendering_rule": "runtime_owned_exact_span",
            "verification_rule": "pa4_exact_span_verified_answer_kernel",
            "plan_sha256": "",
        }
        plan["plan_sha256"] = canonical_sha256({**plan, "plan_sha256": ""})
        validate_grounding_plan(plan)
        plans.append(plan)
    return plans


def validate_grounding_plan(plan: Mapping[str, Any]) -> None:
    qid = str(plan.get("question_id", ""))
    identity = plan.get("artifact_identity")
    candidates = plan.get("candidate_evidence")
    if not qid or not isinstance(identity, Mapping) or not isinstance(candidates, list):
        raise PA5V8Error("grounding plan structure invalid")
    if plan.get("abstention_policy"):
        if candidates:
            raise PA5V8Error(f"{qid}: abstention plan must not carry evidence")
        return
    if not candidates:
        raise PA5V8Error(f"{qid}: answerable grounding plan has no evidence")
    for evidence in candidates:
        if not isinstance(evidence, Mapping):
            raise PA5V8Error(f"{qid}: evidence structure invalid")
        required = ("evidence_id", "span_id", "span_text", "span_text_sha256", "locator")
        if any(key not in evidence for key in required):
            raise PA5V8Error(f"{qid}: evidence field missing")
        evidence_id = str(evidence["evidence_id"])
        text = str(evidence["span_text"])
        text_sha256 = sha256_bytes(text.encode("utf-8"))
        if evidence["span_text_sha256"] != text_sha256:
            raise PA5V8Error(f"{qid}: evidence text digest mismatch")
        if evidence["span_id"] != _span_id(qid, evidence_id, text):
            raise PA5V8Error(f"{qid}: runtime span ID mismatch")
        locator = evidence["locator"]
        if not isinstance(locator, Mapping):
            raise PA5V8Error(f"{qid}: locator structure invalid")
        if locator.get("locator_id") != _locator_id(qid, identity, evidence_id):
            raise PA5V8Error(f"{qid}: canonical locator ID mismatch")
        if locator.get("text_sha256") != text_sha256:
            raise PA5V8Error(f"{qid}: locator text digest mismatch")
        if locator.get("artifact_key") != str(identity.get("artifact_path")):
            raise PA5V8Error(f"{qid}: locator artifact key mismatch")
        if locator.get("artifact_sha256") != str(identity.get("artifact_sha256")):
            raise PA5V8Error(f"{qid}: locator artifact digest mismatch")
        if locator.get("release_id") != str(identity.get("release_id")):
            raise PA5V8Error(f"{qid}: locator release mismatch")


def manifest(plans: list[dict[str, Any]]) -> dict[str, Any]:
    safe_plans = []
    for plan in plans:
        validate_grounding_plan(plan)
        safe = json.loads(json.dumps(plan))
        for evidence in safe["candidate_evidence"]:
            evidence.pop("span_text", None)
        safe_plans.append(safe)
    result = {
        "schema_version": "knowledge-engine-m26-pa-5-v8-grounding-plan-manifest/v1",
        "stage_id": "M26.PA.5",
        "status": "m26_pa_5_v8_full_population_grounding_plans_compiled",
        "population_count": len(plans),
        "population_sha256": POPULATION_SHA256,
        "stratum_counts": dict(Counter(p["stratum"] for p in plans)),
        "plans": safe_plans,
        "raw_evidence_persisted": False,
        "self_sha256": "",
    }
    result["self_sha256"] = canonical_sha256(result)
    return result


def deterministic_calibration_sample(plans: list[dict[str, Any]]) -> dict[str, Any]:
    selected: list[dict[str, Any]] = []
    for stratum in STRATA:
        candidates = sorted(
            (p for p in plans if p["stratum"] == stratum),
            key=lambda p: hashlib.sha256(
                (p["question_id"] + POPULATION_SHA256).encode()
            ).hexdigest(),
        )
        if len(candidates) < 5:
            raise PA5V8Error(f"{stratum}: fewer than five calibration candidates")
        selected.extend(candidates[:5])
    sample = {
        "schema_version": "knowledge-engine-m26-pa-5-v8-calibration-sample/v1",
        "population_sha256": POPULATION_SHA256,
        "count": 35,
        "per_stratum": 5,
        "question_ids": [p["question_id"] for p in selected],
        "self_sha256": "",
    }
    sample["self_sha256"] = canonical_sha256(sample)
    return sample


def provider_selection_contract(plan: Mapping[str, Any]) -> dict[str, Any]:
    validate_grounding_plan(plan)
    return {
        "required_keys": [
            "status",
            "selected_span_ids",
            "selected_evidence_ids",
            "relation",
            "abstention_reason",
        ],
        "status_values": ["select", "abstain"],
        "allowed_span_ids": [e["span_id"] for e in plan["candidate_evidence"]],
        "allowed_evidence_ids": [e["evidence_id"] for e in plan["candidate_evidence"]],
        "allowed_relations": list(plan["allowed_relation_enums"]),
        "allowed_abstention_reasons": list(ABSTENTION_CODES),
        "authoritative_fields_forbidden": [
            "claim_text",
            "locator_id",
            "source_id",
            "section_id",
            "evidence_excerpt",
            "support_verdict",
            "conflict_verdict",
            "temporal_verdict",
            "citation_digest",
        ],
    }


def render_and_verify_selection(
    plan: Mapping[str, Any], selection: Mapping[str, Any]
) -> dict[str, Any]:
    contract = provider_selection_contract(plan)
    if set(contract["authoritative_fields_forbidden"]).intersection(selection):
        raise PA5V8Error("provider authored authoritative citation field")
    status = selection.get("status")
    if plan.get("abstention_policy"):
        if status != "abstain" or selection.get("abstention_reason") != plan["abstention_policy"]:
            raise PA5V8Error("mandatory abstention policy mismatch")
        return {"terminal_status": "safe_abstention", "reason_code": plan["abstention_policy"]}

    evidence_by_span = {e["span_id"]: e for e in plan["candidate_evidence"]}
    selected_span_ids = selection.get("selected_span_ids")
    if status != "select" or not isinstance(selected_span_ids, list) or not selected_span_ids:
        raise PA5V8Error("answerable plan did not select evidence")
    selected = []
    for span_id in selected_span_ids:
        evidence = evidence_by_span.get(str(span_id))
        if evidence is None:
            raise PA5V8Error("selected span ID is not runtime-provided")
        selected.append(evidence)
    selected_evidence_ids = selection.get("selected_evidence_ids")
    if not isinstance(selected_evidence_ids, list) or selected_evidence_ids != [
        e["evidence_id"] for e in selected
    ]:
        raise PA5V8Error("selected evidence IDs do not match selected spans")
    if plan["stratum"] == "cross_document_comparison":
        if len(selected) != 2 or selection.get("relation") not in RELATIONS:
            raise PA5V8Error("comparison requires two spans and an allowed relation")
    else:
        selected = selected[:1]

    verified = []
    for evidence in selected:
        locator = evidence["locator"]
        case = {
            "case_id": plan["question_id"],
            "question": {"text": plan["question_id"]},
            "expected_terminal_policy": "answer_candidate_required",
            "material_claim_type": plan["stratum"],
            "passage_locator": locator,
        }
        provider_object = {
            "status": "draft_candidate",
            "answer_text": "",
            "claims": [
                {
                    "claim_id": evidence["evidence_id"],
                    "claim_text": evidence["span_text"],
                    "citation": {"locator_id": locator["locator_id"]},
                }
            ],
            "reason_codes": [],
        }
        verified.append(
            verify_provider_output(
                case=case,
                passage_text=evidence["span_text"],
                provider_text=json.dumps(provider_object, sort_keys=True),
                policy=PA4_POLICY,
            )
        )
    return {
        "terminal_status": "verified_answer_ready_candidate",
        "question_id": plan["question_id"],
        "selected_span_ids": [e["span_id"] for e in selected],
        "relation": selection.get("relation"),
        "pa4_verified_items": verified,
        "runtime_owned_citations": True,
    }


def non_live_full_population_gate(root: Path) -> dict[str, Any]:
    plans = compile_grounding_plans(root)
    for plan in plans:
        if plan["abstention_policy"]:
            render_and_verify_selection(
                plan,
                {
                    "status": "abstain",
                    "selected_span_ids": [],
                    "selected_evidence_ids": [],
                    "relation": None,
                    "abstention_reason": plan["abstention_policy"],
                },
            )
        else:
            render_and_verify_selection(
                plan,
                {
                    "status": "select",
                    "selected_span_ids": [e["span_id"] for e in plan["candidate_evidence"]],
                    "selected_evidence_ids": [
                        e["evidence_id"] for e in plan["candidate_evidence"]
                    ],
                    "relation": (
                        "contrasts_with"
                        if plan["stratum"] == "cross_document_comparison"
                        else None
                    ),
                    "abstention_reason": None,
                },
            )
    return {
        "status": "m26_pa_5_v8_non_live_full_population_gate_passed",
        "population_count": 200,
        "population_sha256": POPULATION_SHA256,
        "grounding_plan_manifest": manifest(plans),
        "calibration_sample": deterministic_calibration_sample(plans),
        "pa4_kernel_reused": True,
        "provider_calls": 0,
        "raw_evidence_persisted": False,
    }


def main() -> None:
    result = non_live_full_population_gate(Path("."))
    print(
        json.dumps(
            {
                "status": result["status"],
                "population_count": result["population_count"],
                "population_sha256": result["population_sha256"],
                "grounding_plan_manifest_sha256": result["grounding_plan_manifest"][
                    "self_sha256"
                ],
                "calibration_sample_sha256": result["calibration_sample"]["self_sha256"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
