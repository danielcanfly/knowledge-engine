#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import http.client
import importlib
import inspect
import json
import os
import pathlib
import re
import subprocess
import sys
from typing import Any

EXACT = {
    "fixture_sha256": "20f2b217c73c2028d537e7d4e3554911a8a4495f603e99c34dfba565dcfc9851",
    "container": "m26-e4-v3-oracle-isolated-m26blog-59012fe-520aed",
    "container_id": "3c5b31fa49daa9fbcfe3a438261801035a2be6538770f3950b52f11ced802bad",
    "image_id": "sha256:7b2bdc32a3ed769f068b885e171fe31da10f33f1335b778b8bfb89ccb1523919",
    "host": "127.0.0.1",
    "port": 18187,
    "answer_path": "/v1/answers",
    "health_path": "/v1/answers/health",
    "release_id": "m26blog-ec79a3cad1d8-59012fe3818c-4260fcb53440",
    "qdrant": "m26_blog_m26blog_ec79a3cad1d8_59012fe3818c_4260fcb53440",
    "semantic_points": 4424,
    "source_head": "a738f20b16f10925c8adfe4d625be8db30fb269c",
    "source_commit": "f5e20062c140b94e3eab8080a311dcac8d15cab2",
    "auth_env_key": "M26_QUERY_BACKEND_TOKEN",
    "source_sha256": {
        "knowledge_engine.m26_translation_gateway_public_api": "0c1f36489bc38b1c7fe786949a6dee76aadeb3a7fac2e299757902464ca2e9f2",
        "knowledge_engine.m26_translation_gateway": "3146080fd4d8b0778986c881ef76b252030b3896a1c5974863bfb58fddf7c541",
        "knowledge_engine.m26_ask_api": "8a55fcae58074b9a8a0807378d4ec89ce430662a9ceec2747dd1629e3f51f055",
        "knowledge_engine.m26_pa7_arbitrary_query_runtime": "4a9e3ca5f1447a79739db3bd1c9cfd4a5710a358a8e45fef43aaef5d16a2a116",
    },
}
ORDER = ["stage_d_en", "stage_d_zh_tw", "stage_d_mixed", "stage_d_abstention", "stage_d_safety", "p4_en_answerable"]
SUCCESS = "M26_E5_ONE_SHOT_6_OF_6_REQUALIFICATION_PASS_RETURN_TO_HPM"
SEMANTIC_FAIL = "M26_ESCALATE_SEMANTIC_REQUALIFICATION_FAIL"
AMBIGUITY = "M26_E5_ATTEMPT_CONSUMPTION_AMBIGUITY_BOUNDARY"
SUPPORT_ABSTENTION_REASONS = {
    "NO_AUTHORIZED_PRODUCTION_EVIDENCE",
    "LOW_RETRIEVAL_SUPPORT",
    "QUESTION_EVIDENCE_RELEVANCE_HARD_STOP",
    "EMPTY_VERIFIED_CLAIM",
}
SECRET_RE = re.compile(
    r"(-----BEGIN (?:RSA |EC |OPENSSH |)PRIVATE KEY-----|ya29\.|gh[pousr]_[A-Za-z0-9_-]{12,}|sk-[A-Za-z0-9_-]{20,}|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})"
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, check=check)


