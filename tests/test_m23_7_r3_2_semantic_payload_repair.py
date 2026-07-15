from __future__ import annotations

import copy
import json

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m23_7_r3_2_semantic_payload_repair import (
    PAYLOAD_SCHEMA_V2,
    build_payload_v2,
    build_repaired_ingestion_preview,
    canonical_repair_contract,
    compile_repaired_probe_plan,
)
from knowledge_engine.m23_cloudflare_qdrant import deterministic_point_id


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
        "證據來源驗證與來源綁定策略",
        "Durable thread state and checkpoint recovery",
        "Tool calling proposal boundary and approval",
        "Graph explorer read only access boundary",
        "詞彙回滾權限與復原政策",
    )
    languages = ("en", "en", "en", "zh-TW", "en", "en", "en", "zh-TW")
    output: list[dict[str, object]] = []
    for index, (title, language) in enumerate(zip(titles, languages, strict=True), start=1):
        text = f"repair fixture text {index}"
        section_id = (
            f"pilot/harness-theory-part-{index:02d}-{language.lower()}"
            f"/chunk-{index:03d}"
        )
        output.append(
            {
                "section_id": section_id,
                "concept_id": (
                    title.lower().replace(" ", "-")
                    if language == "en"
                    else f"repair-concept-{index:02d}"
                ),
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


def _vectors(count: int = 8) -> list[list[float]]:
    vectors: list[list[float]] = []
    for index in range(count):
        vector = [0.0] * 1024
        vector[index] = 1.0
        vectors.append(vector)
    return vectors


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


def test_repaired_ingestion_binds_document_payload_and_vector_row() -> None:
    documents = _documents()
    preview = build_repaired_ingestion_preview(
        documents,
        _vectors(),
        release=_release(),
        expected_point_count=8,
    )
    assert preview["mode"] == "offline-no-write-preview"
    assert preview["point_count"] == 8
    assert len(preview["points"]) == 8
    assert len({item["binding_sha256"] for item in preview["bindings"]}) == 8
    first = preview["points"][0]
    assert first["id"] == deterministic_point_id(str(documents[0]["section_id"]))
    assert first["payload"]["section_title"] == documents[0]["title"]
    assert first["vector"]["default"][0] == 1.0
    assert preview["authority"]["qdrant_write_dispatched"] is False


def test_repaired_ingestion_rejects_vector_row_drift() -> None:
    vectors = _vectors()
    vectors[3][3] = 2.0
    with pytest.raises(IntegrityError, match="not L2-normalized"):
        build_repaired_ingestion_preview(
            _documents(),
            vectors,
            release=_release(),
            expected_point_count=8,
        )


def test_repaired_compiler_produces_eight_unique_query_texts() -> None:
    probes = compile_repaired_probe_plan(_samples())
    assert len(probes) == 8
    assert len({probe["query_text_sha256"] for probe in probes}) == 8
    assert len({probe["query_digest"] for probe in probes}) == 8
    assert all(probe["payload_schema_version"] == PAYLOAD_SCHEMA_V2 for probe in probes)
    assert all(probe["expected_relevant_ids"] == [probe["target_section_id"]] for probe in probes)
    assert any(probe["target_section_id"].endswith("zh-tw/chunk-004") for probe in probes)


def test_compiler_rejects_old_payload_schema() -> None:
    samples = _samples()
    samples[0]["payload"]["payload_schema_version"] = "knowledge-engine-m23-qdrant-payload/v1"
    with pytest.raises(IntegrityError, match="payload v2 required"):
        compile_repaired_probe_plan(samples)


def test_compiler_fails_closed_on_text_only_query_collision() -> None:
    samples = _samples()
    first = samples[0]["payload"]
    second = samples[4]["payload"]
    second["section_title"] = first["section_title"]
    second["concept_id"] = first["concept_id"]
    second["language"] = first["language"]
    first["section_id"] = "pilot/a/chunk-alpha"
    second["section_id"] = "pilot/b/chunk-beta"
    with pytest.raises(IntegrityError, match="query text collision"):
        compile_repaired_probe_plan(samples)


def test_payload_title_is_bound_to_document_not_derived_from_generic_id() -> None:
    document = copy.deepcopy(_documents()[0])
    document["section_id"] = "pilot/harness-theory-part-99-en/chunk-999"
    payload = build_payload_v2(
        document,
        article_id="pilot/harness-theory-part-99-en",
        release=_release(),
    )
    assert payload["section_title"] == document["title"]
    assert "part-99" not in payload["section_title"]


def test_repair_contract_preserves_fail_closed_authority() -> None:
    contract = canonical_repair_contract()
    assert contract["implementation_issue"] == 484
    assert contract["repair"]["embedding_model_changed"] is False
    assert contract["repair"]["full_reingestion_required"] is True
    assert contract["repair"]["payload_vector_row_binding_revalidated"] is True
    assert contract["authority"]["production_retrieval"] == "lexical"
    assert contract["authority"]["qdrant_write_authorized"] is False
    assert contract["next_gate"] == "offline_rebuild_and_retrieval_evaluation"
    encoded = json.dumps(contract, sort_keys=True)
    assert "https://" not in encoded
    assert len(contract["contract_sha256"]) == 64
