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
RELATION_AUTHORITY_REGISTRY_PATH = ROOT / "RELATION_AUTHORITY_REGISTRY.jsonl"
COMPARISON_AUTHORITY_REGISTRY_PATH = ROOT / "COMPARISON_AUTHORITY_REGISTRY.jsonl"
POSITIVE_FAMILY_ELIGIBILITY = {
    "definition": [
        "simple_definition",
        "contextual_definition",
        "paraphrase_equivalence",
        "narrow_factual",
        "short_query",
        "long_compositional_query",
        "multi_part",
        "broad_synthesis",
        "partially_sufficient_evidence",
    ],
    "role": [
        "role_responsibility",
        "narrow_factual",
        "short_query",
        "long_compositional_query",
        "multi_part",
        "broad_synthesis",
        "partially_sufficient_evidence",
    ],
    "effect": [
        "impact_effect",
        "causal_why",
        "narrow_factual",
        "short_query",
        "long_compositional_query",
        "multi_part",
        "broad_synthesis",
        "partially_sufficient_evidence",
    ],
    "causal": [
        "causal_why",
        "impact_effect",
        "narrow_factual",
        "short_query",
        "long_compositional_query",
        "multi_part",
        "broad_synthesis",
        "partially_sufficient_evidence",
    ],
    "process": [
        "how_process",
        "contextual_definition",
        "narrow_factual",
        "short_query",
        "long_compositional_query",
        "multi_part",
        "broad_synthesis",
        "partially_sufficient_evidence",
    ],
    "comparison_dimension": ["comparison"],
    "relationship": [
        "relationship",
        "narrow_factual",
        "short_query",
        "long_compositional_query",
        "multi_part",
        "broad_synthesis",
        "partially_sufficient_evidence",
    ],
    "example": [
        "examples",
        "narrow_factual",
        "short_query",
        "long_compositional_query",
        "multi_part",
        "broad_synthesis",
        "partially_sufficient_evidence",
    ],
    "tradeoff": ["trade_offs"],
    "component": [
        "architecture_components",
        "enumerative_list",
        "narrow_factual",
        "short_query",
        "long_compositional_query",
        "multi_part",
        "broad_synthesis",
        "partially_sufficient_evidence",
    ],
    "capability": [
        "capability_skill_requirement",
        "enumerative_list",
        "narrow_factual",
        "short_query",
        "long_compositional_query",
        "multi_part",
        "broad_synthesis",
        "partially_sufficient_evidence",
    ],
    "requirement": [
        "capability_skill_requirement",
        "enumerative_list",
        "narrow_factual",
        "short_query",
        "long_compositional_query",
        "multi_part",
        "broad_synthesis",
        "partially_sufficient_evidence",
    ],
    "enumeration": [
        "enumerative_list",
        "architecture_components",
        "narrow_factual",
        "short_query",
        "long_compositional_query",
        "multi_part",
        "broad_synthesis",
        "partially_sufficient_evidence",
    ],
    "factual": [
        "narrow_factual",
        "short_query",
        "long_compositional_query",
        "multi_part",
        "broad_synthesis",
        "partially_sufficient_evidence",
    ],
    "conflict": ["conflicting_evidence"],
    "provenance": ["provenance_source_trace"],
    "graph": ["graph_relationship"],
    "temporal": [],
    "context_only": [],
}
LOW_RISK_CONSUMER_FAMILIES = [
    "simple_definition",
    "contextual_definition",
    "role_responsibility",
    "how_process",
    "examples",
    "enumerative_list",
    "narrow_factual",
    "short_query",
    "long_compositional_query",
    "paraphrase_equivalence",
    "multi_part",
    "broad_synthesis",
    "partially_sufficient_evidence",
]
for _relation_kind in (
    "definition",
    "role",
    "effect",
    "causal",
    "process",
    "relationship",
    "example",
    "component",
    "capability",
    "requirement",
    "enumeration",
    "factual",
):
    POSITIVE_FAMILY_ELIGIBILITY[_relation_kind] = list(
        dict.fromkeys(
            [
                *POSITIVE_FAMILY_ELIGIBILITY.get(_relation_kind, []),
                *LOW_RISK_CONSUMER_FAMILIES,
            ]
        )
    )
