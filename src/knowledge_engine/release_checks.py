from __future__ import annotations

from typing import Any

from .errors import IntegrityError


def validate_runtime_evidence(
    *,
    health: dict[str, Any],
    internal: dict[str, Any],
    public: dict[str, Any],
    expected_release_id: str,
    expected_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    expected_health = {
        "status": "healthy",
        "channel": "production",
        "release_id": expected_release_id,
    }
    if expected_manifest_sha256 is not None:
        expected_health["manifest_sha256"] = expected_manifest_sha256
    for key, expected in expected_health.items():
        if health.get(key) != expected:
            raise IntegrityError(
                f"health {key} mismatch: expected {expected!r}, got {health.get(key)!r}"
            )

    if internal.get("status") != "answered":
        raise IntegrityError("internal query did not answer")
    internal_release = internal.get("release")
    if not isinstance(internal_release, dict):
        raise IntegrityError("internal query omitted release identity")
    if internal_release.get("release_id") != expected_release_id:
        raise IntegrityError("internal query returned the wrong release")
    if (
        expected_manifest_sha256 is not None
        and internal_release.get("manifest_sha256") != expected_manifest_sha256
    ):
        raise IntegrityError("internal query returned the wrong manifest")
    internal_results = internal.get("results")
    if not isinstance(internal_results, list) or not internal_results:
        raise IntegrityError("internal query returned no results")
    citation_count = 0
    for result in internal_results:
        if isinstance(result, dict) and isinstance(result.get("citations"), list):
            citation_count += len(result["citations"])
    if citation_count < 1:
        raise IntegrityError("internal query returned no citations")

    if public.get("status") != "not_found":
        raise IntegrityError("public query unexpectedly answered")
    public_release = public.get("release")
    if not isinstance(public_release, dict):
        raise IntegrityError("public query omitted release identity")
    if public_release.get("release_id") != expected_release_id:
        raise IntegrityError("public query returned the wrong release")
    if (
        expected_manifest_sha256 is not None
        and public_release.get("manifest_sha256") != expected_manifest_sha256
    ):
        raise IntegrityError("public query returned the wrong manifest")
    if public.get("results") != []:
        raise IntegrityError("public query exposed restricted results")
    retrieval = public.get("retrieval")
    if not isinstance(retrieval, dict):
        raise IntegrityError("public query omitted retrieval evidence")
    acl_filtered_count = int(retrieval.get("acl_filtered_count", 0))
    if acl_filtered_count < 1:
        raise IntegrityError("public query did not prove ACL filtering")
    if retrieval.get("raw_fallback_used") is True:
        raise IntegrityError("public query used raw fallback")

    result = {
        "schema_version": "1.0",
        "status": "passed",
        "release_id": expected_release_id,
        "internal_result_count": len(internal_results),
        "internal_citation_count": citation_count,
        "public_result_count": 0,
        "public_acl_filtered_count": acl_filtered_count,
        "raw_fallback_used": False,
    }
    if expected_manifest_sha256 is not None:
        result["manifest_sha256"] = expected_manifest_sha256
    return result