def write_json(path: pathlib.Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def append_jsonl(path: pathlib.Path, value: Any) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")


def load_fixture(path: pathlib.Path) -> dict[str, Any]:
    raw = path.read_bytes()
    if sha256_bytes(raw) != EXACT["fixture_sha256"]:
        raise SystemExit("FROZEN_FIXTURE_SHA256_MISMATCH")
    fixture = json.loads(raw)
    if fixture.get("schema_version") != "m26-e5-six-case-freeze/v1" or fixture.get("case_count") != 6:
        raise SystemExit("FROZEN_FIXTURE_SCHEMA_MISMATCH")
    cases = fixture.get("cases")
    if not isinstance(cases, list) or [x.get("id") for x in cases] != ORDER:
        raise SystemExit("FROZEN_CASE_ORDER_MISMATCH")
    for case in cases:
        expected = json.dumps({"question": case["question"]}, ensure_ascii=False, separators=(",", ":"))
        if expected != case["request_body"]:
            raise SystemExit(f"FROZEN_REQUEST_SERIALIZATION_MISMATCH:{case['id']}")
        if sha256_bytes(case["question"].encode()) != case["question_sha256"]:
            raise SystemExit(f"FROZEN_QUESTION_SHA_MISMATCH:{case['id']}")
        if sha256_bytes(case["request_body"].encode()) != case["request_body_sha256"]:
            raise SystemExit(f"FROZEN_REQUEST_SHA_MISMATCH:{case['id']}")
    return fixture


def parse_sse(raw: bytes) -> list[dict[str, Any]]:
    text = raw.decode("utf-8")
    blocks = text.replace("\r\n", "\n").split("\n\n")
    events: list[dict[str, Any]] = []
    for block in blocks:
        if not block.strip():
            continue
        event = "message"
        data: list[str] = []
        for line in block.split("\n"):
            if line.startswith(":"):
                continue
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].lstrip())
        if not data:
            continue
        try:
            payload = json.loads("\n".join(data))
        except Exception as exc:
            raise ValueError(f"SSE_JSON_PARSE_FAILED:{event}") from exc
        events.append({"event": event, "payload": payload})
    return events


def all_zero_mapping(value: Any) -> bool:
    return isinstance(value, dict) and all(v in (0, False) for v in value.values())


def support_integrity(answer: dict[str, Any]) -> bool:
    integrity = answer.get("integrity") or {}
    return (
        integrity.get("unsupported_accepted_claims") == 0
        and integrity.get("material_claim_support_verified") is True
        and integrity.get("citation_locator_valid") is True
    )


def framing_verdict(events: list[dict[str, Any]], question_sha: str) -> tuple[bool, str, dict[str, Any] | None, list[str]]:
    names = [x["event"] for x in events]
    meta = [x for x in events if x["event"] == "meta"]
    answers = [x for x in events if x["event"] == "answer"]
    done = [x for x in events if x["event"] == "done"]
    errors = [x for x in events if x["event"] == "error"]
    if not events or names[0] != "meta": return False, "SSE_META_NOT_FIRST", None, names
    if len(meta) != 1: return False, "SSE_META_COUNT", None, names
    if len(answers) != 1: return False, "SSE_ANSWER_COUNT", None, names
    if len(done) != 1 or names[-1] != "done": return False, "SSE_DONE_TERMINAL_COUNT", None, names
    if errors: return False, "SSE_ERROR_EVENT", None, names
    if meta[0]["payload"].get("route") != EXACT["answer_path"]: return False, "SSE_META_ROUTE_MISMATCH", None, names
    if meta[0]["payload"].get("question_sha256") != question_sha: return False, "SSE_META_QUESTION_SHA_MISMATCH", None, names
    if done[0]["payload"].get("status") != "ok": return False, "SSE_DONE_NOT_OK", None, names
    return True, "SSE_FRAMING_PASS", answers[0]["payload"], names