HIGH_RISK_POSITIVE_FAMILIES = {
    "architecture_components",
    "impact_effect",
    "causal_why",
    "trade_offs",
    "capability_skill_requirement",
    "comparison",
    "relationship",
    "conflicting_evidence",
    "temporal_version",
    "provenance_source_trace",
    "graph_relationship",
}
REQUESTED_RELATION_FOR_NEGATIVE_FAMILY = {
    "impact_effect": "effect",
    "causal_why": "causal",
    "trade_offs": "tradeoff",
    "capability_skill_requirement": "requirement",
    "comparison": "comparison_dimension",
    "relationship": "relationship",
    "conflicting_evidence": "conflict",
    "temporal_version": "temporal",
    "causal_strengthening_negative": "causal",
    "universalization_negative": "universal",
    "modality_necessity_strengthening_negative": "necessity",
    "mixed_domain_distractor": "mixed_domain",
}
RELATION_AUTHORITY_REGISTRY: dict[str, dict[str, Any]] = {}
COMPARISON_AUTHORITY_REGISTRY: dict[str, dict[str, Any]] = {}

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


def concept_title(section_id: str) -> str:
    concept = concept_id_from_section(section_id).rsplit("/", 1)[-1]
    return concept.replace("-", " ").title()


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


def support_subject(support: dict[str, Any]) -> str:
    section_id = str(support.get("section_id", ""))
    if "#" in section_id:
        locator = section_locator(section_id)
        if re.search(r"(section_[0-9a-f]{8,}|dec [0-9a-f]{12,})", locator, re.I):
            return concept_title(section_id)
        return locator
    locator = str(support.get("locator", "")).strip()
    return locator or section_id or "the topic"


def first_matching_cue(text: str, patterns: list[str]) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            return match.group(0)
    return ""


def explicit_relation_cue(snippet: str, proposition_text: str) -> tuple[str, list[str], str]:
    text = f"{snippet}\n{proposition_text}"
    cue = first_matching_cue(
        text,
        [
            r"\btrade[- ]?off\b",
            r"\bversus\b",
            r"\bvs\.\b",
            r"\bat the cost of\b",
            r"\bbenefit[s]? / cost[s]?\b",
            r"\blatency / quality tension\b",
            r"\bsimplicity / control tension\b",
            r"\bwhile\b",
            r"\bhowever\b",
            r"\bbut\b",
        ],
    )
    if cue:
        return "tradeoff", [cue], "Explicit competing dimension or tension cue."

    cue = first_matching_cue(
        text,
        [
            r"\bbecause\b",
            r"\bso that\b",
            r"\bin order to\b",
            r"\btherefore\b",
            r"\bfor the purpose of\b",
            r"\bthe reason\b",
            r"\bprevents\b.{0,80}\bby\b",
            r"\benables\b.{0,80}\bby\b",
        ],
    )
    if cue:
        return "causal", [cue], "Explicit rationale, purpose, or causal cue."

    cue = first_matching_cue(
        text,
        [
            r"\benables?\b",
            r"\bprevents?\b",
            r"\breduces?\b",
            r"\bincreases?\b",
            r"\bchanges?\b",
            r"\bleads to\b",
            r"\bresults? in\b",
            r"\bproduces?\b",
            r"\bkeeps?\b",
            r"\baffects?\b",
        ],
    )
    if cue:
        return "effect", [cue], "Explicit outcome or effect cue."

    cue = first_matching_cue(
        text,
        [
            r"\bfirst\b",
            r"\bthen\b",
            r"\bnext\b",
            r"\bfinally\b",
            r"\bsequence\b",
            r"\bstages?\b",
            r"\bphases?\b",
            r"\blifecycle\b",
        ],
    )
    if cue:
        return "process", [cue], "Explicit ordered sequence or lifecycle cue."

    cue = first_matching_cue(
        text,
        [
            r"\bmust\b",
            r"\brequired\b",
            r"\brequires\b",
            r"\bshould receive\b",
            r"\bshould define\b",
            r"\bshould include\b",
            r"\bneeds?\b",
            r"\bcalls for\b",
            r"\bacceptance criteria\b",
        ],
    )
    if cue:
        return "requirement", [cue], "Explicit requirement cue."

    cue = first_matching_cue(
        text,
        [
            r"\bcan execute\b",
            r"\bcan\b",
            r"\bcapable\b",
            r"\bsupports?\b",
            r"\bmay\b",
        ],
    )
    if cue:
        return "capability", [cue], "Explicit capability cue."

    cue = first_matching_cue(
        text,
        [
            r"\bconsists of\b",
            r"\bincludes these components\b",
            r"\bcomponents?\b",
            r"\bparts?\b",
            r"\blayers?\b",
            r"\belements?\b",
            r"\bseparates?\b",
        ],
    )
    if cue:
        return "component", [cue], "Explicit component or structure cue."

    cue = first_matching_cue(
        text,
        [
            r"\bfor example\b",
            r"\bexamples include\b",
            r"\bsuch as\b",
        ],
    )
    if cue:
        return "example", [cue], "Explicit example cue."

    cue = first_matching_cue(
        text,
        [
            r"\bowns?\b",
            r"\bcontrols?\b",
            r"\bperforms?\b",
            r"\bverifies?\b",
            r"\bdecides?\b",
            r"\bis responsible for\b",
            r"\bdecomposes?\b",
            r"\bmanages?\b",
        ],
    )
    if cue:
        return "role", [cue], "Explicit action, function, or ownership cue."

    cue = first_matching_cue(
        text,
        [
            r"\baccounts for\b",
            r"\badopts?\b",
            r"\bbound to\b",
            r"\brelated to\b",
            r"\breplaces\b",
            r"\bmaps? to\b",
        ],
    )
    if cue:
        return "relationship", [cue], "Explicit relation between named concepts."

    cue = first_matching_cue(
        text,
        [
            r"\bis defined as\b",
            r"\bmeans\b",
            r"\brefers to\b",
            r"\brepresents\b",
            r"\bis the\b",
            r"\bis a\b",
            r"\bare\b",
            r"\bdefines\b",
        ],
    )
    if cue:
        return "definition", [cue], "Explicit identity, meaning, or category cue."

    if re.search(r"(^|\n)\s*[-*]\s+", snippet) or snippet.count(";") >= 3:
        return "enumeration", ["bounded list"], "Explicit bounded list structure."

    return "factual", ["exact factual snippet"], "Direct factual source assertion."


