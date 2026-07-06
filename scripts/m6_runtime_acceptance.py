from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any


PUBLIC_QUERY_1 = "What is the Knowledge Source governance boundary in Knowledge OS?"
PUBLIC_QUERY_2 = "How should LLM agent architectures be reviewed across six engineering dimensions?"
BOUNDARY_QUERY = "What candidate delivery controls are available for public users in Knowledge OS?"
EXPECTED_CITATION_2 = "https://www.danielcanfly.com/en/blog/the-atlas-of-agent-design-patterns-part-1/"
EXPECTED_RELEASE_ID = "20260706T061437Z-bc48bf4810c0"
EXPECTED_MANIFEST_SHA256 = "8eefb904d1eea0f6ca87b074c60edfe94c725bd76adb77961919b8d2bd4c8f96"


def _run_query(channel: str, query: str, audiences: str) -> dict[str, Any]:
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
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def _raw_fallback_used(payload: dict[str, Any]) -> bool:
    return bool(payload.get("retrieval", {}).get("raw_fallback_used"))


def _citations(payload: dict[str, Any]) -> list[str]:
    uris: list[str] = []
    for result in payload.get("results", []):
        for citation in result.get("citations", []):
            uri = citation.get("uri")
            if isinstance(uri, str):
                uris.append(uri)
    return uris


def _release_identity(payload: dict[str, Any]) -> tuple[str | None, str | None]:
    release = payload.get("release", {})
    return release.get("release_id"), release.get("manifest_sha256")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    outputs = {
        "public_query_1": _run_query(args.channel, PUBLIC_QUERY_1, "public"),
        "public_query_2": _run_query(args.channel, PUBLIC_QUERY_2, "public"),
        "boundary_query": _run_query(args.channel, BOUNDARY_QUERY, "public"),
    }

    for name, payload in outputs.items():
        _write_json(args.out_dir / f"{name}.json", payload)

    q1 = outputs["public_query_1"]
    q2 = outputs["public_query_2"]
    boundary = outputs["boundary_query"]

    for name, payload in [("public_query_1", q1), ("public_query_2", q2), ("boundary_query", boundary)]:
        release_id, manifest_sha = _release_identity(payload)
        _require(release_id == EXPECTED_RELEASE_ID, f"{name} release_id={release_id!r}")
        _require(manifest_sha == EXPECTED_MANIFEST_SHA256, f"{name} manifest_sha256={manifest_sha!r}")
        _require(not _raw_fallback_used(payload), f"{name} used raw fallback")

    q1_citations = _citations(q1)
    q2_citations = _citations(q2)

    _require(q1.get("status") == "answered", f"public_query_1 status={q1.get('status')!r}")
    _require(q1.get("results"), "public_query_1 returned no results")
    _require(q1_citations, "public_query_1 returned no citations")
    _require(
        any("source-governance" in uri for uri in q1_citations),
        f"public_query_1 citations did not include source-governance: {q1_citations!r}",
    )

    _require(q2.get("status") == "answered", f"public_query_2 status={q2.get('status')!r}")
    _require(q2.get("results"), "public_query_2 returned no results")
    _require(EXPECTED_CITATION_2 in q2_citations, f"public_query_2 citations={q2_citations!r}")

    _require(boundary.get("status") == "not_found", f"boundary_query status={boundary.get('status')!r}")
    _require(not boundary.get("results"), "boundary_query returned public results")
    _require(
        int(boundary.get("retrieval", {}).get("acl_filtered_count", 0)) >= 1,
        "boundary_query did not prove ACL filtering",
    )

    summary = {
        "status": "passed",
        "channel": args.channel,
        "release_id": EXPECTED_RELEASE_ID,
        "manifest_sha256": EXPECTED_MANIFEST_SHA256,
        "checks": {
            "public_query_1": {
                "status": q1.get("status"),
                "citation_count": len(q1_citations),
                "raw_fallback_used": _raw_fallback_used(q1),
            },
            "public_query_2": {
                "status": q2.get("status"),
                "citation_count": len(q2_citations),
                "raw_fallback_used": _raw_fallback_used(q2),
            },
            "boundary_query": {
                "status": boundary.get("status"),
                "acl_filtered_count": boundary.get("retrieval", {}).get("acl_filtered_count"),
                "raw_fallback_used": _raw_fallback_used(boundary),
            },
        },
    }
    _write_json(args.out_dir / "summary.json", summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
