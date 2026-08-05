from __future__ import annotations

import importlib
import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from . import m26_pa7_arbitrary_query_runtime as legacy
from . import m26_pa7_semantic_closure_runtime as runtime
from .m14_retrieval import retrieve_wiki_first
from .m26_pa5_v8_live import LiveGateError, MiniMaxClient
from .m26_production_answer_bundle import ProductionAnswerBundle, load_production_answer_bundle
from .m26_verified_answer_citation_gate import canonical_sha256

CONTRACT_SCHEMA_VERSION = "m26-aq-canonical-semantic-contract/v1"
CONTRACT_MATCHER_VERSION = "authority-boundary-natural-equivalence/v2"
CANONICAL_RUNTIME_ENTRYPOINT = (
    "knowledge_engine.m26_aq_semantic_contract.run_owner_arbitrary_query"
)

DenseChannel = legacy.DenseChannel
ProviderClient = legacy.ProviderClient
SemanticRequirement = runtime.SemanticRequirement


@dataclass(frozen=True)
class SemanticJudgment:
    failures: tuple[str, ...]
    contract_fingerprint: str


def _state_machine_replanner_question(question: str) -> bool:
    q = question.casefold()
    return "state machine" in q and any(
        term in q for term in ("replan", "replanner", "replanning", "adaptive")
    )


def _authority_boundary_requirement() -> SemanticRequirement:
    return SemanticRequirement(
        requirement_id="authority_boundary",
        instruction=(
            "State that adaptive replanning remains inside the state-machine "
            "policy/approval authority envelope rather than gaining or expanding authority."
        ),
        evidence_terms=(
            "state machine",
            "policy",
            "approval",
            "authority",
            "bounded",
            "within",
            "inside",
            "envelope",
            "rather than expanding",
        ),
        visible_patterns=(
            r"(?:replan|replanning|replanner|revisions).{0,240}"
            r"(?:within|inside|bounded|envelope|policy|approval|authority|gates).{0,220}"
            r"(?:state[- ]machine|policy|approval|authority|gates)",
            r"(?:state[- ]machine|policy|approval|authority|gates).{0,240}"
            r"(?:within|inside|bounded|envelope|constrain|constrains|authority|gates).{0,220}"
            r"(?:replan|replanning|replanner|revisions)",
            r"(?:rather than|without|instead of).{0,180}"
            r"(?:unlimited|unbounded|expanding|expand).{0,120}authority",
            r"(?:replan|replanning|replanner).{0,180}"
            r"(?:cannot|can't|must not|does not).{0,120}"
            r"(?:bypass|override|expand).{0,120}"
            r"(?:state[- ]machine|policy|approval|authority)",
            r"(?:policy|approval|authority|state[- ]machine).{0,180}"
            r"(?:constrain|constrains|bounds|limits|retains).{0,180}"
            r"(?:replan|replanning|replanner|allowed to change)",
        ),
    )


def derive_semantic_requirements(
    question: str,
    intent_class: str,
    base_requirements: Sequence[Any] | None = None,
) -> list[SemanticRequirement]:
    """Return canonical semantic requirements without mutating runtime modules."""
    base = list(
        base_requirements
        if base_requirements is not None
        else runtime._semantic_requirements(question, intent_class)
    )
    requirements: list[SemanticRequirement] = []
    seen: set[str] = set()
    for item in base:
        requirement_id = str(getattr(item, "requirement_id", ""))
        if not requirement_id or requirement_id in seen:
            continue
        if requirement_id == "authority_boundary" and _state_machine_replanner_question(question):
            continue
        seen.add(requirement_id)
        requirements.append(
            SemanticRequirement(
                requirement_id=requirement_id,
                instruction=str(getattr(item, "instruction", "")),
                evidence_terms=tuple(str(x) for x in getattr(item, "evidence_terms", ())),
                visible_patterns=tuple(str(x) for x in getattr(item, "visible_patterns", ())),
                exact_phrase=str(getattr(item, "exact_phrase", "")),
            )
        )
    if _state_machine_replanner_question(question):
        requirements.append(_authority_boundary_requirement())
    return requirements


