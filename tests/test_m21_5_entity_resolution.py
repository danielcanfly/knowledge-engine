from __future__ import annotations

import copy
import hashlib
import json

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m21_entity_resolution import (
    FOUNDATION_SHA,
    SOURCE_SHA,
    build_resolution_candidate_packet,
)

ENGINE_SHA = "a" * 40
def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def sign(value: dict[str, object], field: str) -> dict[str, object]:
    unsigned = dict(value)
    unsigned.pop(field, None)
    value[field] = digest(unsigned)
    return value


def evidence(seed: str = "one") -> list[dict[str, object]]:
    return [
        {
            "snapshot_id": f"snapshot_{seed}",
            "plan_sha256": hashlib.sha256(f"plan-{seed}".encode()).hexdigest(),
            "derivative_id": f"derivative_{seed}",
            "start": 0,
            "end": 4,
            "excerpt_sha256": hashlib.sha256(seed.encode()).hexdigest(),
        }
    ]


def candidate(
    candidate_id: str,
    label: str,
    *,
    kind: str = "concept",
    aliases: list[str] | None = None,
    tags: list[str] | None = None,
    confidence: float = 0.8,
    **extra: object,
) -> dict[str, object]:
    value: dict[str, object] = {
        "candidate_id": candidate_id,
        "kind": kind,
        "label": label,
        "normalized_label": " ".join(label.split()).casefold(),
        "language": "en",
        "confidence": confidence,
        "aliases": aliases or [],
        "controlled_tags": tags or [],
        "evidence_spans": evidence(candidate_id),
        "status": "pending_review",
        "authority": "candidate_only",
        "canonical_knowledge": False,
        "production_authority": False,
    }
    value.update(extra)
    return value


def extraction(candidates: list[dict[str, object]]) -> dict[str, object]:
    packet: dict[str, object] = {
        "schema": "knowledge-engine-extraction-candidates/v1",
        "authority": "candidate_only",
        "canonical_knowledge": False,
        "production_authority": False,
        "review_required": True,
        "source_text_untrusted": True,
        "plan_sha256": "1" * 64,
        "checkpoint_sha256": "2" * 64,
        "inventory_sha256": "3" * 64,
        "identity": {
            "engine_sha": ENGINE_SHA,
            "source_sha": SOURCE_SHA,
            "foundation_sha": FOUNDATION_SHA,
        },
        "allowed_tags": ["rag"],
        "derivative_count": 1,
        "candidate_count": len(candidates),
        "candidates": candidates,
    }
    return sign(packet, "packet_sha256")


