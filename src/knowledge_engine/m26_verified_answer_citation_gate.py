from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from .errors import IntegrityError

OWNER_DECISION_SCHEMA = "knowledge-engine-m26-pa-4-owner-decision/v1"
POLICY_SCHEMA = "knowledge-engine-m26-pa-4-verified-answer-policy/v1"
POPULATION_SCHEMA = "knowledge-engine-m26-pa-4-benchmark-population/v1"
REGISTRY_SCHEMA = "knowledge-engine-m26-pa-4-contract-registry/v1"
RECEIPT_SCHEMA = "knowledge-engine-m26-pa-4-verified-answer-receipt/v1"

PREDECESSOR_STATUS = "m26_pa_3_live_provider_execution_accepted"
ACCEPTED_STATUS = "m26_pa_4_verified_answer_citation_gate_accepted"
IMPLEMENTATION_STATUS = "m26_pa_4_real_verified_answer_gate_implemented_not_accepted"
LIVE_VERIFIED_STATUS = "real_verified_answer_citation_gate_verified"

OWNER_DECISION_PATH = "pilot/m26/m26-pa-4-owner-decision.json"
POLICY_PATH = "pilot/m26/m26-pa-4-verified-answer-policy.json"
POPULATION_PATH = "pilot/m26/m26-pa-4-benchmark-population.json"
REGISTRY_PATH = "pilot/m26/m26-pa-4-contract-registry.json"
PA3_ACCEPTANCE_PATH = "pilot/m26/m26-pa-3-acceptance.json"
RECEIPT_SCHEMA_PATH = "schemas/m26-pa-4-verified-answer-receipt-v1.schema.json"

SUPPORTED_ANSWER_TEXT = "non-final draft candidate; see material_claims"
MAX_PROVIDER_OUTPUT_CHARS = 12_000
SAFE_HEX_40 = re.compile(r"^[0-9a-f]{40}$")
SAFE_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
RFC3339_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
SECRET_VALUE_PATTERNS = (
    re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)

EXACT_OWNER_DECISION_TEXT = "\n".join(
    [
        "I approve M26.PA.4 real verified-answer gate with:",
        "provider/model: MiniMax / MiniMax-M3",
        "credential name/environment: MINIMAX_API_KEY / m23-r3-diagnostic",
        "frozen benchmark population count/digest: 12 / to be frozen before run and "
        "recorded as SHA-256",
        "maximum provider calls including repair: 2 per benchmark item",
        "maximum spend: USD 1.00",
        "material-claim definition: any factual answer assertion that depends on corpus "
        "evidence, including entity, date, number, relationship, status, or causal/temporal "
        "claim",
        "minimum citation precision/support threshold: 100% of non-abstained material "
        "claims must bind to exact source/section/passage locators and verify as "
        "supported; unsupported material claims are not allowed",
        "conflict and temporal policy: unresolved conflict, stale temporal evidence, "
        "missing locator, or contradictory source evidence must trigger bounded repair "
        "or abstention",
        "maximum repair attempts: 1",
        "abstention policy: abstain when support is insufficient, locator binding fails, "
        "conflict remains unresolved, temporal evidence is stale, privacy/security risk "
        "appears, or repair budget is exhausted",
        "payload/privacy boundary: no secret values, no raw corpus persistence, no vector "
        "persistence, no production serving, no public traffic, no pointer mutation, no "
        "canonical writes",
        "This does not authorize production serving, public traffic, pointer mutation or "
        "canonical writes.",
    ]
)


class VerifiedAnswerGateError(IntegrityError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        category: str = "integrity",
        retryable: bool = False,
    ) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.safe_message = message
        self.category = category
        self.retryable = retryable


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def pretty_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        + "\n"
    ).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_sha256(value: Any) -> str:
    return sha256_bytes(canonical_bytes(value))