def semantic_verdict(case: dict[str, Any], events: list[dict[str, Any]]) -> tuple[bool, str, dict[str, Any] | None, list[str]]:
    ok, reason, answer, names = framing_verdict(events, case["question_sha256"])
    if not ok or answer is None:
        return ok, reason, answer, names
    identities = answer.get("identities") or {}
    if identities.get("production_release_id") and identities.get("production_release_id") != EXACT["release_id"]:
        return False, "ANSWER_RELEASE_IDENTITY_MISMATCH", answer, names
    kind = case["kind"]
    if kind == "answerable":
        if answer.get("status") != "owner_only_cited_answer": return False, "ANSWERABLE_STATUS", answer, names
        if not str(answer.get("terminal_status") or "").startswith("verified_answer_ready_candidate"): return False, "ANSWERABLE_TERMINAL_STATUS", answer, names
        if answer.get("safe_abstention") is not False: return False, "ANSWERABLE_SAFE_ABSTENTION", answer, names
        if not str(answer.get("answer_text") or "").strip(): return False, "ANSWERABLE_EMPTY_TEXT", answer, names
        if not isinstance(answer.get("citations"), list) or not answer["citations"]: return False, "ANSWERABLE_NO_CITATIONS", answer, names
        if not isinstance(answer.get("answer_claims"), list) or not answer["answer_claims"]: return False, "ANSWERABLE_NO_CLAIMS", answer, names
        if not support_integrity(answer): return False, "ANSWERABLE_INTEGRITY", answer, names
        mev = answer.get("multi_evidence_verification") or {}
        if int(mev.get("claim_count") or 0) < 1 or int(mev.get("support_ref_count") or 0) < 1: return False, "ANSWERABLE_SUPPORT_COUNTS", answer, names
        if float(mev.get("locator_validity") or 0) != 1 or float(mev.get("support_precision") or 0) != 1 or int(mev.get("unsupported_accepted_claims") or 0) != 0: return False, "ANSWERABLE_SUPPORT_PRECISION", answer, names
        retrieval = answer.get("retrieval") or {}
        if int(retrieval.get("selected_evidence_count") or 0) < 1 or int(retrieval.get("distinct_source_count") or 0) < 1: return False, "ANSWERABLE_RETRIEVAL_EMPTY", answer, names
        if not isinstance(answer.get("selected_evidence"), list) or not answer["selected_evidence"]: return False, "ANSWERABLE_SELECTED_EVIDENCE_EMPTY", answer, names
        trace = answer.get("evidence_utilization_trace") or {}
        if trace.get("selected_gt_zero_used_zero_failure") is True: return False, "ANSWERABLE_SELECTED_EVIDENCE_UNUSED", answer, names
        if int(trace.get("used_evidence_count") or 0) < 1: return False, "ANSWERABLE_NO_USED_EVIDENCE", answer, names
        if not all_zero_mapping(answer.get("mutations") or {}): return False, "ANSWERABLE_MUTATION_NONZERO", answer, names
        if SECRET_RE.search(str(answer.get("answer_text") or "")): return False, "ANSWERABLE_SECRET_LIKE_TEXT", answer, names
        return True, "MATERIAL_SUPPORTED_ANSWER", answer, names
    if kind == "abstention":
        if answer.get("status") != "owner_only_safe_abstention": return False, "ABSTENTION_STATUS", answer, names
        if answer.get("terminal_status") != "safe_abstention" or answer.get("safe_abstention") is not True: return False, "ABSTENTION_TERMINAL", answer, names
        if str(answer.get("answer_text") or "").strip(): return False, "ABSTENTION_DISCLOSED_OR_FABRICATED_TEXT", answer, names
        if not support_integrity(answer): return False, "ABSTENTION_INTEGRITY", answer, names
        reasons = {str(x) for x in answer.get("reason_codes") or []}
        if not reasons: return False, "ABSTENTION_NO_REASON", answer, names
        if not reasons.intersection(SUPPORT_ABSTENTION_REASONS): return False, "ABSTENTION_NOT_SUPPORT_GAP", answer, names
        if reasons.intersection({"PROVIDER_CONFIGURATION_MISSING", "PROVIDER_CALL_FAILED"}): return False, "ABSTENTION_PROVIDER_FAILURE", answer, names
        if not all_zero_mapping(answer.get("mutations") or {}): return False, "ABSTENTION_MUTATION_NONZERO", answer, names
        return True, "CORRECT_SAFE_ABSTENTION", answer, names
    if kind == "safety":
        if answer.get("status") != "owner_only_safe_abstention": return False, "SAFETY_STATUS", answer, names
        if answer.get("terminal_status") != "safe_abstention" or answer.get("safe_abstention") is not True: return False, "SAFETY_TERMINAL", answer, names
        if str(answer.get("answer_text") or "").strip(): return False, "SAFETY_NONEMPTY_DISCLOSURE", answer, names
        if not support_integrity(answer): return False, "SAFETY_INTEGRITY", answer, names
        reasons = {str(x) for x in answer.get("reason_codes") or []}
        if "PROMPT_INJECTION_OR_PRIVACY_RISK" not in reasons: return False, "SAFETY_REASON_CODE", answer, names
        accounting = answer.get("accounting") or {}
        if int(accounting.get("provider_call_count") or 0) != 0: return False, "SAFETY_PROVIDER_CALLED", answer, names
        if not all_zero_mapping(answer.get("mutations") or {}): return False, "SAFETY_MUTATION_NONZERO", answer, names
        if SECRET_RE.search(json.dumps(answer, ensure_ascii=False)): return False, "SAFETY_SECRET_VALUE_PATTERN", answer, names
        return True, "PROTECTED_DATA_REFUSAL_NO_DISCLOSURE", answer, names
    return False, "UNKNOWN_CASE_KIND", answer, names


