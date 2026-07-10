from __future__ import annotations

import copy
import json
from pathlib import Path

from knowledge_engine.m17_architecture_canon import (
    REQUIRED_MODELS,
    REQUIRED_PLANES,
    validate_architecture_registry,
    verify_report_digest,
)


def _write_fixture(root: Path) -> Path:
    (root / "docs/architecture/m17").mkdir(parents=True)
    (root / "src").mkdir()
    (root / "docs/architecture/README.md").write_text(
        "# Canon\n\n## Architecture document ownership\n",
        encoding="utf-8",
    )
    (root / "docs/architecture/m17/system-map.md").write_text(
        "# System map\n",
        encoding="utf-8",
    )
    implementation = "\n".join(
        [
            "CONTROL_ANCHOR",
            "BUILD_ANCHOR",
            "RUNTIME_ANCHOR",
            "FEEDBACK_ANCHOR",
            *[f"MODEL_{name.upper()}" for name in sorted(REQUIRED_MODELS)],
        ]
    )
    (root / "src/implementation.py").write_text(implementation, encoding="utf-8")

    claims = []
    for plane in sorted(REQUIRED_PLANES):
        claims.append(
            {
                "claim_id": f"plane.{plane}",
                "plane": plane,
                "model": "lifecycle_model",
                "statement": f"The {plane} plane has a stable implementation reference.",
                "reference": {
                    "kind": "code",
                    "path": "src/implementation.py",
                    "anchor": f"{plane.upper()}_ANCHOR",
                },
                "owner": plane,
            }
        )
    for model in sorted(REQUIRED_MODELS - {"lifecycle_model"}):
        claims.append(
            {
                "claim_id": f"model.{model}",
                "plane": "control",
                "model": model,
                "statement": f"The {model} is documented by a stable implementation anchor.",
                "reference": {
                    "kind": "contract",
                    "path": "src/implementation.py",
                    "anchor": f"MODEL_{model.upper()}",
                },
                "owner": "architecture",
            }
        )

    registry = {
        "schema_version": "knowledge-engine-architecture-canon/v1",
        "canonical_entry": "docs/architecture/README.md",
        "owned_documents": [
            "docs/architecture/README.md",
            "docs/architecture/m17/system-map.md",
            "docs/architecture/m17/architecture-claims.json",
        ],
        "required_planes": sorted(REQUIRED_PLANES),
        "required_models": sorted(REQUIRED_MODELS),
        "claims": claims,
    }
    path = root / "docs/architecture/m17/architecture-claims.json"
    path.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _save(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_valid_registry_passes_and_is_deterministic(tmp_path: Path) -> None:
    registry = _write_fixture(tmp_path)
    first = validate_architecture_registry(root=tmp_path, registry_path=registry)
    second = validate_architecture_registry(root=tmp_path, registry_path=registry)

    assert first == second
    assert first["status"] == "passed"
    assert first["covered_planes"] == sorted(REQUIRED_PLANES)
    assert first["covered_models"] == sorted(REQUIRED_MODELS)
    assert verify_report_digest(first)


def test_missing_anchor_fails_closed(tmp_path: Path) -> None:
    registry = _write_fixture(tmp_path)
    payload = _load(registry)
    payload["claims"][0]["reference"]["anchor"] = "DOES_NOT_EXIST"
    _save(registry, payload)

    report = validate_architecture_registry(root=tmp_path, registry_path=registry)

    assert report["status"] == "failed"
    assert "missing_reference_anchor" in {item["code"] for item in report["issues"]}
    assert verify_report_digest(report)


def test_missing_plane_and_model_coverage_are_reported(tmp_path: Path) -> None:
    registry = _write_fixture(tmp_path)
    payload = _load(registry)
    payload["claims"] = [
        claim
        for claim in payload["claims"]
        if claim["plane"] != "feedback" and claim["model"] != "trust_boundaries"
    ]
    _save(registry, payload)

    report = validate_architecture_registry(root=tmp_path, registry_path=registry)
    codes = {item["code"] for item in report["issues"]}

    assert report["status"] == "failed"
    assert "missing_plane_coverage" in codes
    assert "missing_model_coverage" in codes


def test_stale_dynamic_identity_in_owned_document_is_rejected(tmp_path: Path) -> None:
    registry = _write_fixture(tmp_path)
    entry = tmp_path / "docs/architecture/README.md"
    entry.write_text(entry.read_text() + "\n" + ("a" * 40) + "\n", encoding="utf-8")

    report = validate_architecture_registry(root=tmp_path, registry_path=registry)

    assert report["status"] == "failed"
    assert "stale_dynamic_identity" in {item["code"] for item in report["issues"]}


def test_path_escape_is_rejected(tmp_path: Path) -> None:
    registry = _write_fixture(tmp_path)
    payload = _load(registry)
    payload["claims"][0]["reference"]["path"] = "../outside.py"
    _save(registry, payload)

    report = validate_architecture_registry(root=tmp_path, registry_path=registry)

    assert report["status"] == "failed"
    assert "unsafe_reference_path" in {item["code"] for item in report["issues"]}


def test_report_tampering_is_detected(tmp_path: Path) -> None:
    registry = _write_fixture(tmp_path)
    report = validate_architecture_registry(root=tmp_path, registry_path=registry)
    tampered = copy.deepcopy(report)
    tampered["counts"]["claims"] += 1

    assert verify_report_digest(report)
    assert not verify_report_digest(tampered)