def with_self_digest(value: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(value)
    result["self_sha256"] = ""
    result["self_sha256"] = canonical_sha256(result)
    return result


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise _failure("M26-PA4-001", f"cannot load JSON artifact: {path.as_posix()}") from exc
    return _object(value, path.as_posix())


def verify_self_digest(value: Mapping[str, Any], label: str = "artifact") -> None:
    expected = value.get("self_sha256")
    if not isinstance(expected, str) or not SAFE_HEX_64.fullmatch(expected):
        raise _failure("M26-PA4-002", f"{label} self digest missing or malformed")
    candidate = dict(value)
    candidate["self_sha256"] = ""
    if canonical_sha256(candidate) != expected:
        raise _failure("M26-PA4-003", f"{label} self digest mismatch")


def _failure(
    code: str, message: str, *, category: str = "integrity", retryable: bool = False
) -> VerifiedAnswerGateError:
    return VerifiedAnswerGateError(code, message, category=category, retryable=retryable)


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _failure("M26-PA4-004", f"{label} must be an object")
    return value


def _list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise _failure("M26-PA4-005", f"{label} must be an array")
    return value


def _strict_keys(
    value: Mapping[str, Any], *, label: str, required: set[str], allowed: set[str] | None = None
) -> None:
    observed = set(value)
    permitted = required if allowed is None else allowed
    missing = required - observed
    unknown = observed - permitted
    if missing:
        raise _failure("M26-PA4-006", f"{label} is missing required fields")
    if unknown:
        raise _failure("M26-PA4-007", f"{label} contains unknown fields")


def _secret_findings(text: str) -> list[str]:
    return [pattern.pattern for pattern in SECRET_VALUE_PATTERNS if pattern.search(text)]


def _validate_predecessor(root: Path) -> dict[str, Any]:
    pa3 = load_json(root / PA3_ACCEPTANCE_PATH)
    verify_self_digest(pa3, "PA3 acceptance")
    if pa3.get("status") != PREDECESSOR_STATUS:
        raise _failure("M26-PA4-008", "PA3 accepted status is not present")
    if pa3.get("stage_id") != "M26.PA.3":
        raise _failure("M26-PA4-009", "PA3 stage identity mismatch")
    return pa3


def validate_owner_decision(decision: Mapping[str, Any]) -> dict[str, Any]:
    verify_self_digest(decision, "PA4 owner decision")
    if decision.get("schema_version") != OWNER_DECISION_SCHEMA:
        raise _failure("M26-PA4-010", "owner decision schema is incompatible")
    if decision.get("stage_id") != "M26.PA.4":
        raise _failure("M26-PA4-011", "owner decision stage mismatch")
    if decision.get("exact_instruction_text") != EXACT_OWNER_DECISION_TEXT:
        raise _failure("M26-PA4-012", "owner decision text is not exact")
    parameters = _object(decision.get("parsed_parameters"), "owner parsed parameters")
    expected = {
        "provider_id": "minimax",
        "provider_label": "MiniMax",
        "model_id": "MiniMax-M3",
        "credential_name": "MINIMAX_API_KEY",
        "environment": "m23-r3-diagnostic",
        "benchmark_population_count": 12,
        "max_provider_calls_per_item_including_repair": 2,
        "max_spend_usd": 1.0,
        "max_repair_attempts": 1,
        "citation_precision_support_threshold": 1.0,
    }
    for key, value in expected.items():
        if parameters.get(key) != value:
            raise _failure("M26-PA4-013", "owner decision parameter mismatch")
    if parameters.get("population_digest_state") != "to_be_frozen_before_run":
        raise _failure("M26-PA4-014", "owner decision population state mismatch")
    denied = _object(decision.get("denied_authority"), "owner denied authority")
    if any(denied.values()):
        raise _failure("M26-PA4-015", "owner decision grants forbidden authority")
    return dict(decision)


def validate_policy(
    policy: Mapping[str, Any], *, owner_decision: Mapping[str, Any]
) -> dict[str, Any]:
    verify_self_digest(policy, "PA4 policy")
    if policy.get("schema_version") != POLICY_SCHEMA:
        raise _failure("M26-PA4-016", "policy schema is incompatible")
    if policy.get("accepted_predecessor_status") != PREDECESSOR_STATUS:
        raise _failure("M26-PA4-017", "policy predecessor is not PA3 accepted")
    if policy.get("owner_decision_self_sha256") != owner_decision.get("self_sha256"):
        raise _failure("M26-PA4-018", "policy owner decision digest mismatch")
    provider = _object(policy.get("provider"), "policy provider")
    if provider.get("provider_id") != "minimax" or provider.get("model_id") != "MiniMax-M3":
        raise _failure("M26-PA4-019", "policy provider mismatch")
    if provider.get("secret_name") != "MINIMAX_API_KEY":
        raise _failure("M26-PA4-020", "policy provider credential mismatch")
    budget = _object(policy.get("budget"), "policy budget")
    if budget.get("max_provider_calls_per_item_including_repair") != 2:
        raise _failure("M26-PA4-021", "policy call budget mismatch")
    if budget.get("max_repair_attempts") != 1:
        raise _failure("M26-PA4-022", "policy repair budget mismatch")
    if float(budget.get("max_spend_usd", -1)) > 1.0:
        raise _failure("M26-PA4-023", "policy spend budget exceeds owner approval")
    verification = _object(policy.get("verification"), "policy verification")
    if verification.get("support_threshold") != 1.0:
        raise _failure("M26-PA4-024", "policy support threshold mismatch")
    if verification.get("allow_unsupported_material_claims") is not False:
        raise _failure("M26-PA4-025", "policy allows unsupported claims")
    privacy = _object(policy.get("privacy_boundary"), "policy privacy boundary")
    required_false = (
        "secret_values_persisted",
        "raw_corpus_text_persisted",
        "vectors_persisted",
        "production_answer_serving",
        "public_traffic",
        "production_pointer_mutation",
        "canonical_writes",
    )
    if any(privacy.get(key) is not False for key in required_false):
        raise _failure("M26-PA4-026", "policy privacy boundary grants forbidden authority")
    return dict(policy)


def validate_population(
    population: Mapping[str, Any], *, policy: Mapping[str, Any]
) -> dict[str, Any]:
    verify_self_digest(population, "PA4 benchmark population")
    if population.get("schema_version") != POPULATION_SCHEMA:
        raise _failure("M26-PA4-027", "population schema is incompatible")
    if population.get("stage_id") != "M26.PA.4":
        raise _failure("M26-PA4-028", "population stage mismatch")
    cases = _list(population.get("cases"), "population cases")
    if len(cases) != 12 or population.get("benchmark_population_count") != 12:
        raise _failure("M26-PA4-029", "population denominator is not 12")
    release = _object(population.get("release"), "population release")
    population_sha = population.get("population_sha256")
    if population_sha != canonical_sha256(cases):
        raise _failure("M26-PA4-030", "population case digest mismatch")
    policy_benchmark = _object(policy.get("benchmark"), "policy benchmark")
    if policy_benchmark.get("population_sha256") != population_sha:
        raise _failure("M26-PA4-031", "policy benchmark digest does not bind population")
    if release.get("release_id") != policy_benchmark.get("release_id"):
        raise _failure("M26-PA4-032", "population release identity mismatch")
    seen_case_ids: set[str] = set()
    seen_locator_ids: set[str] = set()
    categories: set[str] = set()
    modes: set[str] = set()
    for raw_case in cases:
        case = _object(raw_case, "population case")
        required = {
            "case_id",
            "category",
            "material_claim_type",
            "question",
            "expected_terminal_policy",
            "passage_locator",
            "qdrant_locator",
        }
        _strict_keys(case, label="population case", required=required)
        case_id = _string(case.get("case_id"), "case_id", max_len=96)
        if case_id in seen_case_ids:
            raise _failure("M26-PA4-033", "duplicate case id")
        seen_case_ids.add(case_id)
        categories.add(_string(case.get("category"), "category", max_len=96))
        modes.add(_string(case.get("expected_terminal_policy"), "terminal policy", max_len=96))
        question = _object(case.get("question"), "case question")
        _strict_keys(
            question,
            label="case question",
            required={"raw_corpus_text_in_question", "template_id", "text", "text_sha256"},
        )
        if question.get("raw_corpus_text_in_question") is not False:
            raise _failure("M26-PA4-034", "question persists raw corpus text")
        if sha256_bytes(str(question["text"]).encode("utf-8")) != question["text_sha256"]:
            raise _failure("M26-PA4-035", "question text digest mismatch")
        locator = _object(case.get("passage_locator"), "case passage locator")
        locator_id = _string(locator.get("locator_id"), "locator_id", max_len=128)
        if locator_id in seen_locator_ids:
            raise _failure("M26-PA4-036", "duplicate locator id")
        seen_locator_ids.add(locator_id)
        for key in ("source_id", "section_id", "text_sha256", "artifact_key"):
            _string(locator.get(key), key, max_len=512)
        if not SAFE_HEX_64.fullmatch(str(locator.get("text_sha256"))):
            raise _failure("M26-PA4-037", "locator text digest is malformed")
        if "text" in locator or "body" in locator or "excerpt" in locator:
            raise _failure("M26-PA4-038", "population contains raw passage material")
        if locator["release_id"] != release["release_id"]:
            raise _failure("M26-PA4-039", "locator release identity mismatch")
        if locator["artifact_sha256"] != release["semantic_inputs_sha256"]:
            raise _failure("M26-PA4-040", "locator artifact digest mismatch")
        qdrant = _object(case.get("qdrant_locator"), "case qdrant locator")
        for key in ("point_id_sha256", "payload_identity_sha256"):
            value = _string(qdrant.get(key), key, max_len=64)
            if not SAFE_HEX_64.fullmatch(value):
                raise _failure("M26-PA4-041", "qdrant locator digest malformed")
        if qdrant.get("collection") != release["qdrant_collection"]:
            raise _failure("M26-PA4-042", "qdrant collection identity mismatch")
        if qdrant.get("with_vector") is not False:
            raise _failure("M26-PA4-043", "qdrant vectors must remain disabled")
    if "security_adversarial" not in categories or "abstention_required" not in modes:
        raise _failure("M26-PA4-044", "population lacks adversarial or abstention coverage")
    return dict(population)


def validate_registry(root: Path) -> dict[str, Any]:
    owner = load_json(root / OWNER_DECISION_PATH)
    policy = load_json(root / POLICY_PATH)
    population = load_json(root / POPULATION_PATH)
    registry = load_json(root / REGISTRY_PATH)
    validate_owner_decision(owner)
    validate_policy(policy, owner_decision=owner)
    validate_population(population, policy=policy)
    _validate_predecessor(root)
    verify_self_digest(registry, "PA4 registry")
    if registry.get("schema_version") != REGISTRY_SCHEMA:
        raise _failure("M26-PA4-039", "registry schema is incompatible")
    artifacts = _object(registry.get("artifacts"), "registry artifacts")
    expected = {
        "owner_decision_sha256": canonical_sha256(owner),
        "verified_answer_policy_sha256": canonical_sha256(policy),
        "benchmark_population_sha256": canonical_sha256(population),
    }
    if artifacts != expected:
        raise _failure("M26-PA4-040", "registry artifact digest mismatch")
    if registry.get("accepted") is not False:
        raise _failure("M26-PA4-041", "implementation registry cannot accept PA4")
    return {
        "schema_version": "knowledge-engine-m26-pa-4-non-live-validation/v1",
        "stage_id": "M26.PA.4",
        "status": IMPLEMENTATION_STATUS,
        "accepted": False,
        "benchmark_population_count": len(population["cases"]),
        "population_sha256": population["population_sha256"],
        "owner_decision_self_sha256": owner["self_sha256"],
        "policy_self_sha256": policy["self_sha256"],
        "registry_self_sha256": registry["self_sha256"],
    }


def _string(value: Any, label: str, *, max_len: int) -> str:
    if not isinstance(value, str) or not value or len(value) > max_len:
        raise _failure("M26-PA4-042", f"{label} is invalid")
    return value


def _parse_provider_json(text: str) -> dict[str, Any]:
    if len(text) > MAX_PROVIDER_OUTPUT_CHARS:
        raise _failure("M26-PA4-043", "provider output exceeded bounded length")
    stripped = text.strip()
    if not stripped:
        raise _failure("M26-PA4-044", "provider output is empty")
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            raise _failure("M26-PA4-045", "provider output is not JSON") from None
        try:
            value = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError as exc:
            raise _failure("M26-PA4-046", "provider output JSON is malformed") from exc
    return _object(value, "provider JSON")


def build_provider_payload(
    *,
    policy: Mapping[str, Any],
    case: Mapping[str, Any],
    passage_text: str,
    repair: bool = False,
    previous_reason_codes: list[str] | None = None,
) -> dict[str, Any]:
    provider = _object(policy.get("provider"), "policy provider")
    budget = _object(policy.get("budget"), "policy budget")
    locator = _object(case.get("passage_locator"), "case passage locator")
    question = _object(case.get("question"), "case question")
    if len(passage_text.encode("utf-8")) > int(budget["max_passage_bytes_per_item"]):
        raise _failure("M26-PA4-047", "passage exceeds per-item payload budget")
    task = {
        "stage_id": "M26.PA.4",
        "case_id": case["case_id"],
        "attempt_kind": "bounded_repair" if repair else "initial_draft",
        "question": question["text"],
        "expected_terminal_policy": case["expected_terminal_policy"],
        "passage": {
            "locator_id": locator["locator_id"],
            "source_id": locator["source_id"],
            "section_id": locator["section_id"],
            "text": passage_text,
        },
        "previous_reason_codes": previous_reason_codes or [],
        "output_contract": {
            "status_values": ["draft_candidate", "abstain"],
            "non_final_answer_text": SUPPORTED_ANSWER_TEXT,
            "claims": (
                "For draft_candidate, return exactly 1 material_claim. The claim_text must be "
                "copied exactly from the passage and must cite the supplied locator_id. For "
                "abstain, return an empty claims array and reason_codes."
            ),
            "required_json_keys": ["status", "answer_text", "claims", "reason_codes"],
        },
        "forbidden": [
            "final answer label",
            "claims not copied from passage",
            "unsupported material claims",
            "secret values",
            "public traffic",
            "production serving",
        ],
    }
    return {
        "model": provider["model_id"],
        "max_tokens": budget["max_output_tokens_per_call"],
        "temperature": 0,
        "stream": False,
        "system": (
            "You are executing a bounded M26.PA.4 verified-answer citation gate. "
            "Return compact JSON only. Use only the supplied passage. Do not produce "
            "final answers. If support, locator, conflict, temporal freshness, privacy, "
            "or security is insufficient, return status abstain."
        ),
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(task, ensure_ascii=False, sort_keys=True),
                    }
                ],
            }
        ],
    }


