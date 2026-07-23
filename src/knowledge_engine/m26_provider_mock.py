from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from typing import Any

from .errors import IntegrityError
from .m26_context_compiler import compile_context_package
from .m26_retrieval_envelope import (
    assemble_retrieval_envelope,
    build_retrieval_plan,
    sha256_value,
    verify_self_digest,
    with_self_digest,
)

PROVIDER_POLICY_SCHEMA = "knowledge-engine-m26-provider-mock-policy/v1"
PROVIDER_CASES_SCHEMA = "knowledge-engine-m26-provider-mock-benchmark-cases/v1"
PROVIDER_REPLAY_SCHEMA = "knowledge-engine-m26-provider-replay/v1"
PRIVACY_REVIEW_SCHEMA = "knowledge-engine-m26-privacy-review/v1"
PROVIDER_BENCHMARK_SCHEMA = "knowledge-engine-m26-provider-mock-benchmark/v1"

_SECRET_PATTERNS = (
    ("password_assignment", re.compile(r"\bpassword\s*[:=]\s*\S+", re.I)),
    ("bearer_token", re.compile(r"\bbearer\s+[A-Za-z0-9._~+/=-]{12,}", re.I)),
    ("api_key_assignment", re.compile(r"\bapi[_-]?key\s*[:=]\s*\S+", re.I)),
    ("private_key", re.compile(r"BEGIN [A-Z ]*PRIVATE KEY")),
)
_PRIVACY_PATTERNS = (
    ("actor_hash", re.compile(r"\b[a-f0-9]{64}\b")),
    ("email_like", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)),
    ("phone_like", re.compile(r"\+?\d[\d\s().-]{8,}\d")),
)


