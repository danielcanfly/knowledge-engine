from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
SOURCE_BANK = REPO / "evals" / "m26_broad_semantic"
LEXICAL_INDEX = REPO / "pilot" / "m24" / "canonical-release" / "artifacts" / "lexical-index.json"
PROVENANCE = REPO / "pilot" / "m24" / "canonical-release" / "artifacts" / "provenance.json"
GRAPH = REPO / "pilot" / "m24" / "canonical-release" / "artifacts" / "graph-v2.json"
R2F_EVIDENCE = REPO / "M26_R2F_INTERNAL_VERIFIER_FAILURE_DECOMPOSITION_CODEX_RETURN_v1_2026-08-29" / "raw" / "evidence_payloads.json"
R2K_CITATION = REPO / "r2l_refs_20260830" / "R2K" / "raw" / "citation_support_sources.json"

RUNTIME_CANDIDATE_SHA = "8942859bbe3491de084dda09326fe03fec82989f"
REQUIRED_PROP_ID = "{case_id}-PROP01"
GOLD_MODE_EXTRACTIVE = "extractive"
GOLD_MODE_STRUCTURAL = "structural"
GOLD_MODE_SENTINEL_SYNTHESIS = "sentinel_synthesis"
GOLD_MODE_CONTEXT_ONLY = "context_only"
CONTEXT_SUPPORT_ROLES = {"context", "negative_distractor"}

PRIMARY_ONLY_NEW = [
    ("BROAD-0001", "R2O-PG-P063"),
    ("BROAD-0002", "R2O-PG-P064"),
    ("BROAD-0004", "R2O-PG-P065"),
    ("BROAD-0005", "R2O-PG-P066"),
    ("BROAD-0007", "R2O-PG-P067"),
    ("BROAD-0011", "R2O-PG-P068"),
    ("BROAD-0015", "R2O-PG-P069"),
    ("BROAD-0031", "R2O-PG-P070"),
    ("BROAD-0032", "R2O-PG-P071"),
    ("BROAD-0061", "R2O-PG-P072"),
]

HOLDOUT_FIXUPS = [
    ("BROAD-0067", "R2O-PG-H029", "role_responsibility", "concepts/steering-control-plane#steering-control-plane"),
    ("BROAD-0068", "R2O-PG-H030", "causal_why", "concepts/goal-drift#control"),
    ("BROAD-0071", "R2O-PG-H031", "trade_offs", "concepts/tool-call-proposal#authority"),
]

HOLDOUT_ADDITIONS = [
    ("R2O-PG-H032", "impact_effect", "BROAD-0065", "concepts/completion-gate#gate-behavior"),
    ("R2O-PG-H033", "examples", "BROAD-0066", "concepts/goal-drift#signals"),
    ("R2O-PG-H034", "architecture_components", "BROAD-0069", "concepts/agent-execution-paths#controls-shared-by-every-structure"),
    ("R2O-PG-H035", "capability_skill_requirement", "BROAD-0070", "concepts/harnessability#assessment"),
    ("R2O-PG-H036", "enumerative_list", "BROAD-0072", "concepts/agent-planning-strategies#selection-sequence"),
    ("R2O-PG-H037", "multi_part", "BROAD-0073", "concepts/item-turn-thread-protocol#item-turn-thread-protocol"),
    ("R2O-PG-H038", "broad_synthesis", "BROAD-0074", "concepts/six-dimensional-map-of-llm-agent-architectures#reviewed-synthesis-dec-1f9025c488e9c83356e402ec4f859d11"),
    ("R2O-PG-H039", "narrow_factual", "BROAD-0075", "concepts/durable-thread-state#durable-thread-state"),
    ("R2O-PG-H040", "ambiguous_clarification", "BROAD-0076", "concepts/harnessability#narrowed-scope"),
    ("R2O-PG-H041", "partially_sufficient_evidence", "BROAD-0077", "concepts/request-boundary#request-boundary"),
    ("R2O-PG-H042", "short_query", "BROAD-0078", "concepts/harness#operational-role"),
    ("R2O-PG-H043", "long_compositional_query", "BROAD-0079", "concepts/agent-planning-strategies#plan-and-execute"),
    ("R2O-PG-H044", "temporal_version", "BROAD-0080", "concepts/goal-drift#source-adoption"),
]

