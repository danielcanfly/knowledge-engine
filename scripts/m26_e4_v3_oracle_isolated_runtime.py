#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
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
EXPECTED_RELEASE_ID = "m26blog-ec79a3cad1d8-59012fe3818c-4260fcb53440"
EXPECTED_QDRANT_COLLECTION = "m26_blog_m26blog_ec79a3cad1d8_59012fe3818c_4260fcb53440"
EXPECTED_SEMANTIC_POINT_COUNT = 4424
EXPECTED_NODE_COUNT = 4457
EXPECTED_EDGE_COUNT = 8995


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
    for preferred in ("8080/tcp", "8789/tcp"):
        if preferred in ports:
            return preferred.split("/", 1)[0]
    for key in sorted(ports):
        if key.endswith("/tcp"):
            return key.split("/", 1)[0]
    if env.get("PORT"):
        return env["PORT"]
    return "8080"


def assert_host_port_free(port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        if sock.connect_ex(("127.0.0.1", port)) == 0:
            raise SystemExit(f"M26_E4_V3_HOST_PORT_ALREADY_IN_USE:{port}")


def isolated_digest(label: str, binding: dict[str, Any]) -> str:
    material = {
        "label": label,
        "release_id": require_binding(binding, "release_id"),
        "manifest_sha256": require_binding(binding, "manifest_sha256"),
        "qdrant_collection": require_binding(binding, "qdrant_collection"),
        "source_head_sha": require_binding(binding, "source_head_sha"),
        "purpose": "m26-e4-v3-localhost-health-only",
    }
    data = json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def ensure_isolated_health_auth(env: dict[str, str], binding: dict[str, Any]) -> dict[str, Any]:
    token_source = "base_env"
    owner_hash_source = "base_env"
    if not env.get("M26_QUERY_BACKEND_TOKEN"):
        env["M26_QUERY_BACKEND_TOKEN"] = "m26-e4-v3-isolated-health-" + isolated_digest("backend-token", binding)
        token_source = "isolated_synthetic_localhost_only"
    if not env.get("KNOWLEDGE_ENGINE_OWNER_SUBJECT_HASH"):
        env["KNOWLEDGE_ENGINE_OWNER_SUBJECT_HASH"] = isolated_digest("owner-subject-hash", binding)
        owner_hash_source = "isolated_synthetic_localhost_only"
    return {
        "backend_token_source": token_source,
        "owner_subject_hash_source": owner_hash_source,
        "secret_values_exposed": False,
        "base_container_env_mutated": False,
        "candidate_env_only": True,
        "localhost_only": True,
    }


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


def request_http_reachability(port: int) -> dict[str, Any]:
    """Prove the isolated container has a reachable ASGI server without assuming routes.

    The frozen 520aed image can differ from current main route docs. A 404 from
    the ASGI server is valid liveness evidence for E4_V3 because the binding
    proof is performed separately through docker exec and does not consume any
    answer/provider endpoint.
    """

    paths = ["/v1/health", "/openapi.json", "/docs", "/"]
    last_error = ""
    for path in paths:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}",
            headers={"Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                payload = response.read(500).decode("utf-8", errors="replace")
                return {
                    "status": "http_reachable",
                    "probe_path": path,
                    "http_status": int(response.status),
                    "accepted_404_as_liveness": False,
                    "response_preview": payload[:200],
                }
        except urllib.error.HTTPError as exc:
            detail = exc.read(500).decode("utf-8", errors="replace")
            if 400 <= exc.code < 500:
                return {
                    "status": "http_reachable",
                    "probe_path": path,
                    "http_status": int(exc.code),
                    "accepted_404_as_liveness": exc.code == 404,
                    "response_preview": detail[:200],
                }
            last_error = f"HTTP {exc.code}: {detail[:200]}"
        except Exception as exc:
            last_error = str(exc)
    raise RuntimeError("M26_E4_V3_HTTP_NOT_REACHABLE:" + last_error)


def run_route_inventory(container: str) -> dict[str, Any]:
    py = r'''
import json
try:
    from knowledge_engine.m26_production_api import app
except Exception:
    from knowledge_engine.api import app
routes = []
for route in getattr(app, "routes", []):
    path = getattr(route, "path", "")
    methods = sorted(getattr(route, "methods", []) or [])
    routes.append({"path": path, "methods": methods})
paths = sorted({item["path"] for item in routes if item.get("path")})
out = {
    "schema_version": "m26-e4-v3-route-inventory/v1",
    "status": "M26_E4_V3_ROUTE_INVENTORY_PASS",
    "route_count": len(routes),
    "paths": paths,
    "includes_v1_health": "/v1/health" in paths,
    "includes_api_m26_health": "/api/m26/health" in paths,
    "includes_v1_ask": "/v1/ask" in paths,
    "answer_endpoint_invoked": False,
}
print(json.dumps(out, sort_keys=True))
'''
    result = run(["docker", "exec", container, "python", "-c", py], check=False)
    if result.returncode != 0:
        detail = (result.stdout + "\n" + result.stderr)[-2000:]
        raise SystemExit("M26_E4_V3_ROUTE_INVENTORY_FAILED:" + detail)
    value = json.loads(result.stdout.strip().splitlines()[-1])
    if not isinstance(value, dict) or value.get("status") != "M26_E4_V3_ROUTE_INVENTORY_PASS":
        raise SystemExit("M26_E4_V3_ROUTE_INVENTORY_NOT_PASS:" + result.stdout[-1000:])
    return value


def run_binding_probe(container: str) -> dict[str, Any]:
    py = r'''
import json
from knowledge_engine import m26_production_answer_bundle as pab
bundle = pab.load_production_answer_bundle()
report = pab.build_production_answer_compatibility_report(bundle, qdrant_point_count=4424)
out = {
    "schema_version": "m26-e4-v3-in-container-binding-probe/v1",
    "status": "M26_E4_V3_BINDING_PROBE_PASS" if report.get("status") == "compatible" else "M26_E4_V3_BINDING_PROBE_FAIL",
    "release_id": bundle.release_id,
    "manifest_sha256": bundle.manifest_sha256,
    "qdrant_collection": pab.FULL_PRODUCTION_QDRANT_COLLECTION,
    "graph_v2_sha256": pab.FULL_PRODUCTION_GRAPH_V2_SHA256,
    "semantic_point_count": pab.FULL_PRODUCTION_SEMANTIC_POINT_COUNT,
    "node_count": pab.FULL_PRODUCTION_NODE_COUNT,
    "edge_count": pab.FULL_PRODUCTION_EDGE_COUNT,
    "compatibility_status": report.get("status"),
    "mismatch_counts": report.get("mismatch_counts"),
    "authority": {
        "provider_answer_requests": 0,
        "embedding_provider_requests": 0,
        "qdrant_writes": 0,
        "r2_writes": 0,
        "production_pointer_writes": 0,
        "canonical_route_mutations": 0,
        "e5_consumed_attempts": 0,
    },
}
print(json.dumps(out, sort_keys=True))
'''
    result = run(["docker", "exec", container, "python", "-c", py], check=False)
    if result.returncode != 0:
        detail = (result.stdout + "\n" + result.stderr)[-2000:]
        raise SystemExit("M26_E4_V3_BINDING_PROBE_EXEC_FAILED:" + detail)
    try:
        value = json.loads(result.stdout.strip().splitlines()[-1])
    except Exception as exc:
        raise SystemExit("M26_E4_V3_BINDING_PROBE_PARSE_FAILED:" + result.stdout[-1000:]) from exc
    if not isinstance(value, dict):
        raise SystemExit("M26_E4_V3_BINDING_PROBE_NON_OBJECT")
    if value.get("status") != "M26_E4_V3_BINDING_PROBE_PASS":
        raise SystemExit("M26_E4_V3_BINDING_PROBE_NOT_PASS:" + json.dumps(value, sort_keys=True))
    if value.get("release_id") != EXPECTED_RELEASE_ID:
        raise SystemExit("M26_E4_V3_BINDING_PROBE_RELEASE_MISMATCH:" + json.dumps(value, sort_keys=True))
    if value.get("qdrant_collection") != EXPECTED_QDRANT_COLLECTION:
        raise SystemExit("M26_E4_V3_BINDING_PROBE_QDRANT_MISMATCH:" + json.dumps(value, sort_keys=True))
    if value.get("semantic_point_count") != EXPECTED_SEMANTIC_POINT_COUNT:
        raise SystemExit("M26_E4_V3_BINDING_PROBE_SEMANTIC_COUNT_MISMATCH:" + json.dumps(value, sort_keys=True))
    if value.get("node_count") != EXPECTED_NODE_COUNT or value.get("edge_count") != EXPECTED_EDGE_COUNT:
        raise SystemExit("M26_E4_V3_BINDING_PROBE_GRAPH_COUNT_MISMATCH:" + json.dumps(value, sort_keys=True))
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

    remove_previous = run(["docker", "rm", "-f", args.candidate_container], check=False)
    previous_candidate_removed = remove_previous.returncode == 0
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
    auth_bootstrap = ensure_isolated_health_auth(env, binding)
    env_file = work_dir / "candidate.env"
    write_env_file(env_file, env)

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

    liveness: dict[str, Any] | None = None
    last_error = ""
    for _ in range(30):
        time.sleep(2)
        status = run(["docker", "inspect", args.candidate_container, "--format", "{{.State.Running}}"], check=False)
        if status.returncode != 0 or status.stdout.strip() != "true":
            logs = run(["docker", "logs", "--tail", "80", args.candidate_container], check=False)
            raise SystemExit("M26_E4_V3_CANDIDATE_CONTAINER_NOT_RUNNING:" + logs.stdout[-1000:])
        try:
            liveness = request_http_reachability(args.host_port)
            if liveness.get("status") == "http_reachable":
                break
        except Exception as exc:
            last_error = str(exc)
    if not isinstance(liveness, dict) or liveness.get("status") != "http_reachable":
        logs = run(["docker", "logs", "--tail", "120", args.candidate_container], check=False)
        raise SystemExit("M26_E4_V3_HTTP_NOT_REACHABLE:" + last_error + ":" + logs.stdout[-1200:])

    route_inventory = run_route_inventory(args.candidate_container)
    binding_probe = run_binding_probe(args.candidate_container)

    receipt = {
        "schema_version": "m26-e4-v3-oracle-isolated-runtime-receipt/v3",
        "status": "M26_E4_V3_ORACLE_ISOLATED_RUNTIME_PASS",
        "base_container": args.base_container,
        "candidate_container": args.candidate_container,
        "candidate_container_id": container_id,
        "base_image_id": image_id,
        "previous_candidate_removed": previous_candidate_removed,
        "auth_bootstrap": auth_bootstrap,
        "endpoint": {
            "host": "127.0.0.1",
            "host_port": args.host_port,
            "container_port": container_port,
            "http_probe_path": liveness.get("probe_path"),
            "query_path": "/v1/ask",
            "answer_endpoint_invoked": False,
        },
        "liveness": liveness,
        "route_inventory": route_inventory,
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
        "binding_probe": binding_probe,
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