def authority_id_for(
    *,
    source_identity: str,
    section_id: str,
    exact_support_snippet: str,
    relation_kind: str,
    subject: str,
    object_or_complement: str,
) -> str:
    payload = "\0".join(
        [
            source_identity,
            section_id,
            exact_support_snippet,
            relation_kind,
            subject,
            object_or_complement,
        ]
    )
    return "rel_auth_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def register_relation_authority(
    *,
    support: dict[str, Any],
    relation_kind: str,
    subject: str,
    predicate: str,
    object_or_complement: str,
    cue_spans: list[str],
    certificate_mode: str,
    authority_note: str,
    manual_hostile_review_required: bool = False,
    positive_family_eligibility: list[str] | None = None,
) -> str:
    exact_support_snippet = str(support.get("exact_support_snippet", ""))
    matched_cues = [cue for cue in cue_spans if cue and cue in exact_support_snippet]
    if not matched_cues and exact_support_snippet:
        matched_cues = [exact_support_snippet.strip()[:120]]
    authority_id = authority_id_for(
        source_identity=str(support.get("source_identity", "")),
        section_id=str(support.get("section_id", "")),
        exact_support_snippet=exact_support_snippet,
        relation_kind=relation_kind,
        subject=subject,
        object_or_complement=object_or_complement,
    )
    RELATION_AUTHORITY_REGISTRY[authority_id] = {
        "authority_id": authority_id,
        "source_identity": str(support.get("source_identity", "")),
        "section_id": str(support.get("section_id", "")),
        "locator": str(support.get("locator", "")),
        "exact_support_snippet": exact_support_snippet,
        "relation_kind": relation_kind,
        "subject": subject,
        "predicate": predicate,
        "object_or_complement": object_or_complement,
        "cue_spans": matched_cues,
        "certificate_mode": certificate_mode,
        "positive_family_eligibility": positive_family_eligibility
        if positive_family_eligibility is not None
        else POSITIVE_FAMILY_ELIGIBILITY.get(relation_kind, []),
        "negative_upgrade_families": [],
        "authority_note": authority_note,
        "manual_hostile_review_required": manual_hostile_review_required,
    }
    return authority_id


def structural_relation_from_support(
    support: dict[str, Any],
    proposition_text: str,
) -> tuple[str, str, str, str, list[str], str]:
    if support.get("graph_certificate"):
        graph_certificate = support["graph_certificate"]
        return (
            "graph",
            str(graph_certificate.get("source_node_id", support_subject(support))),
            "graph",
            str(graph_certificate.get("target_node_id", proposition_text)),
            [str(graph_certificate.get("edge_id", support.get("exact_support_snippet", "")))],
            "Structured graph edge authority.",
        )
    if support.get("provenance_certificate"):
        provenance_certificate = support["provenance_certificate"]
        return (
            "provenance",
            str(provenance_certificate.get("record_id", support_subject(support))),
            "provenance",
            proposition_text,
            [str(provenance_certificate.get("record_id", support.get("exact_support_snippet", "")))],
            "Structured provenance record authority.",
        )
    return (
        "temporal",
        support_subject(support),
        "temporal",
        proposition_text,
        ["observed_temporal_record_count"],
        "Structured temporal insufficiency authority.",
    )


