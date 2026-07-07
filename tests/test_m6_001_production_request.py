from __future__ import annotations

from pathlib import Path

from knowledge_engine.promotion_request import load_promotion_request_spec

REQUEST_PATH = Path("production_promotions/m6-001-llm-wiki-foundation.json")


def test_m6_001_production_request_is_valid_and_identity_bound() -> None:
    spec = load_promotion_request_spec(
        request_path=REQUEST_PATH,
        control_plane_sha="0" * 40,
    )

    assert spec.raw.get("control_plane_sha") is None
    assert spec.request.operation_id == "m6-001-llm-wiki-foundation-001"
    assert (
        spec.request.candidate_channel
        == "candidate-source-6a35f9f35e4c6c599a266710344f760c399d914d"
    )
    assert spec.request.expected_release_id == "20260706T061437Z-bc48bf4810c0"
    assert (
        spec.request.expected_manifest_sha256
        == "8eefb904d1eea0f6ca87b074c60edfe94c725bd76adb77961919b8d2bd4c8f96"
    )
    assert (
        spec.request.expected_previous_release_id
        == "20260706T024200Z-19b86982de27"
    )
    assert (
        spec.request.expected_previous_manifest_sha256
        == "8697f5ab6258d8545328fd32cea60b09c2c80aef4599611b0571a0553ea24a7e"
    )
    assert spec.expected_public_status == "answered"
    assert (
        spec.expected_citation_url
        == "https://www.danielcanfly.com/en/blog/"
        "the-atlas-of-agent-design-patterns-part-1/"
    )
    assert spec.post_promote_acl_query == "delivery controls"
    assert spec.expected_acl_status == "not_found"
