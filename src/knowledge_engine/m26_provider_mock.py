from __future__ import annotations

import json
import re
from collections.abc import Mapping
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

_BLOCK_PATTERNS = (
    ("password_assignment", re.compile(r"\bpassword\s*[:=]\s*\S+", re.I)),
    ("bearer_token", re.compile(r"\bbearer\s+[A-Za-z0-9._~+/=-]{12,}", re.I)),
    ("api_key_assignment", re.compile(r"\bapi[_-]?key\s*[:=]\s*\S+", re.I)),
    ("private_key", re.compile(r"BEGIN [A-Z ]*PRIVATE KEY")),
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
        raise ProviderMockError("PROVIDER_POLICY_INVALID", "schema is incompatible")
    if policy.get("accepted_predecessor_status") != "m26_3_context_compiler_accepted":
        raise ProviderMockError("PREDECESSOR_NOT_ACCEPTED", "M26.3 acceptance is not pinned")
    authority = policy.get("authority")
    runtime = policy.get("mock_runtime")
    if not isinstance(authority, Mapping) or not isinstance(runtime, Mapping):
        raise ProviderMockError("PROVIDER_POLICY_INVALID", "authority or runtime is missing")
    if authority.get("synthetic_only") is not True:
        raise ProviderMockError("PROVIDER_AUTHORITY_INVALID", "M26.4 must be synthetic-only")
    if authority.get("provider_mock_replay") is not True:
        raise ProviderMockError("PROVIDER_AUTHORITY_INVALID", "mock replay must be explicit")
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
    if any(authority.get(key) is not False for key in required_false):
        raise ProviderMockError("PROVIDER_AUTHORITY_INVALID", "forbidden authority is enabled")
    if any(
        runtime.get(key) is not False
        for key in ("network", "live_provider", "credentials", "provider_sdk")
    ):
        raise ProviderMockError("PROVIDER_AUTHORITY_INVALID", "mock runtime is not isolated")
    return dict(policy)


def _validate_context_package(package: Mapping[str, Any]) -> dict[str, Any]:
    verify_self_digest(package)
    if package.get("schema_version") != "knowledge-engine-m26-context-package/v1":
        raise ProviderMockError("CONTEXT_PACKAGE_INVALID", "context schema is incompatible")
    if package.get("synthetic_only") is not True:
        raise ProviderMockError("CONTEXT_PACKAGE_INVALID", "context is not synthetic")
    if package.get("provider_calls") is not False:
        raise ProviderMockError("CONTEXT_AUTHORITY_ESCALATION", "provider calls are enabled")
    if package.get("production_answer_serving") is not False:
        raise ProviderMockError("CONTEXT_AUTHORITY_ESCALATION", "production answer serving enabled")
    if package.get("semantic_or_hybrid_serving") is not False:
        raise ProviderMockError("CONTEXT_AUTHORITY_ESCALATION", "semantic or hybrid is enabled")
    if package.get("status") not in {"compiled", "compiled_with_warnings", "abstain_required"}:
        raise ProviderMockError("CONTEXT_PACKAGE_INVALID", "unsupported context status")
    return dict(package)


def _findings(surface: str, text: str) -> list[dict[str, str]]:
    return [
        {"surface": surface, "finding_type": code, "action": "block"}
        for code, pattern in _BLOCK_PATTERNS
        if pattern.search(text)
    ]


def run_privacy_review(
    *,
    request_id: str,
    input_surfaces: Mapping[str, str],
    output_surfaces: Mapping[str, str],
) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    for surface, text in sorted(input_surfaces.items()):
        findings.extend(_findings(f"input:{surface}", text))
    for surface, text in sorted(output_surfaces.items()):
        findings.extend(_findings(f"output:{surface}", text))
    return with_self_digest(
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


def _citation_bindings(package: Mapping[str, Any]) -> list[dict[str, str]]:
    manifest = package.get("context_manifest")
    if not isinstance(manifest, Mapping):
        return []
    selected = {str(item) for item in manifest.get("selected_passage_ids", [])}
    bindings = []
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


def _mock_draft_text(package: Mapping[str, Any], bindings: list[Mapping[str, str]]) -> str:
    citation_ids = [str(item["citation_id"]) for item in bindings[:6]]
    citation_text = ", ".join(citation_ids) if citation_ids else "none"
    diagnostics = package.get("diagnostics", {})
    reasons = sorted(str(item) for item in diagnostics.get("reason_codes", []))
    parts = [
        "Non-final synthetic provider mock draft.",
        "This replay validates provider input and citation plumbing only.",
        f"Evidence citations available to a later draft-answer stage: {citation_text}.",
    ]
    if "CONFLICTING_EVIDENCE" in reasons:
        parts.append("Warning: conflicting evidence must be preserved in downstream drafting.")
    if diagnostics.get("prompt_injection_quarantined") is True:
        parts.append("Warning: prompt-injection evidence remains quoted evidence only.")
    parts.append("No live provider was called and this is not a production answer.")
    return " ".join(parts)


def _diagnostics(package: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, Any]:
    source = package.get("diagnostics", {})
    return {
        "context_status": package["status"],
        "context_sufficiency": source.get("sufficiency"),
        "reason_codes": list(source.get("reason_codes", [])),
        "prompt_injection_quarantined": bool(source.get("prompt_injection_quarantined")),
        "provider_profile": str(policy["provider_profile"]),
    }


def _replay(
    package: Mapping[str, Any],
    *,
    status: str,
    safe_for_m26_5: bool,
    privacy: Mapping[str, Any],
    diagnostics: Mapping[str, Any],
    mock_draft: Mapping[str, Any] | None = None,
    citation_bindings: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return with_self_digest(
        {
            "schema_version": PROVIDER_REPLAY_SCHEMA,
            "request_id": package["request_id"],
            "context_package_sha256": package["self_sha256"],
            "context_manifest_sha256": package.get("context_manifest_sha256"),
            "evidence_budget_sha256": package.get("evidence_budget_sha256"),
            "status": status,
            "safe_for_m26_5": safe_for_m26_5,
            "synthetic_only": True,
            "provider_called": False,
            "credentials_used": False,
            "network_called": False,
            "production_answer_serving": False,
            "mock_draft": mock_draft,
            "citation_bindings": citation_bindings or [],
            "privacy_review": dict(privacy),
            "replay_diagnostics": dict(diagnostics),
            "next_stage": "m26_5_draft_answer_contract" if safe_for_m26_5 else "abstain",
        }
    )


def compile_provider_replay(
    context_package: Mapping[str, Any],
    provider_policy: Mapping[str, Any],
    *,
    output_suffix: str = "",
) -> dict[str, Any]:
    package = _validate_context_package(context_package)
    policy = validate_provider_policy(provider_policy)
    diagnostics = _diagnostics(package, policy)
    request_id = str(package["request_id"])
    if package.get("safe_for_provider_mock") is not True:
        privacy = run_privacy_review(
            request_id=request_id,
            input_surfaces={"abstain_reason": json.dumps(diagnostics, sort_keys=True)},
            output_surfaces={},
        )
        return _replay(
            package,
            status="abstain_replayed",
            safe_for_m26_5=False,
            privacy=privacy,
            diagnostics=diagnostics,
        )

    bindings = _citation_bindings(package)
    if not bindings:
        raise ProviderMockError("CITATION_BINDINGS_EMPTY", "safe package has no citations")
    draft_text = _mock_draft_text(package, bindings) + output_suffix
    privacy = run_privacy_review(
        request_id=request_id,
        input_surfaces={"diagnostics": json.dumps(diagnostics, sort_keys=True)},
        output_surfaces={"mock_draft": draft_text},
    )
    if privacy["status"] == "blocked":
        return _replay(
            package,
            status="privacy_blocked",
            safe_for_m26_5=False,
            privacy=privacy,
            diagnostics=diagnostics,
        )
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
        "citation_ids": [str(item["citation_id"]) for item in bindings],
        "non_final": True,
    }
    return _replay(
        package,
        status=status,
        safe_for_m26_5=True,
        privacy=privacy,
        diagnostics=diagnostics,
        mock_draft=draft,
        citation_bindings=bindings,
    )


def _case_by_id(cases: Mapping[str, Any], case_id: str, *, label: str) -> Mapping[str, Any]:
    for case in cases.get("cases", []):
        if isinstance(case, Mapping) and case.get("case_id") == case_id:
            return case
    raise ProviderMockError(f"{label}_CASE_NOT_FOUND", f"case not found: {case_id}")


def build_context_package_for_case(
    provider_case: Mapping[str, Any],
    *,
    context_cases: Mapping[str, Any],
    retrieval_cases: Mapping[str, Any],
    corpus: Mapping[str, Any],
    retrieval_policy: Mapping[str, Any],
    context_policy: Mapping[str, Any],
) -> dict[str, Any]:
    context_case = _case_by_id(
        context_cases,
        str(provider_case["m26_3_case_id"]),
        label="CONTEXT",
    )
    retrieval_case = _case_by_id(
        retrieval_cases,
        str(context_case["m26_2_case_id"]),
        label="RETRIEVAL",
    )
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
    suffix = str(tamper.get("append_mock_text", "")) if isinstance(tamper, Mapping) else ""
    replay = compile_provider_replay(package, provider_policy, output_suffix=suffix)
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
    serialized = json.dumps(replay, ensure_ascii=False).casefold()
    for fragment in expected.get("forbidden_text_fragments", []):
        if str(fragment).casefold() in serialized:
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
    return with_self_digest(
        {
            "schema_version": PROVIDER_BENCHMARK_SCHEMA,
            "status": (
                "m26_4_provider_mock_ready"
                if passed == len(results)
                else "repair_required"
            ),
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
    )
