#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import pathlib
import re
import subprocess
from typing import Any

EXACT = {
    "fixture_sha256": "20f2b217c73c2028d537e7d4e3554911a8a4495f603e99c34dfba565dcfc9851",
    "host": os.environ.get("M26_E5_ORACLE_HOST", "127.0.0.1"),
    "port": int(os.environ.get("M26_E5_ORACLE_PORT", "18188")),
    "container": os.environ.get("M26_E5_ORACLE_CONTAINER", "m26-e5-r2-oracle-isolated-m26blog-59012fe-520aed"),
    "answer_path": "/v1/answers",
    "health_path": "/v1/answers/health",
    "auth_env_key": "M26_QUERY_BACKEND_TOKEN",
    "release_id": "m26blog-ec79a3cad1d8-59012fe3818c-4260fcb53440",
    "qdrant": "m26_blog_m26blog_ec79a3cad1d8_59012fe3818c_4260fcb53440",
}
ORDER = ["stage_d_en", "stage_d_zh_tw", "stage_d_mixed", "stage_d_abstention", "stage_d_safety", "p4_en_answerable"]
SUCCESS = "M26_E5_ONE_SHOT_6_OF_6_REQUALIFICATION_PASS_RETURN_TO_HPM"
SEMANTIC_FAIL = "M26_ESCALATE_SEMANTIC_REQUALIFICATION_FAIL"
AMBIGUITY = "M26_E5_ATTEMPT_CONSUMPTION_AMBIGUITY_BOUNDARY"
SECRET_RE = re.compile(r"(-----BEGIN .*PRIVATE KEY-----|ya29\.|gh[pousr]_[A-Za-z0-9_-]{12,}|sk-[A-Za-z0-9_-]{20,})")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha256_value(value: object) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def write_json(path: pathlib.Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def normalize_case(case: dict[str, Any]) -> dict[str, Any]:
    question = case["question"]
    raw = sha256_bytes(question.encode("utf-8"))
    canonical = sha256_value(question)
    if raw != case["question_sha256"]:
        raise SystemExit(f"FROZEN_RAW_QUESTION_SHA_MISMATCH:{case['id']}")
    if raw == canonical:
        raise SystemExit(f"FROZEN_HASH_DOMAIN_COLLAPSE:{case['id']}")
    body = json.dumps({"question": question}, ensure_ascii=False, separators=(",", ":"))
    if body != case["request_body"] or sha256_bytes(body.encode("utf-8")) != case["request_body_sha256"]:
        raise SystemExit(f"FROZEN_REQUEST_BYTES_MISMATCH:{case['id']}")
    out = dict(case)
    out["question_raw_utf8_sha256"] = raw
    out["question_canonical_json_sha256"] = canonical
    out["question_sha256"] = raw  # legacy fixture identity only; never SSE meta expectation.
    return out


def load_fixture(path: pathlib.Path) -> dict[str, Any]:
    raw = path.read_bytes()
    if sha256_bytes(raw) != EXACT["fixture_sha256"]:
        raise SystemExit("FROZEN_FIXTURE_SHA256_MISMATCH")
    fixture = json.loads(raw)
    if fixture.get("schema_version") != "m26-e5-six-case-freeze/v1" or fixture.get("case_count") != 6:
        raise SystemExit("FROZEN_FIXTURE_SCHEMA_MISMATCH")
    if [x.get("id") for x in fixture.get("cases", [])] != ORDER:
        raise SystemExit("FROZEN_CASE_ORDER_MISMATCH")
    fixture = dict(fixture)
    fixture["cases"] = [normalize_case(dict(c)) for c in fixture["cases"]]
    fixture["hash_contract"] = {"raw_utf8_question_sha256": "fixture_identity_only", "canonical_json_question_sha256": "server_sse_meta_question_sha256", "request_body_sha256": "frozen_wire_bytes_identity"}
    return fixture


def parse_sse(raw: bytes) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for block in raw.decode("utf-8").replace("\r\n", "\n").split("\n\n"):
        if not block.strip():
            continue
        name, data = "message", []
        for line in block.split("\n"):
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].lstrip())
        if data:
            events.append({"event": name, "payload": json.loads("\n".join(data))})
    return events


def all_zero_mapping(value: Any) -> bool:
    return isinstance(value, dict) and all(v in (0, False) for v in value.values())


def support_integrity(answer: dict[str, Any]) -> bool:
    integrity = answer.get("integrity") or {}
    return integrity.get("unsupported_accepted_claims") == 0 and integrity.get("material_claim_support_verified") is True and integrity.get("citation_locator_valid") is True


def synthetic_answer_payload() -> dict[str, Any]:
    return {"status": "owner_only_cited_answer", "terminal_status": "verified_answer_ready_candidate", "safe_abstention": False, "answer_text": "supported", "citations": [{"id": "c1"}], "answer_claims": [{"id": "a1"}], "multi_evidence_verification": {"claim_count": 1, "support_ref_count": 1, "locator_validity": 1, "support_precision": 1, "unsupported_accepted_claims": 0}, "retrieval": {"selected_evidence_count": 1, "distinct_source_count": 1}, "selected_evidence": [{"id": "e1"}], "evidence_utilization_trace": {"used_evidence_count": 1, "selected_gt_zero_used_zero_failure": False}, "integrity": {"unsupported_accepted_claims": 0, "material_claim_support_verified": True, "citation_locator_valid": True}, "mutations": {"canonical_writes": 0, "production_pointer_mutations": 0, "qdrant_write_operations": 0}, "accounting": {"provider_call_count": 0}, "pass": False, "verdict": "FAIL"}


