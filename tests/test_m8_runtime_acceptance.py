from __future__ import annotations

from copy import deepcopy
from runpy import run_path

import pytest

module = run_path("scripts/m8_runtime_acceptance.py")
verify_outputs = module["verify_outputs"]

RELEASE_ID = "20260707T111500Z-abcdef123456"
MANIFEST = "a" * 64


def _payload(*, concept_id: str, x_kos_id: str, citation: str) -> dict:
    return {
        "status": "answered",
        "release": {
            "release_id": RELEASE_ID,
            "manifest_sha256": MANIFEST,
        },
        "results": [
            {
                "concept_id": concept_id,
                "x_kos_id": x_kos_id,
                "citations": [{"uri": citation}],
            }
        ],
        "retrieval": {
            "raw_fallback_used": False,
            "acl_filtered_count": 0,
        },
    }


def _valid_outputs() -> dict:
    return {
        "channel": "candidate-source-" + "b" * 40,
        "new_query": _payload(
            concept_id="concepts/agent-execution-paths",
            x_kos_id="ko_7FHJFQQ11PKPEWC4W25CCBCGZM",
            citation=(
                "https://www.danielcanfly.com/en/blog/"
                "the-atlas-of-agent-design-patterns-part-2/"
            ),
        ),
        "regression_query": _payload(
            concept_id="concepts/six-dimensional-map-of-llm-agent-architectures",
            x_kos_id="ko_HW0QBJBSFFJ9SWVXJTDHVV604T",
            citation=(
                "https://www.danielcanfly.com/en/blog/"
                "the-atlas-of-agent-design-patterns-part-1/"
            ),
        ),
        "boundary_query": {
            "status": "not_found",
            "release": {
                "release_id": RELEASE_ID,
                "manifest_sha256": MANIFEST,
            },
            "results": [],
            "retrieval": {
                "raw_fallback_used": False,
                "acl_filtered_count": 1,
            },
        },
    }


def test_m8_runtime_acceptance_passes() -> None:
    summary = verify_outputs(**_valid_outputs())
    assert summary["status"] == "passed"
    assert summary["release_id"] == RELEASE_ID
    assert summary["manifest_sha256"] == MANIFEST
    assert summary["production_mutated"] is False


def test_m8_runtime_acceptance_rejects_release_drift() -> None:
    outputs = _valid_outputs()
    outputs["regression_query"]["release"]["release_id"] = (
        "20260707T111501Z-abcdef123456"
    )
    with pytest.raises(SystemExit, match="release identity mismatch"):
        verify_outputs(**outputs)


def test_m8_runtime_acceptance_rejects_acl_or_fallback() -> None:
    outputs = _valid_outputs()
    outputs["boundary_query"]["status"] = "answered"
    with pytest.raises(SystemExit, match="boundary_query status"):
        verify_outputs(**outputs)

    outputs = deepcopy(_valid_outputs())
    outputs["new_query"]["retrieval"]["raw_fallback_used"] = True
    with pytest.raises(SystemExit, match="used raw fallback"):
        verify_outputs(**outputs)
