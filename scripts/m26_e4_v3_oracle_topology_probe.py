#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
from typing import Any

FROZEN_BASE_CONTAINER = "m26-public-api-production-repair2-ownerhash-r2-auth-520aed"

NONSECRET_ENV_NAMES = {
    "M26_QUERY_BUILD_SHA",
    "M26_PA7_DENSE_COLLECTION",
    "M26_QUERY_REQUIRE_REMOTE_DENSE",
    "KNOWLEDGE_CHANNEL",
    "APP_ENV",
    "OBJECT_STORE_BACKEND",
}

SECRET_ENV_NAMES = {
    "R2_ENDPOINT_URL",
    "R2_BUCKET",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "QDRANT_URL",
    "QDRANT_API_KEY",
    "CLOUDFLARE_ACCOUNT_ID",
    "CLOUDFLARE_API_TOKEN",
    "CLOUDFLARE_AI_TOKEN",
    "MINIMAX_API_KEY",
    "M26_QUERY_BACKEND_TOKEN",
    "KNOWLEDGE_ENGINE_OWNER_SUBJECT_HASH",
}

RUNTIME_MODULES = [
    "knowledge_engine.m26_aq_semantic_contract",
    "knowledge_engine.m26_pa7_arbitrary_query_runtime",
    "knowledge_engine.m26_production_answer_bundle",
    "knowledge_engine.m26_verified_answer_citation_gate",
    "knowledge_engine.m26_pa5_v8_live",
    "knowledge_engine.m26_cloudflare_provider_router",
    "knowledge_engine.m26_ask_api",
]


def run(args: list[str]) -> str:
    return subprocess.run(args, text=True, capture_output=True, check=True).stdout.strip()


def env_summary(rows: list[str]) -> tuple[dict[str, str], dict[str, dict[str, int | bool]]]:
    selected_nonsecret: dict[str, str] = {}
    secret_presence: dict[str, dict[str, int | bool]] = {}
    for row in rows:
        if "=" not in row:
            continue
        name, value = row.split("=", 1)
        if name in NONSECRET_ENV_NAMES:
            selected_nonsecret[name] = value
        elif name in SECRET_ENV_NAMES:
            secret_presence[name] = {"present": bool(value), "length": len(value)}
    return selected_nonsecret, secret_presence


def runtime_module_hashes(container: str) -> dict[str, Any]:
    script = r'''
import importlib, hashlib, json, pathlib
mods = REPLACE_MODULES
out = {}
for name in mods:
    try:
        mod = importlib.import_module(name)
        path = pathlib.Path(mod.__file__).resolve()
        data = path.read_bytes()
        out[name] = {"path": str(path), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    except Exception as exc:
        out[name] = {"error": type(exc).__name__ + ":" + str(exc)[:160]}
print(json.dumps(out, sort_keys=True))
'''.replace("REPLACE_MODULES", repr(RUNTIME_MODULES))
    return json.loads(run(["docker", "exec", container, "python", "-c", script]))


def sha_runtime_candidates(container: str) -> dict[str, str]:
    script = r'''
import hashlib, json, pathlib
out = {}
for root in ("/app", "/workspace", "/opt"):
    p = pathlib.Path(root)
    if not p.exists():
        continue
    for path in sorted(p.rglob("*.py")):
        try:
            data = path.read_bytes()
        except Exception:
            continue
        if b"m26" in data or b"knowledge_engine" in data or b"FULL_PRODUCTION_RELEASE_ID" in data:
            out[str(path)] = hashlib.sha256(data).hexdigest()
print(json.dumps(out, sort_keys=True))
'''
    return json.loads(run(["docker", "exec", container, "python", "-c", script]))


def main() -> None:
    docker_names = run(["docker", "ps", "-a", "--format", "{{.Names}}"]).splitlines()
    if FROZEN_BASE_CONTAINER not in docker_names:
        raise SystemExit("M26_E4_V3_FROZEN_BASE_CONTAINER_MISSING")

    inspected = json.loads(run(["docker", "inspect", FROZEN_BASE_CONTAINER]))[0]
    image_id = inspected["Image"]
    config = inspected.get("Config") or {}
    host_config = inspected.get("HostConfig") or {}
    network_settings = inspected.get("NetworkSettings") or {}
    selected_nonsecret, secret_presence = env_summary(config.get("Env") or [])

    image_meta = json.loads(run(["docker", "image", "inspect", image_id]))[0]
    ports = {
        key: [{"host_ip": row.get("HostIp"), "host_port": row.get("HostPort")} for row in (value or [])]
        for key, value in (network_settings.get("Ports") or {}).items()
    }
    mounts = [
        {"type": item.get("Type"), "destination": item.get("Destination"), "rw": item.get("RW")}
        for item in inspected.get("Mounts") or []
    ]

    out = {
        "schema_version": "m26-e4-v3-oracle-topology-probe/v2",
        "status": "M26_E4_V3_ORACLE_TOPOLOGY_PROBE_PASS",
        "container": FROZEN_BASE_CONTAINER,
        "image_id": image_id,
        "configured_image": config.get("Image"),
        "repo_digests": image_meta.get("RepoDigests") or [],
        "entrypoint": config.get("Entrypoint"),
        "cmd": config.get("Cmd"),
        "working_dir": config.get("WorkingDir"),
        "restart_policy": (host_config.get("RestartPolicy") or {}).get("Name"),
        "network_mode": host_config.get("NetworkMode"),
        "networks": sorted((network_settings.get("Networks") or {}).keys()),
        "ports": ports,
        "mounts": mounts,
        "selected_nonsecret_env": selected_nonsecret,
        "secret_presence": secret_presence,
        "module_hashes": runtime_module_hashes(FROZEN_BASE_CONTAINER),
        "runtime_py_hashes": sha_runtime_candidates(FROZEN_BASE_CONTAINER),
        "authority": {
            "semantic_requests": 0,
            "provider_answer_requests": 0,
            "qdrant_writes": 0,
            "r2_writes": 0,
            "production_pointer_writes": 0,
            "canonical_route_mutations": 0,
            "container_mutations": 0,
        },
    }
    print(json.dumps(out, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
