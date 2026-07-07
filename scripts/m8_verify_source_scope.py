from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

EXPECTED_ORIGIN_COMMIT = "27e2fe996f878f2129bf510d6a326c02f7d87be5"
EXPECTED_ORIGIN_BLOB = "9b8912a4dc0193c0c478bcfe83dfaccff21b7ffe"
EXPECTED_SOURCE_SHA = "6a35f9f35e4c6c599a266710344f760c399d914d"
EXPECTED_TARGET = "bundle/concepts/agent-execution-paths.md"
EXPECTED_CONCEPTS = [
    {
        "path": "bundle/concepts/candidate-delivery-controls.md",
        "blob_sha": "2e1759c4c1968e38dff55cbdcaaed08f5df627a5",
        "audience": "internal",
    },
    {
        "path": "bundle/concepts/six-dimensional-map-of-llm-agent-architectures.md",
        "blob_sha": "4feaba133e91d4ebd4d422f8aea7d252fb81f112",
        "audience": "public",
    },
    {
        "path": "bundle/concepts/source-governance.md",
        "blob_sha": "b5d9a76ccf31df61ce9cf455ea144593367d85e5",
        "audience": "public",
    },
]


def _load_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo), *args],
        text=True,
    ).strip()


def verify(*, origin_repo: Path, attestation_path: Path) -> dict[str, Any]:
    origin_path = Path(
        "src/content/blog/the-atlas-of-agent-design-patterns-part-2/en.md"
    )
    if not (origin_repo / origin_path).is_file():
        raise ValueError("exact blog origin path is missing")

    origin_commit = _git(origin_repo, "rev-parse", "HEAD")
    origin_blob = _git(origin_repo, "hash-object", str(origin_path))
    if origin_commit != EXPECTED_ORIGIN_COMMIT:
        raise ValueError("blog origin commit mismatch")
    if origin_blob != EXPECTED_ORIGIN_BLOB:
        raise ValueError("blog origin blob mismatch")

    attestation = _load_object(attestation_path)
    required = {
        "schema_version": "m8-source-baseline-attestation/v1",
        "verification_method": "github-connector-exact-ref-content-lookup",
        "source_repository": "danielcanfly/knowledge-source",
        "source_sha": EXPECTED_SOURCE_SHA,
        "intended_source_path": EXPECTED_TARGET,
        "intended_source_path_fetch_status": 404,
        "intended_source_path_exists": False,
        "existing_concepts": EXPECTED_CONCEPTS,
    }
    if attestation != required:
        raise ValueError("Source baseline attestation mismatch")

    return {
        "status": "verified",
        "origin_repository": "huaihsuanbusiness/daniel-blog",
        "origin_commit": origin_commit,
        "origin_path": str(origin_path),
        "origin_blob_sha": origin_blob,
        "source_repository": attestation["source_repository"],
        "source_baseline_sha": attestation["source_sha"],
        "source_verification_method": attestation["verification_method"],
        "intended_source_path": attestation["intended_source_path"],
        "intended_source_path_fetch_status": 404,
        "intended_source_path_exists": False,
        "existing_concepts": attestation["existing_concepts"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--origin-repo", type=Path, required=True)
    parser.add_argument("--attestation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    result = verify(
        origin_repo=args.origin_repo,
        attestation_path=args.attestation,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print("M8_SOURCE_SCOPE_VERIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