def governed(
    extraction_packet: dict[str, object],
    *,
    tags: list[dict[str, object]] | None = None,
    relations: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    packet: dict[str, object] = {
        "schema": "knowledge-engine-governed-candidates/v1",
        "authority": "candidate_only",
        "canonical_knowledge": False,
        "production_authority": False,
        "review_required": True,
        "foundation_sha": FOUNDATION_SHA,
        "extraction_packet_sha256": extraction_packet["packet_sha256"],
        "identity": extraction_packet["identity"],
        "relation_ontology": {
            "schema_version": "knowledge-os-relation-ontology/v0.1",
            "ontology_id": "daniel-knowledge-os/relation-ontology",
            "version": "0.1.0",
            "sha256": "4" * 64,
        },
        "tag_taxonomy": {
            "schema_version": "knowledge-os-tag-taxonomy/v0.1",
            "taxonomy_id": "daniel-knowledge-os/tag-taxonomy",
            "version": "0.1.0",
            "sha256": "5" * 64,
        },
        "typed_relation_count": len(relations or []),
        "governed_tag_count": len(tags or []),
        "typed_relation_candidates": relations or [],
        "governed_tag_candidates": tags or [],
    }
    return sign(packet, "packet_sha256")


def governed_tag(candidate_id: str, tag: str = "rag") -> dict[str, object]:
    return {
        "tag_candidate_id": f"tag_{candidate_id}_{tag}",
        "source_candidate_id": candidate_id,
        "source_tag": tag,
        "canonical_tag": tag,
        "dimension": "domain",
        "confidence": 0.7,
        "evidence_spans": evidence(candidate_id),
        "status": "pending_review",
        "authority": "candidate_only",
        "canonical_knowledge": False,
        "production_authority": False,
    }


def governed_relation(left: str, right: str) -> dict[str, object]:
    return {
        "relation_candidate_id": f"rel_{left}_{right}",
        "hint_candidate_id": "hint",
        "source_candidate_id": left,
        "target_candidate_id": right,
        "relation_type": "related_to",
        "direction": "undirected",
        "inverse_type": "related_to",
        "provenance_expectation": "required_factual",
        "retrieval_semantics": ["generic"],
        "qualifiers": {},
        "confidence": 0.7,
        "evidence_spans": evidence("relation"),
        "status": "pending_review",
        "authority": "candidate_only",
        "canonical_knowledge": False,
        "production_authority": False,
    }


def source_concept(
    x_kos_id: str,
    title: str,
    *,
    path: str | None = None,
    aliases: list[str] | None = None,
    terms: list[str] | None = None,
    tags: list[str] | None = None,
    audience: str = "public",
) -> dict[str, object]:
    return {
        "x_kos_id": x_kos_id,
        "concept_path": path or f"concepts/{x_kos_id}.md",
        "title": title,
        "normalized_title": " ".join(title.split()).casefold(),
        "aliases": aliases or [],
        "bilingual_terms": terms or [],
        "tags": tags or [],
        "audience": audience,
        "source_sha256": hashlib.sha256(x_kos_id.encode()).hexdigest(),
    }


def source_index(concepts: list[dict[str, object]]) -> dict[str, object]:
    index: dict[str, object] = {
        "schema": "knowledge-engine-source-resolution-index/v1",
        "source_sha": SOURCE_SHA,
        "foundation_sha": FOUNDATION_SHA,
        "authority": "reviewed_source_index",
        "concept_count": len(concepts),
        "concepts": concepts,
    }
    return sign(index, "index_sha256")


def build(
    candidates: list[dict[str, object]],
    concepts: list[dict[str, object]],
    *,
    tags: list[dict[str, object]] | None = None,
    relations: list[dict[str, object]] | None = None,
    audiences: dict[str, str] | None = None,
    claims: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    extract = extraction(candidates)
    govern = governed(extract, tags=tags, relations=relations)
    audience_map = audiences or {item["candidate_id"]: "public" for item in candidates}
    return build_resolution_candidate_packet(
        extract,
        govern,
        source_index(concepts),
        candidate_audiences=audience_map,
        claim_assertions=claims,
    )


def test_exact_title_match_is_review_only() -> None:
    packet = build(
        [candidate("concept_1", "Retrieval Augmented Generation")],
        [source_concept("kos_rag", "Retrieval Augmented Generation")],
    )
    resolution = packet["resolutions"][0]
    assert resolution["outcome"] == "exact_existing_match"
    assert resolution["existing_x_kos_id"] == "kos_rag"
    assert resolution["strong_signals"] == ["exact_normalized_title"]
    assert resolution["blocks_packaging"] is False
    assert packet["authority"] == "candidate_only"
    assert packet["canonical_knowledge"] is False
    assert packet["production_authority"] is False


def test_exact_id_and_path_signals_are_supported() -> None:
    concepts = [source_concept("kos_rag", "RAG", path="concepts/rag.md")]
    by_id = build([candidate("concept_1", "kos_rag")], concepts)
    by_path = build([candidate("concept_1", "concepts/rag.md")], concepts)
    assert by_id["resolutions"][0]["strong_signals"] == ["exact_x_kos_id"]
    assert by_path["resolutions"][0]["strong_signals"] == ["exact_concept_path"]


def test_unicode_normalization_replays_to_same_target() -> None:
    concepts = [source_concept("kos_agent", "Ａgent Harness")]
    packet = build([candidate("concept_1", "Agent Harness")], concepts)
    assert packet["resolutions"][0]["outcome"] == "exact_existing_match"


def test_duplicate_source_titles_are_ambiguous() -> None:
    packet = build(
        [candidate("concept_1", "Agent")],
        [source_concept("kos_a", "Agent"), source_concept("kos_b", "Agent")],
    )
    assert packet["resolutions"][0]["outcome"] == "ambiguous"
    assert packet["packaging_blocked"] is True


def test_source_alias_collision_fails_closed() -> None:
    concepts = [
        source_concept("kos_a", "Alpha", aliases=["Shared"]),
        source_concept("kos_b", "Beta", aliases=["Shared"]),
    ]
    with pytest.raises(IntegrityError, match="alias ownership collision"):
        build([candidate("concept_1", "New")], concepts)


def test_bilingual_ownership_collision_is_ambiguous() -> None:
    concepts = [
        source_concept("kos_a", "Alpha", terms=["代理"]),
        source_concept("kos_b", "Beta", terms=["代理"]),
    ]
    packet = build([candidate("concept_1", "代理")], concepts)
    assert packet["resolutions"][0]["outcome"] == "ambiguous"


def test_alias_attachment_is_pending_review() -> None:
    alias = candidate(
        "alias_1",
        "RAG",
        kind="alias",
        target_label="Retrieval Augmented Generation",
    )
    packet = build(
        [alias],
        [source_concept("kos_rag", "Retrieval Augmented Generation")],
    )
    resolution = packet["resolutions"][0]
    assert resolution["outcome"] == "attach_alias_candidate"
    assert resolution["proposed_alias"] == "RAG"
    assert resolution["ownership_unique"] is True
    assert resolution["status"] == "pending_review"


def test_alias_equal_to_other_canonical_title_is_ambiguous() -> None:
    alias = candidate("alias_1", "Beta", kind="alias", target_label="Alpha")
    packet = build(
        [alias],
        [source_concept("kos_a", "Alpha"), source_concept("kos_b", "Beta")],
    )
    assert packet["resolutions"][0]["outcome"] == "ambiguous"


def test_alias_chain_is_rejected() -> None:
    first = candidate("alias_1", "A", kind="alias", target_label="B")
    second = candidate("alias_2", "B", kind="alias", target_label="Alpha")
    packet = build(
        [first, second],
        [source_concept("kos_a", "Alpha")],
    )
    outcomes = {item["candidate_ids"][0]: item["outcome"] for item in packet["resolutions"]}
    assert outcomes["alias_1"] == "reject"


def test_within_batch_duplicate_cluster_is_deterministic() -> None:
    candidates = [candidate("concept_b", "Agent"), candidate("concept_a", "Agent")]
    first = build(candidates, [])
    second = build(copy.deepcopy(candidates), [])
    assert first["resolutions"][0]["outcome"] == "probable_duplicate"
    assert first["resolutions"][0]["candidate_ids"] == ["concept_a", "concept_b"]
    assert first["resolutions"][0]["cluster_id"] == second["resolutions"][0]["cluster_id"]
    assert first["packet_sha256"] == second["packet_sha256"]


def test_explicit_duplicate_hint_clusters_candidates() -> None:
    candidates = [
        candidate("concept_a", "Agent Harness"),
        candidate("concept_b", "Harness Engineering"),
        candidate(
            "hint_1",
            "Agent Harness",
            kind="duplicate_hint",
            target_label="Harness Engineering",
        ),
    ]
    packet = build(candidates, [])
    resolution = packet["resolutions"][0]
    assert resolution["outcome"] == "probable_duplicate"
    assert resolution["candidate_ids"] == ["concept_a", "concept_b"]


def test_shared_tags_are_weak_and_never_exact_merge() -> None:
    candidates = [candidate("concept_1", "Fresh Concept", tags=["rag"])]
    packet = build(
        candidates,
        [source_concept("kos_rag", "RAG", tags=["rag"])],
        tags=[governed_tag("concept_1")],
    )
    resolution = packet["resolutions"][0]
    assert resolution["outcome"] == "probable_duplicate"
    assert resolution["strong_signals"] == []
    assert resolution["weak_signals"] == ["shared_governed_tags_only"]


def test_relation_similarity_is_not_used_for_merge() -> None:
    candidates = [candidate("concept_1", "One"), candidate("concept_2", "Two")]
    packet = build(
        candidates,
        [source_concept("kos_existing", "Existing")],
        relations=[governed_relation("concept_1", "concept_2")],
    )
    assert {item["outcome"] for item in packet["resolutions"]} == {
        "distinct_new_candidate"
    }


def test_acl_mismatch_rejects_exact_match() -> None:
    packet = build(
        [candidate("concept_1", "Private")],
        [source_concept("kos_private", "Private", audience="restricted")],
        audiences={"concept_1": "public"},
    )
    resolution = packet["resolutions"][0]
    assert resolution["outcome"] == "reject"
    assert resolution["weak_signals"] == ["audience_acl_mismatch"]


def test_cross_audience_candidate_cluster_is_rejected() -> None:
    candidates = [candidate("concept_1", "Same"), candidate("concept_2", "Same")]
    packet = build(
        candidates,
        [],
        audiences={"concept_1": "public", "concept_2": "restricted"},
    )
    assert packet["resolutions"][0]["outcome"] == "reject"
    assert packet["resolutions"][0]["audience"] == "mixed"


def test_same_scope_opposite_polarity_is_contradiction() -> None:
    claims = [
        candidate("claim_1", "Needs index", kind="claim", subject_label="RAG", body="yes"),
        candidate("claim_2", "No index", kind="claim", subject_label="RAG", body="no"),
    ]
    assertions = [
        {
            "candidate_id": "claim_1",
            "predicate": "requires",
            "scope": {"context": "runtime"},
            "polarity": "positive",
            "value": "index",
        },
        {
            "candidate_id": "claim_2",
            "predicate": "requires",
            "scope": {"context": "runtime"},
            "polarity": "negative",
            "value": "index",
        },
    ]
    packet = build(claims, [source_concept("kos_rag", "RAG")], claims=assertions)
    contradiction = packet["contradictions"][0]
    assert contradiction["outcome"] == "contradiction_candidate"
    assert contradiction["subject_x_kos_id"] == "kos_rag"
    assert contradiction["incompatibility"] == "opposite_polarity"
    assert packet["packaging_blocked"] is True


def test_different_scope_is_not_contradiction() -> None:
    claims = [
        candidate("claim_1", "A", kind="claim", subject_label="RAG", body="yes"),
        candidate("claim_2", "B", kind="claim", subject_label="RAG", body="no"),
    ]
    assertions = [
        {
            "candidate_id": "claim_1",
            "predicate": "requires",
            "scope": {"context": "runtime"},
            "polarity": "positive",
            "value": "index",
        },
        {
            "candidate_id": "claim_2",
            "predicate": "requires",
            "scope": {"context": "design"},
            "polarity": "negative",
            "value": "index",
        },
    ]
    packet = build(claims, [source_concept("kos_rag", "RAG")], claims=assertions)
    assert packet["contradictions"] == []


def test_wrong_packet_digest_fails() -> None:
    candidates = [candidate("concept_1", "RAG")]
    extract = extraction(candidates)
    govern = governed(extract)
    extract["candidate_count"] = 99
    with pytest.raises(IntegrityError, match="M21.3 digest mismatch"):
        build_resolution_candidate_packet(
            extract,
            govern,
            source_index([]),
            candidate_audiences={"concept_1": "public"},
        )


def test_wrong_governed_binding_fails() -> None:
    candidates = [candidate("concept_1", "RAG")]
    extract = extraction(candidates)
    govern = governed(extract)
    govern["extraction_packet_sha256"] = "0" * 64
    sign(govern, "packet_sha256")
    with pytest.raises(IntegrityError, match="cross-release"):
        build_resolution_candidate_packet(
            extract,
            govern,
            source_index([]),
            candidate_audiences={"concept_1": "public"},
        )


def test_source_index_digest_and_sha_are_pinned() -> None:
    candidates = [candidate("concept_1", "RAG")]
    extract = extraction(candidates)
    govern = governed(extract)
    index = source_index([])
    index["source_sha"] = "c" * 40
    sign(index, "index_sha256")
    with pytest.raises(IntegrityError, match="Source index identity drift"):
        build_resolution_candidate_packet(
            extract,
            govern,
            index,
            candidate_audiences={"concept_1": "public"},
        )


def test_duplicate_candidate_ids_fail() -> None:
    duplicate = candidate("same", "One")
    packet = extraction([duplicate, copy.deepcopy(duplicate)])
    with pytest.raises(IntegrityError, match="duplicate candidate id"):
        build_resolution_candidate_packet(
            packet,
            governed(packet),
            source_index([]),
            candidate_audiences={"same": "public"},
        )


def test_missing_evidence_and_authority_escalation_fail() -> None:
    missing = candidate("concept_1", "RAG")
    missing["evidence_spans"] = []
    packet = extraction([missing])
    with pytest.raises(IntegrityError, match="missing or unbounded evidence"):
        build_resolution_candidate_packet(
            packet,
            governed(packet),
            source_index([]),
            candidate_audiences={"concept_1": "public"},
        )
    escalated = candidate("concept_1", "RAG")
    escalated["canonical_knowledge"] = True
    packet = extraction([escalated])
    with pytest.raises(IntegrityError, match="authority drift"):
        build_resolution_candidate_packet(
            packet,
            governed(packet),
            source_index([]),
            candidate_audiences={"concept_1": "public"},
        )


def test_confidence_and_secret_like_payload_fail() -> None:
    bad_confidence = candidate("concept_1", "RAG", confidence=1.2)
    with pytest.raises(IntegrityError, match="invalid candidate confidence"):
        build([bad_confidence], [])
    secret = candidate("concept_1", "api_key=abcdefghijk")
    with pytest.raises(IntegrityError, match="secret-like"):
        build([secret], [])


def test_audience_binding_must_cover_exact_packet() -> None:
    candidates = [
        candidate("concept_1", "RAG"),
        candidate(
            "claim_1",
            "Claim",
            kind="claim",
            subject_label="RAG",
            body="body",
        ),
    ]
    extract = extraction(candidates)
    with pytest.raises(IntegrityError, match="audience binding coverage"):
        build_resolution_candidate_packet(
            extract,
            governed(extract),
            source_index([]),
            candidate_audiences={"concept_1": "public"},
        )


def test_byte_identical_replay() -> None:
    candidates = [candidate("concept_1", "RAG")]
    concepts = [source_concept("kos_rag", "RAG")]
    first = build(candidates, concepts)
    second = build(copy.deepcopy(candidates), copy.deepcopy(concepts))
    assert first == second
    unsigned = dict(first)
    packet_sha = unsigned.pop("packet_sha256")
    assert digest(unsigned) == packet_sha