def sentinel_positive_eligibility(proposition_text: str, support: dict[str, Any]) -> list[str]:
    text = f"{support.get('source_identity', '')} {proposition_text}".lower()
    if "product manager" in text or "pm-" in text:
        return [
            "simple_definition",
            "contextual_definition",
            "role_responsibility",
            "capability_skill_requirement",
            "narrow_factual",
        ]
    if "skill | what method should the agent follow" in text:
        return [
            "simple_definition",
            "contextual_definition",
            "capability_skill_requirement",
            "narrow_factual",
        ]
    if "research should help" in text:
        return ["relationship", "role_responsibility", "narrow_factual"]
    return ["narrow_factual"]


def build_relation_certificate(
    *,
    family: str,
    behavior: str,
    proposition_text: str,
    supports: list[dict[str, Any]],
    certificate_mode: str,
) -> dict[str, Any]:
    support = supports[0] if supports else {}
    subject = support_subject(support) if support else "the topic"
    object_or_complement = proposition_text.strip()
    cue_spans: list[str] = []
    authority_note = "No source support was available."
    if certificate_mode == "structural":
        relation_kind, subject, predicate, object_or_complement, cue_spans, authority_note = (
            structural_relation_from_support(support, proposition_text)
        )
    elif certificate_mode == "sentinel":
        relation_kind, cue_spans, authority_note = explicit_relation_cue(
            str(support.get("exact_support_snippet", "")),
            proposition_text,
        )
        if "Skill | What method should the agent follow" in proposition_text:
            relation_kind = "requirement"
            cue_spans = ["should"]
            authority_note = "Manual sentinel authority from the Skill table row."
        elif "Research should help you recover" in proposition_text:
            relation_kind = "relationship"
            cue_spans = ["Research should help"]
            authority_note = "Manual sentinel authority for user-research role in PM workflow."
        elif "Product Manager" in proposition_text:
            relation_kind = "requirement"
            cue_spans = ["need"]
            authority_note = "Manual sentinel authority for PM skill requirement evidence."
        predicate = relation_kind
    else:
        relation_kind, cue_spans, authority_note = explicit_relation_cue(
            "\n\n".join(str(item.get("exact_support_snippet", "")) for item in supports),
            proposition_text,
        )
        predicate = relation_kind

    if relation_kind == "relationship":
        quoted = re.findall(r"`([^`]+)`", proposition_text)
        if "Source PR #19 review item" in proposition_text:
            object_or_complement = "Source PR #19 review item"
        elif "Source PR #19 item" in proposition_text and quoted:
            object_or_complement = f"Source PR #19 item {quoted[0]}"
        elif quoted:
            object_or_complement = quoted[0]
    if relation_kind == "graph" and supports:
        graph_support = next(
            (support for support in supports if support.get("graph_certificate")),
            supports[0],
        )
        graph_certificate = graph_support.get("graph_certificate", {})
        subject = str(graph_certificate.get("source_node_id", subject))
        object_or_complement = str(graph_certificate.get("target_node_id", object_or_complement))
    positive_family_eligibility = (
        sentinel_positive_eligibility(proposition_text, support)
        if certificate_mode == "sentinel"
        else POSITIVE_FAMILY_ELIGIBILITY.get(relation_kind, [])
    )
    authority_ids = []
    for item in supports:
        authority_ids.append(
            register_relation_authority(
                support=item,
                relation_kind=relation_kind,
                subject=subject,
                predicate=predicate,
                object_or_complement=object_or_complement,
                cue_spans=cue_spans,
                certificate_mode=certificate_mode,
                authority_note=authority_note,
                manual_hostile_review_required=relation_kind
                in {
                    "effect",
                    "causal",
                    "tradeoff",
                    "requirement",
                    "capability",
                    "relationship",
                    "comparison_dimension",
                    "conflict",
                    "temporal",
                    "provenance",
                    "graph",
                },
                positive_family_eligibility=positive_family_eligibility,
            )
        )
    return {
        "relation_kind": relation_kind,
        "subject": subject,
        "predicate": predicate,
        "object_or_complement": object_or_complement,
        "source_support_ids": [support["support_id"] for support in supports],
        "source_relation_authority_ids": authority_ids,
        "positive_family_eligibility": positive_family_eligibility,
        "negative_family_eligibility": [family] if behavior == "abstain" else [],
        "certificate_mode": certificate_mode,
    }