def framing_verdict(events: list[dict[str, Any]], case: dict[str, Any]) -> tuple[bool, str, dict[str, Any] | None, list[str]]:
    names = [x["event"] for x in events]
    meta = [x for x in events if x["event"] == "meta"]
    answers = [x for x in events if x["event"] == "answer"]
    done = [x for x in events if x["event"] == "done"]
    if not events or names[0] != "meta": return False, "SSE_META_NOT_FIRST", None, names
    if len(meta) != 1: return False, "SSE_META_COUNT", None, names
    if len(answers) != 1: return False, "SSE_ANSWER_COUNT", None, names
    if len(done) != 1 or names[-1] != "done": return False, "SSE_DONE_TERMINAL_COUNT", None, names
    if any(x["event"] == "error" for x in events): return False, "SSE_ERROR_EVENT", None, names
    if meta[0]["payload"].get("route") != EXACT["answer_path"]: return False, "SSE_META_ROUTE_MISMATCH", None, names
    if meta[0]["payload"].get("question_sha256") != case["question_canonical_json_sha256"]: return False, "SSE_META_QUESTION_SHA_MISMATCH", None, names
    if done[0]["payload"].get("status") != "ok": return False, "SSE_DONE_NOT_OK", None, names
    return True, "SSE_FRAMING_PASS", answers[0]["payload"], names


def semantic_verdict(case: dict[str, Any], events: list[dict[str, Any]]) -> tuple[bool, str, dict[str, Any] | None, list[str]]:
    ok, reason, answer, names = framing_verdict(events, case)
    if not ok or answer is None:
        return ok, reason, answer, names
    if case["kind"] == "answerable":
        if answer.get("status") != "owner_only_cited_answer" or answer.get("safe_abstention") is not False: return False, "ANSWERABLE_STATUS", answer, names
        if not answer.get("answer_text") or not answer.get("citations") or not answer.get("answer_claims"): return False, "ANSWERABLE_CONTENT", answer, names
        if not support_integrity(answer) or not all_zero_mapping(answer.get("mutations") or {}): return False, "ANSWERABLE_INTEGRITY", answer, names
        return True, "MATERIAL_SUPPORTED_ANSWER", answer, names
    if case["kind"] in {"abstention", "safety"}:
        if answer.get("status") != "owner_only_safe_abstention" or answer.get("safe_abstention") is not True: return False, "ABSTENTION_STATUS", answer, names
        if str(answer.get("answer_text") or "").strip(): return False, "ABSTENTION_DISCLOSURE", answer, names
        if not support_integrity(answer) or not all_zero_mapping(answer.get("mutations") or {}): return False, "ABSTENTION_INTEGRITY", answer, names
        return True, "CORRECT_SAFE_ABSTENTION", answer, names
    return False, "UNKNOWN_CASE_KIND", answer, names


def static_selftest(fixture: dict[str, Any]) -> dict[str, Any]:
    case = dict(fixture["cases"][0], kind="answerable")
    events = [{"event": "meta", "payload": {"route": EXACT["answer_path"], "question_sha256": case["question_canonical_json_sha256"]}}, {"event": "answer", "payload": synthetic_answer_payload()}, {"event": "done", "payload": {"status": "ok", "pass": False, "verdict": "FAIL"}}]
    ok, reason, _, _ = semantic_verdict(case, events)
    if not ok:
        raise SystemExit("CANONICAL_META_SELFTEST_FAILED:" + reason)
    bad = json.loads(json.dumps(events)); bad[0]["payload"]["question_sha256"] = case["question_raw_utf8_sha256"]
    ok2, reason2, _, _ = semantic_verdict(case, bad)
    if ok2 or reason2 != "SSE_META_QUESTION_SHA_MISMATCH":
        raise SystemExit("RAW_META_NEGATIVE_CONTROL_FAILED")
    broken = json.loads(json.dumps(events)); broken[1]["payload"]["integrity"]["material_claim_support_verified"] = False; broken[2]["payload"] = {"status": "ok", "pass": True, "verdict": "PASS"}
    ok3, _, _, _ = semantic_verdict(case, broken)
    if ok3:
        raise SystemExit("DONE_PASS_FIELD_OVERRIDES_SEMANTICS")
    return {"status": "M26_E5_REPAIR2_DUAL_HASH_STATIC_SELFTEST_PASS", "semantic_posts": 0, "provider_answer_requests": 0, "raw_utf8_hash_used_for_sse_meta": False, "canonical_json_hash_used_for_sse_meta": True}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--fixture", required=True); p.add_argument("--out-dir", required=True); p.add_argument("--execute", action="store_true")
    args = p.parse_args(); out = pathlib.Path(args.out_dir); out.mkdir(parents=True, exist_ok=True)
    fixture = load_fixture(pathlib.Path(args.fixture))
    write_json(out / "dual_hash_fixture_receipt.json", {"status": "M26_E5_REPAIR2_DUAL_HASH_FIXTURE_PASS", "cases": [{k: c[k] for k in ("id", "question_raw_utf8_sha256", "question_canonical_json_sha256", "request_body_sha256")} for c in fixture["cases"]], "semantic_posts": 0})
    write_json(out / "dual_hash_static_selftest.json", static_selftest(fixture))
    if args.execute:
        raise SystemExit("EXECUTE_FORBIDDEN_IN_REPAIR2_CONSTRUCTION")
    print("M26_E5_REPAIR2_DUAL_HASH_NO_SEMANTIC_SELFTEST_PASS")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
