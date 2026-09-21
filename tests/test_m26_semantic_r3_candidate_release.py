from __future__ import annotations

import hashlib
import json
from dataclasses import replace

from knowledge_engine import m25_blog_live_candidate as live_candidate
from knowledge_engine import m26_aq_semantic_contract as contract
from knowledge_engine import m26_semantic_r3_candidate_release as subject
from knowledge_engine.m26_production_answer_bundle import ProductionAnswerBundle
from knowledge_engine.m26_verified_answer_citation_gate import canonical_sha256


def _pretty_sha(value: object) -> str:
    data = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    return hashlib.sha256(data).hexdigest()


def _fixture_bundle() -> ProductionAnswerBundle:
    release_id = subject.SEMANTIC_R3_RELEASE_ID
    graph = {
        "schema_version": "knowledge-engine-document-graph/v1",
        "release_id": release_id,
        "nodes": [{"concept_id": "node_a"}],
        "edges": [],
    }
    graph_v2 = {
        "schema_version": "knowledge-engine-graph-v2/v1",
        "release": {"release_id": release_id},
        "nodes": [{"concept_id": "node_a"}],
        "edges": [],
    }
    lexical = {"release_id": release_id, "documents": [{"section_id": "node_a"}]}
    semantic = {"release_id": release_id, "documents": [{"section_id": "node_a"}]}
    provenance = {"release_id": release_id, "records": []}
    source_index = {"release_id": release_id, "sources": []}
    source_documents = {"documents": {}}
    manifest = {
        "release_id": release_id,
        "identities": {
            "engine_commit_sha": subject.SEMANTIC_R3_ENGINE_SHA,
            "repair_parent_sha": subject.SEMANTIC_R3_PARENT_SHA,
            "repaired_source_graph_canonical_sha256": "source-graph",
        },
    }
    payloads = {
        "graph": graph,
        "graph_v2": graph_v2,
        "lexical_index": lexical,
        "semantic_inputs": semantic,
        "document_source_index": source_index,
        "provenance": provenance,
        "source_documents": source_documents,
    }
    return ProductionAnswerBundle(
        manifest=manifest,
        graph=graph,
        graph_v2=graph_v2,
        lexical_index=lexical,
        provenance=provenance,
        manifest_sha256=_pretty_sha(manifest),
        artifact_sha256={kind: _pretty_sha(value) for kind, value in payloads.items()},
        artifact_keys={},
        loaded_at="test",
        source_documents=source_documents,
        document_source_index=source_index,
        semantic_inputs=semantic,
    )


def _bind_fixture_authority(monkeypatch, bundle: ProductionAnswerBundle) -> None:
    payloads = {
        "graph": bundle.graph,
        "graph_v2": bundle.graph_v2,
        "lexical_index": bundle.lexical_index,
        "semantic_inputs": bundle.semantic_inputs or {},
        "document_source_index": bundle.document_source_index or {},
        "provenance": bundle.provenance,
        "source_documents": bundle.source_documents or {},
    }
    monkeypatch.setattr(subject, "SEMANTIC_R3_MANIFEST_SHA256", bundle.manifest_sha256)
    monkeypatch.setattr(subject, "SEMANTIC_R3_SOURCE_GRAPH_CANONICAL_SHA256", "source-graph")
    monkeypatch.setattr(subject, "SEMANTIC_R3_ARTIFACT_SHA256", dict(bundle.artifact_sha256))
    monkeypatch.setattr(
        subject,
        "SEMANTIC_R3_CANONICAL_SHA256",
        {kind: canonical_sha256(value) for kind, value in payloads.items()},
    )
    monkeypatch.setattr(
        subject,
        "SEMANTIC_R3_COUNTS",
        {
            "graph_nodes": 1,
            "graph_edges": 0,
            "lexical_documents": 1,
            "semantic_documents": 1,
            "sections": 0,
            "sources": 0,
        },
    )


def test_release_identity_reuses_non_circular_engine_scoped_rule() -> None:
    assert live_candidate._candidate_release_id(
        subject.SEMANTIC_R3_ENGINE_SHA
    ) == subject.SEMANTIC_R3_RELEASE_ID
    assert subject.SEMANTIC_R3_RELEASE_ID.endswith("45fd829578eb")
    assert "c948b759975c" not in subject.SEMANTIC_R3_RELEASE_ID


def test_artifact_and_runtime_graph_digests_are_distinct_authorities() -> None:
    assert (
        subject.SEMANTIC_R3_ARTIFACT_SHA256["graph_v2"]
        != subject.SEMANTIC_R3_CANONICAL_SHA256["graph_v2"]
    )


def test_validator_accepts_consistent_bundle_and_fails_closed_on_each_digest_layer(
    monkeypatch,
) -> None:
    bundle = _fixture_bundle()
    _bind_fixture_authority(monkeypatch, bundle)
    assert subject.semantic_r3_authority_mismatch(bundle) is None

    raw_tampered = replace(
        bundle,
        artifact_sha256={**bundle.artifact_sha256, "graph_v2": "0" * 64},
    )
    assert (
        subject.semantic_r3_authority_mismatch(raw_tampered)
        == "PA7_SEMANTIC_R3_CANDIDATE_ARTIFACT_DIGEST_MISMATCH"
    )

    runtime_tampered = replace(
        bundle,
        graph_v2={**bundle.graph_v2, "edges": [{"edge_id": "tampered"}]},
    )
    assert (
        subject.semantic_r3_authority_mismatch(runtime_tampered)
        == "PA7_SEMANTIC_R3_CANDIDATE_RUNTIME_ARTIFACT_MISMATCH"
    )


def test_semantic_contract_uses_candidate_authority_validator(monkeypatch) -> None:
    bundle = _fixture_bundle()
    monkeypatch.setattr(contract, "semantic_r3_authority_mismatch", lambda value: None)
    contract._assert_canonical_answer_bundle(bundle)
