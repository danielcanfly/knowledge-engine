from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

EXPECTED_RELEASE_ID = "m25blog-5250f8422f4f-f5f01d82c7a1-fe499db2e043"
EXPECTED_GRAPH_SHA256 = (
    "ddaceb89bfda15618fdf9360953d9f66a5c8b33c3853480c1db7abe41ba32869"
)
EXPECTED_NODE_COUNT = 4222
EXPECTED_EDGE_COUNT = 8525
EXPECTED_GRAPH_EDGE = "edge_3f15206278e63ccf8981"
ANSWER_SOURCE = "provider_verified_runtime_bound_semantic_closure"
_TRANSIENT_REQUEST_ERRORS = (
    ConnectionResetError,
    TimeoutError,
    http.client.RemoteDisconnected,
    urllib.error.URLError,
)
_TRANSIENT_HTTP_STATUSES = {409, 425, 429, 500, 502, 503, 504}
GET_REQUEST_ATTEMPTS = 4
GET_REQUEST_TIMEOUT_SECONDS = 45
QUERY_POST_ATTEMPTS = 1
PROVIDER_NETWORK_DEADLINE_SECONDS = 120
PRODUCTION_QUERY_WALLCLOCK_DEADLINE_SECONDS = 300
QUERY_COLLECTOR_REQUEST_TIMEOUT_SECONDS = 330
POPULATION_DEADLINE_SECONDS = 2700
GET_RETRY_BACKOFF_SECONDS = (2, 5, 10)


@dataclass(frozen=True)
class RequestFailure(RuntimeError):
    reason: str
    http_status: int = 0
    payload: dict[str, Any] | None = None
    elapsed_ms: int = 0
    attempts: int = 1


def _emit_progress(key: str, value: str | int) -> None:
    print(f"{key}={value}", flush=True)


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _parse_json_response(raw: bytes) -> dict[str, Any]:
    try:
        parsed = json.loads(raw)
    except Exception:
        return {"error": "non-json response"}
    return parsed if isinstance(parsed, dict) else {"error": "non-object json response"}


def _headers(*, token: str, owner_hash: str) -> dict[str, str]:
    return {
        "authorization": f"Bearer {token}",
        "x-m26-owner-subject-hash": owner_hash,
    }