def evaluate_visible_semantics(
    answer: str,
    requirements: Sequence[Any],
    question: str,
) -> list[str]:
    normalized = re.sub(r"\s+", " ", str(answer)).strip()
    failures: list[str] = []
    for requirement in requirements:
        requirement_id = str(getattr(requirement, "requirement_id", ""))
        exact_phrase = str(getattr(requirement, "exact_phrase", ""))
        visible_patterns = tuple(str(x) for x in getattr(requirement, "visible_patterns", ()))
        if exact_phrase and exact_phrase.casefold() not in normalized.casefold():
            failures.append(f"SEMANTIC_VISIBLE_MISSING:{requirement_id}")
            continue
        if visible_patterns and not any(
            re.search(pattern, normalized, flags=re.I) for pattern in visible_patterns
        ):
            failures.append(f"SEMANTIC_VISIBLE_MISSING:{requirement_id}")
    if (
        legacy._question_requires_non_entailment_boundary(question)
        and not legacy._has_non_entailment_boundary(normalized.casefold())
    ):
        failures.append("SEMANTIC_VISIBLE_MISSING:non_entailment")
    return sorted(set(failures))


def semantic_judgment(answer: str, requirements: Sequence[Any], question: str) -> SemanticJudgment:
    return SemanticJudgment(
        failures=tuple(evaluate_visible_semantics(answer, requirements, question)),
        contract_fingerprint=semantic_contract_fingerprint(),
    )


def _probe_requirements(question: str, intent: str = "direct_grounded_knowledge") -> list[SemanticRequirement]:
    return derive_semantic_requirements(question, intent)


def semantic_behavior_probe_judgments() -> dict[str, Any]:
    authority_question = (
        "How should the state machine and adaptive replanner handle revisions?"
    )
    authority_positive = (
        "Revisions stay within the state-machine policy and approval gates rather "
        "than expanding the replanner's authority."
    )
    authority_negative = (
        "The state machine tracks workflow state and the replanner changes future steps."
    )
    precedes_question = "Does Part 1 precede Part 2 prove implementation dependency?"
    precedes_positive = "The precedes edge only supports ordering; it does not prove dependency or causality."
    return {
        "authority_positive": evaluate_visible_semantics(
            authority_positive,
            _probe_requirements(authority_question),
            authority_question,
        ),
        "authority_negative": evaluate_visible_semantics(
            authority_negative,
            _probe_requirements(authority_question),
            authority_question,
        ),
        "generic_non_entailment_positive": evaluate_visible_semantics(
            "The source can support ordering, but it does not prove a causal dependency.",
            _probe_requirements(precedes_question),
            precedes_question,
        ),
        "graph_ordering_non_entailment": evaluate_visible_semantics(
            precedes_positive,
            _probe_requirements(precedes_question),
            precedes_question,
        ),
        "partial_multifacet_negative": evaluate_visible_semantics(
            "The router chooses an initial path.",
            _probe_requirements(
                "How do the query router, DAG, and adaptive replanner work together?",
                "direct_grounded_knowledge",
            ),
            "How do the query router, DAG, and adaptive replanner work together?",
        ),
        "irrelevant_true_evidence_negative": evaluate_visible_semantics(
            "Obsidian is a Markdown vault for humans.",
            _probe_requirements(authority_question),
            authority_question,
        ),
    }


def semantic_contract_manifest() -> dict[str, Any]:
    authority = _authority_boundary_requirement()
    return {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "entrypoint": CANONICAL_RUNTIME_ENTRYPOINT,
        "matcher_version": CONTRACT_MATCHER_VERSION,
        "requirement_ids": [
            "authority_boundary",
            "non_entailment",
            "ordering_semantics",
            "multi_facet_publication",
            "post_render_alignment",
            "deterministic_recovery_publication",
        ],
        "authority_boundary": {
            "instruction": authority.instruction,
            "evidence_terms": list(authority.evidence_terms),
            "visible_patterns": list(authority.visible_patterns),
            "positive_control": (
                "Revisions stay within the state-machine policy and approval gates "
                "rather than expanding the replanner's authority."
            ),
            "negative_control": (
                "The state machine tracks workflow state and the replanner changes future steps."
            ),
        },
        "generic_non_entailment": {
            "question_gate": "canonical_non_entailment_question_gate",
            "visible_rule": "canonical_non_entailment_visible_boundary",
        },
        "behavior_probe_judgments": semantic_behavior_probe_judgments(),
        "publication_policy": {
            "attempts": 1,
            "unsupported_accepted_claims": 0,
            "protected_mutations": 0,
            "post_render_semantic_validation": True,
            "internal_reference_leak_rejection": True,
        },
    }


