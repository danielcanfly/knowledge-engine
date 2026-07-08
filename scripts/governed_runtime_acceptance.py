from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from knowledge_engine.config import Settings
from knowledge_engine.storage import create_object_store

CONTRACT_SCHEMA = "governed-runtime-acceptance-contract/v1"
SAFE_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_contract(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    _require(payload.get("schema_version") == CONTRACT_SCHEMA, "invalid contract schema")
    _require(isinstance(payload.get("batch_id"), str), "contract has no batch_id")
    candidate = payload.get("candidate")
    _require(isinstance(candidate, dict), "contract has no candidate identity")
    _require(bool(candidate.get("channel")), "contract candidate has no channel")
    _require(bool(candidate.get("release_id")), "contract candidate has no release_id")
    _require(
        bool(candidate.get("manifest_sha256")),
        "contract candidate has no manifest_sha256",
    )
    queries = payload.get("queries")
    _require(isinstance(queries, list) and bool(queries), "contract has no queries")
    names: set[str] = set()
    for item in queries:
        _require(isinstance(item, dict), "query contract must be an object")
        name = item.get("name")
        _require(
            isinstance(name, str) and SAFE_NAME.fullmatch(name) is not None,
            "unsafe query name",
        )
        _require(name not in names, f"duplicate query name: {name}")
        names.add(name)
        for field in (
            "query",
            "audiences",
            "expected_status",
            "expected_concept_id",
            "expected_x_kos_id",
            "expected_citation",
        ):
            _require(bool(item.get(field)), f"query {name} has no {field}")
    boundary = payload.get("boundary_query")
    _require(isinstance(boundary, dict), "contract has no boundary_query")
    boundary_name = boundary.get("name")
    _require(
        isinstance(boundary_name, str)
        and SAFE_NAME.fullmatch(boundary_name) is not None,
        "unsafe boundary query name",
    )
    _require(boundary_name not in names, f"duplicate query name: {boundary_name}")
    return payload


def _run_query(
    *,
    channel: str,
    query: str,
    audiences: str,
    cache_dir: Path,
) -> dict[str, Any]:
    env = os.environ.copy()
    env["CACHE_DIR"] = str(cache_dir)
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
        env=env,
    )
    return json.loads(completed.stdout)


def _release_identity(payload: dict[str, Any]) -> tuple[str | None, str | None]:
    release = payload.get("release", {})
    return release.get("release_id"), release.get("manifest_sha256")


def _raw_fallback(payload: dict[str, Any]) -> bool:
    return bool(payload.get("retrieval", {}).get("raw_fallback_used"))


