from __future__ import annotations

import copy

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m23_7_r1_semantic_alignment import (
    BLOCKERS,
    SAMPLE_CAP,
    build_alignment_report,
    canonical_alignment_report,
    canonical_fixture_samples,
    canonical_manifest,
    compile_probe_plan,
    validate_manifest,
)


def test_manifest_has_eight_balanced_positive_slots() -> None:
    manifest = validate_manifest(canonical_manifest())
    assert len(manifest["slots"]) == SAMPLE_CAP
    assert [slot["offline_case_id"] for slot in manifest["slots"]] == [
        "m23q-01",
        "m23q-02",
        "m23q-03",
        "m23q-04",
        "m23q-07",
        "m23q-08",
        "m23q-09",
        "m23q-10",
    ]
    counts = {
        name: sum(1 for slot in manifest["slots"] if slot["query_class"] == name)
        for name in manifest["templates"]
    }
    assert counts == {
        "direct-fact": 2,
        "terminology": 2,
        "cross-section": 2,
        "provenance": 2,
    }
    assert all(slot["acl_allowed"] is True for slot in manifest["slots"])
    assert all(slot["no_answer_expected"] is False for slot in manifest["slots"])


def test_compiler_replaces_raw_section_id_with_semantic_query() -> None:
    probes = compile_probe_plan(canonical_manifest(), canonical_fixture_samples())
    assert len(probes) == SAMPLE_CAP
    for probe in probes:
        assert probe["query_text"] != probe["target_section_id"]
        assert probe["semantic_token_count"] >= 3
        assert probe["expected_relevant_ids"] == [probe["target_section_id"]]
        assert len(probe["query_digest"]) == 64


def test_compiler_uses_full_path_chunk_discriminators() -> None:
    samples = canonical_fixture_samples()
    samples[0]["payload"] = {
        **samples[0]["payload"],
        "concept_id": "concept-001",
        "article_id": "article-001",
        "document_id": "document-001",
        "source_path": "pilot/harness-theory-part-01-en/chunk-012.md",
        "section_id": "pilot/harness-theory-part-01-en/chunk-012",
    }

    probe = compile_probe_plan(canonical_manifest(), samples)[0]

    assert probe["query_text"] != probe["target_section_id"]
    assert "harness theory part01 chunk012" in probe["query_text"]


def test_compiler_is_deterministic_under_input_reordering() -> None:
    samples = canonical_fixture_samples()
    forward = compile_probe_plan(canonical_manifest(), samples)
    reverse = compile_probe_plan(canonical_manifest(), list(reversed(samples)))
    assert forward == reverse


def test_report_redacts_compiled_query_text() -> None:
    report = canonical_alignment_report()
    assert report["status"] == "pass_ready_for_r3_binding"
    assert all("query_text" not in mapping for mapping in report["mappings"])
    assert all(mapping["raw_query_persisted"] is False for mapping in report["mappings"])
    assert all(mapping["raw_answer_persisted"] is False for mapping in report["mappings"])


def test_non_public_sample_fails_closed() -> None:
    samples = canonical_fixture_samples()
    samples[0]["payload"]["audience"] = "private"
    with pytest.raises(IntegrityError, match="sample identity drifted: audience"):
        compile_probe_plan(canonical_manifest(), samples)


def test_release_identity_drift_fails_closed() -> None:
    samples = canonical_fixture_samples()
    samples[0]["payload"]["release_id"] = "wrong-release"
    with pytest.raises(IntegrityError, match="sample identity drifted: release_id"):
        compile_probe_plan(canonical_manifest(), samples)


def test_exactly_eight_samples_are_required() -> None:
    with pytest.raises(IntegrityError, match="exactly eight samples"):
        compile_probe_plan(canonical_manifest(), canonical_fixture_samples()[:-1])