def natural_question_for(
    *,
    family: str,
    behavior: str,
    question: str,
    proposition: dict[str, Any],
    case_id: str,
) -> str:
    if case_id.startswith("SENTINEL-"):
        return question
    if family in {"provenance_source_trace", "graph_relationship", "temporal_version"}:
        return question
    certificate = proposition["relation_certificate"]
    subject = certificate["subject"]
    relation_kind = certificate["relation_kind"]
    if behavior == "abstain":
        return question
    if behavior == "partial":
        return f"What does {subject} establish, and what remains unresolved?"
    if family == "comparison":
        comparison = proposition.get("comparison_certificate", {})
        left = comparison.get("left_subject", "the first topic")
        right = comparison.get("right_subject", "the second topic")
        dimension = comparison.get("dimension", "their stated role")
        return f"How do {left} and {right} differ on {dimension}?"
    if relation_kind == "definition":
        return f"What is {subject}?"
    if relation_kind == "role":
        return f"What does {subject} do?"
    if relation_kind == "effect":
        return f"What effect does {subject} have?"
    if relation_kind == "causal":
        return f"Why does {subject} matter?"
    if relation_kind == "process":
        return f"How does {subject} work?"
    if relation_kind == "relationship":
        return f"How is {subject} related to {certificate['object_or_complement']}?"
    if relation_kind == "example":
        return f"What examples of {subject} are given?"
    if relation_kind == "tradeoff":
        return f"What trade-off does {subject} describe?"
    if relation_kind == "component":
        return f"What are the main components of {subject}?"
    if relation_kind in {"capability", "requirement"}:
        return f"What does {subject} require?"
    if relation_kind == "enumeration":
        return f"What items are listed for {subject}?"
    if family == "broad_synthesis":
        return f"What does the corpus say about {subject}?"
    if family == "multi_part":
        return f"What does {subject} say about its parts?"
    return f"What does {subject} say?"


def requested_relation_for_family(family: str) -> str:
    return REQUESTED_RELATION_FOR_NEGATIVE_FAMILY.get(family, family)


def convert_to_negative_relation_control(record: dict[str, Any], reason: str) -> None:
    family = record["family"]
    requested_relation = requested_relation_for_family(family)
    record["expected_behavior"] = "abstain"
    record["expected_behavior_set"] = ["abstain"]
    record["expected_terminal_set"] = ["safe_abstention", "owner_only_safe_abstention"]
    record["minimum_material_claims"] = 0
    record["negative_control_of"] = record.get("negative_control_of") or f"unsupported-{requested_relation}"
    record["requested_unsupported_relation_kind"] = requested_relation
    record["supported_relation_authority_ids"] = [
        authority_id
        for prop in record.get("required_propositions", [])
        for authority_id in prop.get("relation_certificate", {}).get(
            "source_relation_authority_ids", []
        )
    ]
    record["forbidden_inferences"] = [
        {
            "inference_id": f"{record['case_id']}-R5F01",
            "forbidden_text_or_relation": requested_relation,
            "reason": reason,
        }
    ]
    for prop in record["required_propositions"]:
        prop["gold_mode"] = GOLD_MODE_CONTEXT_ONLY
        prop["relation_type"] = "context_only"
        prop["entailment_note"] = (
            "The source supports only the certified weaker relation; it does not "
            f"support the requested {requested_relation} relation."
        )


def comparison_authority_id(
    left_authority_id: str,
    right_authority_id: str,
    dimension: str,
) -> str:
    payload = f"{left_authority_id}\0{right_authority_id}\0{dimension}"
    return "cmp_auth_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def register_comparison_authority(
    *,
    left_authority_id: str,
    right_authority_id: str,
    left_subject: str,
    right_subject: str,
    dimension: str,
    left_value_proposition: str,
    right_value_proposition: str,
    comparison_statement: str,
    manual_entailment_note: str,
) -> str:
    authority_id = comparison_authority_id(left_authority_id, right_authority_id, dimension)
    COMPARISON_AUTHORITY_REGISTRY[authority_id] = {
        "comparison_authority_id": authority_id,
        "left_authority_id": left_authority_id,
        "right_authority_id": right_authority_id,
        "left_subject": left_subject,
        "right_subject": right_subject,
        "dimension": dimension,
        "left_value_proposition": left_value_proposition,
        "right_value_proposition": right_value_proposition,
        "comparison_statement": comparison_statement,
        "manual_entailment_note": manual_entailment_note,
    }
    return authority_id


