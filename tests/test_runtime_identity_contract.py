from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.release_checks import validate_runtime_evidence

RELEASE_ID = "20260703T074814Z-1b18538bfbac"
MANIFEST_SHA256 = "e" * 64


def _health(*, include_manifest: bool = False) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": "healthy",
        "channel": "production",
        "release_id": RELEASE_ID,
    }
    if include_manifest:
        payload["manifest_sha256"] = MANIFEST_SHA256
    return payload


def _internal() -> dict[str, object]:
    return {
        "status": "answered",
        "release": {
            "release_id": RELEASE_ID,
            "manifest_sha256": MANIFEST_SHA256,
        },
        "results": [
            {
                "citations": [
                    {
                        "source_id": "source-1",
                        "uri": "https://example.com/source-1",
                        "retrieved_at": "2026-07-03T00:00:00Z",
                    }
                ]
            }
        ],
        "retrieval": {
            "acl_filtered_count": 0,
            "raw_fallback_used": False,
        },
    }


def _public() -> dict[str, object]:
    return {
        "status": "not_found",
        "release": {
            "release_id": RELEASE_ID,
            "manifest_sha256": MANIFEST_SHA256,
        },
        "results": [],
        "retrieval": {
            "acl_filtered_count": 1,
            "raw_fallback_used": False,
        },
    }


def test_legacy_health_without_manifest_uses_query_identity() -> None:
    result = validate_runtime_evidence(
        health=_health(),
        internal=_internal(),
        public=_public(),
        expected_release_id=RELEASE_ID,
        expected_manifest_sha256=MANIFEST_SHA256,
    )

    assert result["status"] == "passed"
    assert result["release_id"] == RELEASE_ID
    assert result["manifest_sha256"] == MANIFEST_SHA256


def test_new_health_manifest_is_checked_when_present() -> None:
    health = _health(include_manifest=True)
    health["manifest_sha256"] = "f" * 64

    with pytest.raises(IntegrityError, match="health manifest_sha256 mismatch"):
        validate_runtime_evidence(
            health=health,
            internal=_internal(),
            public=_public(),
            expected_release_id=RELEASE_ID,
            expected_manifest_sha256=MANIFEST_SHA256,
        )


def test_internal_query_manifest_mismatch_is_rejected() -> None:
    internal = deepcopy(_internal())
    release = internal["release"]
    assert isinstance(release, dict)
    release["manifest_sha256"] = "f" * 64

    with pytest.raises(IntegrityError, match="internal query returned the wrong manifest"):
        validate_runtime_evidence(
            health=_health(),
            internal=internal,
            public=_public(),
            expected_release_id=RELEASE_ID,
            expected_manifest_sha256=MANIFEST_SHA256,
        )


def test_public_query_manifest_mismatch_is_rejected() -> None:
    public = deepcopy(_public())
    release = public["release"]
    assert isinstance(release, dict)
    release["manifest_sha256"] = "f" * 64

    with pytest.raises(IntegrityError, match="public query returned the wrong manifest"):
        validate_runtime_evidence(
            health=_health(),
            internal=_internal(),
            public=public,
            expected_release_id=RELEASE_ID,
            expected_manifest_sha256=MANIFEST_SHA256,
        )


def test_oracle_scripts_verify_manifest_at_query_layer() -> None:
    smoke = Path("scripts/oracle_refresh_smoke.sh").read_text(encoding="utf-8")
    restart = Path("scripts/oracle_restart_verify.sh").read_text(encoding="utf-8")

    assert "--expected-manifest-sha256" in smoke
    assert '"manifest_sha256": sys.argv[3]' not in smoke
    assert "oracle-identity-query.json" in restart
    assert "runtime identity probe returned the wrong manifest" in restart