def _citations(payload: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for result in payload.get("results", []):
        for citation in result.get("citations", []):
            uri = citation.get("uri")
            if isinstance(uri, str):
                values.append(uri)
    return values


def _result_values(payload: dict[str, Any], field: str) -> list[str]:
    values: list[str] = []
    for result in payload.get("results", []):
        value = result.get(field)
        if isinstance(value, str):
            values.append(value)
    return values


def _pointer_identity(pointer_bytes: bytes) -> tuple[str | None, str | None]:
    pointer = json.loads(pointer_bytes)
    return pointer.get("release_id"), pointer.get("manifest_sha256")


def verify_acceptance(
    *,
    contract: dict[str, Any],
    outputs: dict[str, dict[str, Any]],
    production_before: bytes,
    production_after: bytes,
) -> dict[str, Any]:
    candidate = contract["candidate"]
    requirements = contract["requirements"]
    expected_identity = (
        candidate["release_id"],
        candidate["manifest_sha256"],
    )

    checks: dict[str, Any] = {}
    for query_contract in contract["queries"]:
        name = query_contract["name"]
        payload = outputs[name]
        identity = _release_identity(payload)
        _require(
            identity == expected_identity,
            f"{name} candidate identity mismatch: {identity!r}",
        )
        _require(
            payload.get("status") == query_contract["expected_status"],
            f"{name} status={payload.get('status')!r}",
        )
        result_count = len(payload.get("results", []))
        _require(
            result_count >= int(requirements["minimum_result_count"]),
            f"{name} returned too few results: {result_count}",
        )
        _require(not _raw_fallback(payload), f"{name} used raw fallback")
        concept_ids = _result_values(payload, "concept_id")
        x_kos_ids = _result_values(payload, "x_kos_id")
        citations = _citations(payload)
        _require(
            query_contract["expected_concept_id"] in concept_ids,
            f"{name} concept missing: {concept_ids!r}",
        )
        _require(
            query_contract["expected_x_kos_id"] in x_kos_ids,
            f"{name} x-kos-id missing: {x_kos_ids!r}",
        )
        _require(
            query_contract["expected_citation"] in citations,
            f"{name} citation missing: {citations!r}",
        )
        checks[name] = {
            "status": payload.get("status"),
            "result_count": result_count,
            "concept_ids": concept_ids,
            "x_kos_ids": x_kos_ids,
            "citations": citations,
            "raw_fallback_used": _raw_fallback(payload),
            "release_id": identity[0],
            "manifest_sha256": identity[1],
        }

    boundary_contract = contract["boundary_query"]
    boundary_name = boundary_contract["name"]
    boundary = outputs[boundary_name]
    boundary_identity = _release_identity(boundary)
    _require(
        boundary_identity == expected_identity,
        f"{boundary_name} candidate identity mismatch: {boundary_identity!r}",
    )
    _require(
        boundary.get("status") == boundary_contract["expected_status"],
        f"{boundary_name} status={boundary.get('status')!r}",
    )
    _require(not boundary.get("results"), f"{boundary_name} returned public results")
    acl_filtered_count = int(
        boundary.get("retrieval", {}).get("acl_filtered_count", 0)
    )
    _require(
        acl_filtered_count >= int(boundary_contract["minimum_acl_filtered_count"]),
        f"{boundary_name} did not prove ACL filtering",
    )
    _require(not _raw_fallback(boundary), f"{boundary_name} used raw fallback")
    checks[boundary_name] = {
        "status": boundary.get("status"),
        "result_count": len(boundary.get("results", [])),
        "acl_filtered_count": acl_filtered_count,
        "raw_fallback_used": _raw_fallback(boundary),
        "release_id": boundary_identity[0],
        "manifest_sha256": boundary_identity[1],
    }

    baseline = contract["production_baseline"]
    expected_pointer_sha256 = baseline["pointer_sha256"]
    before_sha256 = _sha256(production_before)
    after_sha256 = _sha256(production_after)
    _require(
        before_sha256 == expected_pointer_sha256,
        f"production baseline pointer drifted before acceptance: {before_sha256}",
    )
    _require(
        after_sha256 == expected_pointer_sha256,
        f"production pointer changed during acceptance: {after_sha256}",
    )
    _require(
        production_before == production_after,
        "production pointer bytes changed during acceptance",
    )
    expected_production_identity = (
        baseline["release_id"],
        baseline["manifest_sha256"],
    )
    _require(
        _pointer_identity(production_before) == expected_production_identity,
        "production pointer identity does not match baseline",
    )

    return {
        "schema_version": "governed-runtime-acceptance-result/v1",
        "status": "passed",
        "batch_id": contract["batch_id"],
        "candidate": candidate,
        "checks": checks,
        "production_pointer": {
            "key": baseline["pointer_key"],
            "release_id": baseline["release_id"],
            "manifest_sha256": baseline["manifest_sha256"],
            "before_sha256": before_sha256,
            "after_sha256": after_sha256,
            "byte_exact_unchanged": production_before == production_after,
        },
        "production_mutated": False,
        "next_legal_action": "reconcile_runtime_acceptance",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    contract = _load_contract(args.contract)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    _write_json(args.out_dir / "contract.json", contract)

    settings = Settings.from_env()
    store = create_object_store(settings)
    pointer_key = contract["production_baseline"]["pointer_key"]
    production_before = store.get(pointer_key)
    (args.out_dir / "production-pointer-before.json").write_bytes(production_before)

    channel = contract["candidate"]["channel"]
    outputs: dict[str, dict[str, Any]] = {}
    for query_contract in contract["queries"]:
        name = query_contract["name"]
        payload = _run_query(
            channel=channel,
            query=query_contract["query"],
            audiences=query_contract["audiences"],
            cache_dir=args.out_dir / "cache" / name,
        )
        outputs[name] = payload
        _write_json(args.out_dir / f"{name}.json", payload)

    boundary_contract = contract["boundary_query"]
    boundary_name = boundary_contract["name"]
    boundary = _run_query(
        channel=channel,
        query=boundary_contract["query"],
        audiences=boundary_contract["audiences"],
        cache_dir=args.out_dir / "cache" / boundary_name,
    )
    outputs[boundary_name] = boundary
    _write_json(args.out_dir / f"{boundary_name}.json", boundary)

    production_after = store.get(pointer_key)
    (args.out_dir / "production-pointer-after.json").write_bytes(production_after)

    summary = verify_acceptance(
        contract=contract,
        outputs=outputs,
        production_before=production_before,
        production_after=production_after,
    )
    _write_json(args.out_dir / "summary.json", summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
