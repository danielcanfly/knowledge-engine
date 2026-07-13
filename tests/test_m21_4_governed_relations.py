from __future__ import annotations

import copy
import hashlib
import json

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m21_governed_relations import (
    FOUNDATION_SHA,
    RELATIONS,
    TAG_ALIASES,
    TAG_DIMENSIONS,
    build_governed_candidate_packet,
)


def _digest(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def _evidence() -> list[dict]:
    return [
        {
            "snapshot_id": "1" * 64,
            "plan_sha256": "2" * 64,
            "derivative_id": "derivative_example",
            "start": 0,
            "end": 20,
            "excerpt_sha256": "3" * 64,
        }
    ]


def _candidate(candidate_id: str, kind: str, label: str, **extra: object) -> dict:
    candidate = {
        "candidate_id": candidate_id,
        "kind": kind,
        "label": label,
        "normalized_label": label.casefold(),
        "language": "en",
        "confidence": 0.9,
        "aliases": [],
        "controlled_tags": [],
        "evidence_spans": _evidence(),
        "status": "pending_review",
        "authority": "candidate_only",
        "canonical_knowledge": False,
        "production_authority": False,
    }
    candidate.update(extra)
    return candidate


def _packet() -> dict:
    concept = _candidate(
        "conceptcand_rag",
        "concept",
        "Retrieval-Augmented Generation",
        aliases=["RAG"],
        controlled_tags=["retrieval-augmented-generation", "retrieval"],
    )
    entity = _candidate("entitycand_qdrant", "entity", "Qdrant", entity_type="software")
    hint = _candidate(
        "relhint_rag_qdrant",
        "relation_hint",
        "RAG uses Qdrant",
        source_label="RAG",
        target_label="Qdrant",
        predicate="uses",
        ontology_type=None,
        confidence=0.8,
    )
    packet = {
        "schema": "knowledge-engine-extraction-candidates/v1",
        "authority": "candidate_only",
        "canonical_knowledge": False,
        "production_authority": False,
        "review_required": True,
        "source_text_untrusted": True,
        "plan_sha256": "4" * 64,
        "checkpoint_sha256": "5" * 64,
        "inventory_sha256": "6" * 64,
        "identity": {
            "engine_sha": "a" * 40,
            "source_sha": "b" * 40,
            "foundation_sha": FOUNDATION_SHA,
            "captured_at": "2026-07-13T18:00:00Z",
        },
        "allowed_tags": ["retrieval", "retrieval-augmented-generation"],
        "derivative_count": 1,
        "candidate_count": 3,
        "candidates": [concept, entity, hint],
    }
    packet["packet_sha256"] = _digest(packet)
    return packet


def _ontology() -> dict:
    entries = []
    for relation_type, directed, symmetric, inverse, provenance, retrieval in RELATIONS:
        entries.append(
            {
                "type": relation_type,
                "directed": directed,
                "symmetric": symmetric,
                "inverse": inverse,
                "provenance_expectation": provenance,
                "allowed_qualifiers": ["scope", "context", "valid_from", "valid_to"],
                "retrieval_semantics": list(retrieval),
                "description": f"Governed description for relation type {relation_type} in Knowledge OS.",
            }
        )
    return {
        "schema_version": "knowledge-os-relation-ontology/v0.1",
        "ontology_id": "daniel-knowledge-os/relation-ontology",
        "version": "0.1.0",
        "status": "normative_draft",
        "fallback_type": "related_to",
        "relation_types": entries,
    }


def _taxonomy() -> dict:
    return {
        "schema_version": "knowledge-os-tag-taxonomy/v0.1",
        "taxonomy_id": "daniel-knowledge-os/tag-taxonomy",
        "version": "0.1.0",
        "status": "active",
        "dimensions": copy.deepcopy(TAG_DIMENSIONS),
        "tag_aliases": copy.deepcopy(TAG_ALIASES),
    }


def _relation(**changes: object) -> dict:
    value = {
        "hint_candidate_id": "relhint_rag_qdrant",
        "source_candidate_id": "conceptcand_rag",
        "target_candidate_id": "entitycand_qdrant",
        "relation_type": "uses",
        "direction": "directed",
        "confidence": 0.75,
        "qualifiers": {"context": "vector retrieval"},
    }
    value.update(changes)
    return value


def _tag(**changes: object) -> dict:
    value = {
        "candidate_id": "conceptcand_rag",
        "source_tag": "retrieval-augmented-generation",
        "dimension": "domain",
        "confidence": 0.85,
    }
    value.update(changes)
    return value


def _build(
    packet: dict | None = None,
    relations: list[dict] | None = None,
    tags: list[dict] | None = None,
    ontology: dict | None = None,
    taxonomy: dict | None = None,
    foundation_sha: str = FOUNDATION_SHA,
) -> dict:
    return build_governed_candidate_packet(
        packet or _packet(),
        [_relation()] if relations is None else relations,
        [_tag()] if tags is None else tags,
        foundation_sha=foundation_sha,
        relation_ontology=ontology or _ontology(),
        tag_taxonomy=taxonomy or _taxonomy(),
    )


def test_packet_is_deterministic_candidate_only_and_contract_bound() -> None:
    first = _build()
    second = _build()
    assert first == second
    assert first["authority"] == "candidate_only"
    assert first["canonical_knowledge"] is False
    assert first["production_authority"] is False
    assert first["review_required"] is True
    assert first["typed_relation_count"] == 1
    assert first["governed_tag_count"] == 1
    relation = first["typed_relation_candidates"][0]
    assert relation["relation_type"] == "uses"
    assert relation["direction"] == "directed"
    assert relation["inverse_type"] == "used_by"
    assert relation["evidence_spans"] == _evidence()
    tag = first["governed_tag_candidates"][0]
    assert tag["source_tag"] == "retrieval-augmented-generation"
    assert tag["canonical_tag"] == "rag"
    assert tag["dimension"] == "domain"
    assert first["relation_ontology"]["sha256"]
    assert first["tag_taxonomy"]["sha256"]


def test_unknown_free_form_and_inverse_only_relation_types_fail_closed() -> None:
    with pytest.raises(IntegrityError, match="unknown or inverse-only"):
        _build(relations=[_relation(relation_type="integrates_with")], tags=[])
    with pytest.raises(IntegrityError, match="unknown or inverse-only"):
        _build(relations=[_relation(relation_type="used_by")], tags=[])


def test_direction_self_loop_and_unresolved_endpoints_fail_closed() -> None:
    with pytest.raises(IntegrityError, match="direction mismatch"):
        _build(relations=[_relation(direction="undirected")], tags=[])
    with pytest.raises(IntegrityError, match="self-loop"):
        _build(
            relations=[_relation(target_candidate_id="conceptcand_rag")],
            tags=[],
        )
    with pytest.raises(IntegrityError, match="unresolved relation endpoint"):
        _build(relations=[_relation(target_candidate_id="missing")], tags=[])


def test_label_resolution_confidence_and_qualifiers_fail_closed() -> None:
    packet = _packet()
    packet["candidates"][2]["source_label"] = "Unrelated"
    packet["packet_sha256"] = _digest(
        {key: value for key, value in packet.items() if key != "packet_sha256"}
    )
    with pytest.raises(IntegrityError, match="source label does not resolve"):
        _build(packet=packet, tags=[])
    with pytest.raises(IntegrityError, match="invalid relation confidence"):
        _build(relations=[_relation(confidence=0.9)], tags=[])
    with pytest.raises(IntegrityError, match="unsupported qualifier"):
        _build(relations=[_relation(qualifiers={"weight": "high"})], tags=[])
    with pytest.raises(IntegrityError, match="secret-like"):
        _build(
            relations=[_relation(qualifiers={"context": "api_key=supersecretvalue123"})],
            tags=[],
        )


def test_duplicate_directed_and_symmetric_relations_fail_closed() -> None:
    with pytest.raises(IntegrityError, match="duplicate normalized relation"):
        _build(relations=[_relation(), _relation()], tags=[])
    packet = _packet()
    second_hint = copy.deepcopy(packet["candidates"][2])
    second_hint["candidate_id"] = "relhint_qdrant_rag"
    second_hint["source_label"] = "Qdrant"
    second_hint["target_label"] = "RAG"
    packet["candidates"].append(second_hint)
    packet["candidate_count"] = 4
    packet["packet_sha256"] = _digest(
        {key: value for key, value in packet.items() if key != "packet_sha256"}
    )
    first = _relation(relation_type="contrasts_with", direction="undirected")
    second = _relation(
        hint_candidate_id="relhint_qdrant_rag",
        source_candidate_id="entitycand_qdrant",
        target_candidate_id="conceptcand_rag",
        relation_type="contrasts_with",
        direction="undirected",
    )
    with pytest.raises(IntegrityError, match="duplicate normalized relation"):
        _build(packet=packet, relations=[first, second], tags=[])


def test_tag_alias_category_source_evidence_and_duplicates_fail_closed() -> None:
    with pytest.raises(IntegrityError, match="dimension mismatch"):
        _build(relations=[], tags=[_tag(dimension="technique")])
    with pytest.raises(IntegrityError, match="lacks M21.3 evidence"):
        _build(relations=[], tags=[_tag(source_tag="rag")])
    with pytest.raises(IntegrityError, match="duplicate governed tag"):
        _build(relations=[], tags=[_tag(), _tag()])
    with pytest.raises(IntegrityError, match="invalid tag confidence"):
        _build(relations=[], tags=[_tag(confidence=0.95)])


def test_ontology_identity_semantics_and_inverse_drift_fail_closed() -> None:
    ontology = _ontology()
    ontology["version"] = "0.2.0"
    with pytest.raises(IntegrityError, match="ontology identity drift"):
        _build(ontology=ontology)
    ontology = _ontology()
    ontology["relation_types"][4]["inverse"] = "requires"
    with pytest.raises(IntegrityError, match="ontology semantics drift"):
        _build(ontology=ontology)
    ontology = _ontology()
    ontology["relation_types"][14]["directed"] = True
    with pytest.raises(IntegrityError, match="ontology semantics drift"):
        _build(ontology=ontology)


def test_taxonomy_identity_dimensions_and_alias_drift_fail_closed() -> None:
    taxonomy = _taxonomy()
    taxonomy["dimensions"]["domain"].append("unknown")
    with pytest.raises(IntegrityError, match="taxonomy semantics drift"):
        _build(taxonomy=taxonomy)
    taxonomy = _taxonomy()
    taxonomy["tag_aliases"]["rag"] = "retrieval"
    with pytest.raises(IntegrityError, match="taxonomy semantics drift"):
        _build(taxonomy=taxonomy)
    taxonomy = _taxonomy()
    taxonomy["status"] = "deprecated"
    with pytest.raises(IntegrityError, match="taxonomy semantics drift"):
        _build(taxonomy=taxonomy)


def test_packet_digest_authority_foundation_and_empty_mappings_fail_closed() -> None:
    packet = _packet()
    packet["packet_sha256"] = "0" * 64
    with pytest.raises(IntegrityError, match="packet digest mismatch"):
        _build(packet=packet)
    packet = _packet()
    packet["production_authority"] = True
    packet["packet_sha256"] = _digest(
        {key: value for key, value in packet.items() if key != "packet_sha256"}
    )
    with pytest.raises(IntegrityError, match="packet authority drift"):
        _build(packet=packet)
    with pytest.raises(IntegrityError, match="unpinned Foundation"):
        _build(foundation_sha="f" * 40)
    with pytest.raises(IntegrityError, match="mapping count"):
        _build(relations=[], tags=[])