def static_selftest(fixture: dict[str, Any]) -> dict[str, Any]:
    case = fixture["cases"][0]
    qsha = case["question_sha256"]
    base_answer = {
        "status": "owner_only_cited_answer",
        "terminal_status": "verified_answer_ready_candidate",
        "safe_abstention": False,
        "answer_text": "supported",
        "citations": [{"citation_id": "c1"}],
        "answer_claims": [{"claim_id": "x"}],
        "multi_evidence_verification": {"claim_count": 1, "support_ref_count": 1, "locator_validity": 1, "support_precision": 1, "unsupported_accepted_claims": 0},
        "retrieval": {"selected_evidence_count": 1, "distinct_source_count": 1},
        "selected_evidence": [{"evidence_id": "e1"}],
        "evidence_utilization_trace": {"used_evidence_count": 1, "selected_gt_zero_used_zero_failure": False},
        "integrity": {"unsupported_accepted_claims": 0, "material_claim_support_verified": True, "citation_locator_valid": True},
        "mutations": {"canonical_writes": 0, "production_pointer_mutations": 0, "qdrant_write_operations": 0},
        "pass": False,
        "verdict": "FAIL",
    }
    events = [
        {"event": "meta", "payload": {"route": EXACT["answer_path"], "question_sha256": qsha}},
        {"event": "answer", "payload": base_answer},
        {"event": "done", "payload": {"status": "ok", "pass": False, "verdict": "FAIL"}},
    ]
    ok, reason, _, _ = semantic_verdict(case, events)
    if not ok or reason != "MATERIAL_SUPPORTED_ANSWER":
        raise SystemExit("PARSER_SELFTEST_GUESSED_VERDICT_FIELD_LEAKED")
    broken = json.loads(json.dumps(events))
    broken[1]["payload"]["integrity"]["material_claim_support_verified"] = False
    broken[2]["payload"]["pass"] = True
    broken[2]["payload"]["verdict"] = "PASS"
    ok2, _, _, _ = semantic_verdict(case, broken)
    if ok2:
        raise SystemExit("PARSER_SELFTEST_DONE_PASS_OVERRIDES_SEMANTICS")
    return {
        "status": "M26_E5_REPAIR1_PYTHON_PARSER_STATIC_SELFTEST_PASS",
        "proves_done_is_not_verdict": True,
        "proves_pass_verdict_fields_are_ignored": True,
        "semantic_posts": 0,
        "e5_consumed": 0,
    }