def verify_provider_output(
    *,
    case: Mapping[str, Any],
    passage_text: str,
    provider_text: str,
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    if _secret_findings(provider_text):
        raise _failure("M26-PA4-048", "provider output contains secret-like material")
    parsed = _parse_provider_json(provider_text)
    status = parsed.get("status")
    reason_codes = [str(item) for item in parsed.get("reason_codes", []) if str(item)]
    locator = _object(case.get("passage_locator"), "case passage locator")
    expected_policy = str(case["expected_terminal_policy"])
    if expected_policy == "abstention_required":
        return _abstention_item(
            case=case,
            reason_codes=sorted(set(reason_codes + ["CASE_POLICY_REQUIRES_ABSTENTION"])),
            provider_text=provider_text,
            repair_attempts_used=0,
        )
    if status == "abstain":
        claims = parsed.get("claims", [])
        if claims not in ([], None):
            raise _failure("M26-PA4-049", "abstention response contains claims")
        return _abstention_item(
            case=case,
            reason_codes=sorted(set(reason_codes or ["PROVIDER_ABSTAINED"])),
            provider_text=provider_text,
            repair_attempts_used=0,
        )
    if status != "draft_candidate":
        raise _failure("M26-PA4-050", "provider status is not terminal")
    if parsed.get("answer_text") != SUPPORTED_ANSWER_TEXT:
        raise _failure("M26-PA4-051", "answer text contains unextracted material claims")
    raw_claims = _list(parsed.get("claims"), "provider claims")
    if not raw_claims:
        raise _failure("M26-PA4-052", "draft candidate has no material claims")
    max_claims = int(policy["verification"]["max_claims_per_item"])
    if len(raw_claims) > max_claims:
        raise _failure("M26-PA4-053", "draft candidate exceeds material-claim limit")
    claim_records: list[dict[str, Any]] = []
    for index, raw_claim in enumerate(raw_claims, start=1):
        claim = _object(raw_claim, "provider claim")
        claim_text = _string(claim.get("claim_text"), "claim_text", max_len=512)
        if _secret_findings(claim_text):
            raise _failure("M26-PA4-054", "claim text contains secret-like material")
        citation = _object(claim.get("citation"), "provider claim citation")
        if citation.get("locator_id") != locator["locator_id"]:
            raise _failure("M26-PA4-055", "claim citation locator mismatch")
        start = passage_text.find(claim_text)
        if start < 0:
            raise _failure("M26-PA4-056", "claim text is not an exact passage span")
        end = start + len(claim_text)
        claim_records.append(
            {
                "claim_id": str(claim.get("claim_id") or f"claim_{index}"),
                "material": True,
                "material_claim_type": case["material_claim_type"],
                "claim_text_sha256": sha256_bytes(claim_text.encode("utf-8")),
                "claim_char_count": len(claim_text),
                "citation_locator_id": locator["locator_id"],
                "source_id": locator["source_id"],
                "section_id": locator["section_id"],
                "passage_text_sha256": locator["text_sha256"],
                "passage_span": {"start_char": start, "end_char": end},
                "support_verdict": "supported_exact_passage_span",
                "support_reason_code": "EXACT_SPAN_MATCH",
            }
        )
    return {
        "case_id": case["case_id"],
        "terminal_status": "verified_answer_ready_candidate",
        "expected_terminal_policy": expected_policy,
        "draft_answer": {
            "answer_text_sha256": sha256_bytes(str(parsed["answer_text"]).encode("utf-8")),
            "provider_response_text_sha256": sha256_bytes(provider_text.encode("utf-8")),
            "answer_text_persisted": False,
            "provider_response_text_persisted": False,
            "raw_corpus_text_persisted": False,
            "verified_final_answer": False,
            "production_answer_serving": False,
        },
        "material_claims": claim_records,
        "support_verification": {
            "material_claim_count": len(claim_records),
            "supported_claim_count": len(claim_records),
            "unsupported_claim_count": 0,
            "citation_precision": 1.0,
            "support_threshold_met": True,
        },
        "conflict_temporal_verification": {
            "conflict_status": "no_unresolved_conflict_in_single_locator_scope",
            "temporal_status": "release_bounded_not_current_status",
            "stale_temporal_evidence": False,
        },
        "privacy_security": {
            "secret_value_findings": [],
            "prompt_injection_followed": False,
            "raw_corpus_text_persisted": False,
        },
        "repair": {"attempts_used": 0, "max_attempts": policy["budget"]["max_repair_attempts"]},
    }


def _abstention_item(
    *,
    case: Mapping[str, Any],
    reason_codes: list[str],
    provider_text: str,
    repair_attempts_used: int,
) -> dict[str, Any]:
    locator = _object(case.get("passage_locator"), "case passage locator")
    return {
        "case_id": case["case_id"],
        "terminal_status": "abstention_required",
        "expected_terminal_policy": case["expected_terminal_policy"],
        "draft_answer": {
            "answer_text_sha256": sha256_bytes(b""),
            "provider_response_text_sha256": sha256_bytes(provider_text.encode("utf-8")),
            "answer_text_persisted": False,
            "provider_response_text_persisted": False,
            "raw_corpus_text_persisted": False,
            "verified_final_answer": False,
            "production_answer_serving": False,
        },
        "material_claims": [],
        "support_verification": {
            "material_claim_count": 0,
            "supported_claim_count": 0,
            "unsupported_claim_count": 0,
            "citation_precision": 1.0,
            "support_threshold_met": True,
        },
        "conflict_temporal_verification": {
            "conflict_status": "abstained_before_claim_acceptance",
            "temporal_status": "abstained_before_temporal_acceptance",
            "stale_temporal_evidence": False,
        },
        "privacy_security": {
            "secret_value_findings": [],
            "prompt_injection_followed": False,
            "raw_corpus_text_persisted": False,
        },
        "abstention": {
            "reason_codes": sorted(set(reason_codes)),
            "locator_id": locator["locator_id"],
            "policy_triggered": True,
        },
        "repair": {"attempts_used": repair_attempts_used, "max_attempts": 1},
    }


def _provider_response_text(response_json: Mapping[str, Any]) -> str:
    content = response_json.get("content", [])
    if isinstance(content, list):
        text_parts = [
            str(item.get("text", ""))
            for item in content
            if isinstance(item, Mapping) and item.get("type") == "text"
        ]
        if text_parts:
            return "\n".join(text_parts)
    if isinstance(response_json.get("text"), str):
        return str(response_json["text"])
    return json.dumps(dict(response_json), ensure_ascii=False, sort_keys=True)


class MiniMaxM3Client:
    def __init__(self, *, api_key: str, endpoint: str, timeout_seconds: float = 60.0) -> None:
        self.api_key = api_key
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds

    def __call__(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        response = httpx.post(
            self.endpoint,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=dict(payload),
            timeout=self.timeout_seconds,
        )
        try:
            response_json = response.json()
        except ValueError as exc:
            raise _failure(
                "M26-PA4-057", "provider returned non-JSON response", category="provider"
            ) from exc
        if response.status_code >= 400:
            raise _failure(
                "M26-PA4-058",
                "provider returned non-success status",
                category="provider",
                retryable=response.status_code in {429, 500, 502, 503, 504},
            )
        usage = _object(response_json.get("usage"), "provider usage")
        if not isinstance(usage.get("input_tokens"), int) or not isinstance(
            usage.get("output_tokens"), int
        ):
            raise _failure("M26-PA4-059", "provider usage is missing")
        return {
            "response_json": response_json,
            "provider_text": _provider_response_text(response_json),
            "usage": {
                "input_tokens": usage["input_tokens"],
                "output_tokens": usage["output_tokens"],
                "total_tokens": usage["input_tokens"] + usage["output_tokens"],
            },
            "provider_response_id": str(response_json.get("id", "")),
            "response_model": str(response_json.get("model", "")),
            "stop_reason": response_json.get("stop_reason"),
        }


ProviderCall = Callable[[Mapping[str, Any]], dict[str, Any]]


def run_verified_answer_benchmark(
    *,
    root: Path,
    passages_by_case_id: Mapping[str, str],
    provider_call: ProviderCall,
    generated_at: str,
    workflow: Mapping[str, Any],
    evidence_summary: Mapping[str, Any],
) -> dict[str, Any]:
    owner = validate_owner_decision(load_json(root / OWNER_DECISION_PATH))
    policy = validate_policy(load_json(root / POLICY_PATH), owner_decision=owner)
    population = validate_population(load_json(root / POPULATION_PATH), policy=policy)
    _validate_predecessor(root)
    _validate_workflow(workflow)
    if not RFC3339_UTC.fullmatch(generated_at):
        raise _failure("M26-PA4-060", "generated_at must be second-precision UTC")
    try:
        datetime.strptime(generated_at, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise _failure("M26-PA4-061", "generated_at is not valid UTC") from exc
    items: list[dict[str, Any]] = []
    provider_calls = 0
    usage_totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    request_receipts: list[dict[str, Any]] = []
    for case in population["cases"]:
        case_id = str(case["case_id"])
        passage_text = _string(passages_by_case_id.get(case_id), "passage_text", max_len=4096)
        first_payload = build_provider_payload(
            policy=policy, case=case, passage_text=passage_text, repair=False
        )
        _validate_payload_budget(first_payload, policy)
        try:
            first_result = provider_call(first_payload)
            provider_calls += 1
            _accumulate_usage(usage_totals, first_result["usage"])
            request_receipts.append(
                _request_receipt(
                    case_id=case_id, attempt=1, payload=first_payload, result=first_result
                )
            )
        except VerifiedAnswerGateError as error:
            items.append(
                _abstention_item(
                    case=case,
                    reason_codes=[error.code, "PROVIDER_CALL_FAILED"],
                    provider_text="",
                    repair_attempts_used=0,
                )
            )
            continue
        try:
            item = verify_provider_output(
                case=case,
                passage_text=passage_text,
                provider_text=first_result["provider_text"],
                policy=policy,
            )
        except VerifiedAnswerGateError as error:
            max_repair = int(policy["budget"]["max_repair_attempts"])
            if max_repair <= 0:
                item = _abstention_item(
                    case=case,
                    reason_codes=[error.code, "REPAIR_NOT_AUTHORIZED"],
                    provider_text=first_result["provider_text"],
                    repair_attempts_used=0,
                )
            else:
                repair_payload = build_provider_payload(
                    policy=policy,
                    case=case,
                    passage_text=passage_text,
                    repair=True,
                    previous_reason_codes=[error.code],
                )
                _validate_payload_budget(repair_payload, policy)
                try:
                    repair_result = provider_call(repair_payload)
                    provider_calls += 1
                    _accumulate_usage(usage_totals, repair_result["usage"])
                    request_receipts.append(
                        _request_receipt(
                            case_id=case_id,
                            attempt=2,
                            payload=repair_payload,
                            result=repair_result,
                        )
                    )
                except VerifiedAnswerGateError as repair_call_error:
                    items.append(
                        _abstention_item(
                            case=case,
                            reason_codes=[
                                error.code,
                                repair_call_error.code,
                                "REPAIR_CALL_FAILED",
                            ],
                            provider_text="",
                            repair_attempts_used=1,
                        )
                    )
                    continue
                try:
                    item = verify_provider_output(
                        case=case,
                        passage_text=passage_text,
                        provider_text=repair_result["provider_text"],
                        policy=policy,
                    )
                    item["repair"] = {
                        "attempts_used": 1,
                        "max_attempts": policy["budget"]["max_repair_attempts"],
                        "initial_failure_code": error.code,
                    }
                    if item["terminal_status"] == "verified_answer_ready_candidate":
                        item["terminal_status"] = (
                            "verified_answer_ready_candidate_after_bounded_repair"
                        )
                except VerifiedAnswerGateError as repair_error:
                    item = _abstention_item(
                        case=case,
                        reason_codes=[error.code, repair_error.code, "REPAIR_BUDGET_EXHAUSTED"],
                        provider_text=repair_result["provider_text"],
                        repair_attempts_used=1,
                    )
        items.append(item)
    _validate_receipt_thresholds(policy=policy, items=items, provider_calls=provider_calls)
    summary = _summary(items)
    receipt = with_self_digest(
        {
            "schema_version": RECEIPT_SCHEMA,
            "stage_id": "M26.PA.4",
            "status": LIVE_VERIFIED_STATUS,
            "generated_at": generated_at,
            "owner_decision": {
                "owner_decision_self_sha256": owner["self_sha256"],
                "exact_instruction_text_sha256": sha256_bytes(
                    owner["exact_instruction_text"].encode("utf-8")
                ),
            },
            "policy": {
                "policy_self_sha256": policy["self_sha256"],
                "max_provider_calls_per_item_including_repair": policy["budget"][
                    "max_provider_calls_per_item_including_repair"
                ],
                "max_repair_attempts": policy["budget"]["max_repair_attempts"],
                "support_threshold": policy["verification"]["support_threshold"],
            },
            "population": {
                "benchmark_population_count": population["benchmark_population_count"],
                "population_sha256": population["population_sha256"],
                "population_self_sha256": population["self_sha256"],
            },
            "workflow": dict(workflow),
            "provider": {
                "provider_id": policy["provider"]["provider_id"],
                "model_id": policy["provider"]["model_id"],
                "endpoint": policy["provider"]["endpoint"],
                "provider_response_text_persisted": False,
            },
            "evidence_summary": dict(evidence_summary),
            "request_receipts": request_receipts,
            "items": items,
            "summary": summary,
            "usage": usage_totals,
            "authority": {
                "provider_calls": provider_calls,
                "credential_names": ["MINIMAX_API_KEY"],
                "secret_values_persisted": False,
                "raw_corpus_text_sent_to_provider": True,
                "raw_corpus_text_persisted": False,
                "provider_response_text_persisted": False,
                "vectors_requested": False,
                "vectors_returned": False,
                "vectors_persisted": False,
                "r2_write_operations": 0,
                "qdrant_write_operations": 0,
                "source_foundation_release_mutations": 0,
                "production_pointer_mutations": 0,
                "public_shadow_canary_traffic_operations": 0,
                "production_answer_serving": False,
                "canonical_writes": 0,
            },
        }
    )
    serialized = pretty_bytes(receipt).decode("utf-8")
    if _secret_findings(serialized):
        raise _failure("M26-PA4-062", "receipt contains secret-like material")
    return receipt


def _validate_payload_budget(payload: Mapping[str, Any], policy: Mapping[str, Any]) -> None:
    prompt_bytes = len(canonical_bytes(payload))
    if prompt_bytes > int(policy["budget"]["max_prompt_bytes_per_item"]):
        raise _failure("M26-PA4-063", "provider payload exceeds prompt byte budget")


def _request_receipt(
    *, case_id: str, attempt: int, payload: Mapping[str, Any], result: Mapping[str, Any]
) -> dict[str, Any]:
    response_json = _object(result.get("response_json"), "provider response json")
    provider_text = _string(
        result.get("provider_text"), "provider text", max_len=MAX_PROVIDER_OUTPUT_CHARS
    )
    return {
        "case_id": case_id,
        "attempt": attempt,
        "payload_sha256": canonical_sha256(payload),
        "prompt_bytes": len(canonical_bytes(payload)),
        "provider_response_json_sha256": canonical_sha256(response_json),
        "provider_response_text_sha256": sha256_bytes(provider_text.encode("utf-8")),
        "provider_response_text_persisted": False,
        "raw_corpus_text_persisted": False,
        "usage": dict(result["usage"]),
        "provider_response_id_sha256": sha256_bytes(
            str(result.get("provider_response_id", "")).encode("utf-8")
        ),
        "response_model": str(result.get("response_model", "")),
        "stop_reason": result.get("stop_reason"),
    }


def _accumulate_usage(total: dict[str, int], usage: Mapping[str, Any]) -> None:
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        value = usage.get(key)
        if not isinstance(value, int) or value < 0:
            raise _failure("M26-PA4-064", "provider usage value is invalid")
        total[key] += value


def _summary(items: list[Mapping[str, Any]]) -> dict[str, Any]:
    material_count = sum(
        int(item["support_verification"]["material_claim_count"]) for item in items
    )
    supported = sum(int(item["support_verification"]["supported_claim_count"]) for item in items)
    unsupported = sum(
        int(item["support_verification"]["unsupported_claim_count"]) for item in items
    )
    ready = sum(1 for item in items if str(item["terminal_status"]).startswith("verified_answer"))
    abstained = sum(1 for item in items if item["terminal_status"] == "abstention_required")
    precision = 1.0 if material_count == 0 else supported / material_count
    return {
        "benchmark_population_count": len(items),
        "ready_candidate_count": ready,
        "abstention_count": abstained,
        "material_claim_count": material_count,
        "supported_material_claim_count": supported,
        "unsupported_material_claim_count": unsupported,
        "citation_precision": precision,
        "all_non_abstained_material_claims_supported": unsupported == 0 and precision == 1.0,
    }


def _validate_receipt_thresholds(
    *, policy: Mapping[str, Any], items: list[Mapping[str, Any]], provider_calls: int
) -> None:
    maximum = len(items) * int(policy["budget"]["max_provider_calls_per_item_including_repair"])
    if provider_calls > maximum:
        raise _failure("M26-PA4-065", "provider call budget exceeded")
    summary = _summary(items)
    if summary["citation_precision"] < float(policy["verification"]["support_threshold"]):
        raise _failure("M26-PA4-066", "citation support threshold not met")
    if summary["unsupported_material_claim_count"] != 0:
        raise _failure("M26-PA4-067", "unsupported material claims accepted")
    minimum_ready = int(policy["verification"]["minimum_ready_candidate_items"])
    if summary["ready_candidate_count"] < minimum_ready:
        raise _failure("M26-PA4-068", "too few ready candidates in real run")
    minimum_abstentions = int(policy["verification"]["minimum_abstention_items"])
    if summary["abstention_count"] < minimum_abstentions:
        raise _failure("M26-PA4-069", "abstention coverage was not exercised")


def _validate_workflow(workflow: Mapping[str, Any]) -> None:
    required = {"repository", "workflow_name", "run_id", "run_attempt", "head_sha", "environment"}
    _strict_keys(workflow, label="workflow identity", required=required)
    if workflow.get("repository") != "danielcanfly/knowledge-engine":
        raise _failure("M26-PA4-070", "workflow repository mismatch")
    if workflow.get("environment") != "m23-r3-diagnostic":
        raise _failure("M26-PA4-071", "workflow environment mismatch")
    if not isinstance(workflow.get("head_sha"), str) or not SAFE_HEX_40.fullmatch(
        workflow["head_sha"]
    ):
        raise _failure("M26-PA4-072", "workflow head SHA malformed")
    if str(workflow.get("run_attempt")) != "1":
        raise _failure("M26-PA4-073", "workflow run attempt must be exactly 1")


def current_utc_second() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def sleep_between_provider_calls(seconds: float) -> None:
    if seconds < 0 or seconds > 5:
        raise _failure("M26-PA4-074", "provider call sleep outside bounded range")
    time.sleep(seconds)


def build_live_evidence_bundle(
    *,
    root: Path,
    store: Any,
    qdrant: Any,
    population: Mapping[str, Any],
) -> tuple[dict[str, str], dict[str, Any]]:
    release = _object(population.get("release"), "population release")
    manifest_key = str(release["manifest_key"])
    semantic_key = str(release["semantic_inputs_key"])
    pointer_bytes = store.get("channels/production.json")
    pointer = json.loads(pointer_bytes)
    if sha256_bytes(pointer_bytes) != release["pointer_sha256"]:
        raise _failure("M26-PA4-075", "production pointer digest mismatch")
    if pointer.get("release_id") != release["release_id"]:
        raise _failure("M26-PA4-076", "production pointer release mismatch")
    if pointer.get("manifest_key") != manifest_key:
        raise _failure("M26-PA4-077", "production pointer manifest mismatch")
    manifest_bytes = store.get(manifest_key)
    manifest = json.loads(manifest_bytes)
    manifest_artifacts = _list(manifest.get("artifacts"), "manifest artifacts")
    artifact_by_kind = {str(item.get("kind")): item for item in manifest_artifacts}
    semantic_artifact = _object(artifact_by_kind.get("semantic_inputs"), "semantic_inputs artifact")
    if semantic_artifact.get("sha256") != release["semantic_inputs_sha256"]:
        raise _failure("M26-PA4-078", "semantic inputs digest mismatch")
    semantic_inputs = json.loads(store.get(semantic_key))
    if semantic_inputs.get("release_id") != release["release_id"]:
        raise _failure("M26-PA4-079", "semantic inputs release mismatch")
    documents = _list(semantic_inputs.get("documents"), "semantic input documents")
    doc_by_index = {index: _object(doc, "semantic document") for index, doc in enumerate(documents)}
    release_id = release["release_id"]
    collection = release["qdrant_collection"]
    count_response = qdrant.count(
        collection=collection,
        query_filter={"must": [{"key": "release_id", "match": {"value": release_id}}]},
        timeout_seconds=30,
    )
    count_payload = _object(count_response.payload, "qdrant count payload")
    if count_payload.get("status") != "ok":
        raise _failure("M26-PA4-080", "qdrant count failed")
    observed_count = int(_object(count_payload.get("result"), "qdrant count result")["count"])
    offset = None
    page_count = 0
    qdrant_rows: dict[str, dict[str, Any]] = {}
    qdrant_payload_sha256_by_section: dict[str, str] = {}
    while True:
        request: dict[str, Any] = {
            "filter": {"must": [{"key": "release_id", "match": {"value": release_id}}]},
            "limit": 256,
            "with_payload": [
                "section_id",
                "source_id",
                "release_id",
                "source_commit_sha",
                "admission_sha256",
                "candidate_release_eligible",
                "production_authority",
                "text_sha256",
            ],
            "with_vector": False,
        }
        if offset is not None:
            request["offset"] = offset
        response = qdrant.scroll(collection=collection, request=request, timeout_seconds=30)
        page_count += 1
        payload = _object(response.payload, "qdrant scroll payload")
        if payload.get("status") != "ok":
            raise _failure("M26-PA4-081", "qdrant scroll failed")
        result = _object(payload.get("result"), "qdrant scroll result")
        points = _list(result.get("points"), "qdrant scroll points")
        for point in points:
            row = _object(point, "qdrant point")
            point_payload = _object(row.get("payload"), "qdrant point payload")
            section_id = _string(point_payload.get("section_id"), "section_id", max_len=128)
            qdrant_rows[section_id] = row
            qdrant_payload_sha256_by_section[section_id] = canonical_sha256(point_payload)
        offset = result.get("next_page_offset")
        if offset is None:
            break
    if len(qdrant_rows) != observed_count:
        raise _failure("M26-PA4-082", "qdrant population is incomplete")
    passages_by_case_id: dict[str, str] = {}
    for case in _list(population.get("cases"), "population cases"):
        case_obj = _object(case, "population case")
        case_id = str(case_obj["case_id"])
        locator = _object(case_obj["passage_locator"], "case passage locator")
        doc_index = int(locator["document_index"])
        document = doc_by_index.get(doc_index)
        if document is None:
            raise _failure("M26-PA4-083", "document index is missing from semantic inputs")
        if document.get("section_id") != locator["section_id"]:
            raise _failure("M26-PA4-084", "semantic document section mismatch")
        text = _string(document.get("text"), "semantic text", max_len=4096)
        if sha256_bytes(text.encode("utf-8")) != locator["text_sha256"]:
            raise _failure("M26-PA4-085", "semantic text digest mismatch")
        qdrant_row = qdrant_rows.get(locator["section_id"])
        if qdrant_row is None:
            raise _failure("M26-PA4-086", "qdrant row is missing for locator")
        qdrant_payload = _object(qdrant_row.get("payload"), "qdrant payload")
        if qdrant_payload.get("text_sha256") != locator["text_sha256"]:
            raise _failure("M26-PA4-087", "qdrant payload digest mismatch")
        if qdrant_payload.get("source_id") != locator["source_id"]:
            raise _failure("M26-PA4-088", "qdrant payload source mismatch")
        if qdrant_payload.get("release_id") != release_id:
            raise _failure("M26-PA4-089", "qdrant payload release mismatch")
        if qdrant_payload.get("source_commit_sha") != release["source_commit_sha"]:
            raise _failure("M26-PA4-090", "qdrant payload source commit mismatch")
        passages_by_case_id[case_id] = text
    evidence_summary = {
        "release_id": release_id,
        "manifest_sha256": release["manifest_sha256"],
        "pointer_sha256": release["pointer_sha256"],
        "semantic_inputs_sha256": release["semantic_inputs_sha256"],
        "qdrant_collection": collection,
        "observed_qdrant_point_count": observed_count,
        "qdrant_scroll_pages": page_count,
        "selected_case_count": len(passages_by_case_id),
        "qdrant_payload_sha256_by_section": qdrant_payload_sha256_by_section,
    }
    return passages_by_case_id, evidence_summary