def test_duplicate_target_section_fails_closed() -> None:
    samples = canonical_fixture_samples()
    samples[1]["payload"]["section_id"] = samples[0]["payload"]["section_id"]
    with pytest.raises(IntegrityError, match="target sections are duplicated"):
        compile_probe_plan(canonical_manifest(), samples)


def test_weak_identifier_only_topic_fails_closed() -> None:
    samples = canonical_fixture_samples()
    payload = samples[0]["payload"]
    payload["concept_id"] = "concept-001"
    payload["section_id"] = "section-001"
    payload["article_id"] = "article-001"
    payload["document_id"] = "document-001"
    payload["source_path"] = "docs/section-001.md"
    with pytest.raises(IntegrityError, match="not contain enough semantic tokens"):
        compile_probe_plan(canonical_manifest(), samples)


def test_manifest_tamper_fails_closed() -> None:
    manifest = canonical_manifest()
    manifest["slots"][0]["offline_case_id"] = "m23q-05"
    with pytest.raises(IntegrityError, match="manifest digest mismatch"):
        validate_manifest(manifest)


def test_expected_relevance_tamper_fails_closed() -> None:
    probes = compile_probe_plan(canonical_manifest(), canonical_fixture_samples())
    probes[0]["expected_relevant_ids"] = ["wrong-section"]
    with pytest.raises(IntegrityError, match="expected relevance set drifted"):
        build_alignment_report(canonical_manifest(), probes)


def test_query_digest_tamper_fails_closed() -> None:
    probes = compile_probe_plan(canonical_manifest(), canonical_fixture_samples())
    probes[0]["query_digest"] = "0" * 64
    with pytest.raises(IntegrityError, match="query digest drifted"):
        build_alignment_report(canonical_manifest(), probes)


def test_r1_does_not_clear_blockers_or_grant_promotion() -> None:
    report = canonical_alignment_report()
    assert tuple(report["carry_forward_blockers"]) == BLOCKERS
    assert report["exit"]["r1_complete"] is True
    assert report["exit"]["retrieval_quality_blocker_cleared"] is False
    assert report["exit"]["latency_blocker_cleared"] is False
    assert report["exit"]["promotion_eligibility_granted"] is False
    assert report["exit"]["live_target_binding_pending_r3"] is True


def test_authority_and_external_call_boundaries_remain_closed() -> None:
    manifest = canonical_manifest()
    report = canonical_alignment_report()
    assert manifest["entry"]["source_pr_19"] == {
        "state": "open",
        "draft": True,
        "merged": False,
        "head_sha": "deb3ad1e631c2149183d10561fbceb0a1848a989",
    }
    assert all(value is False for value in manifest["protected_mutations"].values())
    assert report["authority"] == {
        "production_retrieval": "lexical",
        "candidate_mode_enabled": False,
        "production_authority": False,
        "protected_mutations_dispatched": False,
    }
    assert report["external_calls"] == {
        "network": 0,
        "provider": 0,
        "qdrant_read": 0,
        "qdrant_write": 0,
    }


def test_report_digest_is_stable() -> None:
    first = canonical_alignment_report()
    second = canonical_alignment_report()
    assert first == second
    assert first["manifest_sha256"] == (
        "ebff335d572461f4438ed06c4cc35288b0d0def8bbfc2b51e80bb262db12c576"
    )
    assert first["report_sha256"] == (
        "22a9e361243758adc25c7572d1314706c7fa252a7190a3ceee91f1025d47ed19"
    )


def test_recomputed_manifest_tamper_still_fails_canonical_identity() -> None:
    manifest = copy.deepcopy(canonical_manifest())
    manifest["probe_contract"]["user_queries_allowed"] = True
    unsigned = dict(manifest)
    unsigned.pop("manifest_sha256")
    from knowledge_engine.m23_7_r1_semantic_alignment import canonical_sha256

    manifest["manifest_sha256"] = canonical_sha256(unsigned)
    with pytest.raises(IntegrityError, match="manifest drifted"):
        validate_manifest(manifest)
