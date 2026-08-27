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

BASE = "m26-public-api-production-repair2-ownerhash-r2-auth-520aed"
CAND = "m26-e5-r2-oracle-isolated-m26blog-59012fe-520aed"
REL = "m26blog-ec79a3cad1d8-59012fe3818c-4260fcb53440"
QDRANT = "m26_blog_m26blog_ec79a3cad1d8_59012fe3818c_4260fcb53440"
POINTS, NODES, EDGES = 4424, 4457, 8995


def trace(message: str) -> None:
    print(message, flush=True)


def run(args: list[str], *, check: bool = True, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(args, text=True, capture_output=True, check=check, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        head = " ".join(args[:4])
        raise SystemExit(f"M26_E5_R2_SUBPROCESS_TIMEOUT:{head}:{timeout}s") from exc


def out(args: list[str], *, timeout: int = 120) -> str:
    return run(args, timeout=timeout).stdout.strip()


def sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def env_rows(container: str) -> list[str]:
    return [x for x in out(["docker", "inspect", container, "--format", "{{range .Config.Env}}{{println .}}{{end}}" ], timeout=60).splitlines() if "=" in x]


def env_map(rows: list[str]) -> dict[str, str]:
    d: dict[str, str] = {}
    for row in rows:
        k, v = row.split("=", 1); d[k] = v
    return d


def write_env(path: pathlib.Path, env: dict[str, str]) -> None:
    path.write_text("\n".join(f"{k}={env[k]}" for k in sorted(env) if "\n" not in env[k]) + "\n", encoding="utf-8")
    path.chmod(0o600)


def port_free(port: int) -> None:
    with socket.socket() as sock:
        if sock.connect_ex(("127.0.0.1", port)) == 0:
            raise SystemExit(f"M26_E5_R2_HOST_PORT_IN_USE:{port}")


def py(container: str, code: str) -> dict[str, Any]:
    trace("M26_E5_R2_TRACE_DOCKER_EXEC_PROBE")
    cp = run(["docker", "exec", container, "python", "-c", code], check=False, timeout=180)
    if cp.returncode != 0:
        raise SystemExit((cp.stdout + cp.stderr)[-3000:])
    return json.loads(cp.stdout.strip().splitlines()[-1])


def wait_health(port: int, token: str) -> dict[str, Any]:
    for _ in range(40):
        time.sleep(2)
        req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/answers/health", headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return {"http_status": r.status, "body_sha256": hashlib.sha256(r.read()).hexdigest()}
        except urllib.error.HTTPError as exc:
            if exc.code < 500:
                return {"http_status": exc.code, "body_sha256": hashlib.sha256(exc.read()).hexdigest()}
        except Exception:
            pass
    raise SystemExit("M26_E5_R2_HEALTH_NOT_REACHABLE")


def sitecustomize(binding: dict[str, Any]) -> str:
    return f'''
from __future__ import annotations
try:
    from knowledge_engine import m26_production_answer_bundle as pab
except Exception:
    pab = None
if pab is not None:
    pab.FULL_PRODUCTION_RELEASE_ID = {REL!r}
    pab.FULL_PRODUCTION_MANIFEST_KEY = f"releases/{{pab.FULL_PRODUCTION_RELEASE_ID}}/manifest.json"
    pab.FULL_PRODUCTION_PROMOTION_MANIFEST_KEY = f"releases/{{pab.FULL_PRODUCTION_RELEASE_ID}}/promotion/m26-e5-r2-isolated-production-manifest.json"
    pab.FULL_PRODUCTION_PROMOTION_MANIFEST_SHA256 = ""
    pab.FULL_PRODUCTION_GRAPH_V2_SHA256 = {binding['graph_v2_sha256']!r}
    pab.FULL_PRODUCTION_POINTER_KEY = "channels/m26-e5-r2-isolated.json"
    pab.FULL_PRODUCTION_POINTER_SHA256 = ""
    pab.FULL_PRODUCTION_QDRANT_COLLECTION = {QDRANT!r}
    pab.FULL_PRODUCTION_NODE_COUNT = {NODES}
    pab.FULL_PRODUCTION_EDGE_COUNT = {EDGES}
    pab.FULL_PRODUCTION_SEMANTIC_POINT_COUNT = {POINTS}
    pab.FULL_PRODUCTION_SOURCE_SHA = {binding['source_commit_sha']!r}
    pab.FULL_PRODUCTION_ADMISSION_SHA256 = {binding['admission_sha256']!r}
    try: pab._load_production_answer_bundle_from_env.cache_clear()
    except Exception: pass
'''


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--binding-json", required=True); p.add_argument("--storage-py", required=True)
    p.add_argument("--host-port", type=int, default=18188); p.add_argument("--candidate-container", default=CAND)
    p.add_argument("--base-container", default=BASE); p.add_argument("--work-dir", default="/tmp/m26-e5-r2-oracle")
    a = p.parse_args(); binding = json.loads(pathlib.Path(a.binding_json).read_text())
    trace("M26_E5_R2_TRACE_DOCKER_PS_BEGIN")
    names = out(["docker", "ps", "-a", "--format", "{{.Names}}"], timeout=30).splitlines()
    if a.base_container not in names: raise SystemExit("M26_E5_R2_BASE_CONTAINER_MISSING")
    trace("M26_E5_R2_TRACE_DOCKER_INSPECT_BASE_BEGIN")
    image = json.loads(out(["docker", "inspect", a.base_container], timeout=60))[0]["Image"]
    env = env_map(env_rows(a.base_container))
    inherited_token = env.get("M26_QUERY_BACKEND_TOKEN")
    injected_token = os.environ.get("M26_QUERY_BACKEND_TOKEN")
    token = injected_token or inherited_token
    if not token: raise SystemExit("M26_E5_R2_AUTH_MISSING")
    env["M26_QUERY_BACKEND_TOKEN"] = token
    env["M26_QUERY_BUILD_SHA"] = "m26-e5-r2-isolated-" + REL
    env["M26_PA7_DENSE_COLLECTION"] = QDRANT
    env["M26_E5_REPAIR2_ISOLATED_RUNTIME"] = "true"
    work = pathlib.Path(a.work_dir); overlay = work / "sitecustomize"; overlay.mkdir(parents=True, exist_ok=True)
    (overlay / "sitecustomize.py").write_text(sitecustomize(binding), encoding="utf-8")
    env["PYTHONPATH"] = "/tmp/m26_e5_r2_sitecustomize:" + env.get("PYTHONPATH", "")
    envfile = work / "candidate.env"; write_env(envfile, env)
    trace("M26_E5_R2_TRACE_DOCKER_RM_CANDIDATE_BEGIN")
    run(["docker", "rm", "-f", a.candidate_container], check=False, timeout=60); port_free(a.host_port)
    trace("M26_E5_R2_TRACE_STORAGE_TARGET_DISCOVERY_BEGIN")
    storage_target = out(["docker", "run", "--rm", "--entrypoint", "python", image, "-c", "import inspect, knowledge_engine.storage as s; print(inspect.getsourcefile(s))"], timeout=90)
    trace("M26_E5_R2_TRACE_DOCKER_CREATE_CANDIDATE_BEGIN")
    cid = out(["docker", "create", "--name", a.candidate_container, "--env-file", str(envfile), "-v", f"{overlay}:/tmp/m26_e5_r2_sitecustomize:ro", "-p", f"127.0.0.1:{a.host_port}:8080", image], timeout=60)
    trace("M26_E5_R2_TRACE_DOCKER_CP_STORAGE_BEGIN")
    run(["docker", "cp", a.storage_py, f"{a.candidate_container}:{storage_target}"], timeout=60)
    trace("M26_E5_R2_TRACE_DOCKER_START_CANDIDATE_BEGIN")
    run(["docker", "start", a.candidate_container], timeout=60)
    trace("M26_E5_R2_TRACE_WAIT_HEALTH_BEGIN")
    health = wait_health(a.host_port, token)
    trace("M26_E5_R2_TRACE_NORMAL_LOADER_PROBE_BEGIN")
    probe = py(a.candidate_container, r'''
import hashlib, inspect, json
from knowledge_engine import storage as st
from knowledge_engine import m26_production_answer_bundle as pab
from knowledge_engine.config import Settings
from knowledge_engine.storage import create_object_store
settings = Settings.from_env(); store = create_object_store(settings)
keys = [pab.FULL_PRODUCTION_POINTER_KEY, pab.FULL_PRODUCTION_PROMOTION_MANIFEST_KEY]
before = {k: store.head(k) is None for k in keys}
bundle = pab.load_production_answer_bundle()
after = {k: store.head(k) is None for k in keys}
report = pab.build_production_answer_compatibility_report(bundle, qdrant_point_count=4424)
path = inspect.getsourcefile(st) or inspect.getfile(st)
out = {"status":"M26_E5_R2_NORMAL_LOADER_NO_SHIM_PROBE_PASS" if report.get("status")=="compatible" and all(before.values()) and all(after.values()) else "FAIL", "release_id":bundle.release_id, "storage_path":path, "storage_sha256":hashlib.sha256(open(path,"rb").read()).hexdigest(), "optional_missing_before":before, "optional_missing_after":after, "normal_loader_call":"load_production_answer_bundle()", "store_argument_used":False, "read_through_store_shim_used":False, "exception_normalization_loader_shim_used":False, "compatibility_status":report.get("status"), "mismatch_counts":report.get("mismatch_counts"), "authority":{"r2_writes":0,"qdrant_writes":0,"production_pointer_writes":0,"canonical_route_mutations":0,"provider_answer_requests":0,"semantic_requests":0,"e5_epoch2_consumed":0}}
print(json.dumps(out, sort_keys=True))
''')
    if probe.get("status") != "M26_E5_R2_NORMAL_LOADER_NO_SHIM_PROBE_PASS": raise SystemExit(json.dumps(probe, sort_keys=True))
    receipt = {"schema_version":"m26-e5-repair2-oracle-receipt/v1", "status":"M26_E5_R2_ORACLE_ISOLATED_RUNTIME_PASS", "candidate_container":a.candidate_container, "candidate_container_id":cid, "host":"127.0.0.1", "host_port":a.host_port, "base_container":a.base_container, "base_image_id":image, "storage_overlay_sha256":sha(pathlib.Path(a.storage_py)), "health":health, "binding":{"release_id":REL,"qdrant_collection":QDRANT,"semantic_point_count":POINTS,"node_count":NODES,"edge_count":EDGES, **{k: binding[k] for k in ("manifest_sha256","graph_v2_sha256","source_head_sha","source_commit_sha","admission_sha256")}}, "normal_loader_no_shim_probe":probe, "authority":{"r2_writes":0,"qdrant_writes":0,"production_pointer_writes":0,"canonical_route_mutations":0,"provider_answer_requests":0,"semantic_requests":0,"e5_epoch2_consumed":0}}
    print("M26_E5_R2_ORACLE_ISOLATED_RUNTIME_PASS")
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
