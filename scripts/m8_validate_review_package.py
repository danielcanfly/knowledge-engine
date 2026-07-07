from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

BATCH_ID = "m8-001-agent-execution-paths"
TARGET_PATH = "bundle/concepts/agent-execution-paths.md"
CONCEPT_ID = "concepts/agent-execution-paths"
KOS_ID = "ko_7FHJFQQ11PKPEWC4W25CCBCGZM"
ORIGIN_REPOSITORY = "huaihsuanbusiness/daniel-blog"
ORIGIN_COMMIT = "27e2fe996f878f2129bf510d6a326c02f7d87be5"
ORIGIN_PATH = "src/content/blog/the-atlas-of-agent-design-patterns-part-2/en.md"
ORIGIN_BLOB = "9b8912a4dc0193c0c478bcfe83dfaccff21b7ffe"
CITATION_URL = (
    "https://www.danielcanfly.com/en/blog/"
    "the-atlas-of-agent-design-patterns-part-2/"
)
CONCEPT_SHA256 = "c47b44c3495136076d6c0cf7de38d1459e05830f702f2b54464b1f86a1154ec5"
PACKAGE_FILES = (
    "proposed-concept.md",
    "proposed-provenance.json",
    "proposed-source-record.json",
    "proposed-review-decision.json",
    "review-checklist.md",
)
REQUIRED_SECTIONS = (
    "# Agent execution paths",
    "## Five primary structures",
    "### Direct",
    "### Pipeline",
    "### Router",
    "### State machine",
    "### Directed acyclic graph",
    "## Cross-cutting control layers",
    "### Event-driven execution",
    "### Human-in-the-loop",
    "## Related structures and techniques",
    "## Selection sequence",
    "## Controls shared by every structure",
)
FORBIDDEN_FRAGMENTS = (
    "/images/",
    "Figure 2-",
    "AWS Step Functions",
    "Apache Airflow",
    "LangGraph",
    "[[",
)


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


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


def validate_review_package(package_root: Path) -> dict[str, Any]:
    package_root = package_root.resolve()
    for name in PACKAGE_FILES:
        if not (package_root / name).is_file():
            raise ValueError(f"required review-package file is missing: {name}")

    metadata, body, concept_text = _parse_markdown(
        package_root / "proposed-concept.md"
    )
    concept_sha256 = hashlib.sha256(concept_text.encode("utf-8")).hexdigest()
    _expect(concept_sha256, CONCEPT_SHA256, "proposed concept SHA-256")

    expected_metadata = {
        "review-package-schema": "m8-source-review-package/v1",
        "batch-id": BATCH_ID,
        "review-status": "pending_human_review",
        "target-path": TARGET_PATH,
        "proposed-x-kos-id": KOS_ID,
        "proposed-audience": "public",
        "proposed-confidence": 0.9,
        "origin-repository": ORIGIN_REPOSITORY,
        "origin-commit": ORIGIN_COMMIT,
        "origin-path": ORIGIN_PATH,
        "origin-blob-sha": ORIGIN_BLOB,
        "citation-url": CITATION_URL,
    }
    for field, expected in expected_metadata.items():
        _expect(metadata.get(field), expected, f"concept metadata {field}")

    for section in REQUIRED_SECTIONS:
        if section not in body:
            raise ValueError(f"proposed concept is missing section: {section}")
    for fragment in FORBIDDEN_FRAGMENTS:
        if fragment in body:
            raise ValueError(f"proposed concept contains forbidden fragment: {fragment}")

    provenance = _load_json(package_root / "proposed-provenance.json")
    _expect(provenance.get("status"), "pending_human_review", "provenance status")
    _expect(provenance.get("batch_id"), BATCH_ID, "provenance batch_id")
    subject = provenance.get("subject")
    if not isinstance(subject, dict):
        raise ValueError("provenance subject must be an object")
    _expect(subject.get("concept_id"), CONCEPT_ID, "provenance concept_id")
    _expect(subject.get("target_path"), TARGET_PATH, "provenance target_path")
    _expect(subject.get("proposed_x_kos_id"), KOS_ID, "provenance x-kos-id")
    origin = provenance.get("origin")
    if not isinstance(origin, dict):
        raise ValueError("provenance origin must be an object")
    expected_origin = {
        "repository": ORIGIN_REPOSITORY,
        "commit": ORIGIN_COMMIT,
        "path": ORIGIN_PATH,
        "blob_sha": ORIGIN_BLOB,
        "source_id": "source_blog_agent_execution_paths",
        "uri": CITATION_URL,
    }
    for field, expected in expected_origin.items():
        _expect(origin.get(field), expected, f"provenance origin {field}")
    claims = provenance.get("claims")
    if not isinstance(claims, list) or len(claims) != 9:
        raise ValueError("provenance must contain exactly nine claims")
    claim_ids = [str(item.get("claim_id", "")) for item in claims if isinstance(item, dict)]
    if len(claim_ids) != 9 or len(set(claim_ids)) != 9 or not all(claim_ids):
        raise ValueError("provenance claim IDs must be non-empty and unique")
    if any("quote" in item for item in claims if isinstance(item, dict)):
        raise ValueError("review provenance must use locators instead of embedded quotes")

    source = _load_json(package_root / "proposed-source-record.json")
    _expect(source.get("status"), "pending_human_review", "source proposal status")
    _expect(source.get("batch_id"), BATCH_ID, "source proposal batch_id")
    record = source.get("proposed_record")
    if not isinstance(record, dict):
        raise ValueError("proposed source record must be an object")
    _expect(record.get("source_id"), expected_origin["source_id"], "source_id")
    _expect(record.get("origin_commit"), ORIGIN_COMMIT, "source origin commit")
    _expect(record.get("origin_blob_sha"), ORIGIN_BLOB, "source origin blob")
    _expect(record.get("uri"), CITATION_URL, "source citation URI")
    if record.get("content_sha256") is not None:
        raise ValueError("source content_sha256 must remain unset before exact capture")

    decision = _load_json(package_root / "proposed-review-decision.json")
    _expect(decision.get("status"), "pending_human_review", "review status")
    _expect(decision.get("batch_id"), BATCH_ID, "review batch_id")
    _expect(decision.get("concept_id"), CONCEPT_ID, "review concept_id")
    for field in ("reviewer", "reviewed_at", "approved_audience", "decision"):
        if decision.get(field) is not None:
            raise ValueError(f"review field must remain unset before decision: {field}")
    _expect(
        decision.get("canonical_write_authorized"),
        False,
        "canonical write authorization",
    )

    checklist = (package_root / "review-checklist.md").read_text(encoding="utf-8")
    if "Status: `pending_human_review`" not in checklist:
        raise ValueError("review checklist must remain pending")
    for decision_name in ("approve", "request_changes", "reject"):
        if f"`{decision_name}`" not in checklist:
            raise ValueError(f"review checklist is missing decision: {decision_name}")

    return {
        "schema_version": "m8-review-package-validation/v1",
        "status": "passed",
        "batch_id": BATCH_ID,
        "target_path": TARGET_PATH,
        "proposed_concept_sha256": concept_sha256,
        "claim_count": len(claims),
        "review_status": "pending_human_review",
        "source_change_ready": False,
        "mutations_performed": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--package-root",
        type=Path,
        default=Path("review_packages/m8-001"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("evidence/m8-001/review-package-validation.json"),
    )
    args = parser.parse_args()
    result = validate_review_package(args.package_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
