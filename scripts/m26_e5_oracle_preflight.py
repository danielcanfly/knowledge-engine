#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from typing import Any

EXPECTED_CONTAINER = "m26-e4-v3-oracle-isolated-m26blog-59012fe-520aed"
EXPECTED_CONTAINER_ID = "3c5b31fa49daa9fbcfe3a438261801035a2be6538770f3950b52f11ced802bad"
EXPECTED_IMAGE_ID = "sha256:7b2bdc32a3ed769f068b885e171fe31da10f33f1335b778b8bfb89ccb1523919"
EXPECTED_HOST_PORT = 18187
EXPECTED_CONTAINER_PORT = "8080/tcp"
EXPECTED_ROUTE = "/v1/answers"
EXPECTED_HEALTH_ROUTE = "/v1/answers/health"
EXPECTED_RELEASE_ID = "m26blog-ec79a3cad1d8-59012fe3818c-4260fcb53440"
EXPECTED_QDRANT = "m26_blog_m26blog_ec79a3cad1d8_59012fe3818c_4260fcb53440"
EXPECTED_SOURCE_HEAD = "a738f20b16f10925c8adfe4d625be8db30fb269c"
EXPECTED_SOURCE_COMMIT = "f5e20062c140b94e3eab8080a311dcac8d15cab2"
AUTH_ENV_KEY = "M26_QUERY_BACKEND_TOKEN"


def run(args: list[str], *, check: bool = True, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, input=input_text, text=True, capture_output=True, check=check)


def docker_inspect(container: str) -> dict[str, Any]:
    cp = run(["docker", "inspect", container])
    rows = json.loads(cp.stdout)
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise SystemExit("M26_E5_PREFLIGHT_CONTAINER_INSPECT_INVALID")
    return rows[0]


