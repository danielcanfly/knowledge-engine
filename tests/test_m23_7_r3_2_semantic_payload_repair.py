from __future__ import annotations

import copy
import json

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m23_7_r3_2_semantic_payload_repair import (
    PAYLOAD_SCHEMA_V2,
    build_payload_v2,
    canonical_repair_contract,
    compile_repaired_probe_plan,
)


def _release() -> dict[str, str]:
    return {
        "release_id": "m23pilot-repair-preview",
        "release_manifest_sha256": "a" * 64,
    }


def _documents() -> list[dict[str, object]]:
    titles = (
        "Canonical run authority and acceptance boundaries",
        "Request boundary admission control and rejection",
        "Agent loop stopping policy and retry budget",
        "Evidence provenance verification and source binding",
        "Durable thread state and checkpoint recovery",
        "Tool calling proposal boundary and approval",
        "Graph explorer read only access boundary",
        "Lexical rollback authority and recovery policy",
    )
    languages = ("en", "en", "en", "zh-TW", "en", "en", "en", "zh-TW")
    output: list[dict[str, object]] = []
    for index, (title, language) in enumerate(zip(titles, languages, strict=True), start=1):
        text = f"repair fixture text {index}"
        output.append(
            {
                "section_id": f"pilot/harness-theory-part-{index:02d}-{language.lower()}/chunk-{index:03d}",
                "concept_id": title.lower().replace(" ", "-"),
                "language": language,
                "title": title,
                "source_path": f"docs/repair/{index}.md",
                "source_sha256": f"{index:064x}"[-64:],
                "text_sha256": f"{index + 8:064x}"[-64:],
                "audience": "public",
                "text": text,
            }
        )
    return output


def _samples() -> list[dict[str, object]]:
    release = _release()
    samples: list[dict[str, object]] = []
    for index, document in enumerate(_documents(), start=1):
        section_id = str(document["section_id"])
        article_id = section_id.split("/chunk-", 1)[0]
        samples.append(
            {
                "point_id": f"00000000-0000-0000-0000-{index:012d}",
                "payload": build_payload_v2(document, article_id=article_id, release=release),
            }
        )
    return samples


def test_payload_v2_carries_semantic_fields_without_authority() -> None:
    payload = _samples()[0]["payload"]
    assert isinstance(payload, dict)
    assert payload["payload_schema_version"] == PAYLOAD_SCHEMA_V2
    assert payload["section_title"] == "Canonical run authority and acceptance boundaries"
    assert payload["language"] == "en"
    assert payload["canonical_knowledge"] is False
    assert payload["candidate_release_eligible"] is False
    assert payload["production_authority"] is False


def test_repaired_compiler_produces_eight_unique_query_texts() -> None:
    probes = compile_repaired_probe_plan(_samples())
    assert len(probes) == 8
    assert len({probe["query_text_sha256"] for probe in probes}) == 8
    assert len({probe["query_digest"] for probe in probes}) == 8
    assert all(probe["payload_schema_version"] == PAYLOAD_SCHEMA_V2 for probe in probes)
    assert all(probe["expected_relevant_ids"] == [probe["target_section_id"]] for probe in probes)


def test_compiler_rejects_old_payload_schema() -> None:
    samples = _samples()
    samples[0]["payload"]["payload_schema_version"] = "knowledge-engine-m23-qdrant-payload/v1"
    with pytest.raises(IntegrityError, match="payload v2 required"):
        compile_repaired_probe_plan(samples)


def test_compiler_fails_closed_on_query_collision() -> None:
    samples = _samples()
    first = samples[0]["payload"]
    second = samples[4]["payload"]
    second["section_title"] = first["section_title"]
    second["concept_id"] = first["concept_id"]
    second["section_id"] = "pilot/harness-theory-part-01-en/chunk-001"
    first["section_id"] = "pilot/harness-theory-part-01-en/chunk-001"
    with pytest.raises(IntegrityError, match="target sections are duplicated|query text collision"):
        compile_repaired_probe_plan(samples)


def test_payload_title_is_bound_to_document_not_derived_from_generic_id() -> None:
    document = copy.deepcopy(_documents()[0])
    document["section_id"] = "pilot/harness-theory-part-99-en/chunk-999"
    payload = build_payload_v2(document, article_id="pilot/harness-theory-part-99-en", release=_release())
    assert payload["section_title"] == document["title"]
    assert "part-99" not in payload["section_title"]


def test_repair_contract_preserves_fail_closed_authority() -> None:
    contract = canonical_repair_contract()
    assert contract["repair"]["embedding_model_changed"] is False
    assert contract["repair"]["full_reingestion_required"] is True
    assert contract["authority"]["production_retrieval"] == "lexical"
    assert contract["authority"]["qdrant_write_authorized"] is False
    assert contract["next_gate"] == "offline_rebuild_and_retrieval_evaluation"
    encoded = json.dumps(contract, sort_keys=True)
    assert "https://" not in encoded
    assert len(contract["contract_sha256"]) == 64