class ProviderMockError(IntegrityError):
    """Fail-closed M26.4 contract error with a stable reason code."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(f"{reason_code}: {message}")
        self.reason_code = reason_code


def _stable_id(prefix: str, value: object) -> str:
    return f"{prefix}_{sha256_value(value)[:32]}"


def validate_provider_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    verify_self_digest(policy)
    if policy.get("schema_version") != PROVIDER_POLICY_SCHEMA:
        raise ProviderMockError(
            "PROVIDER_POLICY_INVALID",
            "provider mock policy schema is incompatible",
        )
    if policy.get("accepted_predecessor_status") != "m26_3_context_compiler_accepted":
        raise ProviderMockError("PREDECESSOR_NOT_ACCEPTED", "M26.3 acceptance is not pinned")
    authority = policy.get("authority")
    if not isinstance(authority, Mapping):
        raise ProviderMockError("PROVIDER_POLICY_INVALID", "authority section is missing")
    required_false = (
        "live_provider_calls",
        "credentials",
        "provider_sdk",
        "network_execution",
        "real_corpus_binding",
        "semantic_or_hybrid_serving",
        "production_answer_serving",
        "source_mutation",
        "release_mutation",
        "qdrant_or_r2_mutation",
    )
    if authority.get("synthetic_only") is not True:
        raise ProviderMockError("PROVIDER_AUTHORITY_INVALID", "M26.4 must be synthetic-only")
    if authority.get("provider_mock_replay") is not True:
        raise ProviderMockError(
            "PROVIDER_AUTHORITY_INVALID",
            "provider mock replay must be explicit",
        )
    if any(authority.get(key) is not False for key in required_false):
        raise ProviderMockError("PROVIDER_AUTHORITY_INVALID", "forbidden authority is enabled")
    runtime = policy.get("mock_runtime")
    if not isinstance(runtime, Mapping):
        raise ProviderMockError("PROVIDER_POLICY_INVALID", "mock runtime is missing")
    if any(
        runtime.get(key) is not False
        for key in ("network", "live_provider", "credentials", "provider_sdk")
    ):
        raise ProviderMockError("PROVIDER_AUTHORITY_INVALID", "mock runtime is not isolated")
    return dict(policy)


def _validate_context_package(package: Mapping[str, Any]) -> dict[str, Any]:
    verify_self_digest(package)
    if package.get("schema_version") != "knowledge-engine-m26-context-package/v1":
        raise ProviderMockError(
            "CONTEXT_PACKAGE_INVALID",
            "context package schema is incompatible",
        )
    for key in ("synthetic_only", "provider_calls", "production_answer_serving"):
        if key == "synthetic_only":
            if package.get(key) is not True:
                raise ProviderMockError("CONTEXT_PACKAGE_INVALID", "context is not synthetic")
        elif package.get(key) is not False:
            raise ProviderMockError("CONTEXT_AUTHORITY_ESCALATION", f"{key} is enabled")
    if package.get("semantic_or_hybrid_serving") is not False:
        raise ProviderMockError("CONTEXT_AUTHORITY_ESCALATION", "semantic or hybrid is enabled")
    if package.get("status") not in {
        "compiled",
        "compiled_with_warnings",
        "abstain_required",
    }:
        raise ProviderMockError("CONTEXT_PACKAGE_INVALID", "unsupported context status")
    return dict(package)


def _surface_findings(surface: str, text: str) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for finding_type, pattern in (*_SECRET_PATTERNS, *_PRIVACY_PATTERNS):
        if pattern.search(text):
            findings.append(
                {
                    "surface": surface,
                    "finding_type": finding_type,
                    "action": "block",
                }
            )
    return findings


def run_privacy_review(
    *,
    request_id: str,
    input_surfaces: Mapping[str, str],
    output_surfaces: Mapping[str, str],
) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    for surface, text in sorted(input_surfaces.items()):
        findings.extend(_surface_findings(f"input:{surface}", text))
    for surface, text in sorted(output_surfaces.items()):
        findings.extend(_surface_findings(f"output:{surface}", text))
    review = with_self_digest(
        {
            "schema_version": PRIVACY_REVIEW_SCHEMA,
            "request_id": request_id,
            "status": "blocked" if findings else "passed",
            "findings": findings,
            "input_surface_count": len(input_surfaces),
            "output_surface_count": len(output_surfaces),
            "redacted": False,
            "fail_closed": True,
        }
    )
    return review


def _citation_bindings(package: Mapping[str, Any]) -> list[dict[str, Any]]:
    manifest = package.get("context_manifest")
    if not isinstance(manifest, Mapping):
        return []
    selected = set(str(item) for item in manifest.get("selected_passage_ids", []))
    bindings: list[dict[str, Any]] = []
    for citation in package.get("citations", []):
        if not isinstance(citation, Mapping):
            raise ProviderMockError("CITATION_INVALID", "citation must be an object")
        passage_id = str(citation.get("passage_id"))
        if passage_id not in selected:
            raise ProviderMockError(
                "CITATION_WITHOUT_SELECTED_PASSAGE",
                "citation is not backed by selected passage",
            )
        bindings.append(
            {
                "citation_id": str(citation["citation_id"]),
                "passage_id": passage_id,
                "context_manifest_sha256": str(citation["context_manifest_sha256"]),
            }
        )
    return bindings


def _mock_draft_text(
    *,
    package: Mapping[str, Any],
    bindings: list[Mapping[str, Any]],
    policy: Mapping[str, Any],
) -> str:
    max_citations = int(policy["mock_runtime"]["max_mock_citations"])
    citation_ids = [str(item["citation_id"]) for item in bindings[:max_citations]]
    citation_text = ", ".join(citation_ids) if citation_ids else "none"
    diagnostics = package.get("diagnostics", {})
    reason_codes = sorted(str(item) for item in diagnostics.get("reason_codes", []))
    parts = [
        "Non-final synthetic provider mock draft.",
        "This replay validates provider input and citation plumbing only.",
        f"Evidence citations available to a later draft-answer stage: {citation_text}.",
    ]
    if "CONFLICTING_EVIDENCE" in reason_codes:
        parts.append("Warning: conflicting evidence must be preserved in downstream drafting.")
    if diagnostics.get("prompt_injection_quarantined") is True:
        parts.append("Warning: prompt-injection evidence remains quoted evidence only.")
    parts.append("No live provider was called and this is not a production answer.")
    return " ".join(parts)


def compile_provider_replay(
    context_package: Mapping[str, Any],
    provider_policy: Mapping[str, Any],
    *,
    output_suffix: str = "",
) -> dict[str, Any]:
    package = _validate_context_package(context_package)
    policy = validate_provider_policy(provider_policy)
    request_id = str(package["request_id"])
    diagnostics = {
        "context_status": package["status"],
        "context_sufficiency": package.get("diagnostics", {}).get("sufficiency"),
        "reason_codes": list(package.get("diagnostics", {}).get("reason_codes", [])),
        "prompt_injection_quarantined": bool(
            package.get("diagnostics", {}).get("prompt_injection_quarantined")
        ),
        "provider_profile": str(policy["provider_profile"]),
    }

    if package.get("safe_for_provider_mock") is not True:
        privacy = run_privacy_review(
            request_id=request_id,
            input_surfaces={"abstain_reason": json.dumps(diagnostics, sort_keys=True)},
            output_surfaces={},
        )
        replay = with_self_digest(
            {
                "schema_version": PROVIDER_REPLAY_SCHEMA,
                "request_id": request_id,
                "context_package_sha256": package["self_sha256"],
                "context_manifest_sha256": package.get("context_manifest_sha256"),
                "evidence_budget_sha256": package.get("evidence_budget_sha256"),
                "status": "abstain_replayed",
                "safe_for_m26_5": False,
                "synthetic_only": True,
                "provider_called": False,
                "credentials_used": False,
                "network_called": False,
                "production_answer_serving": False,
                "mock_draft": None,
                "citation_bindings": [],
                "privacy_review": privacy,
                "replay_diagnostics": diagnostics,
                "next_stage": "abstain",
            }
        )
        return replay

    bindings = _citation_bindings(package)
    if not bindings:
        raise ProviderMockError("CITATION_BINDINGS_EMPTY", "safe package has no citations")
    draft_text = _mock_draft_text(package=package, bindings=bindings, policy=policy)
    if output_suffix:
        draft_text = f"{draft_text}{output_suffix}"
    input_surfaces = {
        "instruction_roles": json.dumps(
            [
                {
                    "block_id": block.get("block_id"),
                    "role": block.get("role"),
                    "authority": block.get("authority"),
                }
                for block in package.get("instruction_blocks", [])
                if isinstance(block, Mapping)
            ],
            sort_keys=True,
        ),
        "diagnostics": json.dumps(diagnostics, sort_keys=True),
    }
    privacy = run_privacy_review(
        request_id=request_id,
        input_surfaces=input_surfaces,
        output_surfaces={"mock_draft": draft_text},
    )
    if privacy["status"] == "blocked":
        return with_self_digest(
            {
                "schema_version": PROVIDER_REPLAY_SCHEMA,
                "request_id": request_id,
                "context_package_sha256": package["self_sha256"],
                "context_manifest_sha256": package.get("context_manifest_sha256"),
                "evidence_budget_sha256": package.get("evidence_budget_sha256"),
                "status": "privacy_blocked",
                "safe_for_m26_5": False,
                "synthetic_only": True,
                "provider_called": False,
                "credentials_used": False,
                "network_called": False,
                "production_answer_serving": False,
                "mock_draft": None,
                "citation_bindings": [],
                "privacy_review": privacy,
                "replay_diagnostics": diagnostics,
                "next_stage": "abstain",
            }
        )

    citation_ids = [str(item["citation_id"]) for item in bindings]
    status = (
        "mock_draft_with_warnings"
        if package["status"] == "compiled_with_warnings"
        or bool(diagnostics["reason_codes"])
        else "mock_draft"
    )
    draft = {
        "draft_id": _stable_id("mockdraft", {"request_id": request_id, "text": draft_text}),
        "draft_status": (
            "non_final_mock_draft_with_warnings"
            if status == "mock_draft_with_warnings"
            else "non_final_mock_draft"
        ),
        "text": draft_text,
        "citation_ids": citation_ids,
        "non_final": True,
    }
    replay = with_self_digest(
        {
            "schema_version": PROVIDER_REPLAY_SCHEMA,
            "request_id": request_id,
            "context_package_sha256": package["self_sha256"],
            "context_manifest_sha256": package.get("context_manifest_sha256"),
            "evidence_budget_sha256": package.get("evidence_budget_sha256"),
            "status": status,
            "safe_for_m26_5": True,
            "synthetic_only": True,
            "provider_called": False,
            "credentials_used": False,
            "network_called": False,
            "production_answer_serving": False,
            "mock_draft": draft,
            "citation_bindings": bindings,
            "privacy_review": privacy,
            "replay_diagnostics": diagnostics,
            "next_stage": "m26_5_draft_answer_contract",
        }
    )
    return replay


def _context_case_by_id(context_cases: Mapping[str, Any], case_id: str) -> Mapping[str, Any]:
    for case in context_cases.get("cases", []):
        if isinstance(case, Mapping) and case.get("case_id") == case_id:
            return case
    raise ProviderMockError("CONTEXT_CASE_NOT_FOUND", f"context case not found: {case_id}")


def _retrieval_case_by_id(retrieval_cases: Mapping[str, Any], case_id: str) -> Mapping[str, Any]:
    for case in retrieval_cases.get("cases", []):
        if isinstance(case, Mapping) and case.get("case_id") == case_id:
            return case
    raise ProviderMockError("RETRIEVAL_CASE_NOT_FOUND", f"retrieval case not found: {case_id}")


def build_context_package_for_case(
    provider_case: Mapping[str, Any],
    *,
    context_cases: Mapping[str, Any],
    retrieval_cases: Mapping[str, Any],
    corpus: Mapping[str, Any],
    retrieval_policy: Mapping[str, Any],
    context_policy: Mapping[str, Any],
) -> dict[str, Any]:
    context_case = _context_case_by_id(context_cases, str(provider_case["m26_3_case_id"]))
    retrieval_case = _retrieval_case_by_id(retrieval_cases, str(context_case["m26_2_case_id"]))
    plan = build_retrieval_plan(retrieval_case["request"], retrieval_policy)
    envelope, _trace, gap = assemble_retrieval_envelope(
        retrieval_case["request"],
        plan,
        corpus,
        retrieval_policy,
    )
    return compile_context_package(envelope, gap, context_policy)


def run_provider_case(
    provider_case: Mapping[str, Any],
    *,
    context_cases: Mapping[str, Any],
    retrieval_cases: Mapping[str, Any],
    corpus: Mapping[str, Any],
    retrieval_policy: Mapping[str, Any],
    context_policy: Mapping[str, Any],
    provider_policy: Mapping[str, Any],
) -> dict[str, Any]:
    package = build_context_package_for_case(
        provider_case,
        context_cases=context_cases,
        retrieval_cases=retrieval_cases,
        corpus=corpus,
        retrieval_policy=retrieval_policy,
        context_policy=context_policy,
    )
    tamper = provider_case.get("tamper", {})
    output_suffix = ""
    if isinstance(tamper, Mapping):
        output_suffix = str(tamper.get("append_mock_text", ""))
    replay = compile_provider_replay(package, provider_policy, output_suffix=output_suffix)
    expected = provider_case["expected"]
    failures: list[str] = []
    if replay["status"] != expected["status"]:
        failures.append("status")
    if replay["safe_for_m26_5"] is not bool(expected["safe_for_m26_5"]):
        failures.append("safe_for_m26_5")
    citation_count = len(replay["citation_bindings"])
    if citation_count < int(expected.get("min_citations", 0)):
        failures.append("min_citations")
    if expected.get("requires_conflict_warning") and "CONFLICTING_EVIDENCE" not in replay[
        "replay_diagnostics"
    ]["reason_codes"]:
        failures.append("conflict_warning")
    if expected.get("requires_prompt_injection_quarantine") and not replay["replay_diagnostics"][
        "prompt_injection_quarantined"
    ]:
        failures.append("prompt_injection_quarantine")
    if expected.get("requires_privacy_block") and replay["privacy_review"]["status"] != "blocked":
        failures.append("privacy_block")
    forbidden_fragments = [str(item) for item in expected.get("forbidden_text_fragments", [])]
    serialized = json.dumps(replay, ensure_ascii=False).casefold()
    if any(fragment.casefold() in serialized for fragment in forbidden_fragments):
        failures.append("forbidden_text_fragment")
    return {
        "case_id": provider_case["case_id"],
        "m26_3_case_id": provider_case["m26_3_case_id"],
        "passed": not failures,
        "failures": failures,
        "status": replay["status"],
        "safe_for_m26_5": replay["safe_for_m26_5"],
        "replay_sha256": replay["self_sha256"],
        "context_package_sha256": replay["context_package_sha256"],
        "privacy_review_sha256": replay["privacy_review"]["self_sha256"],
        "citation_count": citation_count,
        "provider_called": replay["provider_called"],
        "credentials_used": replay["credentials_used"],
        "network_called": replay["network_called"],
        "production_answer_serving": replay["production_answer_serving"],
        "privacy_status": replay["privacy_review"]["status"],
        "reason_codes": replay["replay_diagnostics"]["reason_codes"],
    }


def run_provider_benchmark(
    provider_cases_artifact: Mapping[str, Any],
    *,
    context_cases: Mapping[str, Any],
    retrieval_cases: Mapping[str, Any],
    corpus: Mapping[str, Any],
    retrieval_policy: Mapping[str, Any],
    context_policy: Mapping[str, Any],
    provider_policy: Mapping[str, Any],
) -> dict[str, Any]:
    verify_self_digest(provider_cases_artifact)
    if provider_cases_artifact.get("schema_version") != PROVIDER_CASES_SCHEMA:
        raise ProviderMockError("PROVIDER_CASES_INVALID", "provider cases schema is incompatible")
    results = [
        run_provider_case(
            case,
            context_cases=context_cases,
            retrieval_cases=retrieval_cases,
            corpus=corpus,
            retrieval_policy=retrieval_policy,
            context_policy=context_policy,
            provider_policy=provider_policy,
        )
        for case in provider_cases_artifact["cases"]
    ]
    passed = sum(item["passed"] for item in results)
    mock_count = sum(item["status"].startswith("mock_draft") for item in results)
    abstain_count = sum(item["status"] == "abstain_replayed" for item in results)
    privacy_blocked = sum(item["status"] == "privacy_blocked" for item in results)
    report = {
        "schema_version": PROVIDER_BENCHMARK_SCHEMA,
        "status": "m26_4_provider_mock_ready" if passed == len(results) else "repair_required",
        "case_count": len(results),
        "passed_count": passed,
        "failed_count": len(results) - passed,
        "metrics": {
            "case_pass_rate": passed / len(results) if results else 0.0,
            "mock_draft_count": mock_count,
            "abstain_replay_count": abstain_count,
            "privacy_blocked_count": privacy_blocked,
            "provider_call_count": 0,
            "credentials_used_count": 0,
            "live_network_call_count": 0,
            "real_corpus_binding_count": 0,
            "semantic_or_hybrid_use_count": 0,
            "production_answer_serving_count": 0,
        },
        "results": results,
        "authority": {
            "synthetic_only": True,
            "provider_mock_replay": True,
            "live_provider_calls": False,
            "production_authority": False,
            "m26_5_authorized": False,
        },
    }
    return with_self_digest(report)


def write_json(path: Any, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
