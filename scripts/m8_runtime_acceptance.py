from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

NEW_QUERY = (
    "How should I choose between Direct, Pipeline, Router, State Machine, "
    "and DAG execution paths?"
)
REGRESSION_QUERY = (
    "How should LLM agent architectures be reviewed across six engineering dimensions?"
)
BOUNDARY_QUERY = "quartz lantern protocol"
EXPECTED_NEW_CONCEPT = "concepts/agent-execution-paths"
EXPECTED_NEW_X_KOS_ID = "ko_7FHJFQQ11PKPEWC4W25CCBCGZM"
EXPECTED_NEW_CITATION = (
    "https://www.danielcanfly.com/en/blog/"
    "the-atlas-of-agent-design-patterns-part-2/"
)
EXPECTED_REGRESSION_CITATION = (
    "https://www.danielcanfly.com/en/blog/"
    "the-atlas-of-agent-design-patterns-part-1/"
)


def _run_query(channel: str, query: str, audiences: str = "public") -> dict[str, Any]:
    completed = subprocess.run(
        [
            "knowledge-engine",
            "query",
            "--channel",
            channel,
            "--query",
            query,
            "--audiences",
            audiences,
            "--limit",
            "10",
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(completed.stdout)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def _raw_fallback(payload: dict[str, Any]) -> bool:
    return bool(payload.get("retrieval", {}).get("raw_fallback_used"))


def _release_identity(payload: dict[str, Any]) -> tuple[str | None, str | None]:
    release = payload.get("release", {})
    return release.get("release_id"), release.get("manifest_sha256")


def _citations(payload: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for result in payload.get("results", []):
        for citation in result.get("citations", []):
            uri = citation.get("uri")
            if isinstance(uri, str):
                values.append(uri)
    return values


def _field_values(payload: dict[str, Any], field: str) -> list[str]:
    values: list[str] = []
    for result in payload.get("results", []):
        value = result.get(field)
        if isinstance(value, str):
            values.append(value)
    return values


def verify_outputs(
    *,
    channel: str,
    new_query: dict[str, Any],
    regression_query: dict[str, Any],
    boundary_query: dict[str, Any],
) -> dict[str, Any]:
    outputs = {
        "new_query": new_query,
        "regression_query": regression_query,
        "boundary_query": boundary_query,
    }
    identities = {name: _release_identity(payload) for name, payload in outputs.items()}
    release_id, manifest_sha256 = identities["new_query"]
    _require(bool(release_id), "new_query returned no release_id")
    _require(bool(manifest_sha256), "new_query returned no manifest_sha256")
    for name, identity in identities.items():
        _require(
            identity == (release_id, manifest_sha256),
            f"{name} release identity mismatch: {identity!r}",
        )
        _require(not _raw_fallback(outputs[name]), f"{name} used raw fallback")

    new_citations = _citations(new_query)
    new_concepts = _field_values(new_query, "concept_id")
    new_x_kos_ids = _field_values(new_query, "x_kos_id")
    _require(new_query.get("status") == "answered", "new_query was not answered")
    _require(bool(new_query.get("results")), "new_query returned no results")
    _require(EXPECTED_NEW_CONCEPT in new_concepts, f"new concept missing: {new_concepts!r}")
    _require(
        EXPECTED_NEW_X_KOS_ID in new_x_kos_ids,
        f"new x-kos-id missing: {new_x_kos_ids!r}",
    )
    _require(
        EXPECTED_NEW_CITATION in new_citations,
        f"Part 2 citation missing: {new_citations!r}",
    )

    regression_citations = _citations(regression_query)
    _require(
        regression_query.get("status") == "answered",
        "regression_query was not answered",
    )
    _require(
        EXPECTED_REGRESSION_CITATION in regression_citations,
        f"Part 1 citation missing: {regression_citations!r}",
    )

    _require(
        boundary_query.get("status") == "not_found",
        f"boundary_query status={boundary_query.get('status')!r}",
    )
    _require(not boundary_query.get("results"), "boundary_query returned public results")
    _require(
        int(boundary_query.get("retrieval", {}).get("acl_filtered_count", 0)) >= 1,
        "boundary_query did not prove ACL filtering",
    )

    return {
        "status": "passed",
        "channel": channel,
        "release_id": release_id,
        "manifest_sha256": manifest_sha256,
        "checks": {
            "new_query": {
                "status": new_query.get("status"),
                "concept_ids": new_concepts,
                "x_kos_ids": new_x_kos_ids,
                "citation_count": len(new_citations),
                "raw_fallback_used": _raw_fallback(new_query),
            },
            "regression_query": {
                "status": regression_query.get("status"),
                "citation_count": len(regression_citations),
                "raw_fallback_used": _raw_fallback(regression_query),
            },
            "boundary_query": {
                "query": BOUNDARY_QUERY,
                "status": boundary_query.get("status"),
                "acl_filtered_count": boundary_query.get("retrieval", {}).get(
                    "acl_filtered_count"
                ),
                "raw_fallback_used": _raw_fallback(boundary_query),
            },
        },
        "production_mutated": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    outputs = {
        "new_query": _run_query(args.channel, NEW_QUERY),
        "regression_query": _run_query(args.channel, REGRESSION_QUERY),
        "boundary_query": _run_query(args.channel, BOUNDARY_QUERY),
    }
    for name, payload in outputs.items():
        _write_json(args.out_dir / f"{name}.json", payload)

    summary = verify_outputs(channel=args.channel, **outputs)
    _write_json(args.out_dir / "summary.json", summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
