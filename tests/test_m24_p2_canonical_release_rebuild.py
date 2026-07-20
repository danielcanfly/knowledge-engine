from __future__ import annotations

import json
from pathlib import Path

from scripts.m23_7_r3_8_remote_operator import canonical_sha256

REBUILD_PATH = Path("pilot/m24/m24-p2-canonical-release-rebuild.json")


def _rebuild() -> dict:
    return json.loads(REBUILD_PATH.read_text(encoding="utf-8"))


def test_m24_p2_rebuild_is_digest_bound() -> None:
    rebuild = _rebuild()
    unsigned = dict(rebuild)
    digest = unsigned.pop("rebuild_sha256")

    assert digest != "TO_BE_FILLED"
    assert canonical_sha256(unsigned) == digest


def test_m24_p2_rebuild_binds_exact_source_and_release_identity() -> None:
    rebuild = _rebuild()

    assert rebuild["issue"] == 989
    assert rebuild["status"] == "canonical_release_rebuild_complete"
    assert rebuild["inputs"] == {
        "source_repository": "danielcanfly/knowledge-source",
        "adopted_source_sha": "acf78596ace8a7366688ccef72b507204d09d9f9",
        "engine_builder_sha": "22041bfecd07c9e4b75146ab4d0b83e417e914e8",
        "foundation_sha": "e5ef644053d34e89c70d2ceb37521e1c59234832",
        "release_time": "2026-07-20T16:00:00Z",
    }
    assert rebuild["release"] == {
        "release_id": "20260720T160000Z-46137c97263e",
        "manifest_key": "releases/20260720T160000Z-46137c97263e/manifest.json",
        "manifest_sha256": (
            "ef5ee828069731e3e7106e1b12fb82e3a578c377930568410bc78421d1600877"
        ),
        "source_snapshot_sha256": (
            "9f2fa3df237616e97b6e3bece5f4dfc96a72342ccba2452ee8fe375286d6a451"
        ),
        "okf_content_sha256": (
            "46137c97263effa21aef5392b41cbd3948ac58b0147342310eed84ec41fb354a"
        ),
        "release_ready": True,
    }


def test_m24_p2_rebuild_preserves_relations_and_lexical_serving_boundary() -> None:
    rebuild = _rebuild()

    assert rebuild["counts"] == {
        "concepts": 20,
        "sections": 92,
        "provenance_records": 20,
        "source_snapshots": 7,
        "graph_v2_nodes": 20,
        "graph_v2_edges": 28,
        "graph_v2_authored_edges": 15,
        "graph_v2_generated_inverse_edges": 13,
    }
    assert rebuild["graph_v2"]["relation_types"] == [
        "complements",
        "has_part",
        "implemented_by",
        "implements",
        "part_of",
        "related_to",
        "required_by",
        "requires",
        "supported_by",
        "supports",
    ]
    assert rebuild["artifact_digests"]["lexical_index"]["required"] is True
    assert rebuild["artifact_digests"]["graph_v2"]["sha256"] == (
        "6737dfb3fa9cd4d992c26dce562329c95e06066cd475f97f2fdffdbab8f25abe"
    )
    assert rebuild["authority_boundary"] == {
        "production_retrieval": "lexical",
        "semantic_promotion_enabled": False,
        "semantic_answer_serving_enabled": False,
        "hybrid_retrieval_enabled": False,
        "production_pointer_mutation_authorized": False,
        "r2_mutation_authorized": False,
        "qdrant_mutation_authorized": False,
        "credential_rotation_authorized": False,
        "production_traffic_change_authorized": False,
    }
    assert rebuild["rebuild_command"]["production_channel_used"] is False
    assert rebuild["channel_pointer"]["non_production"] is True