SENTINELS = [
    {
        "case_id": "SENTINEL-Q1-A",
        "family": "simple_definition",
        "question": "What kind of skill does a Product Manager need?",
        "support_specs": [
            (
                "daniel_blog_en__pm-product-data-and-experimentation-07",
                "section_62e85bad0c00e0029df3",
                "Exposure rules are not a technical footnote. They are the law of the denominator. Many PMs know they need randomisation. Far fewer treat the exposure rule as a first-class decision. That is risky, because assignment is not the same thing as exposure. Without that layer, a great deal of apparent lift is really stage dressing. A good exposure rule should answer three questions: what is the trigger point, what is the analysis unit, and how do repeated exposures count.",
                "primary",
            ),
            (
                "daniel_blog_en__pm-user-research-fieldwork-01",
                "section_0f428df1d419b40aab43",
                "## Put research back into the PM workflow. Analytics should help you find anomalies, patterns, and segments. Research should help you recover meaning, context, and decision logic. In practice, the flow often looks like this: use analytics to find where the drop is, write down competing hypotheses, decide what can only be separated by listening to users or seeing the work in context, run interviews/field study/diary study/usability session, and feed findings back into tracking, funnel definitions, messaging, and hypotheses.",
                "primary",
            ),
            (
                "daniel_blog_en__pm-product-data-and-experimentation-06",
                "article_19e366642b6399741e71",
                "PM Product Data and Experimentation 06 - Retention, Cohorts, and Segmentation: Knowing Who Stays Matters More Than Watching the Average. A product can look healthier than it really is simply because averages are excellent at cosmetics.",
                "primary",
            ),
            (
                "daniel_blog_en__the-atlas-of-agent-design-patterns-part-8",
                "article_675126909c8a466dabcb",
                "The Atlas of Agent Design Patterns Part 8 | Production Agent Architectures in Practice. A production-focused guide to assembling routing, durable orchestration, tools, verification, state, memory, policy, evaluation, observability, budgets, and human control into RAG, deep-research, coding, browser, enterprise-automation, and monitoring systems.",
                "secondary",
            ),
        ],
        "proposition_text": "A Product Manager needs data-analysis, experimentation, retention, and user-research skills grounded in exposure rules, sessionisation, and interpreting user behavior.",
        "terminal_set": ["verified_answer_ready_candidate", "owner_only_cited_answer"],
    },
    {
        "case_id": "SENTINEL-Q1-B",
        "family": "contextual_definition",
        "question": "What kind of skill does a Product Manager need?",
        "support_specs": [
            (
                "daniel_blog_en__pm-product-data-and-experimentation-05",
                "section_ef280e44c12bb9559b47",
                "## Sessionisation is not a fact of nature. It is a modelling choice. A session is not a naturally occurring object waiting to be discovered. It is a boundary you define so that behaviour can be analysed in a tractable way. Different tools make different choices. GA4 defines a session as a period of user interaction and, by default, times it out after 30 minutes of inactivity. PostHog also groups events into sessions and starts a new one by default after 30 minutes of inactivity or after 24 hours. Cohorts and retention often matter more.",
                "primary",
            ),
            (
                "daniel_blog_en__pm-user-research-fieldwork-01",
                "section_0f428df1d419b40aab43",
                "## Put research back into the PM workflow. Analytics should help you find anomalies, patterns, and segments. Research should help you recover meaning, context, and decision logic. In practice, the flow often looks like this: use analytics to find where the drop is, write down competing hypotheses, decide what can only be separated by listening to users or seeing the work in context, run interviews/field study/diary study/usability session, and feed findings back into tracking, funnel definitions, messaging, and hypotheses.",
                "primary",
            ),
            (
                "daniel_blog_en__pm-product-data-and-experimentation-07",
                "section_62e85bad0c00e0029df3",
                "Exposure rules are not a technical footnote. They are the law of the denominator. Many PMs know they need randomisation. Far fewer treat the exposure rule as a first-class decision. That is risky, because assignment is not the same thing as exposure. Without that layer, a great deal of apparent lift is really stage dressing. A good exposure rule should answer three questions: what is the trigger point, what is the analysis unit, and how do repeated exposures count.",
                "primary",
            ),
            (
                "daniel_blog_en__pm-product-data-and-experimentation-06",
                "article_19e366642b6399741e71",
                "PM Product Data and Experimentation 06 - Retention, Cohorts, and Segmentation: Knowing Who Stays Matters More Than Watching the Average. A product can look healthier than it really is simply because averages are excellent at cosmetics.",
                "primary",
            ),
        ],
        "proposition_text": "A Product Manager needs modeling judgment about sessions, exposure, cohorts, and research-based decision logic.",
        "terminal_set": ["verified_answer_ready_candidate", "owner_only_cited_answer"],
    },
    {
        "case_id": "SENTINEL-Q1-C",
        "family": "role_responsibility",
        "question": "What kind of skill does a Product Manager need?",
        "support_specs": [
            (
                "daniel_blog_en__pm-user-research-fieldwork-01",
                "section_42aebd472af535953afb",
                "## Start with a familiar mistake. Imagine you work on a hotel-booking product. One week, you open the dashboard and notice that Start Booking Rate is broadly flat, but Payment Success Rate has fallen sharply. The same drop in payment completion might mask very different realities; the problem is not a lack of volume, it is that you are assigning too much meaning to the event itself.",
                "primary",
            ),
            (
                "daniel_blog_en__pm-user-research-fieldwork-01",
                "section_0f428df1d419b40aab43",
                "## Put research back into the PM workflow. Analytics should help you find anomalies, patterns, and segments. Research should help you recover meaning, context, and decision logic. In practice, the flow often looks like this: use analytics to find where the drop is, write down competing hypotheses, decide what can only be separated by listening to users or seeing the work in context, run interviews/field study/diary study/usability session, and feed findings back into tracking, funnel definitions, messaging, and hypotheses.",
                "primary",
            ),
            (
                "daniel_blog_en__pm-product-data-and-experimentation-05",
                "section_ef280e44c12bb9559b47",
                "## Sessionisation is not a fact of nature. It is a modelling choice. A session is not a naturally occurring object waiting to be discovered. It is a boundary you define so that behaviour can be analysed in a tractable way. Different tools make different choices. GA4 defines a session as a period of user interaction and, by default, times it out after 30 minutes of inactivity. PostHog also groups events into sessions and starts a new one by default after 30 minutes of inactivity or after 24 hours. Cohorts and retention often matter more.",
                "primary",
            ),
            (
                "daniel_blog_en__pm-product-data-and-experimentation-07",
                "section_62e85bad0c00e0029df3",
                "Exposure rules are not a technical footnote. They are the law of the denominator. Many PMs know they need randomisation. Far fewer treat the exposure rule as a first-class decision. That is risky, because assignment is not the same thing as exposure. Without that layer, a great deal of apparent lift is really stage dressing. A good exposure rule should answer three questions: what is the trigger point, what is the analysis unit, and how do repeated exposures count.",
                "primary",
            ),
        ],
        "proposition_text": "A Product Manager needs to read metrics critically, separate signal from noise, and use research to recover context and decision logic.",
        "terminal_set": ["verified_answer_ready_candidate", "owner_only_cited_answer"],
    },
    {
        "case_id": "SENTINEL-Q2-A",
        "family": "contextual_definition",
        "question": "What is a skill in an AI agent architecture?",
        "support_specs": [
            (
                "daniel_blog_en__harness-theory-part-5",
                "section_23030cd5331ceb4938af",
                "## Separate the terms before selecting the technology Capability systems often fail because the same label means different things across products. Rather than memorising one framework's vocabulary, identify the question each mechanism answers. | Term | The question it answers | Typical content | |---|---|---| | Tool | What specific capability can the agent execute? | `search_documents`, `run_tests`, `send_email` | | Command | Which explicit entry point did a user or system invoke? | `/eval`, a CLI command, an API route | | Skill | What method should the agent follow for this class of task? | SOP, tool order, decision rules, acceptance criteria |",
                "primary",
            ),
            (
                "daniel_blog_en__the-atlas-of-agent-design-patterns-part-9",
                "section_77386dae3ac22a648373",
                "## Architecture selection is a constrained decision. A pattern should be added only when it resolves a real requirement. A production decision should instead ask: What must be true for the task to count as complete? What can change during execution? Which actions have side effects? Which evidence can verify success? Which state must persist? Which failures can be recovered? What limits and authorities apply? The architecture is the set of mechanisms required to answer those questions, not a collection of fashionable labels.",
                "primary",
            ),
            (
                "daniel_blog_en__the-atlas-of-agent-design-patterns-part-8",
                "article_675126909c8a466dabcb",
                "The Atlas of Agent Design Patterns Part 8 | Production Agent Architectures in Practice. A production-focused guide to assembling routing, durable orchestration, tools, verification, state, memory, policy, evaluation, observability, budgets, and human control into RAG, deep-research, coding, browser, enterprise-automation, and monitoring systems.",
                "primary",
            ),
        ],
        "proposition_text": "Skill | What method should the agent follow for this class of task? | SOP, tool order, decision rules, acceptance criteria.",
        "terminal_set": ["verified_answer_ready_candidate", "owner_only_cited_answer"],
    },
    {
        "case_id": "SENTINEL-Q2-B",
        "family": "capability_skill_requirement",
        "question": "What is a skill in an AI agent architecture?",
        "support_specs": [
            (
                "daniel_blog_en__harness-theory-part-5",
                "section_23030cd5331ceb4938af",
                "## Separate the terms before selecting the technology Capability systems often fail because the same label means different things across products. Rather than memorising one framework's vocabulary, identify the question each mechanism answers. | Term | The question it answers | Typical content | |---|---|---| | Tool | What specific capability can the agent execute? | `search_documents`, `run_tests`, `send_email` | | Command | Which explicit entry point did a user or system invoke? | `/eval`, a CLI command, an API route | | Skill | What method should the agent follow for this class of task? | SOP, tool order, decision rules, acceptance criteria |",
                "primary",
            ),
            (
                "daniel_blog_en__the-atlas-of-agent-design-patterns-part-9",
                "section_a9daa08b4350ac258cf2",
                "## Complete example: a blog Ask AI system. Requirement: Users ask questions about blog articles. The system answers from the site articles with citations. It may rewrite a query when retrieval is weak, but it may not browse the open web or retry indefinitely.",
                "primary",
            ),
            (
                "daniel_blog_en__the-atlas-of-agent-design-patterns-part-9",
                "section_77386dae3ac22a648373",
                "## Architecture selection is a constrained decision. A pattern should be added only when it resolves a real requirement. A production decision should instead ask: What must be true for the task to count as complete? What can change during execution? Which actions have side effects? Which evidence can verify success? Which state must persist? Which failures can be recovered? What limits and authorities apply? The architecture is the set of mechanisms required to answer those questions, not a collection of fashionable labels.",
                "primary",
            ),
        ],
        "proposition_text": "Skill | What method should the agent follow for this class of task? | SOP, tool order, decision rules, acceptance criteria.",
        "terminal_set": ["verified_answer_ready_candidate", "owner_only_cited_answer"],
    },
    {
        "case_id": "SENTINEL-Q2-C",
        "family": "narrow_factual",
        "question": "What is a skill in an AI agent architecture?",
        "support_specs": [
            (
                "daniel_blog_en__harness-theory-part-5",
                "section_23030cd5331ceb4938af",
                "## Separate the terms before selecting the technology Capability systems often fail because the same label means different things across products. Rather than memorising one framework's vocabulary, identify the question each mechanism answers. | Term | The question it answers | Typical content | |---|---|---| | Tool | What specific capability can the agent execute? | `search_documents`, `run_tests`, `send_email` | | Command | Which explicit entry point did a user or system invoke? | `/eval`, a CLI command, an API route | | Skill | What method should the agent follow for this class of task? | SOP, tool order, decision rules, acceptance criteria |",
                "primary",
            ),
            (
                "daniel_blog_en__the-atlas-of-agent-design-patterns-part-8",
                "article_675126909c8a466dabcb",
                "The Atlas of Agent Design Patterns Part 8 | Production Agent Architectures in Practice. A production-focused guide to assembling routing, durable orchestration, tools, verification, state, memory, policy, evaluation, observability, budgets, and human control into RAG, deep-research, coding, browser, enterprise-automation, and monitoring systems.",
                "primary",
            ),
        ],
        "proposition_text": "Skill | What method should the agent follow for this class of task? | SOP, tool order, decision rules, acceptance criteria.",
        "terminal_set": ["verified_answer_ready_candidate", "owner_only_cited_answer"],
    },
    {
        "case_id": "SENTINEL-Q3-CONTROL",
        "family": "relationship",
        "question": "What is the role of user research in product management?",
        "support_specs": [
            (
                "daniel_blog_en__pm-user-research-fieldwork-01",
                "section_0f428df1d419b40aab43",
                "## Put research back into the PM workflow. Analytics should help you find anomalies, patterns, and segments. Research should help you recover meaning, context, and decision logic. In practice, the flow often looks like this: use analytics to find where the drop is, write down competing hypotheses, decide what can only be separated by listening to users or seeing the work in context, run interviews/field study/diary study/usability session, and feed findings back into tracking, funnel definitions, messaging, and hypotheses.",
                "primary",
            ),
            (
                "daniel_blog_en__pm-user-research-fieldwork-02",
                "article_109bb7a2e52a5bb76cbf",
                "PM User Research and Fieldwork 02 - Qualitative, Quantitative, and Mixed Methods: PMs Do Not Need a Side, They Need the Right Question. A practical guide to choosing qualitative, quantitative, or mixed methods based on the decision you need to make, not the method you prefer.",
                "context",
            ),
        ],
        "proposition_text": "User research helps product management recover meaning, context, and decision logic that analytics alone cannot provide.",
        "terminal_set": ["verified_answer_ready_candidate", "owner_only_cited_answer"],
    },
]


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def split_source_bank(name: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (SOURCE_BANK / name).read_text().splitlines() if line]


