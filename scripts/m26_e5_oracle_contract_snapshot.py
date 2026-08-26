#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
import subprocess

C = "m26-e4-v3-oracle-isolated-m26blog-59012fe-520aed"
CID = "3c5b31fa49daa9fbcfe3a438261801035a2be6538770f3950b52f11ced802bad"
IMG = "sha256:7b2bdc32a3ed769f068b885e171fe31da10f33f1335b778b8bfb89ccb1523919"
AUTH = "M26_QUERY_BACKEND_TOKEN"
MODULES = [
    "knowledge_engine.m26_translation_gateway_public_api",
    "knowledge_engine.m26_translation_gateway",
    "knowledge_engine.m26_ask_api",
    "knowledge_engine.m26_aq_semantic_contract",
    "knowledge_engine.m26_pa7_arbitrary_query_runtime",
    "knowledge_engine.m26_verified_answer_citation_gate",
    "knowledge_engine.m26_answer_evaluation",
    "knowledge_engine.m26_multilingual_publication_adapter",
]


def run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, check=check)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write(path: pathlib.Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    out = pathlib.Path("/tmp/m26-e5-repair1-contract-snapshot")
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)

    inspected = json.loads(run(["docker", "inspect", C]).stdout)[0]
    assert inspected["Id"] == CID, "candidate id mismatch"
    assert inspected["Image"] == IMG, "image id mismatch"
    assert inspected["State"]["Running"] is True, "candidate not running"

    bindings = ((inspected.get("NetworkSettings") or {}).get("Ports") or {}).get("8080/tcp") or []
    assert any(row.get("HostIp") == "127.0.0.1" and row.get("HostPort") == "18187" for row in bindings), "18187 binding mismatch"

    env: dict[str, str] = {}
    for row in (inspected.get("Config") or {}).get("Env") or []:
        if "=" in row:
            key, value = row.split("=", 1)
            env[key] = value
    assert env.get(AUTH), "candidate auth source missing"

    write(
        out / "identity_auth_zero.json",
        {
            "container_id_exact": True,
            "image_id_exact": True,
            "running": True,
            "localhost_18187": True,
            "auth_env_key": AUTH,
            "auth_value_present": True,
            "auth_value_artifacted": False,
            "auth_value_logged": False,
            "semantic_posts": 0,
            "e5_consumed": 0,
            "rerolls": 0,
            "production_mutations": 0,
        },
    )

    module_inventory_code = """
import importlib
import inspect
import json
mods = %r
out = []
for name in mods:
    try:
        module = importlib.import_module(name)
        path = inspect.getsourcefile(module) or inspect.getfile(module)
        out.append({"module": name, "path": path})
    except Exception as exc:
        out.append({"module": name, "error": type(exc).__name__})
print(json.dumps(out, sort_keys=True))
""" % MODULES
    cp = run(["docker", "exec", C, "python", "-c", module_inventory_code], check=False)
    if cp.returncode:
        raise SystemExit("module inventory failed:" + cp.stderr[-1000:])
    inventory = json.loads(cp.stdout.strip().splitlines()[-1])
    write(out / "module_inventory.json", inventory)

    srcdir = out / "candidate_source"
    srcdir.mkdir()
    manifest: list[dict[str, str]] = []
    for index, row in enumerate(inventory):
        path = row.get("path")
        if not path or not str(path).endswith(".py"):
            continue
        artifact_file = f"{index:02d}_{pathlib.Path(path).name}"
        dest = srcdir / artifact_file
        copy = run(["docker", "cp", f"{C}:{path}", str(dest)], check=False)
        if copy.returncode == 0 and dest.is_file():
            manifest.append(
                {
                    "module": row["module"],
                    "container_path": path,
                    "artifact_file": artifact_file,
                    "sha256": sha(dest.read_bytes()),
                }
            )
    write(out / "source_manifest.json", {"files": manifest})

    structural_code = """
import inspect
import json
from knowledge_engine.m26_translation_gateway_public_api import app, _answer_event_stream, _resolve_answer
route = next(
    route for route in app.routes
    if getattr(route, "path", None) == "/v1/answers"
    and "POST" in (getattr(route, "methods", set()) or set())
)
stream_source = inspect.getsource(_answer_event_stream)
print(json.dumps({
    "path": route.path,
    "methods": sorted(route.methods),
    "endpoint_module": route.endpoint.__module__,
    "endpoint_qualname": route.endpoint.__qualname__,
    "stream_generator_module": _answer_event_stream.__module__,
    "stream_generator_qualname": _answer_event_stream.__qualname__,
    "resolve_answer_module": _resolve_answer.__module__,
    "resolve_answer_qualname": _resolve_answer.__qualname__,
    "media_type_literal_present": "text/event-stream" in inspect.getsource(route.endpoint),
    "event_sequence_literals": [
        name for name in ["meta", "progress", "answer", "done", "error"]
        if (f'"{name}"' in stream_source or f"'{name}'" in stream_source)
    ],
    "semantic_posts": 0,
}, sort_keys=True))
"""
    cp = run(["docker", "exec", C, "python", "-c", structural_code], check=False)
    if cp.returncode:
        raise SystemExit("route structural snapshot failed:" + (cp.stderr + cp.stdout)[-1500:])
    write(out / "route_structural_contract.json", json.loads(cp.stdout.strip().splitlines()[-1]))

    print("M26_E5_REPAIR1_CONTRACT_SNAPSHOT_PASS")
    print(
        json.dumps(
            {
                "status": "M26_E5_REPAIR1_CONTRACT_SNAPSHOT_PASS",
                "source_files": len(manifest),
                "semantic_posts": 0,
                "e5_consumed": 0,
                "rerolls": 0,
                "production_mutations": 0,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
