from __future__ import annotations

import argparse
from pathlib import Path

from knowledge_engine.m23_qdrant_pilot_ingestion import (
    EXPECTED_DOCUMENT_COUNT,
    QDRANT_COLLECTION,
    SOURCE_MEMBERSHIP,
    canonical_bytes,
    canonical_sha256,
    validate_ingestion_contract,
)

FORBIDDEN_SOURCE_TOKENS = (
    "httpx",
    "requests",
    "urllib.request",
    "socket.",
    "QDRANT_URL",
    "QDRANT_API_KEY",
    "CLOUDFLARE_API_TOKEN",
    "allow-qdrant-write",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate the M23.6.2 no-write contract."
    )
    parser.add_argument(
        "--contract",
        type=Path,
        default=Path("pilot/m23/m23-6-2-ingestion-contract.json"),
    )
    parser.add_argument(
        "--module",
        type=Path,
        default=Path("src/knowledge_engine/m23_qdrant_pilot_ingestion.py"),
    )
    parser.add_argument(
        "--cli",
        type=Path,
        default=Path("src/knowledge_engine/m23_qdrant_pilot_ingestion_cli.py"),
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=Path("schemas/m23-qdrant-ingestion-manifest-v1.schema.json"),
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    import json

    contract = validate_ingestion_contract(
        json.loads(args.contract.read_text(encoding="utf-8"))
    )
    schema = json.loads(args.schema.read_text(encoding="utf-8"))
    if schema.get("$id") != (
        "https://knowledge-os.local/schemas/"
        "m23-qdrant-ingestion-manifest-v1.schema.json"
    ):
        raise SystemExit("unexpected ingestion manifest schema ID")
    properties = schema.get("properties", {})
    collection = (
        properties.get("qdrant", {})
        .get("properties", {})
        .get("collection", {})
        .get("const")
    )
    if collection != QDRANT_COLLECTION:
        raise SystemExit("schema collection drift")
    if properties.get("points", {}).get("minItems") != EXPECTED_DOCUMENT_COUNT:
        raise SystemExit("schema point-count drift")
    source = args.module.read_text(encoding="utf-8") + args.cli.read_text(
        encoding="utf-8"
    )
    found = sorted(token for token in FORBIDDEN_SOURCE_TOKENS if token in source)
    if found:
        raise SystemExit(f"forbidden network/write surfaces found: {found}")
    report = {
        "schema_version": "knowledge-engine-m23-qdrant-ingestion-acceptance/v1",
        "milestone": "M23.6.2",
        "contract_sha256": contract["contract_sha256"],
        "schema_sha256": canonical_sha256(schema),
        "point_count": EXPECTED_DOCUMENT_COUNT,
        "collection": QDRANT_COLLECTION,
        "source_membership": SOURCE_MEMBERSHIP,
        "synthetic_107_row_contract_tested": True,
        "real_evidence_dry_run_completed": False,
        "real_evidence_dry_run_required_before_m23_6_3": True,
        "network_calls": 0,
        "qdrant_reads": 0,
        "qdrant_writes": 0,
        "production_mutation_dispatched": False,
        "decision": "accepted-for-real-evidence-dry-run-precondition",
    }
    report["report_sha256"] = canonical_sha256(report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical_bytes(report))
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