def parse_env(rows: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in rows:
        if "=" in row:
            k, v = row.split("=", 1)
            out[k] = v
    return out


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: pathlib.Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def safe_http_get(url: str, token: str | None = None) -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            body = response.read(2_000_000)
            return {
                "http_status": int(response.status),
                "content_type": response.headers.get("content-type", ""),
                "body": body,
            }
    except urllib.error.HTTPError as exc:
        body = exc.read(2_000_000)
        return {
            "http_status": int(exc.code),
            "content_type": exc.headers.get("content-type", "") if exc.headers else "",
            "body": body,
        }


def candidate_introspection(container: str) -> dict[str, Any]:
    code = r'''
from __future__ import annotations
import ast, hashlib, inspect, json, pathlib
try:
    from knowledge_engine.m26_production_api import app
except Exception:
    from knowledge_engine.api import app

route = None
for r in getattr(app, "routes", []):
    if getattr(r, "path", None) == "/v1/answers" and "POST" in (getattr(r, "methods", set()) or set()):
        route = r
        break
if route is None:
    raise SystemExit("M26_E5_PREFLIGHT_V1_ANSWERS_ROUTE_MISSING")
endpoint = getattr(route, "endpoint", None)
module = inspect.getmodule(endpoint)
source_file = inspect.getsourcefile(endpoint) or inspect.getfile(endpoint)
source = inspect.getsource(endpoint) if endpoint is not None else ""
module_source = pathlib.Path(source_file).read_text(encoding="utf-8") if source_file else ""

known_events = {
    "meta","progress","answer","done","answer_completed","answer_partial",
    "answer_abstained","abstained","error","answer_failed","failed"
}
known_fields = {
    "answer","final_answer","answer_text","text","content","message","output","result","data",
    "sources","citations","support","references","evidence","context",
    "status","terminal_status","safe_abstention","reason_codes","semantic_closure","accounting","integrity",
    "selected_evidence"
}
string_literals = set()
try:
    tree = ast.parse(module_source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            string_literals.add(node.value)
except Exception:
    pass

def contains_token(token: str) -> bool:
    if token in string_literals:
        return True
    quoted = (f"'{token}'", f'"{token}"')
    return any(q in module_source for q in quoted)

schema = app.openapi()
operation = ((schema.get("paths") or {}).get("/v1/answers") or {}).get("post") or {}
security_schemes = ((schema.get("components") or {}).get("securitySchemes") or {})

endpoint_dir = pathlib.Path(source_file).resolve().parent if source_file else pathlib.Path("/")
selected_files = []
for p in sorted(endpoint_dir.glob("*.py")):
    n = p.name.lower()
    if any(tok in n for tok in ("answer", "api", "adapter", "stream", "query", "production")):
        selected_files.append(str(p))

out = {
    "route": {
        "path": getattr(route, "path", None),
        "methods": sorted(getattr(route, "methods", set()) or set()),
        "response_class": getattr(getattr(route, "response_class", None), "__name__", str(getattr(route, "response_class", None))),
        "endpoint_module": getattr(module, "__name__", None),
        "endpoint_qualname": getattr(endpoint, "__qualname__", None),
        "endpoint_source_file": source_file,
        "endpoint_source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "module_source_sha256": hashlib.sha256(module_source.encode("utf-8")).hexdigest(),
    },
    "openapi_operation": operation,
    "security_schemes": security_schemes,
    "contract_candidates": {
        "event_names_present_in_endpoint_module": sorted(x for x in known_events if contains_token(x)),
        "payload_fields_present_in_endpoint_module": sorted(x for x in known_fields if contains_token(x)),
    },
    "selected_source_files": selected_files,
}
print(json.dumps(out, ensure_ascii=False, sort_keys=True))
'''
    cp = run(["docker", "exec", container, "python", "-c", code], check=False)
    if cp.returncode != 0:
        raise SystemExit("M26_E5_PREFLIGHT_CANDIDATE_INTROSPECTION_FAILED:" + (cp.stderr + cp.stdout)[-2000:])
    line = cp.stdout.strip().splitlines()[-1]
    value = json.loads(line)
    if not isinstance(value, dict):
        raise SystemExit("M26_E5_PREFLIGHT_CANDIDATE_INTROSPECTION_NON_OBJECT")
    return value


def copy_candidate_sources(container: str, files: list[str], dest: pathlib.Path) -> list[dict[str, str]]:
    dest.mkdir(parents=True, exist_ok=True)
    copied: list[dict[str, str]] = []
    for i, src in enumerate(files):
        src = str(src)
        if not src.startswith("/") or not src.endswith(".py"):
            continue
        name = f"{i:02d}_{pathlib.Path(src).name}"
        target = dest / name
        cp = run(["docker", "cp", f"{container}:{src}", str(target)], check=False)
        if cp.returncode != 0 or not target.is_file():
            continue
        data = target.read_bytes()
        copied.append({"container_path": src, "artifact_file": name, "sha256": sha256_bytes(data)})
    return copied


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output-dir", default="/tmp/m26-e5-repair1-preflight")
    args = ap.parse_args()

    outdir = pathlib.Path(args.output_dir)
    if outdir.exists():
        shutil.rmtree(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    inspected = docker_inspect(EXPECTED_CONTAINER)
    container_id = str(inspected.get("Id") or "")
    image_id = str(inspected.get("Image") or "")
    running = bool(((inspected.get("State") or {}).get("Running")))
    restart_count = int(inspected.get("RestartCount") or 0)
    ports = ((inspected.get("NetworkSettings") or {}).get("Ports") or {})
    binding = ports.get(EXPECTED_CONTAINER_PORT) or []
    local_binding_ok = any(
        str(row.get("HostIp")) == "127.0.0.1" and str(row.get("HostPort")) == str(EXPECTED_HOST_PORT)
        for row in binding if isinstance(row, dict)
    )
    env_rows = [x for x in ((inspected.get("Config") or {}).get("Env") or []) if isinstance(x, str)]
    env = parse_env(env_rows)
    token = env.get(AUTH_ENV_KEY, "")

    identity = {
        "container_name": EXPECTED_CONTAINER,
        "container_id": container_id,
        "container_id_expected": EXPECTED_CONTAINER_ID,
        "container_id_exact": container_id == EXPECTED_CONTAINER_ID,
        "image_id": image_id,
        "image_id_expected": EXPECTED_IMAGE_ID,
        "image_id_exact": image_id == EXPECTED_IMAGE_ID,
        "running": running,
        "restart_count": restart_count,
        "host_binding": binding,
        "localhost_18187_exact": local_binding_ok,
        "expected_source_head": EXPECTED_SOURCE_HEAD,
        "expected_source_commit": EXPECTED_SOURCE_COMMIT,
        "expected_release_id": EXPECTED_RELEASE_ID,
        "expected_qdrant_collection": EXPECTED_QDRANT,
    }
    write_json(outdir / "identity.json", identity)

    if not running:
        raise SystemExit("M26_E5_PREFLIGHT_EXACT_CANDIDATE_NOT_RUNNING")
    if container_id != EXPECTED_CONTAINER_ID:
        raise SystemExit("M26_E5_PREFLIGHT_CANDIDATE_ID_MISMATCH")
    if image_id != EXPECTED_IMAGE_ID:
        raise SystemExit("M26_E5_PREFLIGHT_IMAGE_ID_MISMATCH")
    if not local_binding_ok:
        raise SystemExit("M26_E5_PREFLIGHT_LOCALHOST_18187_BINDING_MISMATCH")
    if not token:
        raise SystemExit(f"M26_E5_PREFLIGHT_AUTH_ENV_MISSING:{AUTH_ENV_KEY}")

    auth_meta = {
        "header": "Authorization",
        "scheme": "Bearer",
        "source": "exact_candidate_container_env",
        "source_env_key": AUTH_ENV_KEY,
        "token_present": True,
        "token_value_artifacted": False,
        "token_value_logged": False,
        "memory_only_use": True,
    }
    write_json(outdir / "auth_contract.json", auth_meta)

    health = safe_http_get(f"http://127.0.0.1:{EXPECTED_HOST_PORT}{EXPECTED_HEALTH_ROUTE}", token)
    health_body = health.pop("body")
    health["body_sha256"] = sha256_bytes(health_body)
    try:
        parsed_health = json.loads(health_body.decode("utf-8"))
    except Exception:
        parsed_health = {"body_preview": health_body.decode("utf-8", errors="replace")[:1000]}
    health["body"] = parsed_health
    write_json(outdir / "answers_health.json", health)
    if health["http_status"] != 200:
        raise SystemExit(f"M26_E5_PREFLIGHT_ANSWERS_HEALTH_HTTP_{health['http_status']}")

    introspection = candidate_introspection(EXPECTED_CONTAINER)
    write_json(outdir / "route_contract.json", introspection)
    if ((introspection.get("route") or {}).get("path")) != EXPECTED_ROUTE:
        raise SystemExit("M26_E5_PREFLIGHT_ROUTE_PATH_MISMATCH")
    if "POST" not in (((introspection.get("route") or {}).get("methods")) or []):
        raise SystemExit("M26_E5_PREFLIGHT_ROUTE_NOT_POST")

    copied = copy_candidate_sources(EXPECTED_CONTAINER, introspection.get("selected_source_files") or [], outdir / "candidate_source")
    write_json(outdir / "candidate_source_manifest.json", {"files": copied})

    code = r'''
import json
try:
    from knowledge_engine.m26_production_api import app
except Exception:
    from knowledge_engine.api import app
print(json.dumps(app.openapi(), ensure_ascii=False, sort_keys=True))
'''
    cp = run(["docker", "exec", EXPECTED_CONTAINER, "python", "-c", code], check=False)
    if cp.returncode != 0:
        raise SystemExit("M26_E5_PREFLIGHT_OPENAPI_INTROSPECTION_FAILED")
    openapi_raw = cp.stdout.strip().splitlines()[-1].encode("utf-8")
    openapi = json.loads(openapi_raw.decode("utf-8"))
    write_json(outdir / "openapi.json", openapi)

    zero = {
        "semantic_posts_sent_by_preflight": 0,
        "provider_answer_requests_by_preflight": 0,
        "e5_consumed_attempts_by_preflight": 0,
        "rerolls_by_preflight": 0,
        "candidate_mutations": 0,
        "production_pointer_mutations": 0,
        "canonical_route_mutations": 0,
        "r2_writes": 0,
        "qdrant_writes": 0,
        "source_repo_mutations": 0,
    }
    write_json(outdir / "zero_consumption.json", zero)

    receipt = {
        "status": "M26_E5_REPAIR1_READONLY_PREFLIGHT_PASS",
        "exact_candidate_identity": True,
        "localhost_18187": True,
        "candidate_auth_source_verified": True,
        "answers_health_authenticated_get": True,
        "implementation_openapi_inspected_readonly": True,
        "semantic_posts": 0,
        "e5_consumed": 0,
        "rerolls": 0,
        "production_mutations": 0,
        "source_files_copied": len(copied),
        "route_source_sha256": ((introspection.get("route") or {}).get("endpoint_source_sha256")),
        "route_module_sha256": ((introspection.get("route") or {}).get("module_source_sha256")),
    }
    write_json(outdir / "preflight_receipt.json", receipt)
    print("M26_E5_REPAIR1_READONLY_PREFLIGHT_PASS")
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