def try_apply_curated_comparison(record: dict[str, Any]) -> bool:
    if len(record["required_propositions"]) != 1 or len(record["gold_support"]) < 2:
        return False
    supports = record["gold_support"]
    combined = "\n".join(support["exact_support_snippet"] for support in supports).lower()
    if not (
        "completion is a state transition owned" in combined
        and "system of record that owns authoritative run identity" in combined
    ):
        return False
    prop = record["required_propositions"][0]
    cert = prop["relation_certificate"]
    source_authority_ids = cert.get("source_relation_authority_ids", [])
    if len(source_authority_ids) < 2:
        return False
    left_subject = "completion authority"
    right_subject = "canonical run authority"
    dimension = "what authority each source says owns"
    comparison_statement = (
        "Completion authority owns the completion state transition; canonical run "
        "authority owns authoritative run identity, state, transitions, evidence "
        "pointers, approvals, and terminal status."
    )
    comparison_id = register_comparison_authority(
        left_authority_id=source_authority_ids[0],
        right_authority_id=source_authority_ids[1],
        left_subject=left_subject,
        right_subject=right_subject,
        dimension=dimension,
        left_value_proposition=supports[0]["exact_support_snippet"],
        right_value_proposition=supports[1]["exact_support_snippet"],
        comparison_statement=comparison_statement,
        manual_entailment_note=(
            "Both sides explicitly state ownership; the comparison dimension is "
            "therefore shared and source-defined."
        ),
    )
    comparison_certificate = {
        "comparison_authority_id": comparison_id,
        "left_subject": left_subject,
        "right_subject": right_subject,
        "dimension": dimension,
        "left_prop_ids": [prop["proposition_id"]],
        "right_prop_ids": [prop["proposition_id"]],
    }
    record["comparison_certificate"] = comparison_certificate
    prop["comparison_certificate"] = comparison_certificate
    prop["relation_certificate"] = {
        **cert,
        "relation_kind": "comparison_dimension",
        "predicate": "comparison_dimension",
        "subject": left_subject,
        "object_or_complement": right_subject,
        "positive_family_eligibility": ["comparison"],
        "comparison_authority_id": comparison_id,
    }
    record["question"] = (
        "How do completion authority and canonical run authority differ in what "
        "authority each source says owns?"
    )
    return True


def refresh_relation_certificate(
    record: dict[str, Any],
    *,
    certificate_mode: str | None = None,
) -> None:
    supports_by_id = {support["support_id"]: support for support in record["gold_support"]}
    behavior = record["expected_behavior"]
    for proposition in record["required_propositions"]:
        supports = [
            supports_by_id[ref]
            for ref in proposition.get("support_refs", [])
            if ref in supports_by_id
        ]
        mode = certificate_mode
        if mode is None:
            mode = "structural" if proposition.get("gold_mode") == GOLD_MODE_STRUCTURAL else "extractive"
            if proposition.get("gold_mode") == GOLD_MODE_SENTINEL_SYNTHESIS:
                mode = "sentinel"
        proposition["relation_certificate"] = build_relation_certificate(
            family=record["family"],
            behavior=behavior,
            proposition_text=proposition["proposition_text"],
            supports=supports,
            certificate_mode=mode,
        )