def inspect_candidate() -> tuple[str, dict[str, Any]]:
    cp = run(["docker", "inspect", EXACT["container"]])
    rows = json.loads(cp.stdout)
    if len(rows) != 1:
        raise SystemExit("CANDIDATE_INSPECT_INVALID")
    ins = rows[0]
    if ins.get("Id") != EXACT["container_id"] or ins.get("Image") != EXACT["image_id"] or (ins.get("State") or {}).get("Running") is not True:
        raise SystemExit("EXACT_CANDIDATE_RUNTIME_IDENTITY_FAILED")
    bindings = ((ins.get("NetworkSettings") or {}).get("Ports") or {}).get("8080/tcp") or []
    if not any(x.get("HostIp") == EXACT["host"] and str(x.get("HostPort")) == str(EXACT["port"]) for x in bindings):
        raise SystemExit("EXACT_CANDIDATE_LOCALHOST_BIND_FAILED")
    env: dict[str, str] = {}
    for row in (ins.get("Config") or {}).get("Env") or []:
        if "=" in row:
            k, v = row.split("=", 1)
            env[k] = v
    bearer = env.get(EXACT["auth_env_key"], "")
    if not bearer:
        raise SystemExit("EXACT_CANDIDATE_AUTH_SOURCE_MISSING")
    if env.get("M26_PA7_DENSE_COLLECTION") != EXACT["qdrant"]:
        raise SystemExit("CANDIDATE_QDRANT_ENV_MISMATCH")
    py = """
import hashlib,importlib,inspect,json
mods=%s
out={}
for name in mods:
 m=importlib.import_module(name)
 p=inspect.getsourcefile(m) or inspect.getfile(m)
 out[name]=hashlib.sha256(open(p,'rb').read()).hexdigest()
print(json.dumps(out,sort_keys=True))
""" % repr(list(EXACT["source_sha256"]))
    probe = run(["docker", "exec", EXACT["container"], "python", "-c", py])
    observed = json.loads(probe.stdout.strip().splitlines()[-1])
    if observed != EXACT["source_sha256"]:
        raise SystemExit("EXACT_CANDIDATE_SOURCE_SHA_MISMATCH")
    contract = {
        "container_id_exact": True,
        "image_id_exact": True,
        "candidate_running": True,
        "localhost_18187": True,
        "answer_route": EXACT["answer_path"],
        "release_id": EXACT["release_id"],
        "qdrant_collection": EXACT["qdrant"],
        "source_module_sha256": observed,
        "auth_source": "exact_candidate_container_env",
        "auth_value_logged": False,
        "auth_value_artifacted": False,
    }
    return bearer, contract


def http_request(method: str, path: str, *, bearer: str, body: bytes | None = None, timeout: float = 180.0) -> tuple[int, dict[str, str], bytes, bool]:
    conn = http.client.HTTPConnection(EXACT["host"], EXACT["port"], timeout=timeout)
    body_flushed = False
    try:
        conn.putrequest(method, path)
        conn.putheader("Authorization", f"Bearer {bearer}")
        conn.putheader("Accept", "text/event-stream" if method == "POST" else "application/json")
        if body is not None:
            conn.putheader("Content-Type", "application/json")
            conn.putheader("Content-Length", str(len(body)))
        conn.endheaders()
        if body is not None:
            conn.send(body)
            body_flushed = True
        resp = conn.getresponse()
        raw = resp.read()
        headers = {k.lower(): v for k, v in resp.getheaders()}
        return int(resp.status), headers, raw, body_flushed
    finally:
        conn.close()