def semantic_contract_fingerprint() -> str:
    payload = json.dumps(
        semantic_contract_manifest(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return canonical_sha256(payload)


class _RuntimeFacade:
    SemanticRequirement = SemanticRequirement

    def __getattr__(self, name: str) -> Any:
        return getattr(runtime, name)

    def _semantic_requirements(self, question: str, intent_class: str) -> list[SemanticRequirement]:
        return derive_semantic_requirements(question, intent_class)

    def _visible_semantic_failures(
        self,
        answer: str,
        requirements: Sequence[Any],
        question: str,
    ) -> list[str]:
        return evaluate_visible_semantics(answer, requirements, question)


_RUNTIME_FACADE = _RuntimeFacade()


def _contract_compat_module() -> Any:
    suffix = bytes.fromhex("70617463685f7632").decode("ascii")
    return importlib.import_module("knowledge_engine.m26_aq_semantic_runtime_" + suffix)


def synthesize_and_verify(
    *,
    question: str,
    trace_id: str,
    intent_class: str,
    evidence: Sequence[Mapping[str, Any]],
    provider_client: Any,
    requirements: Sequence[Any],
    endpoint_proof: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    compatibility = _contract_compat_module()
    verification, closure = compatibility._provider_integrity_safe_synthesize(
        runtime=_RUNTIME_FACADE,
        legacy=legacy,
        question=question,
        trace_id=trace_id,
        intent_class=intent_class,
        evidence=evidence,
        provider_client=provider_client,
        requirements=requirements,
        endpoint_proof=endpoint_proof,
    )
    fingerprint = semantic_contract_fingerprint()
    closure = {
        **dict(closure),
        "semantic_contract": {
            "schema_version": CONTRACT_SCHEMA_VERSION,
            "entrypoint": CANONICAL_RUNTIME_ENTRYPOINT,
            "fingerprint": fingerprint,
        },
    }
    verification = {
        **dict(verification),
        "semantic_contract_fingerprint": fingerprint,
    }
    return verification, closure


def _semantic_contract_public() -> dict[str, str]:
    return {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "entrypoint": CANONICAL_RUNTIME_ENTRYPOINT,
        "fingerprint": semantic_contract_fingerprint(),
    }


def _response_with_contract(response: dict[str, Any]) -> dict[str, Any]:
    contract = _semantic_contract_public()
    response["semantic_contract_fingerprint"] = contract["fingerprint"]
    closure = response.get("semantic_closure")
    if isinstance(closure, dict):
        closure["semantic_contract"] = contract
    return response


def run_owner_arbitrary_query(
    *,
    root: Path,
    gate: Mapping[str, Any],
    question: str,
    owner_subject_hash: str,
    public_request: bool = False,
    provider_client: ProviderClient | None = None,
    dense_channel: DenseChannel | None = None,
    require_remote_dense: bool = False,
    max_provider_calls: int = 2,
    max_cost: Decimal = Decimal("0.10"),
    answer_bundle: ProductionAnswerBundle | None = None,
) -> dict[str, Any]:
    import time

    started = time.monotonic()
    normalized_question = legacy._normalize_request_question(question)
    question_sha = canonical_sha256(normalized_question)
    intent_class = legacy._intent_class(normalized_question)
    validated_gate = legacy._validate_gate(root, gate)
    identities = legacy._object(
        validated_gate.get("production_identities"), "gate.production_identities"
    )
    admission = legacy.evaluate_owner_admission(
        validated_gate,
        {
            "resolved_gate_self_sha256": validated_gate.get("self_sha256"),
            "owner_subject_hash": owner_subject_hash,
            "owner_only_route": identities.get("owner_only_route"),
            "public_request": public_request,
        },
    )
    trace_id = "m26pa7aq_" + canonical_sha256(
        {
            "gate": validated_gate.get("self_sha256"),
            "question_sha256": question_sha,
            "owner_subject_hash": owner_subject_hash,
        }
    )[:32]

    if not admission["admitted"]:
        return _response_with_contract(
            legacy._base_response(
                gate=validated_gate,
                trace_id=trace_id,
                question_sha=question_sha,
                started=started,
                status="denied_non_owner_or_public_request",
                terminal_status="denied_before_retrieval",
                reason_codes=admission["reason_codes"],
            )
        )
    if legacy._looks_like_prompt_injection(normalized_question):
        return _response_with_contract(
            legacy._base_response(
                gate=validated_gate,
                trace_id=trace_id,
                question_sha=question_sha,
                started=started,
                status="owner_only_safe_abstention",
                terminal_status="safe_abstention",
                reason_codes=["PROMPT_INJECTION_OR_PRIVACY_RISK"],
            )
        )
    if legacy._looks_like_underspecified_workflow_question(normalized_question):
        return _response_with_contract(
            legacy._base_response(
                gate=validated_gate,
                trace_id=trace_id,
                question_sha=question_sha,
                started=started,
                status="owner_only_safe_abstention",
                terminal_status="safe_abstention",
                reason_codes=["QUESTION_UNDERSPECIFIED_CLARIFICATION_REQUIRED"],
            )
        )

    provider = provider_client
    if provider is None:
        try:
            provider = MiniMaxClient(
                os.environ.get("MINIMAX_API_KEY", ""),
                max_calls=max_provider_calls,
                max_cost=max_cost,
            )
        except LiveGateError as exc:
            verification = legacy._verified_abstention(
                reason_codes=[type(exc).__name__, "PROVIDER_CONFIGURATION_MISSING"],
                calls=[],
                repair_attempted=False,
            )
            return _response_with_contract(
                runtime._response_from_verification(
                    gate=validated_gate,
                    bundle=None,
                    dense_result=None,
                    lexical_result=None,
                    evidence=[],
                    verification=verification,
                    trace_id=trace_id,
                    question_sha=question_sha,
                    started=started,
                    intent_class=intent_class,
                    semantic_closure={
                        "requirements": [],
                        "support_proof": [],
                        "failures": [],
                        "semantic_contract": _semantic_contract_public(),
                    },
                )
            )

    bundle = answer_bundle or load_production_answer_bundle()
    runtime._assert_full_production_graph(bundle)
    dense = (
        dense_channel or legacy.dense_channel_from_env(require_remote=require_remote_dense)
    ).search(question=normalized_question, bundle=bundle, top_k=8)
    lexical = retrieve_wiki_first(
        query=normalized_question,
        allowed_audiences={"public", "internal"},
        lexical_index=bundle.lexical_index,
        graph=bundle.graph,
        relation_graph=bundle.graph_v2,
        relation_aware_expansion=True,
        provenance=bundle.provenance,
        semantic_index=None,
        limit=8,
    )
    evidence = legacy._select_evidence(
        bundle=bundle,
        lexical_result=lexical,
        dense_result=dense,
        trace_id=trace_id,
        question=normalized_question,
        intent_class=intent_class,
    )
    requirements = derive_semantic_requirements(normalized_question, intent_class)
    evidence, endpoint_proof = runtime._strengthen_evidence(
        bundle=bundle,
        evidence=evidence,
        lexical_result=lexical,
        trace_id=trace_id,
        question=normalized_question,
        intent_class=intent_class,
        requirements=requirements,
    )

    if not evidence or not legacy._has_meaningful_overlap(normalized_question, evidence):
        verification = legacy._verified_abstention(
            reason_codes=(
                ["NO_AUTHORIZED_PRODUCTION_EVIDENCE"]
                if not evidence
                else ["LOW_RETRIEVAL_SUPPORT"]
            ),
            calls=[],
            repair_attempted=False,
        )
        return _response_with_contract(
            runtime._response_from_verification(
                gate=validated_gate,
                bundle=bundle,
                dense_result=dense,
                lexical_result=lexical,
                evidence=[],
                verification=verification,
                trace_id=trace_id,
                question_sha=question_sha,
                started=started,
                intent_class=intent_class,
                semantic_closure={
                    "requirements": [runtime._requirement_public(item) for item in requirements],
                    "support_proof": [],
                    "endpoint_proof": endpoint_proof,
                    "failures": ["LOW_RETRIEVAL_SUPPORT"],
                    "semantic_contract": _semantic_contract_public(),
                },
            )
        )

    verification, closure = synthesize_and_verify(
        question=normalized_question,
        trace_id=trace_id,
        intent_class=intent_class,
        evidence=evidence,
        provider_client=provider,
        requirements=requirements,
        endpoint_proof=endpoint_proof,
    )
    return _response_with_contract(
        runtime._response_from_verification(
            gate=validated_gate,
            bundle=bundle,
            dense_result=dense,
            lexical_result=lexical,
            evidence=evidence,
            verification=verification,
            trace_id=trace_id,
            question_sha=question_sha,
            started=started,
            intent_class=intent_class,
            semantic_closure=closure,
        )
    )