def enrich_record_relation_metadata(record: dict[str, Any]) -> None:
    if record["expected_behavior"] == "partial" and not record.get(
        "unanswered_dimensions_expected"
    ):
        record["unanswered_dimensions_expected"] = ["unsupported_requested_dimension"]
    refresh_relation_certificate(record)
    if record["family"] == "comparison" and record["expected_behavior"] in {"answer", "partial"}:
        if not try_apply_curated_comparison(record):
            convert_to_negative_relation_control(
                record,
                "No curated two-sided comparison authority with a shared source-defined dimension.",
            )
    if record["family"] == "multi_part" and record["expected_behavior"] in {"answer", "partial"}:
        record["multipart_clause_certificate"] = {
            "supported_prop_ids": [
                proposition["proposition_id"]
                for proposition in record["required_propositions"]
            ],
            "unanswered_dimensions": list(record.get("unanswered_dimensions_expected", [])),
        }
    if record["family"] == "broad_synthesis" and record["expected_behavior"] == "answer":
        record["broad_synthesis_certificate"] = {
            "atomic_prop_ids": [
                proposition["proposition_id"]
                for proposition in record["required_propositions"]
            ],
            "support_ids": [
                ref
                for proposition in record["required_propositions"]
                for ref in proposition.get("support_refs", [])
            ],
        }
    if (
        record["expected_behavior"] in {"answer", "partial"}
        and record["family"] in HIGH_RISK_POSITIVE_FAMILIES
    ):
        eligibility = {
            family
            for prop in record["required_propositions"]
            for family in prop["relation_certificate"].get("positive_family_eligibility", [])
        }
        if record["family"] not in eligibility:
            convert_to_negative_relation_control(
                record,
                "Source-first relation authority does not certify the requested positive family.",
            )
    if record["expected_behavior"] in {"answer", "partial"}:
        record["question"] = natural_question_for(
            family=record["family"],
            behavior=record["expected_behavior"],
            question=record["question"],
            proposition=record["required_propositions"][0],
            case_id=record["case_id"],
        )


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
        proposition_text = sentinel_proposition_text(case_id, support)
        required.append(
            {
                "proposition_id": proposition_id,
                "proposition_text": proposition_text,
                "gold_mode": GOLD_MODE_SENTINEL_SYNTHESIS,
                "hostile_semantic_review_required": True,
                "extractive_certificate": extractive_certificate([support]),
                "relation_certificate": build_relation_certificate(
                    family="contextual_definition"
                    if case_id.startswith("SENTINEL-Q2")
                    else "role_responsibility"
                    if case_id.startswith("SENTINEL-Q3")
                    else "capability_skill_requirement",
                    behavior="answer",
                    proposition_text=proposition_text,
                    supports=[support],
                    certificate_mode="sentinel",
                ),
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
    family: str,
    behavior: str,
    supports: list[dict[str, Any]],
    proposition_text: str | None = None,
) -> list[dict[str, Any]]:
    proposition_id = prop_id_for_case(case_id)
    refs = direct_authority_refs(supports, proposition_id)
    gold_mode = GOLD_MODE_CONTEXT_ONLY if behavior == "abstain" else GOLD_MODE_EXTRACTIVE
    text = proposition_text or proposition_text_from_support(supports)
    return [
        {
            "proposition_id": proposition_id,
            "proposition_text": text,
            "gold_mode": gold_mode,
            "hostile_semantic_review_required": False,
            "extractive_certificate": extractive_certificate(supports),
            "relation_certificate": build_relation_certificate(
                family=family,
                behavior=behavior,
                proposition_text=text,
                supports=supports,
                certificate_mode="extractive",
            ),
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
            case_id, family or source_case["family"], behavior, direct_supports, proposition_text
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
                "relation_certificate": build_relation_certificate(
                    family=family,
                    behavior="abstain"
                    if family == "temporal_version"
                    else (
                        "partial"
                        if family in {"ambiguous_clarification", "partially_sufficient_evidence"}
                        else "answer"
                    ),
                    proposition_text=proposition_text,
                    supports=[support],
                    certificate_mode="extractive",
                ),
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

    for record in records:
        enrich_record_relation_metadata(record)

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


EVALUATOR_NATIVE_PHRASES = (
    "compare the two cited sections",
    "synthesize the two cited sections",
    "what relationship does the source state for",
    "how would you restate the supported point",
    "what exact factual point is stated in",
    "using only the cited source",
    "cited source",
    "cited sections",
    "supported point",
    "gold",
    "evidence",
)


def natural_question_pass(row: dict[str, Any]) -> bool:
    if row["family"] == "provenance_source_trace":
        return True
    if row["expected_behavior"] not in {"answer", "partial"}:
        return True
    question = str(row["question"]).lower()
    return not any(phrase in question for phrase in EVALUATOR_NATIVE_PHRASES)


def audit_relation_alignment(rows: list[dict[str, Any]]) -> list[list[Any]]:
    audit_rows: list[list[Any]] = []
    for row in rows:
        for prop in row["required_propositions"]:
            cert = prop.get("relation_certificate", {})
            positive_eligibility = cert.get("positive_family_eligibility", [])
            positive = row["expected_behavior"] in {"answer", "partial"}
            question_family_relation_match = (
                row["family"] in positive_eligibility if positive else True
            )
            negative_absent = (
                row["family"] not in positive_eligibility
                if row["expected_behavior"] == "abstain"
                else True
            )
            comparison_cert = (
                bool(row.get("comparison_certificate", {}).get("dimension"))
                if row["family"] == "comparison" and positive
                else True
            )
            multipart_cert = (
                bool(row.get("multipart_clause_certificate", {}).get("supported_prop_ids"))
                if row["family"] == "multi_part" and positive
                else True
            )
            partial_cert = (
                bool(row.get("unanswered_dimensions_expected"))
                if row["expected_behavior"] == "partial"
                else True
            )
            pass_fail = "PASS"
            reason = "ok"
            if not natural_question_pass(row):
                pass_fail = "FAIL"
                reason = "evaluator_native_positive_question"
            elif not question_family_relation_match:
                pass_fail = "FAIL"
                reason = "question_family_relation_mismatch"
            elif not negative_absent:
                pass_fail = "FAIL"
                reason = "negative_requested_relation_present"
            elif not comparison_cert:
                pass_fail = "FAIL"
                reason = "comparison_dimension_missing"
            elif not multipart_cert:
                pass_fail = "FAIL"
                reason = "multipart_clause_coverage_missing"
            elif not partial_cert:
                pass_fail = "FAIL"
                reason = "partial_unanswered_coverage_missing"
            audit_rows.append(
                [
                    row["case_id"],
                    row["pool"],
                    row["family"],
                    row["expected_behavior"],
                    row["question"],
                    natural_question_pass(row),
                    prop["proposition_id"],
                    cert.get("relation_kind", ""),
                    "|".join(positive_eligibility),
                    question_family_relation_match,
                    all(
                        ref in cert.get("source_support_ids", [])
                        for ref in prop.get("support_refs", [])
                    ),
                    negative_absent,
                    comparison_cert,
                    multipart_cert,
                    partial_cert,
                    pass_fail,
                    reason,
                ]
            )
    return audit_rows


def audit_registry_source_cues() -> list[list[Any]]:
    rows: list[list[Any]] = []
    for authority in sorted(
        RELATION_AUTHORITY_REGISTRY.values(),
        key=lambda item: item["authority_id"],
    ):
        snippet = str(authority["exact_support_snippet"])
        cue_spans = list(authority.get("cue_spans", []))
        byte_match = bool(cue_spans) and all(str(cue) in snippet for cue in cue_spans)
        pass_fail = "PASS" if byte_match else "FAIL"
        rows.append(
            [
                authority["authority_id"],
                authority["source_identity"],
                authority["section_id"],
                authority["relation_kind"],
                "|".join(str(cue) for cue in cue_spans),
                byte_match,
                pass_fail,
                "ok" if pass_fail == "PASS" else "cue_span_not_in_exact_support_snippet",
            ]
        )
    return rows


def audit_sentinel_relations(rows: list[dict[str, Any]]) -> list[list[Any]]:
    audit_rows: list[list[Any]] = []
    for row in rows:
        if row["pool"] != "sentinel":
            continue
        certificates = [
            prop["relation_certificate"] for prop in row["required_propositions"]
        ]
        audit_rows.append(
            [
                row["case_id"],
                row["question"],
                "|".join(prop["proposition_id"] for prop in row["required_propositions"]),
                "|".join(cert["relation_kind"] for cert in certificates),
                "|".join(
                    authority_id
                    for cert in certificates
                    for authority_id in cert.get("source_relation_authority_ids", [])
                ),
                "PASS",
                "Sentinel question preserved with bounded manual source authority.",
            ]
        )
    return audit_rows


def write_registry_jsonl(path: Path, rows: dict[str, dict[str, Any]], key: str) -> None:
    ordered = sorted(rows.values(), key=lambda item: str(item[key]))
    write_jsonl(path, ordered)


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
    RELATION_AUTHORITY_REGISTRY.clear()
    COMPARISON_AUTHORITY_REGISTRY.clear()
    records, _, _ = build_primary_holdout_bank()
    primary, holdout, sentinels = group_by_pool(records)
    bank_sha = canonical_bank_sha(primary, holdout, sentinels)

    ROOT.mkdir(parents=True, exist_ok=True)
    write_registry_jsonl(
        RELATION_AUTHORITY_REGISTRY_PATH,
        RELATION_AUTHORITY_REGISTRY,
        "authority_id",
    )
    write_registry_jsonl(
        COMPARISON_AUTHORITY_REGISTRY_PATH,
        COMPARISON_AUTHORITY_REGISTRY,
        "comparison_authority_id",
    )
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
    write_csv(
        ROOT / "RELATION_ALIGNMENT_AUDIT.csv",
        [
            "case_id",
            "pool",
            "family",
            "expected_behavior",
            "question",
            "natural_question_pass",
            "prop_id",
            "relation_kind",
            "positive_family_eligibility",
            "question_family_relation_match",
            "required_support_direct",
            "negative_requested_relation_absent",
            "comparison_dimension_cert",
            "multipart_clause_coverage",
            "partial_unanswered_coverage",
            "PASS_FAIL",
            "reason",
        ],
        audit_relation_alignment(rows),
    )
    write_csv(
        ROOT / "REGISTRY_SOURCE_CUE_AUDIT.csv",
        [
            "authority_id",
            "source_identity",
            "section_id",
            "relation_kind",
            "cue_spans",
            "extractive_cue_byte_match",
            "PASS_FAIL",
            "reason",
        ],
        audit_registry_source_cues(),
    )
    write_csv(
        ROOT / "SENTINEL_RELATION_AUDIT.csv",
        [
            "case_id",
            "question",
            "prop_id",
            "relation_kind",
            "authority_ids",
            "PASS_FAIL",
            "reason",
        ],
        audit_sentinel_relations(rows),
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
