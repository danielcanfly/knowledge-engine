from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.promotion_request import (
    SCHEMA_VERSION,
    load_promotion_request_spec,
    validate_request_path,
    write_github_env,
    write_request_evidence,
)

CONTROL_PLANE_SHA = "f" * 40


def _valid_payload() -> dict[str, str]:
    return {
        "schema_version": SCHEMA_VERSION,
        "operation_id": "m5-agent-architecture-6d-6254725c-001",
        "candidate_channel": "candidate-source-" + "a" * 40,
        "release_id": "20260706T024200Z-19b86982de27",
        "manifest_sha256": "1" * 64,
        "source_repository": "danielcanfly/knowledge-source",
        "source_sha": "a" * 40,
        "builder_sha": "b" * 40,
        "foundation_sha": "d" * 40,
        "expected_previous_release_id": "20260703T074814Z-1b18538bfbac",
        "expected_previous_manifest_sha256": "2" * 64,
        "reason": "Promote reviewed content",
        "actor": "danielcanfly",
        "post_promote_public_query": "six-dimensional map",
        "expected_public_status": "answered",
        "expected_citation_url": "https://www.danielcanfly.com/en/blog/example/",
        "post_promote_acl_query": "internal control phrase",
        "expected_acl_status": "not_found",
    }


def _write_spec(tmp_path: Path, payload: dict[str, str] | None = None) -> Path:
    path = tmp_path / "production_promotions" / "valid.json"
    path.parent.mkdir()
    path.write_text(
        json.dumps(payload or _valid_payload(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return Path("production_promotions/valid.json")


def test_valid_request_loads_normalizes_and_writes_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    request_path = _write_spec(tmp_path)

    spec = load_promotion_request_spec(
        request_path=request_path,
        control_plane_sha=CONTROL_PLANE_SHA,
    )

    assert spec.request.expected_builder_sha == "b" * 40
    assert spec.request.control_plane_sha == CONTROL_PLANE_SHA
    assert spec.normalized()["schema_version"] == SCHEMA_VERSION
    assert spec.normalized()["control_plane_sha"] == CONTROL_PLANE_SHA
    assert spec.normalized()["builder_sha"] != spec.normalized()["control_plane_sha"]

    env_path = tmp_path / "github.env"
    write_github_env(env_path, spec.env())
    env_text = env_path.read_text(encoding="utf-8")
    assert "BUILDER_SHA=" + "b" * 40 in env_text
    assert "CONTROL_PLANE_SHA" not in env_text

    result = write_request_evidence(spec=spec, evidence_dir=Path("evidence"))
    assert result["status"] == "valid"
    assert Path("evidence/request.json").is_file()
    assert Path("evidence/request.normalized.json").is_file()


@pytest.mark.parametrize(
    "bad_path",
    [
        "../production_promotions/valid.json",
        "/tmp/production_promotions/valid.json",
        "other/valid.json",
        "production_promotions/nested/valid.json",
        "production_promotions/valid.txt",
    ],
)
def test_rejects_unsafe_request_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bad_path: str,
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_spec(tmp_path)

    with pytest.raises(IntegrityError):
        validate_request_path(bad_path)


def test_rejects_missing_required_field(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    payload = _valid_payload()
    payload.pop("expected_citation_url")
    request_path = _write_spec(tmp_path, payload)

    with pytest.raises(IntegrityError, match="missing required fields"):
        load_promotion_request_spec(
            request_path=request_path,
            control_plane_sha=CONTROL_PLANE_SHA,
        )


def test_rejects_control_plane_sha_in_committed_spec(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    payload = _valid_payload()
    payload["control_plane_sha"] = "c" * 40
    request_path = _write_spec(tmp_path, payload)

    with pytest.raises(IntegrityError, match="workflow runtime"):
        load_promotion_request_spec(
            request_path=request_path,
            control_plane_sha=CONTROL_PLANE_SHA,
        )


def test_rejects_malformed_release_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    payload = _valid_payload()
    payload["release_id"] = "latest"
    request_path = _write_spec(tmp_path, payload)

    with pytest.raises(IntegrityError, match="immutable release ID"):
        load_promotion_request_spec(
            request_path=request_path,
            control_plane_sha=CONTROL_PLANE_SHA,
        )


def test_rejects_unallowlisted_source_repository(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    payload = _valid_payload()
    payload["source_repository"] = "danielcanfly/other-source"
    request_path = _write_spec(tmp_path, payload)

    with pytest.raises(IntegrityError, match="unexpected source repository"):
        load_promotion_request_spec(
            request_path=request_path,
            control_plane_sha=CONTROL_PLANE_SHA,
        )