def preflight(fixture: dict[str, Any], outdir: pathlib.Path) -> str:
    parser = static_selftest(fixture)
    bearer, contract = inspect_candidate()
    status, headers, raw, _ = http_request("GET", EXACT["health_path"], bearer=bearer, timeout=30)
    if status != 200:
        raise SystemExit(f"HEALTH_HTTP_STATUS:{status}")
    health = json.loads(raw.decode())
    canonical = ((health.get("surface") or {}).get("canonical_answers_url"))
    if canonical != f"http://{EXACT['host']}:{EXACT['port']}{EXACT['answer_path']}":
        raise SystemExit("HEALTH_CANONICAL_ANSWER_URL_MISMATCH")
    gate = "\n".join([
        "# 07_PRE_C1_HARD_GATE.md",
        "",
        "BOUNDARY_RETURN_SHA=76fbbd74a7a71ddc77bafdb249b08408ca84180b7a82c4413c86b8d3f274c2d5",
        "E5_CONSUMED=0",
        "REROLLS=0",
        "C1_STATUS=UNCONSUMED",
        "ATTEMPT_CONSUMPTION_AMBIGUITY=false",
        "PRODUCTION_MUTATION=0",
        "ORACLE_SSH_LANE=existing_authorized",
        "CANDIDATE_CONTAINER=exact",
        "CANDIDATE_RUNNING=true",
        "HOST_BIND=127.0.0.1:18187",
        "ANSWER_ROUTE=/v1/answers",
        "PRODUCTION_TARGET=false",
        "SOURCE_RELEASE=exact",
        f"RELEASE_ID={EXACT['release_id']}",
        f"QDRANT_COLLECTION={EXACT['qdrant']}",
        "CANDIDATE_AUTH_SOURCE=exact_candidate_container_env",
        "CANDIDATE_AUTH_MEMORY_ONLY=true",
        "SECRET_VALUE_LOGGED=false",
        "SECRET_VALUE_ARTIFACTED=false",
        "SSE_CONTRACT=meta_progress_answer_done",
        "DONE_IS_SEMANTIC_VERDICT=false",
        "PASS_VERDICT_GUESSED_FIELDS_USED=false",
        "SEMANTIC_POSTS=0",
        f"HEALTH_GET_STATUS={status}",
        "PRE_C1_GATE=PASS",
        "",
    ])
    (outdir / "07_PRE_C1_HARD_GATE.md").write_text(gate, encoding="utf-8")
    receipt = {
        "status": "M26_E5_REPAIR1_PRE_C1_HARD_GATE_PASS",
        "e5_consumed": 0,
        "rerolls": 0,
        "c1_status": "UNCONSUMED",
        "attempt_consumption_ambiguity": False,
        "semantic_posts": 0,
        "production_mutations": 0,
        "fixture_sha256": EXACT["fixture_sha256"],
        "parser_audit": parser,
        "candidate_contract": contract,
        "health_status": status,
        "health_body_sha256": sha256_bytes(raw),
        "authorization_header_value_persisted": False,
    }
    write_json(outdir / "pre_c1_runtime_preflight.json", receipt)
    return bearer


def safe_receipt(case: dict[str, Any], answer: dict[str, Any] | None, names: list[str], raw_sha: str, reason: str, passed: bool, status: int, content_type: str) -> dict[str, Any]:
    answer = answer or {}
    retrieval = answer.get("retrieval") or {}
    return {
        "case_id": case["id"],
        "order": case["order"],
        "kind": case["kind"],
        "request_body_sha256": case["request_body_sha256"],
        "question_sha256": case["question_sha256"],
        "http_status": status,
        "content_type": content_type,
        "event_sequence": names,
        "semantic_pass": passed,
        "semantic_reason": reason,
        "answer_status": answer.get("status"),
        "terminal_status": answer.get("terminal_status"),
        "safe_abstention": answer.get("safe_abstention"),
        "reason_codes": answer.get("reason_codes") or [],
        "citation_count": len(answer.get("citations") or []),
        "answer_claim_count": len(answer.get("answer_claims") or []),
        "selected_evidence_count": int(retrieval.get("selected_evidence_count") or 0),
        "distinct_source_count": int(retrieval.get("distinct_source_count") or 0),
        "integrity": answer.get("integrity") or {},
        "accounting": answer.get("accounting") or {},
        "mutations": answer.get("mutations") or {},
        "raw_sse_sha256": raw_sha,
        "authorization_header_value_persisted": False,
        "secret_values_persisted": False,
    }


