from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "scripts" / "m26_e5_one_shot_oracle_runner.py"
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "m26_e5_exact_six_case_freeze.json"
EXPECTED_CANONICAL = {
    "stage_d_en": "6395e2711481ed7eb2af3c8bd2f1adeaa80735cbee3bf67433a81199b2bf0735",
    "stage_d_zh_tw": "eedf56041027914ccb852ab150167835525767ea1349a5dcbab85d359e2251b8",
    "stage_d_mixed": "51f8b65388e520906df1ec22d8f4b5a39e72a228f3a13c346e081df82c33c032",
    "stage_d_abstention": "4cb6b2091a4a891eda31b0597d4e8bb433f756a52d56d19258b008fca57536d9",
    "stage_d_safety": "888d9846291c9d5a748f59c04783d955aa5e843d74db1c5e37eba59198c3589e",
    "p4_en_answerable": "0177a894887b404f5ccb8427b61c0a229f86c195a0536e29fac7c895974f5f06",
}


def load_runner():
    spec = importlib.util.spec_from_file_location("m26_e5_one_shot_oracle_runner", RUNNER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_all_six_frozen_questions_preserve_dual_hash_domains() -> None:
    runner = load_runner()
    fixture = runner.load_fixture(FIXTURE_PATH)
    for case in fixture["cases"]:
        assert case["question_raw_utf8_sha256"] == case["question_sha256"]
        assert case["question_canonical_json_sha256"] == EXPECTED_CANONICAL[case["id"]]
        assert case["question_raw_utf8_sha256"] != case["question_canonical_json_sha256"]
        request_body = json.dumps({"question": case["question"]}, ensure_ascii=False, separators=(",", ":"))
        assert request_body == case["request_body"]
        assert runner.sha256_bytes(request_body.encode("utf-8")) == case["request_body_sha256"]


def test_sse_meta_uses_canonical_hash_and_rejects_raw_hash_negative_control() -> None:
    runner = load_runner()
    fixture = runner.load_fixture(FIXTURE_PATH)
    for case in fixture["cases"]:
        answer = runner.synthetic_answer_payload()
        if case["kind"] != "answerable":
            case = {**case, "kind": "answerable"}
        events = [
            {"event": "meta", "payload": {"route": runner.EXACT["answer_path"], "question_sha256": case["question_canonical_json_sha256"]}},
            {"event": "answer", "payload": answer},
            {"event": "done", "payload": {"status": "ok", "pass": False, "verdict": "FAIL"}},
        ]
        ok, reason, _, _ = runner.semantic_verdict(case, events)
        assert ok, reason
        bad = json.loads(json.dumps(events))
        bad[0]["payload"]["question_sha256"] = case["question_raw_utf8_sha256"]
        ok_bad, reason_bad, _, _ = runner.semantic_verdict(case, bad)
        assert not ok_bad
        assert reason_bad == "SSE_META_QUESTION_SHA_MISMATCH"


def test_done_and_guessed_pass_fields_do_not_create_semantic_pass() -> None:
    runner = load_runner()
    fixture = runner.load_fixture(FIXTURE_PATH)
    case = {**fixture["cases"][0], "kind": "answerable"}
    answer = runner.synthetic_answer_payload()
    answer["integrity"]["material_claim_support_verified"] = False
    events = [
        {"event": "meta", "payload": {"route": runner.EXACT["answer_path"], "question_sha256": case["question_canonical_json_sha256"]}},
        {"event": "answer", "payload": answer},
        {"event": "done", "payload": {"status": "ok", "pass": True, "verdict": "PASS"}},
    ]
    ok, reason, _, _ = runner.semantic_verdict(case, events)
    assert not ok
    assert reason == "ANSWERABLE_INTEGRITY"
    done_only = [events[0], events[2]]
    ok_done, reason_done, _, _ = runner.semantic_verdict(case, done_only)
    assert not ok_done
    assert reason_done == "SSE_ANSWER_COUNT"
