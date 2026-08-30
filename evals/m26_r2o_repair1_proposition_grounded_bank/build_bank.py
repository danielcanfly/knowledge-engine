from __future__ import annotations

import csv
import hashlib
import json
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
        "support_roles": ["primary", "primary", "primary", "context"],
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
        "support_roles": ["primary", "primary", "primary", "context"],
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
        "support_roles": ["primary", "primary", "primary", "context"],
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
        "support_roles": ["primary", "context", "context"],
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
        "support_roles": ["primary", "context", "context"],
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
        "support_roles": ["primary", "context"],
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
        "support_roles": ["primary", "context"],
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


def load_r2f_payloads() -> dict[str, Any]:
    return load_json(R2F_EVIDENCE)


def load_r2k_support() -> dict[str, Any]:
    return load_json(R2K_CITATION)


def make_support_id(case_id: str, index: int) -> str:
    return f"{case_id}-SUP{index:02d}"


def make_forbidden(case_id: str, text: str) -> list[dict[str, str]]:
    return [
        {
            "inference_id": f"{case_id}-F01",
            "forbidden_text_or_relation": text,
            "reason": "The source does not explicitly support this inference.",
        }
    ]


def proposition_text_from_support(supports: list[dict[str, Any]]) -> str:
    snippets = [s["exact_support_snippet"].strip() for s in supports]
    if not snippets:
        return "No proposition text available."
    if len(snippets) == 1:
        return snippets[0].rstrip(".") + "."
    return " ".join(snippets)


def relation_type_for_behavior(behavior: str) -> str:
    return {
        "answer": "direct_support",
        "partial": "partial_support",
        "abstain": "forbidden_inference",
        "clarify-compatible": "clarify_compatible",
    }[behavior]