def load_lexical() -> dict[str, dict[str, Any]]:
    obj = load_json(LEXICAL_INDEX)
    return {doc["section_id"]: doc for doc in obj["documents"]}


def load_provenance_map() -> dict[str, dict[str, Any]]:
    obj = load_json(PROVENANCE)
    return {rec["subject"]["concept_id"]: rec for rec in obj["records"]}


def load_graph_map() -> dict[str, dict[str, Any]]:
    obj = load_json(GRAPH)
    return {edge["edge_id"]: edge for edge in obj["edges"]}


def load_r2f_payloads() -> dict[str, Any]:
    return load_json(R2F_EVIDENCE)


def load_r2k_support() -> dict[str, Any]:
    return load_json(R2K_CITATION)


def make_support_id(case_id: str, index: int) -> str:
    return f"{case_id}-SUP{index:02d}"


def concept_id_from_section(section_id: str) -> str:
    return section_id.split("#", 1)[0]


def section_locator(section_id: str) -> str:
    return section_id.rsplit("#", 1)[-1].replace("-", " ").title()


def prop_id_for_case(case_id: str) -> str:
    return REQUIRED_PROP_ID.format(case_id=case_id)


def direct_authority_refs(supports: list[dict[str, Any]], proposition_id: str) -> list[str]:
    return [
        support["support_id"]
        for support in supports
        if proposition_id in support.get("authority_for", [])
    ]


def add_authority(
    support: dict[str, Any],
    proposition_id: str,
    *,
    is_authority: bool = True,
) -> dict[str, Any]:
    support["authority_for"] = [proposition_id] if is_authority else []
    return support


def extractive_certificate(supports: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "extractive_support_ids": [support["support_id"] for support in supports],
        "canonical_source_text": "\n\n".join(
            support["exact_support_snippet"].strip() for support in supports
        ),
    }


def make_forbidden(case_id: str, family: str, question: str, behavior: str) -> list[dict[str, str]]:
    if case_id.startswith("SENTINEL-Q1"):
        text = "Do not contaminate the PM skill answer with agent-architecture or venture claims."
    elif case_id.startswith("SENTINEL-Q2"):
        text = "Do not equate skill with a mechanism, routing step, or unsupported trade-off."
    elif case_id.startswith("SENTINEL-Q3"):
        text = "Do not import agent or RAG infrastructure into the user-research answer."
    elif family == "graph_relationship":
        text = "Do not reverse the edge direction or replace the relation type with a stronger claim."
    elif family == "provenance_source_trace":
        text = "Do not assign the provenance record to the wrong concept or treat context as the authority record."
    elif family == "temporal_version":
        text = "Do not infer chronology from a single record."
    elif family == "mixed_domain_distractor":
        text = "Do not turn the source passage into a finance or medical claim."
    elif behavior == "partial":
        text = "Do not invent the unanswered dimension from unstated evidence."
    elif behavior == "clarify-compatible":
        text = "Do not collapse an ambiguous request into a forced answer."
    else:
        text = "Do not strengthen the cited passage into an unsupported causal or universal claim."
    return [
        {
            "inference_id": f"{case_id}-F01",
            "forbidden_text_or_relation": text,
            "reason": "The source does not explicitly support this inference.",
        }
    ]


