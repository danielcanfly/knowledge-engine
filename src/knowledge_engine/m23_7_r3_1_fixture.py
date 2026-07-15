from __future__ import annotations

from typing import Any

from .m23_7_r1_semantic_alignment import canonical_manifest, compile_probe_plan

RELEASE = "m23pilot-a07eb79e381ca7e635cc9139"
MANIFEST = "a07eb79e381ca7e635cc91397c322fd6ff57a62b5571a54866d26aefb734ebe9"
TARGETS = (
    "pilot/harness-theory-part-01-en/chunk-012",
    "pilot/harness-theory-part-02-en/chunk-008",
    "pilot/harness-theory-part-03-en/chunk-017",
    "pilot/harness-theory-part-03-zh/chunk-002",
    "pilot/harness-theory-part-03-en/chunk-016",
    "pilot/harness-theory-part-01-en/chunk-000",
    "pilot/harness-theory-part-01-en/chunk-011",
    "pilot/harness-theory-part-02-zh/chunk-012",
)
TOP3 = (
    (
        "pilot/harness-theory-part-01-en/chunk-014",
        "pilot/harness-theory-part-01-en/chunk-000",
        "pilot/harness-theory-part-01-zh/chunk-013",
    ),
    (
        "pilot/harness-theory-part-01-en/chunk-014",
        "pilot/harness-theory-part-01-en/chunk-013",
        "pilot/harness-theory-part-01-zh/chunk-013",
    ),
    (
        "pilot/harness-theory-part-01-en/chunk-002",
        "pilot/harness-theory-part-01-en/chunk-013",
        "pilot/harness-theory-part-01-en/chunk-004",
    ),
    (
        "pilot/harness-theory-part-01-en/chunk-014",
        "pilot/harness-theory-part-01-zh/chunk-013",
        "pilot/harness-theory-part-01-en/chunk-013",
    ),
    (
        "pilot/harness-theory-part-01-en/chunk-014",
        "pilot/harness-theory-part-01-en/chunk-000",
        "pilot/harness-theory-part-01-zh/chunk-013",
    ),
    (
        "pilot/harness-theory-part-01-en/chunk-014",
        "pilot/harness-theory-part-01-en/chunk-013",
        "pilot/harness-theory-part-01-zh/chunk-013",
    ),
    (
        "pilot/harness-theory-part-01-en/chunk-002",
        "pilot/harness-theory-part-01-en/chunk-013",
        "pilot/harness-theory-part-01-en/chunk-004",
    ),
    (
        "pilot/harness-theory-part-01-en/chunk-014",
        "pilot/harness-theory-part-01-zh/chunk-013",
        "pilot/harness-theory-part-01-en/chunk-013",
    ),
)


def canonical_fixture() -> dict[str, list[dict[str, Any]]]:
    samples = []
    for index, section_id in enumerate(TARGETS, start=1):
        parent = section_id.rsplit("/", 1)[0].rsplit("/", 1)[-1]
        samples.append(
            {
                "point_id": f"00000000-0000-0000-0000-{index:012d}",
                "payload": {
                    "concept_id": "harness-theory",
                    "section_id": section_id,
                    "article_id": parent,
                    "document_id": parent,
                    "source_path": f"pilot/{parent}.md",
                    "audience": "public",
                    "source_membership": "evaluation-only-pending-proposal",
                    "release_id": RELEASE,
                    "release_manifest_sha256": MANIFEST,
                    "canonical_knowledge": False,
                    "candidate_release_eligible": False,
                    "production_authority": False,
                },
            }
        )
    probes = compile_probe_plan(canonical_manifest(), samples)
    cases = [
        {
            "probe_id": probe["probe_id"],
            "query_digest": probe["query_digest"],
            "target_section_id": target,
            "top3_ranked_section_ids": list(top3),
        }
        for probe, target, top3 in zip(probes, TARGETS, TOP3, strict=True)
    ]
    return {"samples": samples, "cases": cases}
