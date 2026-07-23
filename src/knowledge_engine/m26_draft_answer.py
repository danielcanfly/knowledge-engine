from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .errors import IntegrityError
from .m26_provider_mock import compile_provider_replay, run_provider_case
from .m26_retrieval_envelope import sha256_value, verify_self_digest, with_self_digest

DRAFT_POLICY_SCHEMA = "knowledge-engine-m26-draft-answer-policy/v1"
DRAFT_CASES_SCHEMA = "knowledge-engine-m26-draft-answer-benchmark-cases/v1"
DRAFT_PACKAGE_SCHEMA = "knowledge-engine-m26-draft-answer/v1"
DRAFT_BENCHMARK_SCHEMA = "knowledge-engine-m26-draft-answer-benchmark/v1"
PROVIDER_REPLAY_SCHEMA = "knowledge-engine-m26-provider-replay/v1"


class DraftAnswerError(IntegrityError):
    """Fail-closed M26.5 contract error with a stable reason code."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(f"{reason_code}: {message}")
        self.reason_code = reason_code


def _stable_id(prefix: str, value: object) -> str:
    return f"{prefix}_{sha256_value(value)[:32]}"


def validate_draft_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    verify_self_digest(policy)
    if policy.get("schema_version") != DRAFT_POLICY_SCHEMA:
        raise DraftAnswerError("DRAFT_POLICY_INVALID", "schema is incompatible")
    if policy.get("accepted_predecessor_status") != "m26_4_provider_mock_replay_privacy_accepted":
        raise DraftAnswerError("PREDECESSOR_NOT_ACCEPTED", "M26.4 acceptance is not pinned")
    authority = policy.get("authority")
    claim_policy = policy.get("claim_policy")
    status_policy = policy.get("status_policy")
    if not all(isinstance(item, Mapping) for item in (authority, claim_policy, status_policy)):
        raise DraftAnswerError("DRAFT_POLICY_INVALID", "policy sections are missing")
    if authority.get("synthetic_only") is not True:
        raise DraftAnswerError("DRAFT_AUTHORITY_INVALID", "M26.5 must be synthetic-only")
    if authority.get("draft_answer_contract") is not True:
        raise DraftAnswerError("DRAFT_AUTHORITY_INVALID", "draft contract must be explicit")
    required_false = (
        "live_provider_calls",
        "credentials",
        "provider_sdk",
        "network_execution",
        "real_corpus_binding",
        "semantic_or_hybrid_serving",
        "production_answer_serving",
        "verified_final_answers",
        "source_mutation",
        "foundation_mutation",
        "release_mutation",
        "qdrant_or_r2_mutation",
    )
    if any(authority.get(key) is not False for key in required_false):
        raise DraftAnswerError("DRAFT_AUTHORITY_INVALID", "forbidden authority is enabled")
    if claim_policy.get("allow_orphan_citations") is not False:
        raise DraftAnswerError("DRAFT_CITATION_POLICY_INVALID", "orphan citations are allowed")
    if claim_policy.get("allow_unsupported_claims") is not False:
        raise DraftAnswerError("DRAFT_CLAIM_POLICY_INVALID", "unsupported claims are allowed")
    return dict(policy)


def _validate_provider_replay(replay: Mapping[str, Any]) -> dict[str, Any]:
    verify_self_digest(replay)
    if replay.get("schema_version") != PROVIDER_REPLAY_SCHEMA:
        raise DraftAnswerError("PROVIDER_REPLAY_INVALID", "provider replay schema is incompatible")
    if replay.get("synthetic_only") is not True:
        raise DraftAnswerError("PROVIDER_REPLAY_INVALID", "replay is not synthetic")
    for key in ("provider_called", "credentials_used", "network_called", "production_answer_serving"):
        if replay.get(key) is not False:
            raise DraftAnswerError("PROVIDER_REPLAY_AUTHORITY_ESCALATION", key)
    return dict(replay)


def _propagated_package(replay: Mapping[str, Any], *, status: str) -> dict[str, Any]:
    privacy = replay.get("privacy_review", {})
    diagnostics = {
        "source_replay_status": replay["status"],
        "reason_codes": list(replay.get("replay_diagnostics", {}).get("reason_codes", [])),
        "prompt_injection_quarantined": bool(
            replay.get("replay_diagnostics", {}).get("prompt_injection_quarantined")
        ),
        "privacy_review_status": privacy.get("status"),
    }
    return with_self_digest(
        {
            "schema_version": DRAFT_PACKAGE_SCHEMA,
            "request_id": replay["request_id"],
            "provider_replay_sha256": replay["self_sha256"],
            "context_package_sha256": replay["context_package_sha256"],
            "context_manifest_sha256": replay.get("context_manifest_sha256"),
            "status": status,
            "safe_for_m26_6": False,
            "synthetic_only": True,
            "final_answer": False,
            "verified_final_answer": False,
            "production_answer_serving": False,
            "answer_text": "",
            "claims": [],
            "citation_bindings": [],
            "privacy_review_sha256": privacy.get("self_sha256"),
            "diagnostics": diagnostics,
        }
    )


def _draft_status(replay: Mapping[str, Any]) -> str:
    if replay["status"] == "mock_draft_with_warnings":
        return "non_final_draft_answer_with_warnings"
    if replay["status"] == "mock_draft":
        return "non_final_draft_answer"
    raise DraftAnswerError("PROVIDER_REPLAY_NOT_DRAFTABLE", str(replay["status"]))


def _claim_text(index: int, binding: Mapping[str, Any]) -> str:
    citation_id = str(binding["citation_id"])
    passage_id = str(binding["passage_id"])
    return (
        f"Synthetic draft claim {index} is supported by citation {citation_id} "
        f"and selected passage {passage_id}."
    )


def compile_draft_answer(
    provider_replay: Mapping[str, Any],
    draft_policy: Mapping[str, Any],
) -> dict[str, Any]:
    replay = _validate_provider_replay(provider_replay)
    policy = validate_draft_policy(draft_policy)
    if replay["status"] == "privacy_blocked":
        return _propagated_package(replay, status="privacy_block_propagated")
    if replay.get("safe_for_m26_5") is not True:
        return _propagated_package(replay, status="abstain_propagated")
    mock_draft = replay.get("mock_draft")
    if not isinstance(mock_draft, Mapping) or mock_draft.get("non_final") is not True:
        raise DraftAnswerError("MOCK_DRAFT_INVALID", "missing non-final mock draft")
    source_bindings = replay.get("citation_bindings")
    if not isinstance(source_bindings, list) or not source_bindings:
        raise DraftAnswerError("CITATION_BINDINGS_EMPTY", "draftable replay has no citations")
    allowed_citations = set(str(item) for item in mock_draft.get("citation_ids", []))
    max_claims = int(policy["claim_policy"].get("max_claims", 6))
    claims: list[dict[str, Any]] = []
    bindings: list[dict[str, str]] = []
    for index, source in enumerate(source_bindings[:max_claims], start=1):
        citation_id = str(source["citation_id"])
        if citation_id not in allowed_citations:
            raise DraftAnswerError("CITATION_ID_NOT_IN_MOCK_DRAFT", citation_id)
        claim_id = _stable_id("claim", {"request_id": replay["request_id"], "n": index})
        binding_id = _stable_id("binding", {"claim_id": claim_id, "citation_id": citation_id})
        binding = {
            "binding_id": binding_id,
            "claim_id": claim_id,
            "citation_id": citation_id,
            "passage_id": str(source["passage_id"]),
            "context_manifest_sha256": str(source["context_manifest_sha256"]),
            "context_package_sha256": str(replay["context_package_sha256"]),
            "provider_replay_sha256": str(replay["self_sha256"]),
        }
        bindings.append(binding)
        claims.append(
            {
                "claim_id": claim_id,
                "text": _claim_text(index, binding),
                "binding_ids": [binding_id],
                "non_final": True,
            }
        )
    diagnostics = {
        "source_replay_status": replay["status"],
        "reason_codes": list(replay.get("replay_diagnostics", {}).get("reason_codes", [])),
        "prompt_injection_quarantined": bool(
            replay.get("replay_diagnostics", {}).get("prompt_injection_quarantined")
        ),
        "privacy_review_status": replay.get("privacy_review", {}).get("status"),
        "conflict_warning_preserved": "CONFLICTING_EVIDENCE" in replay.get(
            "replay_diagnostics", {}
        ).get("reason_codes", []),
    }
    answer_text = " ".join(claim["text"] for claim in claims)
    answer_text += " This is a non-final synthetic draft, not a production answer."
    return with_self_digest(
        {
            "schema_version": DRAFT_PACKAGE_SCHEMA,
            "request_id": replay["request_id"],
            "provider_replay_sha256": replay["self_sha256"],
            "context_package_sha256": replay["context_package_sha256"],
            "context_manifest_sha256": replay.get("context_manifest_sha256"),
            "status": _draft_status(replay),
            "safe_for_m26_6": True,
            "synthetic_only": True,
            "final_answer": False,
            "verified_final_answer": False,
            "production_answer_serving": False,
            "answer_text": answer_text,
            "claims": claims,
            "citation_bindings": bindings,
            "privacy_review_sha256": replay.get("privacy_review", {}).get("self_sha256"),
            "diagnostics": diagnostics,
        }
    )


def validate_draft_package(package: Mapping[str, Any]) -> dict[str, Any]:
    verify_self_digest(package)
    if package.get("schema_version") != DRAFT_PACKAGE_SCHEMA:
        raise DraftAnswerError("DRAFT_PACKAGE_INVALID", "draft schema is incompatible")
    for key in ("synthetic_only",):
        if package.get(key) is not True:
            raise DraftAnswerError("DRAFT_PACKAGE_INVALID", key)
    for key in ("final_answer", "verified_final_answer", "production_answer_serving"):
        if package.get(key) is not False:
            raise DraftAnswerError("FINAL_OR_PRODUCTION_FORBIDDEN", key)
    claims = package.get("claims")
    bindings = package.get("citation_bindings")
    if not isinstance(claims, list) or not isinstance(bindings, list):
        raise DraftAnswerError("DRAFT_PACKAGE_INVALID", "claims or bindings missing")
    binding_by_id = {str(item["binding_id"]): item for item in bindings if isinstance(item, Mapping)}
    if package["status"] in {"abstain_propagated", "privacy_block_propagated"}:
        if claims or bindings or package.get("safe_for_m26_6") is not False:
            raise DraftAnswerError("ABSTAIN_OR_PRIVACY_HAS_CLAIMS", package["status"])
        return dict(package)
    if package.get("safe_for_m26_6") is not True:
        raise DraftAnswerError("DRAFT_PACKAGE_INVALID", "draftable package is not safe")
    if not claims or not bindings:
        raise DraftAnswerError("DRAFT_WITHOUT_CLAIMS", "draft has no claims or bindings")
    for claim in claims:
        if not isinstance(claim, Mapping) or claim.get("non_final") is not True:
            raise DraftAnswerError("CLAIM_INVALID", "claim must be non-final")
        claim_id = str(claim["claim_id"])
        binding_ids = claim.get("binding_ids", [])
        if not binding_ids:
            raise DraftAnswerError("CLAIM_WITHOUT_BINDING", claim_id)
        for binding_id in binding_ids:
            binding = binding_by_id.get(str(binding_id))
            if binding is None:
                raise DraftAnswerError("CLAIM_BINDING_NOT_FOUND", str(binding_id))
            if str(binding["claim_id"]) != claim_id:
                raise DraftAnswerError("CLAIM_BINDING_MISMATCH", str(binding_id))
            for required in ("citation_id", "passage_id", "context_manifest_sha256"):
                if not binding.get(required):
                    raise DraftAnswerError("CITATION_BINDING_INCOMPLETE", required)
    return dict(package)


def _case_by_id(cases: Mapping[str, Any], case_id: str, *, label: str) -> Mapping[str, Any]:
    for case in cases.get("cases", []):
        if isinstance(case, Mapping) and case.get("case_id") == case_id:
            return case
    raise DraftAnswerError(f"{label}_CASE_NOT_FOUND", f"case not found: {case_id}")


def run_draft_case(
    draft_case: Mapping[str, Any],
    *,
    provider_cases: Mapping[str, Any],
    context_cases: Mapping[str, Any],
    retrieval_cases: Mapping[str, Any],
    corpus: Mapping[str, Any],
    retrieval_policy: Mapping[str, Any],
    context_policy: Mapping[str, Any],
    provider_policy: Mapping[str, Any],
    draft_policy: Mapping[str, Any],
) -> dict[str, Any]:
    provider_case = _case_by_id(
        provider_cases,
        str(draft_case["m26_4_case_id"]),
        label="PROVIDER",
    )
    replay_result = run_provider_case(
        provider_case,
        context_cases=context_cases,
        retrieval_cases=retrieval_cases,
        corpus=corpus,
        retrieval_policy=retrieval_policy,
        context_policy=context_policy,
        provider_policy=provider_policy,
    )
    replay = compile_provider_replay(
        __import__("knowledge_engine.m26_provider_mock", fromlist=["build_context_package_for_case"])
        .build_context_package_for_case(
            provider_case,
            context_cases=context_cases,
            retrieval_cases=retrieval_cases,
            corpus=corpus,
            retrieval_policy=retrieval_policy,
            context_policy=context_policy,
        ),
        provider_policy,
        output_suffix=str(provider_case.get("tamper", {}).get("append_mock_text", ""))
        if isinstance(provider_case.get("tamper", {}), Mapping)
        else "",
    )
    draft = compile_draft_answer(replay, draft_policy)
    validate_draft_package(draft)
    expected = draft_case["expected"]
    failures: list[str] = []
    if draft["status"] != expected["status"]:
        failures.append("status")
    if draft["safe_for_m26_6"] is not bool(expected["safe_for_m26_6"]):
        failures.append("safe_for_m26_6")
    if len(draft["claims"]) < int(expected.get("min_claims", 0)):
        failures.append("min_claims")
    if len(draft["citation_bindings"]) < int(expected.get("min_citation_bindings", 0)):
        failures.append("min_citation_bindings")
    if expected.get("requires_conflict_warning") and not draft["diagnostics"].get(
        "conflict_warning_preserved"
    ):
        failures.append("conflict_warning")
    if expected.get("requires_prompt_injection_quarantine") and not draft["diagnostics"].get(
        "prompt_injection_quarantined"
    ):
        failures.append("prompt_injection_quarantine")
    if expected.get("requires_privacy_propagation") and draft["status"] != "privacy_block_propagated":
        failures.append("privacy_propagation")
    serialized = json.dumps(draft, ensure_ascii=False).casefold()
    for fragment in expected.get("forbidden_text_fragments", []):
        if str(fragment).casefold() in serialized:
            failures.append("forbidden_text_fragment")
    return {
        "case_id": draft_case["case_id"],
        "m26_4_case_id": draft_case["m26_4_case_id"],
        "passed": not failures,
        "failures": failures,
        "status": draft["status"],
        "safe_for_m26_6": draft["safe_for_m26_6"],
        "draft_package_sha256": draft["self_sha256"],
        "provider_replay_sha256": draft["provider_replay_sha256"],
        "provider_replay_case_sha256": replay_result["replay_sha256"],
        "claim_count": len(draft["claims"]),
        "citation_binding_count": len(draft["citation_bindings"]),
        "final_answer": draft["final_answer"],
        "production_answer_serving": draft["production_answer_serving"],
        "reason_codes": draft["diagnostics"].get("reason_codes", []),
    }


def run_draft_benchmark(
    draft_cases_artifact: Mapping[str, Any],
    *,
    provider_cases: Mapping[str, Any],
    context_cases: Mapping[str, Any],
    retrieval_cases: Mapping[str, Any],
    corpus: Mapping[str, Any],
    retrieval_policy: Mapping[str, Any],
    context_policy: Mapping[str, Any],
    provider_policy: Mapping[str, Any],
    draft_policy: Mapping[str, Any],
) -> dict[str, Any]:
    verify_self_digest(draft_cases_artifact)
    if draft_cases_artifact.get("schema_version") != DRAFT_CASES_SCHEMA:
        raise DraftAnswerError("DRAFT_CASES_INVALID", "draft cases schema is incompatible")
    results = [
        run_draft_case(
            case,
            provider_cases=provider_cases,
            context_cases=context_cases,
            retrieval_cases=retrieval_cases,
            corpus=corpus,
            retrieval_policy=retrieval_policy,
            context_policy=context_policy,
            provider_policy=provider_policy,
            draft_policy=draft_policy,
        )
        for case in draft_cases_artifact["cases"]
    ]
    passed = sum(item["passed"] for item in results)
    draft_count = sum(item["status"].startswith("non_final_draft_answer") for item in results)
    abstain_count = sum(item["status"] == "abstain_propagated" for item in results)
    privacy_count = sum(item["status"] == "privacy_block_propagated" for item in results)
    return with_self_digest(
        {
            "schema_version": DRAFT_BENCHMARK_SCHEMA,
            "status": "m26_5_draft_answer_ready" if passed == len(results) else "repair_required",
            "case_count": len(results),
            "passed_count": passed,
            "failed_count": len(results) - passed,
            "metrics": {
                "case_pass_rate": passed / len(results) if results else 0.0,
                "non_final_draft_count": draft_count,
                "abstain_propagated_count": abstain_count,
                "privacy_block_propagated_count": privacy_count,
                "provider_call_count": 0,
                "credentials_used_count": 0,
                "live_network_call_count": 0,
                "real_corpus_binding_count": 0,
                "semantic_or_hybrid_use_count": 0,
                "production_answer_serving_count": 0,
                "verified_final_answer_count": 0,
            },
            "results": results,
            "authority": {
                "synthetic_only": True,
                "draft_answer_contract": True,
                "live_provider_calls": False,
                "production_authority": False,
                "m26_6_authorized": False,
            },
        }
    )
