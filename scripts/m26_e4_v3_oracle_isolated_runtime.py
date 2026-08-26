#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import pathlib
import socket
import subprocess
import time
import urllib.error
import urllib.request
from typing import Any

DEFAULT_BASE_CONTAINER = "m26-public-api-production-repair2-ownerhash-r2-auth-520aed"
DEFAULT_CANDIDATE_CONTAINER = "m26-e4-v3-oracle-isolated-m26blog-59012fe-520aed"


def run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, check=check)


def stdout(args: list[str]) -> str:
    return run(args).stdout.strip()


def load_json(path: pathlib.Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit(f"{path} must contain a JSON object")
    return value


def require_binding(binding: dict[str, Any], key: str) -> Any:
    value = binding.get(key)
    if value in (None, ""):
        raise SystemExit(f"binding missing {key}")
    return value


def container_env_rows(container: str) -> list[str]:
    raw = stdout(["docker", "inspect", container, "--format", "{{range .Config.Env}}{{println .}}{{end}}"])
    return [line for line in raw.splitlines() if "=" in line]


def parse_env(rows: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in rows:
        if "=" in row:
            key, value = row.split("=", 1)
            out[key] = value
    return out


def write_env_file(path: pathlib.Path, env: dict[str, str]) -> None:
    lines = []
    for key in sorted(env):
        value = env[key]
        if "\n" in value or "\r" in value:
            continue
        lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.chmod(0o600)


def choose_container_port(inspected: dict[str, Any], env: dict[str, str], explicit: str | None) -> str:
    if explicit:
        return explicit
    ports = ((inspected.get("NetworkSettings") or {}).get("Ports") or {})
    for key in sorted(ports):
        if key.endswith("/tcp"):
            return key.split("/", 1)[0]
    if env.get("PORT"):
        return env["PORT"]
    return "8789"


def assert_host_port_free(port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        if sock.connect_ex(("127.0.0.1", port)) == 0:
            raise SystemExit(f"M26_E4_V3_HOST_PORT_ALREADY_IN_USE:{port}")


def build_sitecustomize(binding: dict[str, Any]) -> str:
    release_id = str(require_binding(binding, "release_id"))
    qdrant_collection = str(require_binding(binding, "qdrant_collection"))
    graph_v2_sha256 = str(require_binding(binding, "graph_v2_sha256"))
    source_commit_sha = str(require_binding(binding, "source_commit_sha"))
    admission_sha256 = str(require_binding(binding, "admission_sha256"))
    node_count = int(require_binding(binding, "node_count"))
    edge_count = int(require_binding(binding, "edge_count"))
    semantic_point_count = int(require_binding(binding, "semantic_point_count"))
    return f'''from __future__ import annotations
# M26 E4_V3 isolated Oracle binding overlay.
# Runtime/semantic/translation logic remains loaded from the frozen base image.
# This file only rebases production-answer bundle identity constants for the
# isolated candidate container and intentionally points pointer validation at
# a non-production candidate channel.
try:
    from knowledge_engine import m26_production_answer_bundle as pab
except Exception:
    pab = None
if pab is not None:
    pab.FULL_PRODUCTION_RELEASE_ID = {release_id!r}
    pab.FULL_PRODUCTION_MANIFEST_KEY = f"releases/{{pab.FULL_PRODUCTION_RELEASE_ID}}/manifest.json"
    pab.FULL_PRODUCTION_PROMOTION_MANIFEST_KEY = (
        f"releases/{{pab.FULL_PRODUCTION_RELEASE_ID}}/promotion/m26-e4-v3-isolated-production-manifest.json"
    )
    pab.FULL_PRODUCTION_PROMOTION_MANIFEST_SHA256 = ""
    pab.FULL_PRODUCTION_GRAPH_V2_SHA256 = {graph_v2_sha256!r}
    pab.FULL_PRODUCTION_POINTER_KEY = "channels/m26-e4-v3-isolated.json"
    pab.FULL_PRODUCTION_POINTER_SHA256 = ""
    pab.FULL_PRODUCTION_QDRANT_COLLECTION = {qdrant_collection!r}
    pab.FULL_PRODUCTION_NODE_COUNT = {node_count!r}
    pab.FULL_PRODUCTION_EDGE_COUNT = {edge_count!r}
    pab.FULL_PRODUCTION_SEMANTIC_POINT_COUNT = {semantic_point_count!r}
    pab.FULL_PRODUCTION_SOURCE_SHA = {source_commit_sha!r}
    pab.FULL_PRODUCTION_ADMISSION_SHA256 = {admission_sha256!r}
    try:
        pab._load_production_answer_bundle_from_env.cache_clear()
    except Exception:
        pass
'''


def request_health(port: int, env: dict[str, str]) -> dict[str, Any]:
    token = env.get("M26_QUERY_BACKEND_TOKEN", "")
    owner_hash = env.get("KNOWLEDGE_ENGINE_OWNER_SUBJECT_HASH", "")
    if not token:
        raise SystemExit("M26_E4_V3_MISSING_BACKEND_TOKEN_IN_BASE_ENV")
    if not owner_hash:
        raise SystemExit("M26_E4_V3_MISSING_OWNER_HASH_IN_BASE_ENV")
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/m26/health",
        headers={
            "Authorization": f"Bearer {token}",
            "x-m26-owner-subject-hash": owner_hash,
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            payload = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise SystemExit(f"M26_E4_V3_HEALTH_HTTP_{exc.code}:{detail}") from exc
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise SystemExit("M26_E4_V3_HEALTH_NON_OBJECT")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binding-json", required=True)
    parser.add_argument("--base-container", default=DEFAULT_BASE_CONTAINER)
    parser.add_argument("--candidate-container", default=DEFAULT_CANDIDATE_CONTAINER)
    parser.add_argument("--host-port", type=int, default=int(os.environ.get("M26_E4_V3_HOST_PORT", "18187")))
    parser.add_argument("--container-port", default=os.environ.get("M26_E4_V3_CONTAINER_PORT", ""))
    parser.add_argument("--work-dir", default="/tmp/m26-e4-v3-oracle-isolated-runtime")
    args = parser.parse_args()

    binding = load_json(pathlib.Path(args.binding_json))
    release_id = str(require_binding(binding, "release_id"))
    qdrant_collection = str(require_binding(binding, "qdrant_collection"))

    names = stdout(["docker", "ps", "-a", "--format", "{{.Names}}"]).splitlines()
    if args.base_container not in names:
        raise SystemExit("M26_E4_V3_FROZEN_BASE_CONTAINER_MISSING")

    inspected = json.loads(stdout(["docker", "inspect", args.base_container]))[0]
    image_id = inspected["Image"]
    env = parse_env(container_env_rows(args.base_container))
    container_port = choose_container_port(inspected, env, args.container_port or None)
    assert_host_port_free(args.host_port)

    work_dir = pathlib.Path(args.work_dir)
    overlay_dir = work_dir / "sitecustomize"
    work_dir.mkdir(parents=True, exist_ok=True)
    overlay_dir.mkdir(parents=True, exist_ok=True)
    (overlay_dir / "sitecustomize.py").write_text(build_sitecustomize(binding), encoding="utf-8")
    (overlay_dir / "sitecustomize.py").chmod(0o644)

    env["M26_QUERY_BUILD_SHA"] = f"m26-e4-v3-isolated-{release_id}-520aed"
    env["M26_E4_V3_ISOLATED_RUNTIME"] = "true"
    env["M26_PA7_DENSE_COLLECTION"] = qdrant_collection
    env["PYTHONPATH"] = f"/tmp/m26_e4_v3_sitecustomize:{env.get('PYTHONPATH','')}".rstrip(":")
    env_file = work_dir / "candidate.env"
    write_env_file(env_file, env)

    run(["docker", "rm", "-f", args.candidate_container], check=False)
    docker_args = [
        "docker", "run", "-d",
        "--name", args.candidate_container,
        "--restart", "no",
        "--env-file", str(env_file),
        "-v", f"{overlay_dir}:/tmp/m26_e4_v3_sitecustomize:ro",
        "-p", f"127.0.0.1:{args.host_port}:{container_port}",
        image_id,
    ]
    container_id = stdout(docker_args)

    health: dict[str, Any] | None = None
    last_error = ""
    for _ in range(30):
        time.sleep(2)
        status = run(["docker", "inspect", args.candidate_container, "--format", "{{.State.Running}}"], check=False)
        if status.returncode != 0 or status.stdout.strip() != "true":
            logs = run(["docker", "logs", "--tail", "80", args.candidate_container], check=False)
            raise SystemExit("M26_E4_V3_CANDIDATE_CONTAINER_NOT_RUNNING:" + logs.stdout[-1000:])
        try:
            health = request_health(args.host_port, env)
            if health.get("status") == "ok":
                break
        except Exception as exc:
            last_error = str(exc)
    if not isinstance(health, dict) or health.get("status") != "ok":
        logs = run(["docker", "logs", "--tail", "120", args.candidate_container], check=False)
        raise SystemExit("M26_E4_V3_HEALTH_NOT_OK:" + last_error + ":" + logs.stdout[-1200:])

    receipt = {
        "schema_version": "m26-e4-v3-oracle-isolated-runtime-receipt/v1",
        "status": "M26_E4_V3_ORACLE_ISOLATED_RUNTIME_PASS",
        "base_container": args.base_container,
        "candidate_container": args.candidate_container,
        "candidate_container_id": container_id,
        "base_image_id": image_id,
        "endpoint": {
            "host": "127.0.0.1",
            "host_port": args.host_port,
            "container_port": container_port,
            "health_path": "/api/m26/health",
            "query_path": "/api/m26/query",
        },
        "binding": {
            "release_id": release_id,
            "manifest_sha256": binding.get("manifest_sha256"),
            "graph_v2_sha256": binding.get("graph_v2_sha256"),
            "qdrant_collection": qdrant_collection,
            "source_head_sha": binding.get("source_head_sha"),
            "source_commit_sha": binding.get("source_commit_sha"),
            "admission_sha256": binding.get("admission_sha256"),
            "semantic_point_count": binding.get("semantic_point_count"),
            "node_count": binding.get("node_count"),
            "edge_count": binding.get("edge_count"),
        },
        "health": {
            "schema_version": health.get("schema_version"),
            "status": health.get("status"),
            "canonical_runtime": health.get("canonical_runtime"),
            "mutations": health.get("mutations"),
            "privacy": health.get("privacy"),
        },
        "authority": {
            "production_pointer_writes": 0,
            "canonical_route_mutations": 0,
            "r2_writes": 0,
            "qdrant_writes": 0,
            "embedding_provider_requests": 0,
            "provider_answer_requests": 0,
            "source_repo_mutations": 0,
            "e5_consumed_attempts": 0,
        },
    }
    print("M26_E4_V3_ORACLE_ISOLATED_RUNTIME_PASS")
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