def build_optional_propositions(case_id: str, supports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    optional: list[dict[str, Any]] = []
    context_supports = [support for support in supports if support.get("support_role") == "context"]
    for index, support in enumerate(context_supports, start=1):
        optional.append(
            {
                "proposition_id": f"{case_id}-CTX{index:02d}",
                "proposition_text": support["exact_support_snippet"].strip(),
                "gold_mode": GOLD_MODE_CONTEXT_ONLY,
                "hostile_semantic_review_required": False,
                "extractive_certificate": extractive_certificate([support]),
                "relation_type": "context_support",
                "support_refs": [support["support_id"]],
                "entailment_note": "Context only; not required for the main claim.",
            }
        )
    return optional


def sentinel_proposition_text(case_id: str, support: dict[str, Any]) -> str:
    snippet = support["exact_support_snippet"].strip()
    if case_id.startswith("SENTINEL-Q2"):
        return (
            "Skill | What method should the agent follow for this class of task? | "
            "SOP, tool order, decision rules, acceptance criteria"
        )
    if case_id.startswith("SENTINEL-Q3"):
        return "Research should help you recover meaning, context, and decision logic."
    return snippet


def build_sentinel_required_propositions(
    case_id: str,
    supports: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    required: list[dict[str, Any]] = []
    authority_supports = [
        support
        for support in supports
        if support.get("support_role") not in CONTEXT_SUPPORT_ROLES
    ]
    if case_id.startswith("SENTINEL-Q2"):
        authority_supports = authority_supports[:1]
    if case_id.startswith("SENTINEL-Q3"):
        authority_supports = authority_supports[:1]

    for index, support in enumerate(authority_supports, start=1):
        proposition_id = f"{case_id}-PROP{index:02d}"
        support["authority_for"] = [proposition_id]
        required.append(
            {
                "proposition_id": proposition_id,
                "proposition_text": sentinel_proposition_text(case_id, support),
                "gold_mode": GOLD_MODE_SENTINEL_SYNTHESIS,
                "hostile_semantic_review_required": True,
                "extractive_certificate": extractive_certificate([support]),
                "sentinel_atomic_mapping": {
                    "support_id": support["support_id"],
                    "source_identity": support["source_identity"],
                    "section_id": support["section_id"],
                },
                "relation_type": "direct_support",
                "support_refs": [support["support_id"]],
                "entailment_note": (
                    "Sentinel synthesis is bounded to this atomic source-backed assertion."
                ),
            }
        )
    return required


def make_provenance_support(
    case_id: str,
    index: int,
    record: dict[str, Any],
    *,
    support_id: str | None = None,
) -> dict[str, Any]:
    concept_id = str(record["subject"]["concept_id"])
    return {
        "support_id": support_id or make_support_id(case_id, index),
        "source_identity": "provenance.json",
        "section_id": concept_id,
        "locator": str(record.get("review_decision_id") or record.get("synthesis_id") or record.get("resolution_id") or concept_id.rsplit("/", 1)[-1]),
        "exact_support_snippet": json.dumps(record, ensure_ascii=False, sort_keys=True),
        "support_role": "provenance_record",
        "authority_for": [],
        "provenance_certificate": {
            "record_id": str(record.get("review_decision_id") or record.get("synthesis_id") or record.get("resolution_id") or ""),
            "subject_concept_id": concept_id,
        },
    }


def make_graph_support(
    case_id: str,
    index: int,
    edge: dict[str, Any],
    *,
    support_id: str | None = None,
) -> dict[str, Any]:
    certificate = {
        "edge_id": str(edge["edge_id"]),
        "source_node_id": str(edge["source"]),
        "source_label_or_concept": str(edge["source"]),
        "target_node_id": str(edge["target"]),
        "target_label_or_concept": str(edge["target"]),
        "relation_type": str(edge["relation_type"]),
        "directed": bool(edge["directed"]),
    }
    return {
        "support_id": support_id or make_support_id(case_id, index),
        "source_identity": "graph-v2.json",
        "section_id": f"graph-v2#{edge['edge_id']}",
        "locator": str(edge["edge_id"]),
        "exact_support_snippet": json.dumps(certificate, ensure_ascii=False, sort_keys=True),
        "support_role": "graph_edge",
        "authority_for": [],
        "graph_certificate": certificate,
    }


def build_certificate_bundle(
    *,
    primary_support: dict[str, Any],
    provenance_support: dict[str, Any] | None = None,
    graph_support: dict[str, Any] | None = None,
    temporal_mode: str | None = None,
    minimum_required_for_positive: int | None = None,
    observed_temporal_record_count: int | None = None,
    explicit_mapping_note: str | None = None,
) -> dict[str, Any]:
    bundle: dict[str, Any] = {
        "primary_concept_id": concept_id_from_section(str(primary_support["section_id"])),
        "primary_section_id": str(primary_support["section_id"]),
        "primary_source_identity": str(primary_support["source_identity"]),
    }
    if provenance_support is not None:
        bundle["provenance_record_id"] = provenance_support["provenance_certificate"]["record_id"]
        bundle["provenance_subject_concept_id"] = provenance_support["provenance_certificate"]["subject_concept_id"]
        bundle["subject_match"] = (
            bundle["primary_concept_id"] == bundle["provenance_subject_concept_id"]
        )
        if explicit_mapping_note:
            bundle["explicit_mapping_note"] = explicit_mapping_note
    if graph_support is not None:
        bundle["graph_edge_id"] = graph_support["graph_certificate"]["edge_id"]
        bundle["graph_relation_type"] = graph_support["graph_certificate"]["relation_type"]
        bundle["graph_directed"] = graph_support["graph_certificate"]["directed"]
    if temporal_mode is not None:
        bundle["temporal_evidence_mode"] = temporal_mode
        if minimum_required_for_positive is not None:
            bundle["minimum_required_for_positive"] = minimum_required_for_positive
        if observed_temporal_record_count is not None:
            bundle["observed_temporal_record_count"] = observed_temporal_record_count
    return bundle


def render_provenance_proposition(certificate: dict[str, Any]) -> str:
    return (
        f"{certificate['primary_concept_id']} is bound to provenance record "
        f"{certificate['provenance_record_id']} whose subject is "
        f"{certificate['provenance_subject_concept_id']}."
    )


def render_graph_proposition(graph_support: dict[str, Any]) -> str:
    certificate = graph_support["graph_certificate"]
    return (
        f"{certificate['source_node_id']} {certificate['relation_type']} "
        f"{certificate['target_node_id']}."
    )


def render_temporal_proposition(certificate: dict[str, Any]) -> str:
    count = int(certificate["observed_temporal_record_count"])
    noun = "record" if count == 1 else "records"
    return f"Only {count} {noun} is available; a newer-version ordering cannot be established."


def proposition_text_from_support(supports: list[dict[str, Any]]) -> str:
    snippets = [s["exact_support_snippet"].strip() for s in supports]
    if not snippets:
        return "No proposition text available."
    if len(snippets) == 1:
        return snippets[0]
    return "\n\n".join(snippets)


def relation_type_for_behavior(behavior: str) -> str:
    return {
        "answer": "direct_support",
        "partial": "partial_support",
        "abstain": "context_only",
        "clarify-compatible": "clarify_compatible",
    }[behavior]


def build_required_propositions(
    case_id: str,
    behavior: str,
    supports: list[dict[str, Any]],
    proposition_text: str | None = None,
) -> list[dict[str, Any]]:
    proposition_id = prop_id_for_case(case_id)
    refs = direct_authority_refs(supports, proposition_id)
    gold_mode = GOLD_MODE_CONTEXT_ONLY if behavior == "abstain" else GOLD_MODE_EXTRACTIVE
    return [
        {
            "proposition_id": proposition_id,
            "proposition_text": proposition_text or proposition_text_from_support(supports),
            "gold_mode": gold_mode,
            "hostile_semantic_review_required": False,
            "extractive_certificate": extractive_certificate(supports),
            "relation_type": relation_type_for_behavior(behavior),
            "support_refs": refs,
            "entailment_note": (
                "Directly supported by the quoted source passages."
                if behavior == "answer"
                else "Context only; the cited source does not answer the requested unsupported bridge."
                if behavior == "abstain"
                else "The source supports only a bounded or negative conclusion; the answer must not overreach."
            ),
        }
    ]


def build_case_from_source(
    source_case: dict[str, Any],
    *,
    case_id: str,
    family: str | None = None,
    question: str | None = None,
    expected_behavior: str | None = None,
    expected_terminal_set: list[str] | None = None,
    paraphrase_group: str | None = None,
    negative_control_of: str | None = None,
    temporal_versions_required: int | None = None,
    provenance_required: bool | None = None,
    graph_edge_required: bool | None = None,
    proposition_text: str | None = None,
) -> dict[str, Any]:
    behavior = expected_behavior or source_case["expected_behavior"]
    supports: list[dict[str, Any]] = []
    proposition_id = prop_id_for_case(case_id)
    for index, support in enumerate(source_case["gold_support"], start=1):
        support_role = support["support_role"]
        supports.append(
            {
                "support_id": make_support_id(case_id, index),
                "source_identity": support["source_identity"],
                "section_id": support["section_id"],
                "locator": support["locator"],
                "exact_support_snippet": support["exact_support_snippet"],
                "support_role": support_role,
                "authority_for": []
                if support_role in CONTEXT_SUPPORT_ROLES
                else [proposition_id],
            }
        )
    direct_supports = [
        support for support in supports if proposition_id in support.get("authority_for", [])
    ]
    optional = build_optional_propositions(case_id, supports)
    record = {
        "case_id": case_id,
        "family": family or source_case["family"],
        "pool": source_case["pool"],
        "risk_tags": list(source_case.get("risk_tags", [])),
        "question": question or source_case["question"],
        "expected_behavior": behavior,
        "expected_behavior_set": [behavior],
        "expected_terminal_set": expected_terminal_set or source_case["expected_terminal_set"],
        "minimum_material_claims": 0 if behavior in {"abstain", "clarify-compatible"} else 1,
        "maximum_unsupported_claims": 0,
        "required_propositions": build_required_propositions(
            case_id, behavior, direct_supports, proposition_text
        ),
        "optional_propositions": optional,
        "forbidden_inferences": make_forbidden(
            case_id,
            family or source_case["family"],
            question or source_case["question"],
            behavior,
        ),
        "gold_support": supports,
        "unanswered_dimensions_expected": list(source_case.get("unanswered_dimensions_expected", [])),
        "distinct_source_minimum": int(source_case["distinct_source_minimum"]),
        "graph_edge_required": bool(graph_edge_required if graph_edge_required is not None else source_case["graph_edge_required"]),
        "provenance_required": bool(provenance_required if provenance_required is not None else source_case["provenance_required"]),
        "temporal_versions_required": int(temporal_versions_required if temporal_versions_required is not None else source_case["temporal_versions_required"]),
        "paraphrase_group": paraphrase_group if paraphrase_group is not None else source_case.get("paraphrase_group", ""),
        "negative_control_of": negative_control_of if negative_control_of is not None else source_case.get("negative_control_of", ""),
        "graph_certificate": {},
        "provenance_certificate": {},
        "temporal_certificate": {},
        "derivation_notes": source_case["derivation_notes"] + " Reconstructed into proposition-grounded schema.",
    }
    return record


def build_holdout_replacement(case_id: str, family: str, question: str, source_identity: str, section_id: str, snippet: str, proposition_text: str, support_role: str = "primary") -> dict[str, Any]:
    proposition_id = prop_id_for_case(case_id)
    support = {
        "support_id": f"{case_id}-SUP01",
        "source_identity": source_identity,
        "section_id": section_id,
        "locator": section_id.rsplit("#", 1)[-1].replace("-", " ").title(),
        "exact_support_snippet": snippet,
        "support_role": support_role,
        "authority_for": [] if support_role in CONTEXT_SUPPORT_ROLES else [proposition_id],
    }
    return {
        "case_id": case_id,
        "family": family,
        "pool": "holdout",
        "risk_tags": [family],
        "question": question,
        "expected_behavior": "abstain" if family == "temporal_version" else ("answer" if family not in {"ambiguous_clarification", "partially_sufficient_evidence"} else "partial"),
        "expected_behavior_set": ["abstain" if family == "temporal_version" else ("answer" if family not in {"ambiguous_clarification", "partially_sufficient_evidence"} else "partial")],
        "expected_terminal_set": ["safe_abstention", "owner_only_safe_abstention"] if family == "temporal_version" else ["verified_answer_ready_candidate", "owner_only_cited_answer", "owner_only_safe_abstention"] if family in {"ambiguous_clarification", "partially_sufficient_evidence"} else ["verified_answer_ready_candidate", "owner_only_cited_answer"],
        "minimum_material_claims": 0 if family in {"ambiguous_clarification", "partially_sufficient_evidence", "temporal_version"} else 1,
        "maximum_unsupported_claims": 0,
        "required_propositions": [
            {
                "proposition_id": proposition_id,
                "proposition_text": proposition_text,
                "gold_mode": GOLD_MODE_CONTEXT_ONLY
                if family == "temporal_version"
                else GOLD_MODE_EXTRACTIVE,
                "hostile_semantic_review_required": False,
                "extractive_certificate": extractive_certificate([support]),
                "relation_type": "direct_support"
                if family not in {"ambiguous_clarification", "partially_sufficient_evidence", "temporal_version"}
                else "context_only"
                if family == "temporal_version"
                else "partial_support",
                "support_refs": direct_authority_refs([support], proposition_id),
                "entailment_note": "Directly supported by the reconstructed source passage."
                if family not in {"ambiguous_clarification", "partially_sufficient_evidence", "temporal_version"}
                else "Context only; one source record is insufficient for a newer-version comparison."
                if family == "temporal_version"
                else "The source supports only a bounded or partial conclusion.",
            }
        ],
        "optional_propositions": [],
        "forbidden_inferences": make_forbidden(
            case_id,
            family,
            question,
            "abstain"
            if family == "temporal_version"
            else "partial"
            if family in {"ambiguous_clarification", "partially_sufficient_evidence"}
            else "answer",
        ),
        "gold_support": [support],
        "unanswered_dimensions_expected": ["newer_version"] if family == "temporal_version" else ([] if family not in {"ambiguous_clarification", "partially_sufficient_evidence"} else ["specific_resolution"]),
        "distinct_source_minimum": 1,
        "graph_edge_required": False,
        "provenance_required": False,
        "temporal_versions_required": 0,
        "graph_certificate": {},
        "provenance_certificate": {},
        "temporal_certificate": {},
        "paraphrase_group": "",
        "negative_control_of": "",
        "derivation_notes": "Reconstructed from pool-local accepted corpus material into proposition-grounded schema.",
    }


def build_sentinel_records() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for spec in SENTINELS:
        supports = []
        for index, (source_identity, section_id, snippet, role) in enumerate(spec["support_specs"], start=1):
            if spec["case_id"].startswith("SENTINEL-Q2") and source_identity != "daniel_blog_en__harness-theory-part-5":
                role = "context"
            if spec["case_id"].startswith("SENTINEL-Q1") and "atlas-of-agent" in source_identity:
                role = "negative_distractor"
            supports.append(
                {
                    "support_id": make_support_id(spec["case_id"], index),
                    "source_identity": source_identity,
                    "section_id": section_id,
                    "locator": section_id.rsplit("#", 1)[-1].replace("-", " ").title(),
                    "exact_support_snippet": snippet,
                    "support_role": role,
                    "authority_for": [],
                }
            )
        required_propositions = build_sentinel_required_propositions(spec["case_id"], supports)
        records.append(
            {
                "case_id": spec["case_id"],
                "family": spec["family"],
                "pool": "sentinel",
                "risk_tags": ["sentinel", spec["family"]],
                "question": spec["question"],
                "expected_behavior": "answer",
                "expected_behavior_set": ["answer"],
                "expected_terminal_set": spec["terminal_set"],
                "minimum_material_claims": 1,
                "maximum_unsupported_claims": 0,
                "required_propositions": required_propositions,
                "optional_propositions": build_optional_propositions(spec["case_id"], supports),
                "forbidden_inferences": make_forbidden(spec["case_id"], spec["family"], spec["question"], "answer"),
                "gold_support": supports,
                "unanswered_dimensions_expected": [],
                "distinct_source_minimum": 2 if spec["case_id"] == "SENTINEL-Q1-A" else 1,
                "graph_edge_required": False,
                "provenance_required": False,
                "temporal_versions_required": 0,
                "graph_certificate": {},
                "provenance_certificate": {},
                "temporal_certificate": {},
                "paraphrase_group": f"PG-{spec['family']}",
                "negative_control_of": "",
                "derivation_notes": "Restored known regression sentinel from accepted PM / skill evidence.",
            }
        )
    return records


def build_primary_holdout_bank() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    primary = split_source_bank("broad_bank.primary.jsonl")
    holdout = split_source_bank("broad_bank.holdout.jsonl")

    primary_new: list[dict[str, Any]] = []
    holdout_new: list[dict[str, Any]] = []
    lex = load_lexical()
    prov = load_provenance_map()
    graph = load_graph_map()
    primary_by_id = {r["case_id"]: r for r in primary}
    holdout_by_id = {r["case_id"]: r for r in holdout}

    behavior_overrides = {
        "BROAD-0004": "abstain",
        "BROAD-0005": "partial",
        "BROAD-0010": "abstain",
        "BROAD-0011": "abstain",
        "BROAD-0029": "abstain",
        "BROAD-0061": "abstain",
    }
    terminal_overrides = {
        "BROAD-0004": ["safe_abstention", "owner_only_safe_abstention"],
        "BROAD-0005": ["verified_answer_ready_candidate", "owner_only_cited_answer", "owner_only_safe_abstention"],
        "BROAD-0010": ["safe_abstention", "owner_only_safe_abstention"],
        "BROAD-0011": ["safe_abstention", "owner_only_safe_abstention"],
        "BROAD-0029": ["safe_abstention", "owner_only_safe_abstention"],
        "BROAD-0061": ["safe_abstention", "owner_only_safe_abstention"],
    }
    proposition_overrides: dict[str, str] = {}

    for src_case_id, new_case_id in PRIMARY_ONLY_NEW:
        source = primary_by_id[src_case_id]
        if source["case_id"] in behavior_overrides:
            source = {**source, "expected_behavior": behavior_overrides[source["case_id"]], "expected_terminal_set": terminal_overrides[source["case_id"]]}
        primary_new.append(
            build_case_from_source(
                source,
                case_id=new_case_id,
                family=source["family"],
                question=source["question"],
                expected_behavior=behavior_overrides.get(src_case_id, source["expected_behavior"]),
                expected_terminal_set=terminal_overrides.get(src_case_id, source["expected_terminal_set"]),
                proposition_text=proposition_overrides.get(src_case_id),
                paraphrase_group=source.get("paraphrase_group", ""),
            )
        )

    holdout_fixup_map = {
        "BROAD-0067": ("R2O-PG-H029", "role_responsibility", "concepts/steering-control-plane#steering-control-plane"),
        "BROAD-0068": ("R2O-PG-H030", "causal_why", "concepts/goal-drift#control"),
        "BROAD-0071": ("R2O-PG-H031", "trade_offs", "concepts/tool-call-proposal#authority"),
    }

    addition_specs = [
        ("R2O-PG-H032", "impact_effect", "How does Gate behavior affect task outcomes?", "concepts/completion-gate#gate-behavior"),
        ("R2O-PG-H033", "examples", "What examples are given in Control?", "concepts/goal-drift#control"),
        ("R2O-PG-H034", "architecture_components", "Which architecture components are named in Controls shared by every structure?", "concepts/agent-execution-paths#controls-shared-by-every-structure"),
        ("R2O-PG-H035", "capability_skill_requirement", "What capability or requirement is stated in Harnessability assessment?", "concepts/harnessability#assessment"),
        ("R2O-PG-H036", "enumerative_list", "List the supported sequence in Selection sequence.", "concepts/agent-planning-strategies#selection-sequence"),
        ("R2O-PG-H037", "multi_part", "What does Item Turn Thread Protocol say about its parts?", "concepts/item-turn-thread-protocol#item-turn-thread-protocol"),
        ("R2O-PG-H038", "broad_synthesis", "Synthesize the reviewed LLM architecture claim.", "concepts/six-dimensional-map-of-llm-agent-architectures#reviewed-synthesis-dec-1f9025c488e9c83356e402ec4f859d11"),
        ("R2O-PG-H039", "narrow_factual", "What exact factual point is stated in Durable Thread State?", "concepts/durable-thread-state#durable-thread-state"),
        ("R2O-PG-H040", "ambiguous_clarification", "What about Narrowed scope?", "concepts/harnessability#narrowed-scope"),
        ("R2O-PG-H041", "partially_sufficient_evidence", "What does Request Boundary establish, and what remains unanswered?", "concepts/request-boundary#security-role"),
        ("R2O-PG-H042", "short_query", "Operational role?", "concepts/harness#operational-role"),
        ("R2O-PG-H043", "long_compositional_query", "Using only the cited source, explain what Plan-and-Execute establishes and what must not be inferred beyond the exact snippet.", "concepts/agent-planning-strategies#plan-and-execute"),
        ("R2O-PG-H044", "temporal_version", "Which source-adoption state is newer?", "concepts/goal-drift#source-adoption"),
    ]

    for new_case_id, family, question, section_id in addition_specs:
        source_case = holdout_by_id[
            next(
                case_id
                for case_id, case in holdout_by_id.items()
                if any(s["section_id"] == section_id for s in case["gold_support"])
            )
        ]
        doc = lex[section_id]
        proposition_text = doc["body"].strip()
        if new_case_id == "R2O-PG-H044":
            # Use the current holdout source-adoption pair, not the primary one, to preserve disjointness.
            source_case = holdout_by_id["BROAD-0072"]
        rec = build_case_from_source(
                source_case,
                case_id=new_case_id,
                family=family,
                question=question,
                expected_behavior="clarify-compatible" if family == "ambiguous_clarification" else ("partial" if family == "partially_sufficient_evidence" else ("abstain" if family == "temporal_version" else "answer")),
                expected_terminal_set=(
                    ["safe_abstention", "owner_only_safe_abstention", "clarify"]
                    if family == "ambiguous_clarification"
                    else (
                        ["verified_answer_ready_candidate", "owner_only_cited_answer", "owner_only_safe_abstention"]
                        if family == "partially_sufficient_evidence"
                        else (
                            ["safe_abstention", "owner_only_safe_abstention"]
                            if family == "temporal_version"
                            else ["verified_answer_ready_candidate", "owner_only_cited_answer"]
                        )
                    )
                ),
                proposition_text=proposition_text,
                negative_control_of=source_case.get("negative_control_of", "") if family in {"ambiguous_clarification", "partially_sufficient_evidence"} else "",
                temporal_versions_required=2 if family == "temporal_version" else source_case["temporal_versions_required"],
                provenance_required=False if family == "temporal_version" else None,
                paraphrase_group="PG-holdout-structural" if family in {"impact_effect", "examples", "architecture_components"} else (
                    "PG-holdout-requirement" if family in {"capability_skill_requirement", "enumerative_list", "multi_part"} else (
                        "PG-holdout-synthesis" if family in {"broad_synthesis", "narrow_factual", "ambiguous_clarification"} else (
                            "PG-holdout-partial" if family in {"partially_sufficient_evidence", "short_query", "long_compositional_query", "temporal_version"} else ""
                        )
                    )
                ),
        )
        primary_support = rec["gold_support"][0]
        primary_support["source_identity"] = section_id.split("#")[0] + ".md"
        primary_support["section_id"] = section_id
        primary_support["locator"] = section_locator(section_id)
        primary_support["exact_support_snippet"] = doc["body"].strip()
        rec["required_propositions"][0]["extractive_certificate"] = extractive_certificate(
            [primary_support]
        )
        rec["required_propositions"][0]["proposition_text"] = proposition_text
        holdout_new.append(rec)

    holdout_transformed = []
    for index, case in enumerate(holdout, start=1):
        if case["case_id"] in holdout_fixup_map:
            new_case_id, family, section_id = holdout_fixup_map[case["case_id"]]
            doc = lex[section_id]
            holdout_transformed.append(
                build_holdout_replacement(
                    new_case_id,
                    family,
                    case["question"],
                    section_id.split("#")[0] + ".md",
                    section_id,
                    doc["body"].strip(),
                    doc["body"].strip(),
                )
            )
            continue
        holdout_transformed.append(
            build_case_from_source(
                case,
                case_id=f"R2O-PG-H{index:03d}",
                family=case["family"],
                question=case["question"],
                expected_behavior=behavior_overrides.get(case["case_id"], case["expected_behavior"]),
                expected_terminal_set=terminal_overrides.get(case["case_id"], case["expected_terminal_set"]),
                proposition_text=proposition_overrides.get(case["case_id"]),
                paraphrase_group=case.get("paraphrase_group", ""),
            )
        )

    records = [
        *[
            build_case_from_source(
                case,
                case_id=f"R2O-PG-P{index:03d}",
                family=case["family"],
                question=case["question"],
                expected_behavior=behavior_overrides.get(case["case_id"], case["expected_behavior"]),
                expected_terminal_set=terminal_overrides.get(case["case_id"], case["expected_terminal_set"]),
                proposition_text=proposition_overrides.get(case["case_id"]),
                paraphrase_group=case.get("paraphrase_group", ""),
            )
            for index, case in enumerate(primary, start=1)
        ],
        *primary_new,
        *holdout_transformed,
        *holdout_new,
        *build_sentinel_records(),
    ]

    record_by_id = {rec["case_id"]: rec for rec in records}

    def case_from_source(
        source_case_id: str,
        *,
        case_id: str,
        family: str,
        question: str,
        proposition_text: str,
        expected_behavior: str = "answer",
        expected_terminal_set: list[str] | None = None,
        paraphrase_group: str = "",
        provenance_required: bool = False,
        graph_edge_required: bool = False,
    ) -> dict[str, Any]:
        source = primary_by_id.get(source_case_id) or holdout_by_id.get(source_case_id)
        assert source is not None
        return build_case_from_source(
            source,
            case_id=case_id,
            family=family,
            question=question,
            expected_behavior=expected_behavior,
            expected_terminal_set=expected_terminal_set,
            proposition_text=proposition_text,
            paraphrase_group=paraphrase_group,
            provenance_required=provenance_required,
            graph_edge_required=graph_edge_required,
            temporal_versions_required=0,
        )

    provenance_specs = [
        (
            "R2O-PG-P030",
            "BROAD-0030",
            "Which provenance source supports Human-in-the-loop?",
            "Human-in-the-loop is supported by the agent-execution-paths provenance record.",
            "concepts/agent-execution-paths",
            None,
        ),
        (
            "R2O-PG-P062",
            "BROAD-0062",
            "Which provenance source supports Selection sequence?",
            "Selection sequence is supported by the agent-planning-strategies provenance record.",
            "concepts/agent-execution-paths",
            None,
        ),
        (
            "R2O-PG-H010",
            "BROAD-0072",
            "Which provenance source supports Source adoption?",
            "Source adoption is supported by the goal-drift provenance record.",
            "concepts/goal-drift",
            None,
        ),
    ]
    for case_id, source_case_id, question, proposition_text, provenance_concept_id, mapping_note in provenance_specs:
        rec = case_from_source(
            source_case_id,
            case_id=case_id,
            family="provenance_source_trace",
            question=question,
            proposition_text=proposition_text,
            expected_behavior="answer",
            expected_terminal_set=["verified_answer_ready_candidate", "owner_only_cited_answer"],
            paraphrase_group="PG-provenance_source_trace-intent",
            provenance_required=True,
        )
        primary_support = rec["gold_support"][0]
        provenance_record = prov[provenance_concept_id]
        provenance_support = make_provenance_support(case_id, 2, provenance_record)
        proposition_id = rec["required_propositions"][0]["proposition_id"]
        provenance_support["authority_for"] = [proposition_id]
        rec["gold_support"] = [primary_support, provenance_support]
        rec["provenance_certificate"] = build_certificate_bundle(
            primary_support=primary_support,
            provenance_support=provenance_support,
            explicit_mapping_note=mapping_note,
        )
        rec["required_propositions"][0]["support_refs"] = [provenance_support["support_id"]]
        rec["required_propositions"][0]["relation_type"] = "structural_provenance"
        rec["required_propositions"][0]["gold_mode"] = GOLD_MODE_STRUCTURAL
        rec["required_propositions"][0]["hostile_semantic_review_required"] = False
        rec["required_propositions"][0]["structural_certificate_type"] = "provenance"
        rec["required_propositions"][0]["proposition_text"] = render_provenance_proposition(
            rec["provenance_certificate"]
        )
        rec["required_propositions"][0]["entailment_note"] = (
            "Mechanically rendered from the matching provenance certificate."
        )
        rec["required_propositions"][0].pop("extractive_certificate", None)
        rec["graph_certificate"] = {}
        rec["temporal_certificate"] = {}
        record_by_id[case_id].clear()
        record_by_id[case_id].update(rec)

    graph_specs = [
        (
            "R2O-PG-P031",
            "BROAD-0013",
            "What graph relationship is recorded for Harness Agent Loop?",
            "Harness Agent Loop requires Stopping Policy.",
            "edge_066cda73130d3f1a7cc6dde6ac4897c5",
            "PG-graph_relationship-intent",
        ),
        (
            "R2O-PG-H001",
            "BROAD-0045",
            "What graph relationship is recorded for Harness Verification?",
            "Harness requires Harness Verification.",
            "edge_0cc19496d16008c4250c1ddf5c91ad9d",
            "PG-graph_relationship-intent",
        ),
        (
            "R2O-PG-P070",
            "BROAD-0063",
            "What graph relationship is recorded for Agent decision and planning strategies?",
            "Agent decision and planning strategies complements Agent execution paths.",
            "edge_f55a979c704bddcf552b4e9e713428db",
            "PG-graph_relationship-intent",
        ),
    ]
    for case_id, source_case_id, question, proposition_text, edge_id, paraphrase_group in graph_specs:
        rec = case_from_source(
            source_case_id,
            case_id=case_id,
            family="graph_relationship",
            question=question,
            proposition_text=proposition_text,
            expected_behavior="answer",
            expected_terminal_set=["verified_answer_ready_candidate", "owner_only_cited_answer"],
            paraphrase_group=paraphrase_group,
            graph_edge_required=True,
        )
        primary_support = rec["gold_support"][0]
        graph_support = make_graph_support(case_id, 2, graph[edge_id])
        proposition_id = rec["required_propositions"][0]["proposition_id"]
        graph_support["authority_for"] = [proposition_id]
        rec["gold_support"] = [primary_support, graph_support]
        rec["graph_certificate"] = build_certificate_bundle(
            primary_support=primary_support,
            graph_support=graph_support,
        )
        rec["required_propositions"][0]["support_refs"] = [graph_support["support_id"]]
        rec["required_propositions"][0]["relation_type"] = "structural_graph"
        rec["required_propositions"][0]["gold_mode"] = GOLD_MODE_STRUCTURAL
        rec["required_propositions"][0]["hostile_semantic_review_required"] = False
        rec["required_propositions"][0]["structural_certificate_type"] = "graph"
        rec["required_propositions"][0]["proposition_text"] = render_graph_proposition(graph_support)
        rec["required_propositions"][0]["entailment_note"] = (
            "Mechanically rendered from the structured graph edge certificate."
        )
        rec["required_propositions"][0].pop("extractive_certificate", None)
        rec["provenance_certificate"] = {}
        rec["temporal_certificate"] = {}
        record_by_id[case_id].clear()
        record_by_id[case_id].update(rec)

    temporal_case_specs = [
        ("R2O-PG-P029", "Direct", "Which version is newer for Direct?"),
        ("R2O-PG-P061", "Pipeline", "Which version is newer for Pipeline?"),
        ("R2O-PG-P072", "Pipeline", "Which version is newer for Pipeline?"),
        ("R2O-PG-H044", "source-adoption", "Which source-adoption state is newer?"),
    ]
    for case_id, label, question in temporal_case_specs:
        rec = record_by_id[case_id]
        primary_support = rec["gold_support"][0]
        rec["question"] = question
        rec["expected_behavior"] = "abstain"
        rec["expected_behavior_set"] = ["abstain"]
        rec["expected_terminal_set"] = ["safe_abstention", "owner_only_safe_abstention"]
        rec["minimum_material_claims"] = 0
        rec["required_propositions"][0]["relation_type"] = "context_only"
        rec["required_propositions"][0]["entailment_note"] = "Context only; one source record is insufficient for a newer-version comparison."
        rec["required_propositions"][0]["proposition_text"] = f"The source provides only one {label} record, so no newer version can be determined."
        rec["required_propositions"][0]["support_refs"] = [primary_support["support_id"]]
        rec["provenance_required"] = False
        rec["provenance_certificate"] = {}
        rec["temporal_versions_required"] = 0
        rec["temporal_certificate"] = build_certificate_bundle(
            primary_support=primary_support,
            temporal_mode="insufficient",
            minimum_required_for_positive=2,
            observed_temporal_record_count=1,
        )
        rec["required_propositions"][0]["gold_mode"] = GOLD_MODE_STRUCTURAL
        rec["required_propositions"][0]["structural_certificate_type"] = "temporal"
        rec["required_propositions"][0]["proposition_text"] = render_temporal_proposition(
            rec["temporal_certificate"]
        )
        rec["required_propositions"][0].pop("extractive_certificate", None)
        if case_id == "R2O-PG-H044":
            rec["gold_support"] = [primary_support]
        rec["forbidden_inferences"] = make_forbidden(case_id, "temporal_version", question, "abstain")

    negative_context_specs = [
        (
            "R2O-PG-H013",
            "Does Source adoption prove a finance or medical claim?",
        ),
    ]
    for case_id, question in negative_context_specs:
        rec = record_by_id[case_id]
        primary_support = rec["gold_support"][0]
        rec["question"] = question
        rec["required_propositions"][0]["relation_type"] = "context_only"
        rec["required_propositions"][0]["entailment_note"] = "Context only; the source passage cannot justify the requested mixed-domain bridge."
        rec["required_propositions"][0]["proposition_text"] = primary_support[
            "exact_support_snippet"
        ].strip()
        rec["required_propositions"][0]["support_refs"] = [primary_support["support_id"]]
        rec["provenance_required"] = False
        rec["provenance_certificate"] = {}
        rec["temporal_certificate"] = {}
        rec["gold_support"] = [primary_support]
        rec["forbidden_inferences"] = make_forbidden(case_id, "mixed_domain_distractor", question, "abstain")

    if "R2O-PG-H033" in record_by_id:
        rec = record_by_id["R2O-PG-H033"]
        primary_support = rec["gold_support"][0]
        rec["gold_support"] = [primary_support]
        rec["required_propositions"][0]["support_refs"] = [primary_support["support_id"]]

    return records, primary_new, holdout_new


def group_by_pool(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    primary = [r for r in records if r["pool"] == "primary"]
    holdout = [r for r in records if r["pool"] == "holdout"]
    sentinels = [r for r in records if r["pool"] == "sentinel"]
    return primary, holdout, sentinels


def canonical_bank_sha(primary: list[dict[str, Any]], holdout: list[dict[str, Any]], sentinels: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for name, rows in (
        ("broad_bank.primary.jsonl", primary),
        ("broad_bank.holdout.jsonl", holdout),
        ("broad_bank.sentinels.jsonl", sentinels),
    ):
        payload = "".join(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n" for row in rows)
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(payload.encode("utf-8"))
    return digest.hexdigest()


def pool_ids_sha(rows: list[dict[str, Any]]) -> str:
    ids = "\n".join(sorted(row["case_id"] for row in rows)) + "\n"
    return hashlib.sha256(ids.encode("utf-8")).hexdigest()


def family_counts(rows: list[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for row in rows:
        counts[row["family"]] += 1
    return counts


def behavior_counts(rows: list[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for row in rows:
        counts[row["expected_behavior"]] += 1
    return counts


def normalize_text(text: str) -> str:
    cleaned = re.sub(r"[`*_#>\-|:.(),;]+", " ", text.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def audit_extractiveness(rows: list[dict[str, Any]]) -> list[list[Any]]:
    audit_rows: list[list[Any]] = []
    for row in rows:
        supports = {support["support_id"]: support for support in row["gold_support"]}
        for prop in row["required_propositions"]:
            refs = list(prop.get("support_refs", []))
            if not refs:
                refs = [""]
            ref_supports = [supports[ref] for ref in refs if ref in supports]
            combined_source = "\n\n".join(
                str(support.get("exact_support_snippet", "")) for support in ref_supports
            )
            prop_text = str(prop.get("proposition_text", ""))
            prop_exact_match = bool(prop_text and prop_text in combined_source)
            prop_normalized_match = bool(
                prop_text and normalize_text(prop_text) in normalize_text(combined_source)
            )
            gold_mode = str(prop.get("gold_mode", ""))
            prop_context_authority = any(
                str(support.get("support_role")) in CONTEXT_SUPPORT_ROLES
                for support in ref_supports
            )
            pass_fail = "PASS"
            reason = "ok"
            if prop_context_authority:
                pass_fail = "FAIL"
                reason = "context_or_distractor_used_as_authority"
            elif gold_mode in {
                GOLD_MODE_EXTRACTIVE,
                GOLD_MODE_CONTEXT_ONLY,
                GOLD_MODE_SENTINEL_SYNTHESIS,
            } and not (prop_exact_match or prop_normalized_match):
                pass_fail = "FAIL"
                reason = "extractive_prop_not_in_support"
            for ref in refs:
                support = supports.get(ref, {})
                structural_match = ""
                if gold_mode == GOLD_MODE_STRUCTURAL:
                    structural_match = "PASS"
                sentinel_mapping = (
                    "PASS"
                    if gold_mode == GOLD_MODE_SENTINEL_SYNTHESIS
                    and prop.get("sentinel_atomic_mapping")
                    and prop.get("hostile_semantic_review_required") is True
                    else ""
                )
                context_authority = str(support.get("support_role")) in CONTEXT_SUPPORT_ROLES
                audit_rows.append(
                    [
                        row["case_id"],
                        row["pool"],
                        row["family"],
                        row["expected_behavior"],
                        gold_mode,
                        prop["proposition_id"],
                        prop_text,
                        ref,
                        support.get("support_role", ""),
                        prop_exact_match,
                        prop_normalized_match,
                        structural_match,
                        sentinel_mapping,
                        context_authority,
                        prop.get("hostile_semantic_review_required", False),
                        pass_fail,
                        reason,
                    ]
                )
    return audit_rows


def source_census(rows: list[dict[str, Any]]) -> dict[str, Any]:
    source_identities = set()
    source_files = set()
    source_families = set()
    for row in rows:
        for support in row["gold_support"]:
            source_identities.add(support["source_identity"])
            source_files.add(support["source_identity"])
            source_families.add(support["source_identity"].split("/")[-1].split(".")[0].split("#")[0])
    return {
        "unique_source_identities": len(source_identities),
        "unique_source_files": len(source_files),
        "source_family_count": len(source_families),
    }


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n" for row in rows))


def write_csv(path: Path, header: list[str], rows: list[list[Any]]) -> None:
    with path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)


def build_matrix(
    *,
    rows: list[dict[str, Any]],
    runtime_candidate_sha: str,
    bank_sha: str,
    limit: int,
    sentinel_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    seed = hashlib.sha256(f"{runtime_candidate_sha}:{bank_sha}".encode()).hexdigest()
    sentinel_rows = sentinel_rows or []
    primary = [row for row in rows if row["pool"] == "primary"]
    selected: list[dict[str, Any]] = []
    families_seen = set()

    for row in sorted(primary, key=lambda row: hashlib.sha256(f"{seed}:{row['case_id']}".encode()).hexdigest()):
        if row["family"] not in families_seen:
            selected.append(row)
            families_seen.add(row["family"])
        if len(families_seen) >= 32:
            break
    control_behaviors = {"abstain", "partial", "clarify-compatible"}
    controls = [row for row in sorted(primary, key=lambda row: hashlib.sha256(f"{seed}:{row['case_id']}".encode()).hexdigest()) if row["expected_behavior"] in control_behaviors]
    for row in controls:
        if sum(1 for sel in selected if sel["expected_behavior"] in control_behaviors) >= 18:
            break
        if row not in selected:
            selected.append(row)
    for row in sorted(primary, key=lambda row: hashlib.sha256(f"{seed}:{row['case_id']}".encode()).hexdigest()):
        if len(selected) >= limit:
            break
        if row not in selected:
            selected.append(row)
    selected = sorted(selected, key=lambda row: row["case_id"])
    matrix: list[dict[str, Any]] = []
    for index, row in enumerate([*sentinel_rows, *selected], start=1):
        matrix.append(
            {
                "trial_id": f"LIVE-{index:03d}",
                "schema_version": "m26-r2o-frozen-live-matrix/v2",
                "case_id": row["case_id"],
                "family": row["family"],
                "pool": row["pool"],
                "question": row["question"],
                "expected_behavior": row["expected_behavior"],
                "runtime_candidate_sha": runtime_candidate_sha,
                "bank_sha256": bank_sha,
                "selection_seed": seed,
            }
        )
    return matrix


def build_holdout_matrix(rows: list[dict[str, Any]], runtime_candidate_sha: str, bank_sha: str, limit: int = 24) -> list[dict[str, Any]]:
    seed = hashlib.sha256(f"{runtime_candidate_sha}:{bank_sha}".encode()).hexdigest()
    holdouts = [row for row in rows if row["pool"] == "holdout"]
    controls = {"abstain", "partial", "clarify-compatible"}
    selected: list[dict[str, Any]] = []
    for row in sorted(holdouts, key=lambda row: hashlib.sha256(f"{seed}:{row['case_id']}".encode()).hexdigest()):
        if sum(1 for sel in selected if sel["expected_behavior"] in controls) >= 8:
            break
        if row["expected_behavior"] in controls and row not in selected:
            selected.append(row)
    for row in sorted(holdouts, key=lambda row: hashlib.sha256(f"{seed}:{row['case_id']}".encode()).hexdigest()):
        if len(selected) >= limit:
            break
        if row not in selected:
            selected.append(row)
    matrix: list[dict[str, Any]] = []
    for index, row in enumerate(sorted(selected, key=lambda row: row["case_id"]), start=1):
        matrix.append(
            {
                "trial_id": f"HOLDOUT-{index:03d}",
                "schema_version": "m26-r2o-frozen-live-matrix/v2",
                "case_id": row["case_id"],
                "family": row["family"],
                "pool": row["pool"],
                "question": row["question"],
                "expected_behavior": row["expected_behavior"],
                "runtime_candidate_sha": runtime_candidate_sha,
                "bank_sha256": bank_sha,
                "selection_seed": seed,
            }
        )
    return matrix


def main() -> None:
    records, _, _ = build_primary_holdout_bank()
    primary, holdout, sentinels = group_by_pool(records)
    bank_sha = canonical_bank_sha(primary, holdout, sentinels)

    ROOT.mkdir(parents=True, exist_ok=True)
    write_jsonl(ROOT / "broad_bank.primary.jsonl", primary)
    write_jsonl(ROOT / "broad_bank.holdout.jsonl", holdout)
    write_jsonl(ROOT / "broad_bank.sentinels.jsonl", sentinels)

    manifest = {
        "schema_version": "m26-r2o-proposition-grounded-bank-manifest/v1",
        "bank_sha256": bank_sha,
        "primary_ids_sha256": pool_ids_sha(primary),
        "holdout_ids_sha256": pool_ids_sha(holdout),
        "sentinel_ids_sha256": pool_ids_sha(sentinels),
        "primary_count": len(primary),
        "holdout_count": len(holdout),
        "sentinel_count": len(sentinels),
        "total_count": len(records),
    }
    (ROOT / "broad_bank_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    (ROOT / "BANK_SHA256.md").write_text(
        "\n".join(
            [
                "# M26 R2O Broad Bank SHA256",
                "",
                f"bank_sha256={bank_sha}",
                f"primary_ids_sha256={manifest['primary_ids_sha256']}",
                f"holdout_ids_sha256={manifest['holdout_ids_sha256']}",
                f"sentinel_ids_sha256={manifest['sentinel_ids_sha256']}",
            ]
        )
        + "\n"
    )

    rows = [*primary, *holdout, *sentinels]
    bank = {"primary": primary, "holdout": holdout, "sentinel": sentinels}
    counts = Counter(row["pool"] for row in rows)
    behavior = behavior_counts(rows)
    families = family_counts(rows)
    census = source_census(rows)
    write_csv(
        ROOT / "06_SOURCE_DIVERSITY_CENSUS.csv",
        ["metric", "value"],
        [
            ["TOTAL_CASES", len(rows)],
            ["PRIMARY_CASES", counts["primary"]],
            ["HOLDOUT_CASES", counts["holdout"]],
            ["SENTINELS", counts["sentinel"]],
            ["UNIQUE_SOURCE_IDENTITIES", census["unique_source_identities"]],
            ["UNIQUE_SOURCE_FILES", census["unique_source_files"]],
            ["SOURCE_FAMILY_COUNT", census["source_family_count"]],
        ],
    )
    write_csv(ROOT / "07_FAMILY_COUNTS.csv", ["family", "count"], [[k, v] for k, v in sorted(families.items())])
    write_csv(ROOT / "08_EXPECTED_BEHAVIOR_COUNTS.csv", ["expected_behavior", "count"], [[k, v] for k, v in sorted(behavior.items())])
    write_csv(
        ROOT / "FULL_EXTRACTIVE_AUDIT.csv",
        [
            "case_id",
            "pool",
            "family",
            "expected_behavior",
            "gold_mode",
            "required_prop_id",
            "required_prop_text",
            "support_ref",
            "support_role",
            "extractive_exact_match",
            "deterministic_normalized_match",
            "structural_certificate_match",
            "sentinel_atomic_mapping_pass",
            "context_or_distractor_used_as_authority",
            "hostile_semantic_review_required",
            "PASS_FAIL",
            "reason",
        ],
        audit_extractiveness(rows),
    )

    primary_matrix = build_matrix(rows=rows, runtime_candidate_sha=RUNTIME_CANDIDATE_SHA, bank_sha=bank_sha, limit=48, sentinel_rows=sentinels)
    holdout_matrix = build_holdout_matrix(rows=rows, runtime_candidate_sha=RUNTIME_CANDIDATE_SHA, bank_sha=bank_sha, limit=24)
    write_jsonl(ROOT / "LIVE_MATRIX.jsonl", primary_matrix)
    (ROOT / "LIVE_MATRIX_SUMMARY.json").write_text(
        json.dumps(
            {
                "schema_version": "m26-r2o-frozen-live-matrix/v2",
                "total": len(primary_matrix),
                "sentinels": sum(1 for row in primary_matrix if row["pool"] == "sentinel"),
                "broad_primary": sum(1 for row in primary_matrix if row["pool"] == "primary"),
                "control_count": sum(1 for row in primary_matrix if row["expected_behavior"] in {"abstain", "partial", "clarify-compatible"}),
                "families": sorted({row["family"] for row in primary_matrix}),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    write_jsonl(ROOT / "HOLDOUT_LIVE_MATRIX.jsonl", holdout_matrix)
    (ROOT / "HOLDOUT_LIVE_MATRIX_SUMMARY.json").write_text(
        json.dumps(
            {
                "schema_version": "m26-r2o-frozen-live-matrix/v2",
                "total": len(holdout_matrix),
                "controls": sum(1 for row in holdout_matrix if row["expected_behavior"] in {"abstain", "partial", "clarify-compatible"}),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )

    summary = {
        "TOTAL_CASES": len(rows),
        "PRIMARY_CASES": counts["primary"],
        "HOLDOUT_CASES": counts["holdout"],
        "SENTINELS": counts["sentinel"],
        "UNIQUE_SOURCE_IDENTITIES": census["unique_source_identities"],
        "UNIQUE_SOURCE_FILES": census["unique_source_files"],
        "SOURCE_FAMILY_COUNT": census["source_family_count"],
        "FAMILY_COUNTS": dict(sorted(families.items())),
        "EXPECTED_BEHAVIOR_COUNTS": dict(sorted(behavior.items())),
        "PRIMARY_LIVE_TRIALS": len(primary_matrix),
        "HOLDOUT_LIVE_TRIALS": len(holdout_matrix),
    }
    (ROOT / "bank_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
