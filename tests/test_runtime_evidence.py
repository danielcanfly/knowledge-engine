from __future__ import annotations

import pytest
from scripts.validate_runtime_evidence import validate_runtime_evidence

from knowledge_engine.errors import IntegrityError

RELEASE_ID = "20260703T030000Z-123456789abc"


def _health() -> dict:
    return {
        "status": "healthy",
        "channel": "production",
        "release_id": RELEASE_ID,
    }


def _internal() -> dict:
    return {
        "status": "answered",
        "release": {"release_id": RELEASE_ID},
        "results": [
            {
                "concept_id": "concepts/candidate-delivery-controls",
                "citations": [{"source_id": "source_m4"}],
            }
        ],
    }


def _public() -> dict:
    return {
        "status": "not_found",
        "release": {"release_id": RELEASE_ID},
        "results": [],
        "retrieval": {
            "acl_filtered_count": 1,
            "raw_fallback_used": False,
        },
    }


def test_runtime_evidence_passes() -> None:
    result = validate_runtime_evidence(
        health=_health(),
        internal=_internal(),
        public=_public(),
        expected_release_id=RELEASE_ID,
    )
    assert result["status"] == "passed"
    assert result["internal_citation_count"] == 1
    assert result["public_acl_filtered_count"] == 1


def test_runtime_evidence_rejects_wrong_release() -> None:
    health = _health()
    health["release_id"] = "wrong"
    with pytest.raises(IntegrityError, match="health release_id mismatch"):
        validate_runtime_evidence(
            health=health,
            internal=_internal(),
            public=_public(),
            expected_release_id=RELEASE_ID,
        )


def test_runtime_evidence_requires_answer_and_citation() -> None:
    internal = _internal()
    internal["results"][0]["citations"] = []
    with pytest.raises(IntegrityError, match="no citations"):
        validate_runtime_evidence(
            health=_health(),
            internal=internal,
            public=_public(),
            expected_release_id=RELEASE_ID,
        )


def test_runtime_evidence_requires_public_denial() -> None:
    public = _public()
    public["status"] = "answered"
    with pytest.raises(IntegrityError, match="unexpectedly answered"):
        validate_runtime_evidence(
            health=_health(),
            internal=_internal(),
            public=public,
            expected_release_id=RELEASE_ID,
        )


def test_runtime_evidence_rejects_public_results() -> None:
    public = _public()
    public["results"] = [{"title": "unexpected"}]
    with pytest.raises(IntegrityError, match="exposed restricted"):
        validate_runtime_evidence(
            health=_health(),
            internal=_internal(),
            public=public,
            expected_release_id=RELEASE_ID,
        )


def test_runtime_evidence_rejects_raw_fallback() -> None:
    public = _public()
    public["retrieval"]["raw_fallback_used"] = True
    with pytest.raises(IntegrityError, match="raw fallback"):
        validate_runtime_evidence(
            health=_health(),
            internal=_internal(),
            public=public,
            expected_release_id=RELEASE_ID,
        )