def _request_json_get(
    url: str,
    *,
    token: str,
    owner_hash: str,
) -> tuple[int, dict[str, Any], int, int]:
    total_started = time.monotonic()
    request = urllib.request.Request(
        url,
        headers=_headers(token=token, owner_hash=owner_hash),
        method="GET",
    )
    for attempt in range(1, GET_REQUEST_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(
                request,
                timeout=GET_REQUEST_TIMEOUT_SECONDS,
            ) as response:
                raw = response.read()
                return response.status, _parse_json_response(raw), _elapsed_ms(
                    total_started
                ), attempt
        except urllib.error.HTTPError as exc:
            parsed = _parse_json_response(exc.read())
            if exc.code in _TRANSIENT_HTTP_STATUSES and attempt < GET_REQUEST_ATTEMPTS:
                time.sleep(GET_RETRY_BACKOFF_SECONDS[attempt - 1])
                continue
            return exc.code, parsed, _elapsed_ms(total_started), attempt
        except _TRANSIENT_REQUEST_ERRORS as exc:
            if attempt == GET_REQUEST_ATTEMPTS:
                raise RequestFailure(
                    reason=type(exc).__name__,
                    payload={"error": "transient GET request failure"},
                    elapsed_ms=_elapsed_ms(total_started),
                    attempts=attempt,
                ) from exc
            time.sleep(GET_RETRY_BACKOFF_SECONDS[attempt - 1])
    raise RuntimeError("unreachable GET retry state")


def _query_post_json(
    url: str,
    *,
    token: str,
    owner_hash: str,
    payload: dict[str, Any],
    case_id: str,
) -> tuple[int, dict[str, Any], int, int]:
    total_started = time.monotonic()
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = _headers(token=token, owner_hash=owner_hash)
    headers["content-type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    for attempt in range(1, QUERY_POST_ATTEMPTS + 1):
        _emit_progress("AQ_COLLECT_CASE_ATTEMPT", attempt)
        try:
            with urllib.request.urlopen(
                request,
                timeout=QUERY_COLLECTOR_REQUEST_TIMEOUT_SECONDS,
            ) as response:
                raw = response.read()
                elapsed = _elapsed_ms(total_started)
                _emit_progress("AQ_COLLECT_CASE_HTTP_STATUS", response.status)
                _emit_progress("AQ_COLLECT_CASE_ELAPSED_MS", elapsed)
                return response.status, _parse_json_response(raw), elapsed, attempt
        except urllib.error.HTTPError as exc:
            parsed = _parse_json_response(exc.read())
            elapsed = _elapsed_ms(total_started)
            _emit_progress("AQ_COLLECT_CASE_HTTP_STATUS", exc.code)
            _emit_progress("AQ_COLLECT_CASE_ELAPSED_MS", elapsed)
            return exc.code, parsed, elapsed, attempt
        except _TRANSIENT_REQUEST_ERRORS as exc:
            elapsed = _elapsed_ms(total_started)
            _emit_progress("AQ_COLLECT_CASE_HTTP_STATUS", 0)
            _emit_progress("AQ_COLLECT_CASE_ELAPSED_MS", elapsed)
            raise RequestFailure(
                reason=type(exc).__name__,
                payload={"error": "query POST request failure", "case_id": case_id},
                elapsed_ms=elapsed,
                attempts=attempt,
            ) from exc
    raise RuntimeError("unreachable query POST state")


def _timeout_policy() -> dict[str, int]:
    return {
        "provider_network_deadline_seconds": PROVIDER_NETWORK_DEADLINE_SECONDS,
        "production_query_wallclock_deadline_seconds": (
            PRODUCTION_QUERY_WALLCLOCK_DEADLINE_SECONDS
        ),
        "collector_request_timeout_seconds": QUERY_COLLECTOR_REQUEST_TIMEOUT_SECONDS,
        "population_deadline_seconds": POPULATION_DEADLINE_SECONDS,
        "get_request_attempts": GET_REQUEST_ATTEMPTS,
        "query_post_attempts": QUERY_POST_ATTEMPTS,
    }


def _assert_timeout_hierarchy() -> None:
    if not (
        PROVIDER_NETWORK_DEADLINE_SECONDS
        < PRODUCTION_QUERY_WALLCLOCK_DEADLINE_SECONDS
        < QUERY_COLLECTOR_REQUEST_TIMEOUT_SECONDS
        < POPULATION_DEADLINE_SECONDS
    ):
        raise RuntimeError("invalid AQ closure timeout hierarchy")


def _write_artifact_atomic(output: Path, artifact: dict[str, Any]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.write_text(
        json.dumps(artifact, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)


def _new_artifact(*, expected_sha: str) -> dict[str, Any]:
    return {
        "schema_version": "m26-aq-final-live-closure/v2",
        "expected_deploy_sha": expected_sha,
        "health": {},
        "graph": {},
        "rows": [],
        "collection": {
            "status": "running",
            "started_monotonic_ms": int(time.monotonic() * 1000),
            "elapsed_ms": 0,
            "current_case_id": None,
            "completed_case_ids": [],
            "failure": None,
            "timeout_policy": _timeout_policy(),
        },
        "privacy": {
            "raw_backend_token_recorded": False,
            "raw_owner_hash_recorded": False,
            "provider_secret_recorded": False,
        },
    }


def _update_collection(
    artifact: dict[str, Any],
    *,
    collect_started: float,
    status: str | None = None,
    current_case_id: str | None = None,
    failure: dict[str, Any] | None = None,
) -> None:
    collection = artifact.setdefault("collection", {})
    collection["elapsed_ms"] = _elapsed_ms(collect_started)
    if status is not None:
        collection["status"] = status
    if current_case_id is not None:
        collection["current_case_id"] = current_case_id
    if failure is not None:
        collection["failure"] = failure


def _query_failure_row(
    case: dict[str, Any],
    *,
    http_status: int,
    reason: str,
    elapsed_ms: int,
    attempts: int,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "case_id": case["case_id"],
        "class": case.get("class"),
        "question": case["question"],
        "expected": case.get("expected"),
        "critical": bool(case.get("critical", False)),
        "http_status": http_status,
        "status": "collector_failure",
        "terminal_status": "collector_failure",
        "safe_abstention": False,
        "answer_text": "",
        "answer_source": "",
        "reason_codes": [reason],
        "citations": [],
        "answer_claims": [],
        "relationship_summary": {},
        "multi_evidence_verification": {},
        "semantic_closure": {},
        "selected_evidence": [],
        "evidence_utilization_trace": {},
        "graph_observability": {},
        "retrieval": {},
        "accounting": {"provider_call_count": 0},
        "integrity": {
            "unsupported_accepted_claims": 0,
            "material_claim_support_verified": False,
            "citation_locator_valid": False,
        },
        "mutations": {},
        "canonical_runtime": {},
        "collector": {
            "attempts": attempts,
            "elapsed_ms": elapsed_ms,
            "failure_class": reason,
            "sanitized_failure": payload or {"error": reason},
            "timeout_converted_to_answer": False,
        },
    }


def _row_from_response(
    case: dict[str, Any],
    *,
    code: int,
    response: dict[str, Any],
    elapsed_ms: int,
    attempts: int,
) -> dict[str, Any]:
    deadline_exceeded = elapsed_ms > PRODUCTION_QUERY_WALLCLOCK_DEADLINE_SECONDS * 1000
    return {
        "case_id": case["case_id"],
        "class": case.get("class"),
        "question": case["question"],
        "expected": case.get("expected"),
        "critical": bool(case.get("critical", False)),
        "http_status": code,
        "status": response.get("status"),
        "terminal_status": response.get("terminal_status"),
        "safe_abstention": response.get("safe_abstention"),
        "answer_text": response.get("answer_text", ""),
        "answer_source": response.get("answer_source", ""),
        "reason_codes": response.get("reason_codes", []),
        "citations": response.get("citations", []),
        "answer_claims": response.get("answer_claims", []),
        "relationship_summary": response.get("relationship_summary", {}),
        "multi_evidence_verification": response.get(
            "multi_evidence_verification", {}
        ),
        "semantic_closure": response.get("semantic_closure", {}),
        "selected_evidence": response.get("selected_evidence", []),
        "evidence_utilization_trace": response.get("evidence_utilization_trace", {}),
        "graph_observability": response.get("graph_observability", {}),
        "retrieval": response.get("retrieval", {}),
        "accounting": response.get("accounting", {}),
        "integrity": response.get("integrity", {}),
        "mutations": response.get("mutations", {}),
        "canonical_runtime": response.get("canonical_runtime", {}),
        "collector": {
            "attempts": attempts,
            "elapsed_ms": elapsed_ms,
            "deadline_exceeded": deadline_exceeded,
            "timeout_converted_to_answer": False,
        },
    }


def _graph_summary(graph_code: int, graph: dict[str, Any]) -> dict[str, Any]:
    return {
        "http_status": graph_code,
        "status": graph.get("status"),
        "graph_scope": graph.get("graph_scope"),
        "release_id": graph.get("release_id"),
        "graph_v2_sha256": graph.get("graph_v2_sha256"),
        "node_count": len(graph.get("nodes", []))
        if isinstance(graph.get("nodes"), list)
        else 0,
        "edge_count": len(graph.get("edges", []))
        if isinstance(graph.get("edges"), list)
        else 0,
        "authority": graph.get("authority", {}),
    }


def _fail_collection(
    artifact: dict[str, Any],
    output: Path,
    *,
    collect_started: float,
    reason: str,
    case_id: str | None = None,
) -> None:
    _update_collection(
        artifact,
        collect_started=collect_started,
        status="failed",
        current_case_id=case_id,
        failure={"reason": reason, "case_id": case_id},
    )
    _write_artifact_atomic(output, artifact)
    raise SystemExit(f"AQ collection failed: {reason}")


def collect(
    *,
    questions_path: Path,
    output: Path,
    base_url: str,
    expected_sha: str,
) -> None:
    _assert_timeout_hierarchy()
    collect_started = time.monotonic()
    token = os.environ.get("M26_QUERY_BACKEND_TOKEN", "")
    owner_hash = os.environ.get("KNOWLEDGE_ENGINE_OWNER_SUBJECT_HASH", "")
    if not token or not owner_hash:
        raise SystemExit("missing owner-only backend credentials")
    questions = json.loads(questions_path.read_text(encoding="utf-8"))["questions"]
    artifact = _new_artifact(expected_sha=expected_sha)
    _write_artifact_atomic(output, artifact)
    try:
        health_code, health, _, _ = _request_json_get(
            f"{base_url.rstrip('/')}/api/m26/health",
            token=token,
            owner_hash=owner_hash,
        )
    except RequestFailure as exc:
        artifact["health"] = {
            "http_status": exc.http_status,
            "status": "collector_failure",
            "failure": exc.reason,
        }
        _fail_collection(
            artifact,
            output,
            collect_started=collect_started,
            reason="health_get_failed",
        )
    artifact["health"] = {
        "http_status": health_code,
        "status": health.get("status"),
        "build_sha": health.get("canonical_runtime", {}).get("build_sha"),
        "entrypoint": health.get("canonical_runtime", {}).get("entrypoint"),
    }
    _update_collection(artifact, collect_started=collect_started)
    _write_artifact_atomic(output, artifact)
    try:
        graph_code, graph, _, _ = _request_json_get(
            f"{base_url.rstrip('/')}/api/m26/graph",
            token=token,
            owner_hash=owner_hash,
        )
    except RequestFailure as exc:
        artifact["graph"] = {
            "http_status": exc.http_status,
            "status": "collector_failure",
            "failure": exc.reason,
        }
        _fail_collection(
            artifact,
            output,
            collect_started=collect_started,
            reason="graph_get_failed",
        )
    artifact["graph"] = _graph_summary(graph_code, graph)
    _update_collection(artifact, collect_started=collect_started)
    _write_artifact_atomic(output, artifact)
    for case in questions:
        case_id = str(case["case_id"])
        if time.monotonic() - collect_started > POPULATION_DEADLINE_SECONDS:
            _fail_collection(
                artifact,
                output,
                collect_started=collect_started,
                reason="population_deadline_exceeded_before_case",
                case_id=case_id,
            )
        _emit_progress("AQ_COLLECT_CASE_START", case_id)
        _update_collection(
            artifact,
            collect_started=collect_started,
            current_case_id=case_id,
        )
        _write_artifact_atomic(output, artifact)
        try:
            code, response, elapsed_ms, attempts = _query_post_json(
                f"{base_url.rstrip('/')}/api/m26/query",
                token=token,
                owner_hash=owner_hash,
                payload={"question": case["question"]},
                case_id=case_id,
            )
        except RequestFailure as exc:
            row = _query_failure_row(
                case,
                http_status=exc.http_status,
                reason=exc.reason,
                elapsed_ms=exc.elapsed_ms,
                attempts=exc.attempts,
                payload=exc.payload,
            )
            artifact["rows"].append(row)
            _fail_collection(
                artifact,
                output,
                collect_started=collect_started,
                reason=exc.reason,
                case_id=case_id,
            )
        row = _row_from_response(
            case,
            code=code,
            response=response,
            elapsed_ms=elapsed_ms,
            attempts=attempts,
        )
        artifact["rows"].append(row)
        artifact["collection"]["completed_case_ids"].append(case_id)
        _update_collection(artifact, collect_started=collect_started)
        _write_artifact_atomic(output, artifact)
        _emit_progress("AQ_COLLECT_CASE_DONE", case_id)
        if code != 200:
            _fail_collection(
                artifact,
                output,
                collect_started=collect_started,
                reason="query_http_not_200",
                case_id=case_id,
            )
        if row.get("collector", {}).get("deadline_exceeded"):
            _fail_collection(
                artifact,
                output,
                collect_started=collect_started,
                reason="query_wallclock_deadline_exceeded",
                case_id=case_id,
            )
        if time.monotonic() - collect_started > POPULATION_DEADLINE_SECONDS:
            _fail_collection(
                artifact,
                output,
                collect_started=collect_started,
                reason="population_deadline_exceeded_after_case",
                case_id=case_id,
            )
    _update_collection(
        artifact,
        collect_started=collect_started,
        status="complete",
        current_case_id=None,
    )
    _write_artifact_atomic(output, artifact)


def _provider_telemetry(row: dict[str, Any]) -> list[dict[str, Any]]:
    verification = row.get("multi_evidence_verification", {})
    telemetry = (
        verification.get("provider_attempt_telemetry", [])
        if isinstance(verification, dict)
        else []
    )
    return telemetry if isinstance(telemetry, list) else []


def _zero_mutations(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    return all(
        not isinstance(item, bool) and int(item) == 0
        for item in value.values()
    )


def _validate_visible_semantics(row: dict[str, Any]) -> list[str]:
    from knowledge_engine.m26_pa7_semantic_closure_runtime import (
        _semantic_requirements,
        _visible_semantic_failures,
    )

    question = str(row.get("question", ""))
    relationship = row.get("relationship_summary", {})
    intent = (
        str(relationship.get("intent_class") or "direct_grounded_knowledge")
        if isinstance(relationship, dict)
        else "direct_grounded_knowledge"
    )
    requirements = _semantic_requirements(question, intent)
    return _visible_semantic_failures(
        str(row.get("answer_text", "")),
        requirements,
        question,
    )


def validate(
    *,
    input_path: Path,
    gate_path: Path,
    expected_sha: str,
) -> None:
    artifact = json.loads(input_path.read_text(encoding="utf-8"))
    failures: list[str] = []
    collection = artifact.get("collection", {})
    if isinstance(collection, dict):
        if collection.get("status") != "complete":
            failures.append("collection_not_complete")
        if collection.get("failure"):
            failures.append("collection_failure_recorded")
    else:
        failures.append("collection_metadata_missing")
    health = artifact.get("health", {})
    graph = artifact.get("graph", {})
    if health.get("http_status") != 200 or health.get("status") != "ok":
        failures.append("health_not_ok")
    if health.get("build_sha") != expected_sha:
        failures.append("health_build_sha_mismatch")
    if (
        health.get("entrypoint")
        != "knowledge_engine.m26_pa7_semantic_closure_runtime.run_owner_arbitrary_query"
    ):
        failures.append("wrong_production_entrypoint")
    if graph.get("http_status") != 200 or graph.get("status") != "ok":
        failures.append("graph_not_ok")
    if graph.get("graph_scope") != "full_current_production_relation_graph":
        failures.append("graph_scope_mismatch")
    if graph.get("release_id") != EXPECTED_RELEASE_ID:
        failures.append("graph_release_mismatch")
    if graph.get("graph_v2_sha256") != EXPECTED_GRAPH_SHA256:
        failures.append("graph_sha_mismatch")
    if (
        graph.get("node_count") != EXPECTED_NODE_COUNT
        or graph.get("edge_count") != EXPECTED_EDGE_COUNT
    ):
        failures.append("graph_population_mismatch")
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    identities = gate.get("production_identities", {})
    if identities.get("public_traffic_percent") != 0:
        failures.append("public_traffic_not_zero")

    rows = artifact.get("rows", [])
    if not isinstance(rows, list) or len(rows) != 12:
        failures.append("r3_population_not_12")
        rows = rows if isinstance(rows, list) else []
    by_id = {
        str(row.get("case_id")): row
        for row in rows
        if isinstance(row, dict)
    }
    abstain_ids = {"R3-Q10", "R3-Q11"}
    for case_id in [f"R3-Q{index:02d}" for index in range(1, 13)]:
        row = by_id.get(case_id)
        if row is None:
            failures.append(f"{case_id}:missing")
            continue
        if row.get("http_status") != 200:
            failures.append(f"{case_id}:http")
            continue
        collector = row.get("collector", {})
        if isinstance(collector, dict):
            if collector.get("deadline_exceeded"):
                failures.append(f"{case_id}:collector_deadline_exceeded")
            if collector.get("timeout_converted_to_answer") is not False:
                failures.append(f"{case_id}:timeout_converted_to_answer")
        accounting = (
            row.get("accounting", {})
            if isinstance(row.get("accounting"), dict)
            else {}
        )
        provider_calls = int(accounting.get("provider_call_count", 0))
        if case_id in abstain_ids:
            if (
                not row.get("safe_abstention")
                or row.get("status") != "owner_only_safe_abstention"
            ):
                failures.append(f"{case_id}:expected_safe_abstention")
            if provider_calls != 0:
                failures.append(f"{case_id}:provider_calls_not_zero")
            continue
        if (
            row.get("safe_abstention")
            or row.get("status") != "owner_only_cited_answer"
        ):
            failures.append(f"{case_id}:not_answered")
        if row.get("answer_source") != ANSWER_SOURCE:
            failures.append(f"{case_id}:wrong_answer_source")
        if not str(row.get("answer_text", "")).strip():
            failures.append(f"{case_id}:empty_answer")
        if provider_calls < 1 or provider_calls > 2:
            failures.append(f"{case_id}:provider_call_count")
        if not row.get("citations"):
            failures.append(f"{case_id}:missing_citations")
        integrity = (
            row.get("integrity", {})
            if isinstance(row.get("integrity"), dict)
            else {}
        )
        if int(integrity.get("unsupported_accepted_claims", 0)) != 0:
            failures.append(f"{case_id}:unsupported_claims")
        if not integrity.get("material_claim_support_verified", False):
            failures.append(f"{case_id}:material_support_not_verified")
        if not integrity.get("citation_locator_valid", False):
            failures.append(f"{case_id}:citation_locator_invalid")
        if not _zero_mutations(row.get("mutations", {})):
            failures.append(f"{case_id}:protected_mutation")
        closure = (
            row.get("semantic_closure", {})
            if isinstance(row.get("semantic_closure"), dict)
            else {}
        )
        if closure.get("failures"):
            failures.append(f"{case_id}:semantic_closure_failures")
        if closure.get("broad_deterministic_fallback_used") is not False:
            failures.append(f"{case_id}:deterministic_fallback")
        for telemetry in _provider_telemetry(row):
            if not isinstance(telemetry, dict):
                failures.append(f"{case_id}:invalid_provider_telemetry")
                continue
            if str(telemetry.get("stop_reason", "")).casefold() in {
                "max_tokens",
                "length",
            }:
                failures.append(f"{case_id}:provider_max_tokens")
            parse = telemetry.get("parse_telemetry", {})
            if not isinstance(parse, dict) or not parse.get("parse_ok", False):
                failures.append(f"{case_id}:provider_parse_failure")
        for semantic_failure in _validate_visible_semantics(row):
            failures.append(f"{case_id}:{semantic_failure}")
        if case_id in {"R3-Q05", "R3-Q09"}:
            endpoint = (
                closure.get("endpoint_proof", {})
                if isinstance(closure, dict)
                else {}
            )
            if not endpoint.get("matched"):
                failures.append(f"{case_id}:endpoint_not_matched")
            if endpoint.get("edge_id") != EXPECTED_GRAPH_EDGE:
                failures.append(f"{case_id}:wrong_graph_edge")
            if endpoint.get("relation_type") != "precedes":
                failures.append(f"{case_id}:wrong_graph_relation")
        if case_id == "R3-Q09":
            answer = re.sub(
                r"^\s+",
                "",
                str(row.get("answer_text", "")),
            ).casefold()
            if not re.match(r"^(?:no\b|it does not\b|that does not\b)", answer):
                failures.append("R3-Q09:no_clear_initial_no")

    privacy = artifact.get("privacy", {})
    if privacy.get("raw_backend_token_recorded") is not False:
        failures.append("privacy_token_recorded")
    if privacy.get("raw_owner_hash_recorded") is not False:
        failures.append("privacy_owner_hash_recorded")
    if privacy.get("provider_secret_recorded") is not False:
        failures.append("privacy_provider_secret_recorded")
    if failures:
        print(
            json.dumps(
                {"status": "FAIL", "failures": sorted(set(failures))},
                indent=2,
            )
        )
        raise SystemExit(1)
    print(
        json.dumps(
            {"status": "PASS", "rows": 12, "deploy_sha": expected_sha},
            indent=2,
        )
    )


def validate_junit(*, junit_path: Path, minimum: int) -> None:
    root = ET.parse(junit_path).getroot()
    if root.tag == "testsuites":
        count = sum(
            int(item.attrib.get("tests", 0))
            for item in root.findall("testsuite")
        )
        failures = sum(
            int(item.attrib.get("failures", 0))
            + int(item.attrib.get("errors", 0))
            for item in root.findall("testsuite")
        )
    else:
        count = int(root.attrib.get("tests", 0))
        failures = int(root.attrib.get("failures", 0)) + int(
            root.attrib.get("errors", 0)
        )
    if count < minimum or failures:
        raise SystemExit(
            "regression gate failed "
            f"tests={count} failures={failures} minimum={minimum}"
        )
    print(json.dumps({"status": "PASS", "tests": count, "minimum": minimum}))


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    collect_parser = sub.add_parser("collect")
    collect_parser.add_argument("--questions", type=Path, required=True)
    collect_parser.add_argument("--output", type=Path, required=True)
    collect_parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8080",
    )
    collect_parser.add_argument("--expected-sha", required=True)
    validate_parser = sub.add_parser("validate")
    validate_parser.add_argument("--input", type=Path, required=True)
    validate_parser.add_argument("--gate", type=Path, required=True)
    validate_parser.add_argument("--expected-sha", required=True)
    junit_parser = sub.add_parser("validate-junit")
    junit_parser.add_argument("--junit", type=Path, required=True)
    junit_parser.add_argument("--minimum", type=int, default=82)
    args = parser.parse_args()
    if args.command == "collect":
        collect(
            questions_path=args.questions,
            output=args.output,
            base_url=args.base_url,
            expected_sha=args.expected_sha,
        )
    elif args.command == "validate":
        validate(
            input_path=args.input,
            gate_path=args.gate,
            expected_sha=args.expected_sha,
        )
    else:
        validate_junit(junit_path=args.junit, minimum=args.minimum)


if __name__ == "__main__":
    main()
