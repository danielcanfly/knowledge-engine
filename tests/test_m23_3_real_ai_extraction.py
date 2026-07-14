from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m23_real_ai_extraction import execute_real_ai_extraction

ROOT = Path(__file__).resolve().parents[1]


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    evidence = tmp_path / "evidence"
    batch = evidence / "batches" / "m23batch_d7a9c85f4ac8070448ccf7d96037d320"
    for name in ("plan.json", "checkpoint.json"):
        value = json.loads((ROOT / "tests" / "fixtures" / "m23" / name).read_text())
        _write_json(batch / name, value)
    receipt = json.loads((ROOT / "pilot" / "m23" / "m23-2-live-intake-receipt.json").read_text())
    _write_json(batch / "execution-receipt.json", receipt)

    plan = json.loads((batch / "plan.json").read_text())
    inputs = []
    proposals = []
    endpoint_labels = []
    for index, item in enumerate(plan["items"]):
        text = f"Document {index} defines Concept {index} and a governed agent runtime.\n"
        doc = evidence / "review-packets" / item["document_id"]
        doc.mkdir(parents=True)
        (doc / "normalized.md").write_text(text, encoding="utf-8")
        normalized_sha = hashlib.sha256(text.encode()).hexdigest()
        _write_json(doc / "intake-result.json", {"normalized_sha256": normalized_sha})
        derivative_id = f"derivative_{item['document_id']}"
        inputs.append({
            "document_id": item["document_id"], "derivative_id": derivative_id,
            "text_sha256": normalized_sha, "character_count": len(text),
        })
        anchor = f"Concept {index}"
        start = text.index(anchor)
        label = f"Concept {index}"
        endpoint_labels.append(label)
        proposals.append({
            "kind": "concept", "label": label, "language": item["language"],
            "confidence": 0.9, "aliases": [], "tags": ["agents", "runtime"],
            "definition": f"A bounded pilot concept number {index}.",
            "evidence": [{"derivative_id": derivative_id, "start": start,
                          "end": start + len(anchor),
                          "excerpt_sha256": hashlib.sha256(anchor.encode()).hexdigest()}],
        })
    relation_anchor = "Concept 0"
    first_text = "Document 0 defines Concept 0 and a governed agent runtime.\n"
    start = first_text.index(relation_anchor)
    proposals.append({
        "kind": "relation_hint", "label": "Concept 0 supports Concept 1",
        "language": "zh-TW", "confidence": 0.8, "aliases": [], "tags": [],
        "source_label": "Concept 0", "target_label": "Concept 1", "predicate": "supports",
        "evidence": [{"derivative_id": inputs[0]["derivative_id"], "start": start,
                      "end": start + len(relation_anchor),
                      "excerpt_sha256": hashlib.sha256(relation_anchor.encode()).hexdigest()}],
    })
    provider = {
        "provider_id": "fixture-provider", "model": "fixture-model", "model_version": "v1",
        "prompt_version": "m23.3-test", "adapter_version": "knowledge-engine-m23-provider-envelope/v1",
        "temperature": 0, "seed": 23,
    }
    request = {
        "schema_version": "knowledge-engine-m23-provider-request/v1",
        "batch_id": plan["batch_id"], "m23_2_receipt_sha256": receipt["receipt_sha256"],
        "provider": provider, "inputs": inputs,
        "requested_outputs": ["concept", "relation_hint", "governed_tag_suggestion"],
    }
    request["request_sha256"] = _digest(request)
    response = {
        "schema_version": "knowledge-engine-m23-provider-response/v1",
        "request_sha256": request["request_sha256"], "provider": provider,
        "proposals": proposals,
        "relation_mappings": [{
            "source_label": endpoint_labels[0], "target_label": endpoint_labels[1],
            "predicate": "supports", "relation_type": "supports", "direction": "directed",
            "confidence": 0.8, "qualifiers": {},
        }],
        "tag_mappings": [{
            "label": label, "source_tag": tag,
            "dimension": "domain" if tag == "agents" else "lifecycle",
            "confidence": 0.8,
        } for label in endpoint_labels for tag in ("agents", "runtime")],
        "authority": "candidate_only", "canonical_knowledge": False,
        "production_authority": False, "review_required": True,
    }
    response["response_sha256"] = _digest(response)
    request_path, response_path = tmp_path / "request.json", tmp_path / "response.json"
    _write_json(request_path, request)
    _write_json(response_path, response)
    return evidence, request_path, response_path


def test_real_provider_artifacts_are_frozen_and_candidate_only() -> None:
    receipt = json.loads(
        (ROOT / "pilot" / "m23" / "m23-3-real-ai-extraction-receipt.json").read_text()
    )
    assert receipt["request_sha256"] == (
        "172fc34e5dc744216b520db2ef3c58a111bea54590e8274f4443ec6e670873df"
    )
    assert receipt["response_sha256"] == (
        "32033c80219b2ab0b9013196253f546eac137c508b304e469b64f70eceb73fe3"
    )
    assert receipt["candidate_count"] == 38
    assert receipt["typed_relation_count"] == 12
    assert receipt["governed_tag_count"] == 34
    assert receipt["authority"] == "candidate_only"
    assert receipt["canonical_knowledge"] is False
    assert receipt["production_authority"] is False


def test_adapter_routes_through_m21_validators(tmp_path: Path) -> None:
    evidence, request, response = _fixture(tmp_path)
    result = execute_real_ai_extraction(
        evidence_root=evidence,
        request_path=request,
        response_path=response,
    )
    assert result["receipt"]["document_count"] == 6
    assert result["extraction_packet"]["candidate_count"] == 7
    assert result["governed_packet"]["typed_relation_count"] == 1
    assert result["governed_packet"]["governed_tag_count"] == 12
    assert all(c["authority"] == "candidate_only" for c in result["extraction_packet"]["candidates"])


def test_provider_response_tamper_fails_closed(tmp_path: Path) -> None:
    evidence, request, response = _fixture(tmp_path)
    value = json.loads(response.read_text())
    value["proposals"][0]["label"] = "tampered"
    _write_json(response, value)
    with pytest.raises(IntegrityError, match="response digest mismatch"):
        execute_real_ai_extraction(evidence_root=evidence, request_path=request, response_path=response)


def test_evidence_offset_tamper_is_rejected_by_m21_3(tmp_path: Path) -> None:
    evidence, request, response = _fixture(tmp_path)
    value = json.loads(response.read_text())
    value["proposals"][0]["evidence"][0]["end"] += 1
    unsigned = dict(value)
    unsigned.pop("response_sha256")
    value["response_sha256"] = _digest(unsigned)
    _write_json(response, value)
    with pytest.raises(IntegrityError, match="evidence span digest mismatch"):
        execute_real_ai_extraction(evidence_root=evidence, request_path=request, response_path=response)


def test_unresolved_relation_mapping_fails_closed(tmp_path: Path) -> None:
    evidence, request, response = _fixture(tmp_path)
    value = json.loads(response.read_text())
    value["relation_mappings"][0]["target_label"] = "missing"
    unsigned = dict(value)
    unsigned.pop("response_sha256")
    value["response_sha256"] = _digest(unsigned)
    _write_json(response, value)
    with pytest.raises(IntegrityError, match="unresolved provider relation mapping"):
        execute_real_ai_extraction(evidence_root=evidence, request_path=request, response_path=response)
