from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

MANIFEST_SCHEMA = "governed-source-review-manifest/v1"
PENDING_STATUS = "pending_human_review"


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _required_string(payload: dict[str, Any], key: str, label: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string: {key}")
    return value.strip()


def _parse_markdown(path: Path) -> tuple[dict[str, Any], str, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError("proposed concept must start with YAML frontmatter")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise ValueError("proposed concept frontmatter is not closed")
    metadata = yaml.safe_load(text[4:end])
    if not isinstance(metadata, dict):
        raise ValueError("proposed concept frontmatter must be an object")
    return metadata, text[end + 5 :], text


def _expect(value: Any, expected: Any, label: str) -> None:
    if value != expected:
        raise ValueError(f"{label} mismatch: expected {expected!r}, got {value!r}")


def _manifest_files(
    package_root: Path,
    manifest: dict[str, Any],
) -> dict[str, Path]:
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise ValueError("manifest files must be an object")
    expected_keys = {
        "concept",
        "provenance",
        "source_record",
        "review_decision",
        "checklist",
    }
    if set(files) != expected_keys:
        raise ValueError("manifest files must contain the five required package entries")

    resolved: dict[str, Path] = {}
    for key, value in files.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"manifest file entry must be a non-empty string: {key}")
        candidate = Path(value)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError(f"manifest file entry must stay inside the package: {value}")
        path = package_root / candidate
        if not path.is_file():
            raise ValueError(f"required review-package file is missing: {value}")
        resolved[key] = path
    return resolved


def validate_source_review_package(
    package_root: str | Path,
) -> dict[str, Any]:
    root = Path(package_root).resolve()
    manifest_path = root / "package-manifest.json"
    if not manifest_path.is_file():
        raise ValueError("review package is missing package-manifest.json")

    manifest = _load_json(manifest_path)
    _expect(manifest.get("schema_version"), MANIFEST_SCHEMA, "manifest schema")
    _expect(manifest.get("package_status"), PENDING_STATUS, "package status")
    batch_id = _required_string(manifest, "batch_id", "manifest")
    target_path = _required_string(manifest, "target_path", "manifest")
    concept_id = _required_string(manifest, "concept_id", "manifest")
    kos_id = _required_string(manifest, "proposed_x_kos_id", "manifest")
    audience = _required_string(manifest, "proposed_audience", "manifest")
    confidence = manifest.get("proposed_confidence")
    if not isinstance(confidence, int | float) or not 0 <= confidence <= 1:
        raise ValueError("manifest proposed_confidence must be between 0 and 1")

    origin = manifest.get("origin")
    if not isinstance(origin, dict):
        raise ValueError("manifest origin must be an object")
    origin_repository = _required_string(origin, "repository", "manifest origin")
    origin_commit = _required_string(origin, "commit", "manifest origin")
    origin_path = _required_string(origin, "path", "manifest origin")
    origin_blob = _required_string(origin, "blob_sha", "manifest origin")
    citation_url = _required_string(origin, "citation_url", "manifest origin")

    paths = _manifest_files(root, manifest)
    metadata, body, concept_text = _parse_markdown(paths["concept"])
    expected_metadata = {
        "review-package-schema": "governed-source-review-package/v1",
        "batch-id": batch_id,
        "review-status": PENDING_STATUS,
        "target-path": target_path,
        "proposed-x-kos-id": kos_id,
        "proposed-audience": audience,
        "proposed-confidence": confidence,
        "origin-repository": origin_repository,
        "origin-commit": origin_commit,
        "origin-path": origin_path,
        "origin-blob-sha": origin_blob,
        "citation-url": citation_url,
    }
    for field, expected in expected_metadata.items():
        _expect(metadata.get(field), expected, f"concept metadata {field}")

    concept_sha256 = hashlib.sha256(concept_text.encode("utf-8")).hexdigest()
    _expect(
        concept_sha256,
        _required_string(manifest, "expected_concept_sha256", "manifest"),
        "proposed concept SHA-256",
    )

    required_sections = manifest.get("required_sections")
    if not isinstance(required_sections, list) or not required_sections:
        raise ValueError("manifest required_sections must be a non-empty list")
    for section in required_sections:
        if not isinstance(section, str) or section not in body:
            raise ValueError(f"proposed concept is missing section: {section!r}")

    forbidden_fragments = manifest.get("forbidden_fragments")
    if not isinstance(forbidden_fragments, list):
        raise ValueError("manifest forbidden_fragments must be a list")
    for fragment in forbidden_fragments:
        if not isinstance(fragment, str):
            raise ValueError("forbidden fragments must be strings")
        if fragment in body:
            raise ValueError(f"proposed concept contains forbidden fragment: {fragment}")

    provenance = _load_json(paths["provenance"])
    _expect(provenance.get("status"), PENDING_STATUS, "provenance status")
    _expect(provenance.get("batch_id"), batch_id, "provenance batch_id")
    subject = provenance.get("subject")
    if not isinstance(subject, dict):
        raise ValueError("provenance subject must be an object")
    _expect(subject.get("concept_id"), concept_id, "provenance concept_id")
    _expect(subject.get("target_path"), target_path, "provenance target_path")
    _expect(subject.get("proposed_x_kos_id"), kos_id, "provenance x-kos-id")

    provenance_origin = provenance.get("origin")
    if not isinstance(provenance_origin, dict):
        raise ValueError("provenance origin must be an object")
    expected_origin = {
        "repository": origin_repository,
        "commit": origin_commit,
        "path": origin_path,
        "blob_sha": origin_blob,
        "uri": citation_url,
    }
    for field, expected in expected_origin.items():
        _expect(
            provenance_origin.get(field),
            expected,
            f"provenance origin {field}",
        )

    claims = provenance.get("claims")
    expected_claim_count = manifest.get("expected_claim_count")
    if not isinstance(expected_claim_count, int) or expected_claim_count < 1:
        raise ValueError("manifest expected_claim_count must be a positive integer")
    if not isinstance(claims, list) or len(claims) != expected_claim_count:
        raise ValueError(
            f"provenance must contain exactly {expected_claim_count} claims"
        )
    claim_ids: list[str] = []
    for item in claims:
        if not isinstance(item, dict):
            raise ValueError("every provenance claim must be an object")
        claim_id = _required_string(item, "claim_id", "provenance claim")
        _required_string(item, "text", f"provenance claim {claim_id}")
        locator = item.get("evidence_locator")
        if not isinstance(locator, dict) or not locator:
            raise ValueError(f"claim must include an evidence locator: {claim_id}")
        if "quote" in item:
            raise ValueError("review provenance must use locators, not embedded quotes")
        claim_ids.append(claim_id)
    if len(set(claim_ids)) != len(claim_ids):
        raise ValueError("provenance claim IDs must be unique")

    source = _load_json(paths["source_record"])
    _expect(source.get("status"), PENDING_STATUS, "source proposal status")
    _expect(source.get("batch_id"), batch_id, "source proposal batch_id")
    record = source.get("proposed_record")
    if not isinstance(record, dict):
        raise ValueError("proposed source record must be an object")
    _expect(record.get("origin_repository"), origin_repository, "source repository")
    _expect(record.get("origin_commit"), origin_commit, "source origin commit")
    _expect(record.get("origin_path"), origin_path, "source origin path")
    _expect(record.get("origin_blob_sha"), origin_blob, "source origin blob")
    _expect(record.get("uri"), citation_url, "source citation URI")
    _expect(record.get("audience"), audience, "source audience")
    if record.get("content_sha256") is not None:
        raise ValueError("source content_sha256 must remain unset before approval")

    decision = _load_json(paths["review_decision"])
    _expect(decision.get("status"), PENDING_STATUS, "review status")
    _expect(decision.get("batch_id"), batch_id, "review batch_id")
    _expect(decision.get("concept_id"), concept_id, "review concept_id")
    for field in ("reviewer", "reviewed_at", "approved_audience", "decision"):
        if decision.get(field) is not None:
            raise ValueError(f"review field must remain unset before decision: {field}")
    _expect(
        decision.get("canonical_write_authorized"),
        False,
        "canonical write authorization",
    )
    allowed_decisions = decision.get("allowed_decisions")
    _expect(
        allowed_decisions,
        ["approve", "request_changes", "reject"],
        "allowed review decisions",
    )

    checklist = paths["checklist"].read_text(encoding="utf-8")
    if "Status: `pending_human_review`" not in checklist:
        raise ValueError("review checklist must remain pending")
    for decision_name in allowed_decisions:
        if f"`{decision_name}`" not in checklist:
            raise ValueError(f"review checklist is missing decision: {decision_name}")

    return {
        "schema_version": "governed-source-review-validation/v1",
        "status": "passed",
        "batch_id": batch_id,
        "target_path": target_path,
        "proposed_concept_sha256": concept_sha256,
        "claim_count": len(claims),
        "review_status": PENDING_STATUS,
        "source_change_ready": False,
        "canonical_write_authorized": False,
        "mutations_performed": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    result = validate_source_review_package(args.package_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