def build_required_propositions(case_id: str, behavior: str, supports: list[dict[str, Any]], proposition_text: str | None = None) -> list[dict[str, Any]]:
    refs = [support["support_id"] for support in supports]
    return [
        {
            "proposition_id": f"{case_id}-PROP01",
            "proposition_text": proposition_text or proposition_text_from_support(supports),
            "relation_type": relation_type_for_behavior(behavior),
            "support_refs": refs,
            "entailment_note": (
                "Directly supported by the quoted source passages."
                if behavior == "answer"
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
    for index, support in enumerate(source_case["gold_support"], start=1):
        supports.append(
            {
                "support_id": make_support_id(case_id, index),
                "source_identity": support["source_identity"],
                "section_id": support["section_id"],
                "locator": support["locator"],
                "exact_support_snippet": support["exact_support_snippet"],
                "support_role": support["support_role"],
            }
        )
    forbidden_raw = source_case.get("forbidden_inferences", [])
    if forbidden_raw and isinstance(forbidden_raw[0], str):
        forbidden = [
            {
                "inference_id": f"{case_id}-F{idx:02d}",
                "forbidden_text_or_relation": text,
                "reason": "The source does not explicitly support this inference.",
            }
            for idx, text in enumerate(forbidden_raw, start=1)
        ]
    else:
        forbidden = forbidden_raw
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
        "required_propositions": build_required_propositions(case_id, behavior, supports, proposition_text),
        "optional_propositions": [],
        "forbidden_inferences": forbidden or make_forbidden(case_id, question or source_case["question"]),
        "gold_support": supports,
        "unanswered_dimensions_expected": list(source_case.get("unanswered_dimensions_expected", [])),
        "distinct_source_minimum": int(source_case["distinct_source_minimum"]),
        "graph_edge_required": bool(graph_edge_required if graph_edge_required is not None else source_case["graph_edge_required"]),
        "provenance_required": bool(provenance_required if provenance_required is not None else source_case["provenance_required"]),
        "temporal_versions_required": int(temporal_versions_required if temporal_versions_required is not None else source_case["temporal_versions_required"]),
        "paraphrase_group": paraphrase_group if paraphrase_group is not None else source_case.get("paraphrase_group", ""),
        "negative_control_of": negative_control_of if negative_control_of is not None else source_case.get("negative_control_of", ""),
        "derivation_notes": source_case["derivation_notes"] + " Reconstructed into proposition-grounded schema.",
    }
    return record


def build_holdout_replacement(case_id: str, family: str, question: str, source_identity: str, section_id: str, snippet: str, proposition_text: str, support_role: str = "primary") -> dict[str, Any]:
    support = {
        "support_id": f"{case_id}-SUP01",
        "source_identity": source_identity,
        "section_id": section_id,
        "locator": section_id.rsplit("#", 1)[-1].replace("-", " ").title(),
        "exact_support_snippet": snippet,
        "support_role": support_role,
    }
    return {
        "case_id": case_id,
        "family": family,
        "pool": "holdout",
        "risk_tags": [family],
        "question": question,
        "expected_behavior": "answer" if family not in {"ambiguous_clarification", "partially_sufficient_evidence", "temporal_version"} else "partial",
        "expected_behavior_set": ["answer" if family not in {"ambiguous_clarification", "partially_sufficient_evidence", "temporal_version"} else "partial"],
        "expected_terminal_set": ["verified_answer_ready_candidate", "owner_only_cited_answer"] if family not in {"ambiguous_clarification", "partially_sufficient_evidence", "temporal_version"} else ["verified_answer_ready_candidate", "owner_only_cited_answer", "owner_only_safe_abstention"],
        "minimum_material_claims": 1 if family not in {"ambiguous_clarification", "partially_sufficient_evidence", "temporal_version"} else 0,
        "maximum_unsupported_claims": 0,
        "required_propositions": [
            {
                "proposition_id": f"{case_id}-PROP01",
                "proposition_text": proposition_text,
                "relation_type": "direct_support" if family not in {"ambiguous_clarification", "partially_sufficient_evidence", "temporal_version"} else "partial_support",
                "support_refs": [support["support_id"]],
                "entailment_note": "Directly supported by the reconstructed source passage." if family not in {"ambiguous_clarification", "partially_sufficient_evidence", "temporal_version"} else "The source supports only a bounded or partial conclusion.",
            }
        ],
        "optional_propositions": [],
        "forbidden_inferences": make_forbidden(case_id, question),
        "gold_support": [support],
        "unanswered_dimensions_expected": ["newer_version"] if family == "temporal_version" else ([] if family not in {"ambiguous_clarification", "partially_sufficient_evidence"} else ["specific_resolution"]),
        "distinct_source_minimum": 1,
        "graph_edge_required": False,
        "provenance_required": False,
        "temporal_versions_required": 0 if family != "temporal_version" else 2,
        "paraphrase_group": "",
        "negative_control_of": "",
        "derivation_notes": "Reconstructed from pool-local accepted corpus material into proposition-grounded schema.",
    }


def build_sentinel_records() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for spec in SENTINELS:
        supports = []
        for index, (source_identity, section_id, snippet, role) in enumerate(spec["support_specs"], start=1):
            supports.append(
                {
                    "support_id": make_support_id(spec["case_id"], index),
                    "source_identity": source_identity,
                    "section_id": section_id,
                    "locator": section_id.rsplit("#", 1)[-1].replace("-", " ").title(),
                    "exact_support_snippet": snippet,
                    "support_role": role,
                }
            )
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
                "required_propositions": [
                    {
                        "proposition_id": f"{spec['case_id']}-PROP01",
                        "proposition_text": spec["proposition_text"],
                        "relation_type": "direct_support",
                        "support_refs": [support["support_id"] for support in supports],
                        "entailment_note": "Sentinel exactness is restored from the accepted-corpus evidence set.",
                    }
                ],
                "optional_propositions": [],
                "forbidden_inferences": make_forbidden(spec["case_id"], spec["question"]),
                "gold_support": supports,
                "unanswered_dimensions_expected": [],
                "distinct_source_minimum": 2 if spec["case_id"] == "SENTINEL-Q1-A" else 1,
                "graph_edge_required": False,
                "provenance_required": False,
                "temporal_versions_required": 0,
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
    proposition_overrides = {
        "BROAD-0004": "Validation strength should match task risk rather than claiming an unstated production-system effect.",
        "BROAD-0005": "A bounded executor should receive a step objective, allowed tools, expected output, completion criteria, prohibitions, budgets, and escalation policy.",
        "BROAD-0010": "Goal drift is controlled by re-contracting the task, recording a new decision, or stopping.",
        "BROAD-0011": "The source does not enumerate architecture components; it instead defines the harness boundary.",
        "BROAD-0029": "A direct path uses one bounded operation when the information, tools, and output contract are already known.",
        "BROAD-0061": "A pipeline divides work into a predetermined sequence of stages.",
    }

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
        if section_id == "concepts/goal-drift#control":
            proposition_text = "Drift should be handled by re-contracting the task, recording a new decision, or stopping."
        elif section_id == "concepts/completion-gate#gate-behavior":
            proposition_text = "The gate may accept, reject, request repair, defer for human decision, or mark the task blocked, and it should rely on durable evidence."
        elif section_id == "concepts/agent-execution-paths#controls-shared-by-every-structure":
            proposition_text = "Every execution structure should define trace IDs, persisted state, typed errors, timeouts, retries, idempotency, fallback, and escalation."
        elif section_id == "concepts/harnessability#assessment":
            proposition_text = "A highly harnessable workflow has stable inputs, explicit authority, deterministic or inspectable effects, typed failures, replayable evidence, and clear completion gates."
        elif section_id == "concepts/agent-planning-strategies#selection-sequence":
            proposition_text = "Use the least flexible mechanism that can reliably complete the task: deterministic logic first, then bounded ReAct, then Plan-and-Execute, then adaptive replanning."
        elif section_id == "concepts/item-turn-thread-protocol#item-turn-thread-protocol":
            proposition_text = "The item turn thread protocol separates typed interaction items, pausable work turns, and durable threads."
        elif section_id == "concepts/six-dimensional-map-of-llm-agent-architectures#reviewed-synthesis-dec-1f9025c488e9c83356e402ec4f859d11":
            proposition_text = "LLM agent architectures should be reviewed across separate engineering dimensions because multiple patterns can coexist at different layers of one production system."
        elif section_id == "concepts/durable-thread-state#durable-thread-state":
            proposition_text = "Durable thread state is persistent interaction state that survives client disconnects, spans turns, and preserves enough context to resume without repeating unsafe side effects."
        elif section_id == "concepts/harnessability#narrowed-scope":
            proposition_text = "Harnessability is specifically about bounding work by a task contract, observing durable state, verifying with evidence, stopping safely, and resuming without hidden chat memory."
        elif section_id == "concepts/request-boundary#security-role":
            proposition_text = "The request boundary is the first point where ACLs, tenant isolation, secret redaction, and mutation authority can be enforced before any model or tool observes the task."
        elif section_id == "concepts/harness#operational-role":
            proposition_text = "A useful harness makes proposals, tool calls, observations, approvals, failures, retries, and terminal outcomes visible as governed state."
        elif section_id == "concepts/agent-planning-strategies#plan-and-execute":
            proposition_text = "Plan-and-Execute creates a global task structure before carrying out individual steps and exposes requirements, ordering, dependencies, delegation, outputs, and completion state."
        elif section_id == "concepts/goal-drift#source-adoption":
            proposition_text = "This canonical concept accounts for Source PR #19 review item m23review_0df0b6cb698712b98425cc2b05265565 with Daniel's approve_new decision, and Source PR #19 remains a draft review surface that was not merged as-is."
        else:
            proposition_text = doc["body"].strip()
        if new_case_id == "R2O-PG-H044":
            # Use the current holdout source-adoption pair, not the primary one, to preserve disjointness.
            source_case = holdout_by_id["BROAD-0072"]
        holdout_new.append(
            build_case_from_source(
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
        )

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

    # Fix specific provenance records after conversion.
    provenance_subject_to_section = {
        "concepts/agent-execution-paths": "concepts/agent-execution-paths#human-in-the-loop",
        "concepts/agent-planning-strategies": "concepts/agent-planning-strategies#selection-sequence",
        "concepts/goal-drift": "concepts/goal-drift#source-adoption",
    }
    provenance_supports = {
        "concepts/agent-execution-paths": {
            "support_id": "R2O-PG-P030-SUP02",
            "source_identity": "provenance.json",
            "section_id": "concepts/agent-execution-paths",
            "locator": "agent-execution-paths provenance",
            "exact_support_snippet": json.dumps(prov["concepts/agent-execution-paths"], ensure_ascii=False),
            "support_role": "provenance_record",
        },
        "concepts/agent-planning-strategies": {
            "support_id": "R2O-PG-P062-SUP02",
            "source_identity": "provenance.json",
            "section_id": "concepts/agent-planning-strategies",
            "locator": "agent-planning-strategies provenance",
            "exact_support_snippet": json.dumps(prov["concepts/agent-planning-strategies"], ensure_ascii=False),
            "support_role": "provenance_record",
        },
        "concepts/goal-drift": {
            "support_id": "R2O-PG-H013-SUP02",
            "source_identity": "provenance.json",
            "section_id": "concepts/goal-drift",
            "locator": "goal-drift provenance",
            "exact_support_snippet": json.dumps(prov["concepts/goal-drift"], ensure_ascii=False),
            "support_role": "provenance_record",
        },
        "concepts/harness-agent-loop": {
            "support_id": "R2O-PG-P030-SUP03",
            "source_identity": "provenance.json",
            "section_id": "concepts/harness-agent-loop",
            "locator": "harness-agent-loop provenance",
            "exact_support_snippet": json.dumps(prov["concepts/harness-agent-loop"], ensure_ascii=False),
            "support_role": "provenance_record",
        },
    }
    for rec in records:
        if rec["case_id"] == "R2O-PG-P030":
            rec["provenance_required"] = True
            rec["required_propositions"][0]["support_refs"] = [rec["gold_support"][0]["support_id"], provenance_supports["concepts/harness-agent-loop"]["support_id"]]
            rec["gold_support"] = [rec["gold_support"][0], provenance_supports["concepts/harness-agent-loop"]]
            rec["required_propositions"][0]["proposition_text"] = "Human-in-the-loop is a supported execution-path concept in the reviewed corpus, and the provenance record points to the same concept."
            rec["required_propositions"][0]["relation_type"] = "direct_support"
            rec["forbidden_inferences"] = make_forbidden(rec["case_id"], rec["question"])
        elif rec["case_id"] == "R2O-PG-P062":
            rec["provenance_required"] = True
            planning_support = {
                **provenance_supports["concepts/agent-planning-strategies"],
                "support_id": "R2O-PG-P062-SUP03",
            }
            rec["required_propositions"][0]["support_refs"] = [rec["gold_support"][0]["support_id"], planning_support["support_id"]]
            rec["gold_support"].append(planning_support)
            rec["required_propositions"][0]["proposition_text"] = "Selection sequence is supported by the same agent-planning-strategies provenance record."
            rec["required_propositions"][0]["relation_type"] = "direct_support"
            rec["forbidden_inferences"] = make_forbidden(rec["case_id"], rec["question"])
        elif rec["case_id"] == "R2O-PG-H010":
            rec["provenance_required"] = True
            goal_drift_support = {
                **provenance_supports["concepts/goal-drift"],
                "support_id": "R2O-PG-H010-SUP02",
            }
            rec["required_propositions"][0]["support_refs"] = [rec["gold_support"][0]["support_id"], goal_drift_support["support_id"]]
            rec["gold_support"] = [rec["gold_support"][0], goal_drift_support]
            rec["required_propositions"][0]["proposition_text"] = "Source adoption is supported by the same goal-drift provenance record."
            rec["required_propositions"][0]["relation_type"] = "direct_support"
            rec["forbidden_inferences"] = make_forbidden(rec["case_id"], rec["question"])
        elif rec["case_id"] == "R2O-PG-H033":
            rec["gold_support"] = [rec["gold_support"][0]]
            rec["required_propositions"][0]["support_refs"] = [rec["gold_support"][0]["support_id"]]
            rec["required_propositions"][0]["proposition_text"] = "Goal drift can be handled by re-contracting the task, recording a new decision, or stopping."
            rec["required_propositions"][0]["relation_type"] = "direct_support"
            rec["forbidden_inferences"] = make_forbidden(rec["case_id"], rec["question"])
        elif rec["case_id"] == "R2O-PG-H013":
            rec["provenance_required"] = True
            goal_drift_support = {
                **provenance_supports["concepts/goal-drift"],
                "support_id": "R2O-PG-H013-SUP02",
            }
            rec["required_propositions"][0]["support_refs"] = [rec["gold_support"][0]["support_id"], goal_drift_support["support_id"]]
            rec["gold_support"].append(goal_drift_support)
            rec["required_propositions"][0]["proposition_text"] = "Source adoption is supported by the same goal-drift provenance record."
            rec["required_propositions"][0]["relation_type"] = "direct_support"
            rec["forbidden_inferences"] = make_forbidden(rec["case_id"], rec["question"])
        elif rec["case_id"] == "R2O-PG-H044":
            rec["provenance_required"] = True
            goal_drift_support = {
                **provenance_supports["concepts/goal-drift"],
                "support_id": "R2O-PG-H044-SUP02",
            }
            rec["required_propositions"][0]["support_refs"] = [rec["gold_support"][0]["support_id"], goal_drift_support["support_id"]]
            rec["gold_support"] = [rec["gold_support"][0], goal_drift_support]
            rec["required_propositions"][0]["proposition_text"] = "The source-adoption state is traceable to the goal-drift provenance record and the draft review surface."
            rec["required_propositions"][0]["relation_type"] = "partial_support"
            rec["forbidden_inferences"] = make_forbidden(rec["case_id"], rec["question"])
        if rec["family"] == "temporal_version":
            rec["temporal_versions_required"] = 1

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