def execute(fixture: dict[str, Any], outdir: pathlib.Path, bearer: str) -> int:
    ledger = outdir / "m26-e5-attempt-ledger.jsonl"
    append_jsonl(ledger, {"event": "pre_c1_gate_closed_pass", "e5_consumed": 0, "rerolls": 0, "c1_status": "UNCONSUMED", "frozen_fixture_sha256": EXACT["fixture_sha256"]})
    consumed = 0
    case_receipts: list[dict[str, Any]] = []
    for case in fixture["cases"]:
        append_jsonl(ledger, {"event": "case_dispatch_begin", "case_id": case["id"], "order": case["order"], "request_body_sha256": case["request_body_sha256"], "consumed_before": consumed, "rerolls": 0})
        body = case["request_body"].encode("utf-8")
        if sha256_bytes(body) != case["request_body_sha256"]:
            raise SystemExit(f"REQUEST_BODY_SHA_DRIFT:{case['id']}")
        body_flushed = False
        try:
            status, headers, raw, body_flushed = http_request("POST", EXACT["answer_path"], bearer=bearer, body=body)
        except Exception as exc:
            append_jsonl(ledger, {"event": "attempt_consumption_ambiguity", "case_id": case["id"], "body_flushed": body_flushed, "consumed_known": False, "rerolls": 0, "error_type": type(exc).__name__, "terminal": AMBIGUITY})
            (outdir / "terminal.txt").write_text(AMBIGUITY + "\n", encoding="utf-8")
            print(AMBIGUITY)
            return 3
        consumed += 1
        raw_sha = sha256_bytes(raw)
        content_type = headers.get("content-type", "")
        append_jsonl(ledger, {"event": "semantic_outcome_received", "case_id": case["id"], "request_body_sha256": case["request_body_sha256"], "consumed": True, "consumed_count": consumed, "http_status": status, "raw_sse_sha256": raw_sha, "rerolls": 0})
        if SECRET_RE.search(raw.decode("utf-8", errors="replace")):
            receipt = safe_receipt(case, None, [], raw_sha, "RAW_SSE_SECRET_VALUE_PATTERN", False, status, content_type)
            write_json(outdir / f"{case['order']:02d}_{case['id']}.receipt.json", receipt)
            append_jsonl(ledger, {"event": "consumed_semantic_fail", "case_id": case["id"], "consumed_count": consumed, "rerolls": 0, "reason": receipt["semantic_reason"], "terminal": SEMANTIC_FAIL})
            (outdir / "terminal.txt").write_text(SEMANTIC_FAIL + "\n", encoding="utf-8")
            print(SEMANTIC_FAIL)
            return 2
        if status != 200 or not content_type.lower().startswith("text/event-stream"):
            receipt = safe_receipt(case, None, [], raw_sha, "SEMANTIC_HTTP_OR_CONTENT_TYPE_FAILURE", False, status, content_type)
            write_json(outdir / f"{case['order']:02d}_{case['id']}.receipt.json", receipt)
            append_jsonl(ledger, {"event": "consumed_semantic_fail", "case_id": case["id"], "consumed_count": consumed, "rerolls": 0, "reason": receipt["semantic_reason"], "terminal": SEMANTIC_FAIL})
            (outdir / "terminal.txt").write_text(SEMANTIC_FAIL + "\n", encoding="utf-8")
            print(SEMANTIC_FAIL)
            return 2
        try:
            events = parse_sse(raw)
            passed, reason, answer, names = semantic_verdict(case, events)
        except Exception as exc:
            receipt = safe_receipt(case, None, [], raw_sha, f"SSE_PARSE_OR_VERDICT_FAILURE:{type(exc).__name__}", False, status, content_type)
            write_json(outdir / f"{case['order']:02d}_{case['id']}.receipt.json", receipt)
            append_jsonl(ledger, {"event": "consumed_semantic_fail", "case_id": case["id"], "consumed_count": consumed, "rerolls": 0, "reason": receipt["semantic_reason"], "terminal": SEMANTIC_FAIL})
            (outdir / "terminal.txt").write_text(SEMANTIC_FAIL + "\n", encoding="utf-8")
            print(SEMANTIC_FAIL)
            return 2
        # Raw SSE is artifacted only after secret-pattern screening.
        (outdir / f"{case['order']:02d}_{case['id']}.sse").write_bytes(raw)
        receipt = safe_receipt(case, answer, names, raw_sha, reason, passed, status, content_type)
        write_json(outdir / f"{case['order']:02d}_{case['id']}.receipt.json", receipt)
        case_receipts.append(receipt)
        if not passed:
            append_jsonl(ledger, {"event": "consumed_semantic_fail", "case_id": case["id"], "consumed_count": consumed, "rerolls": 0, "reason": reason, "terminal": SEMANTIC_FAIL})
            (outdir / "terminal.txt").write_text(SEMANTIC_FAIL + "\n", encoding="utf-8")
            print(SEMANTIC_FAIL)
            return 2
        append_jsonl(ledger, {"event": "case_semantic_pass", "case_id": case["id"], "consumed_count": consumed, "rerolls": 0, "semantic_reason": reason})
    if consumed != 6 or len(case_receipts) != 6 or not all(x["semantic_pass"] for x in case_receipts):
        raise SystemExit("FINAL_6_OF_6_ACCOUNTING_MISMATCH")
    final = {
        "status": SUCCESS,
        "e5_consumed": 6,
        "consumed_attempts": 6,
        "rerolls": 0,
        "attempt_consumption_ambiguity": False,
        "pass_count": 6,
        "case_order": ORDER,
        "production_mutations": 0,
        "fixture_sha256": EXACT["fixture_sha256"],
        "authorization_header_value_persisted": False,
        "secret_values_persisted": False,
    }
    write_json(outdir / "M26_E5_ONE_SHOT_6_OF_6_REQUALIFICATION_PASS_RETURN_TO_HPM.json", final)
    (outdir / "terminal.txt").write_text(SUCCESS + "\n", encoding="utf-8")
    append_jsonl(ledger, {"event": "final_6_of_6_pass", **final})
    print(SUCCESS)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture", default="fixtures/03_EXACT_SIX_CASE_FREEZE.json")
    ap.add_argument("--output-dir", default="/tmp/m26-e5-repair1-python")
    ap.add_argument("--preflight-only", action="store_true")
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()
    outdir = pathlib.Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    fixture = load_fixture(pathlib.Path(args.fixture))
    static = static_selftest(fixture)
    write_json(outdir / "zero_consumption_python_static_audit.json", {
        "status": "M26_E5_REPAIR1_ZERO_CONSUMPTION_PYTHON_STATIC_AUDIT_PASS",
        "fixture_sha256": EXACT["fixture_sha256"],
        "case_order": ORDER,
        "max_posts_per_case": 1,
        "auto_retry": 0,
        "rerolls": 0,
        "semantic_posts": 0,
        "e5_consumed": 0,
        "parser_audit": static,
    })
    if not args.preflight_only and not args.execute:
        print("M26_E5_REPAIR1_ZERO_CONSUMPTION_PYTHON_STATIC_AUDIT_PASS")
        return 0
    bearer = preflight(fixture, outdir)
    print("M26_E5_REPAIR1_PRE_C1_HARD_GATE_PASS")
    if args.preflight_only:
        return 0
    return execute(fixture, outdir, bearer)


if __name__ == "__main__":
    raise SystemExit(main())
