from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

EXPECTED_EVIDENCE_SHA256 = "1b71c79ed3fddc24abfb510709a08e6a1ad0a3806df23287d2d14a70994f7272"
DEFAULT_EVIDENCE_KEY = (
    "diagnostic/m23-7/r3-8/M23.5_Cloudflare_BGE_M3_20260714T164215Z.zip"
)
EXPECTED_BUCKET = "llm-wiki-bucket"
WRANGLER_VERSION = "4.111.0"
WORKER_PREFIX = "knowledge-engine-r3-8-"
WORKER_ROUTE = "/v1/m23-7-r3-8/observe"
MAX_EVIDENCE_BYTES = 20_000_000
MAX_WRANGLER_OUTPUT_BYTES = 1_000_000
LIFECYCLE_SCHEMA = "knowledge-engine-m23-7-r3-8-remote-lifecycle/v1"
REMOTE_RECEIPT_SCHEMA = "knowledge-engine-m23-7-r3-8-remote-observation/v1"

_HEX_40 = re.compile(r"^[0-9a-f]{40}$")
_WORKER = re.compile(r"^knowledge-engine-r3-8-[0-9]{1,20}$")


class RemoteOperatorError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RemoteOperatorError(f"missing_{name.lower()}")
    return value


def derive_worker_name(run_id: str, run_attempt: int) -> str:
    if not run_id.isdigit() or not 1 <= len(run_id) <= 20:
        raise RemoteOperatorError("invalid_run_id")
    if run_attempt != 1:
        raise RemoteOperatorError("rerun_attempt_forbidden")
    name = f"{WORKER_PREFIX}{run_id}"
    if not _WORKER.fullmatch(name) or len(name) > 63:
        raise RemoteOperatorError("invalid_worker_name")
    return name


def validate_evidence_key(value: str) -> str:
    key = value.strip()
    if key != DEFAULT_EVIDENCE_KEY:
        raise RemoteOperatorError("evidence_key_not_authorized")
    if ".." in key or key.startswith("/") or len(key) > 240:
        raise RemoteOperatorError("invalid_evidence_key")
    return key


def validate_expected_head(expected: str, actual: str) -> str:
    if not _HEX_40.fullmatch(expected) or expected != actual:
        raise RemoteOperatorError("exact_head_mismatch")
    return expected


def generate_wrangler_config(
    qdrant_url: str,
    worker_name: str,
    output: Path,
) -> dict[str, str | bool]:
    parsed = urlparse(qdrant_url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise RemoteOperatorError("invalid_qdrant_url")
    if not _WORKER.fullmatch(worker_name):
        raise RemoteOperatorError("invalid_worker_name")
    config = {
        "$schema": "node_modules/wrangler/config-schema.json",
        "name": worker_name,
        "main": "worker.mjs",
        "compatibility_date": "2026-07-16",
        "compatibility_flags": ["nodejs_compat"],
        "ai": {"binding": "AI"},
        "placement": {"hostname": parsed.hostname},
        "observability": {
            "enabled": True,
            "head_sampling_rate": 1,
            "logs": {"invocation_logs": False},
        },
    }
    raw = json.dumps(config, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(raw, encoding="utf-8")
    return {
        "config_sha256": hashlib.sha256(raw.encode()).hexdigest(),
        "placement_hostname_sha256": hashlib.sha256(parsed.hostname.encode()).hexdigest(),
        "generated_config_committed": False,
        "ai_binding": "AI",
    }


def parse_deploy_identity(output_file: Path, worker_name: str) -> dict[str, str]:
    if not output_file.is_file() or output_file.stat().st_size > MAX_WRANGLER_OUTPUT_BYTES:
        raise RemoteOperatorError("deploy_output_missing_or_oversized")
    records: list[dict[str, Any]] = []
    for raw in output_file.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RemoteOperatorError("deploy_output_malformed") from exc
        if isinstance(value, dict) and value.get("type") == "deploy":
            records.append(value)
    if len(records) != 1:
        raise RemoteOperatorError("deploy_record_ambiguous")
    record = records[0]
    if record.get("version") != 1 or record.get("worker_name") != worker_name:
        raise RemoteOperatorError("deploy_identity_drift")
    if record.get("worker_name_overridden") is not False:
        raise RemoteOperatorError("deploy_worker_override")
    version_id = record.get("version_id")
    targets = record.get("targets")
    if not isinstance(version_id, str) or not 1 <= len(version_id) <= 100:
        raise RemoteOperatorError("deploy_version_missing")
    if not isinstance(targets, list) or len(targets) != 1 or not isinstance(targets[0], str):
        raise RemoteOperatorError("deploy_target_ambiguous")
    target = targets[0]
    parsed = urlparse(target)
    expected_suffix = ".workers.dev"
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.port is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
        or not parsed.hostname
        or not parsed.hostname.startswith(worker_name + ".")
        or not parsed.hostname.endswith(expected_suffix)
    ):
        raise RemoteOperatorError("deploy_target_invalid")
    middle = parsed.hostname[len(worker_name) + 1 : -len(expected_suffix)]
    if not middle or "." in middle:
        raise RemoteOperatorError("deploy_target_invalid")
    return {"worker_version_id": version_id, "worker_origin": target.rstrip("/")}


def classify_wrangler_error(output: str) -> str:
    lower = output.casefold()
    if any(token in lower for token in ("forbidden", "unauthorized", "authentication")):
        return "authentication_or_authorization"
    if re.search(r"(?<!\d)403(?!\d)", output):
        return "authentication_or_authorization"
    codes = re.findall(r"(?<!\d)(1\d{4})(?!\d)", output)
    if len(codes) == 1 and codes[0] in {"10007", "10090"}:
        return "worker_not_found"
    if codes:
        return "cloudflare_error_code"
    return "wrangler_failure"


def _run_command(
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        args,
        cwd=cwd,
        env=env,
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )
    if len(result.stdout) + len(result.stderr) > MAX_WRANGLER_OUTPUT_BYTES:
        raise RemoteOperatorError("wrangler_output_oversized")
    return result


def _download_evidence(output: Path, key: str) -> int:
    import boto3

    bucket = required_env("R2_BUCKET")
    endpoint = required_env("R2_ENDPOINT_URL")
    if bucket != EXPECTED_BUCKET:
        raise RemoteOperatorError("r2_bucket_drift")
    parsed = urlparse(endpoint)
    if parsed.scheme != "https" or not parsed.hostname:
        raise RemoteOperatorError("invalid_r2_endpoint")
    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=required_env("R2_ACCESS_KEY_ID"),
        aws_secret_access_key=required_env("R2_SECRET_ACCESS_KEY"),
        region_name="auto",
    )
    response = client.get_object(Bucket=bucket, Key=key)
    body = response["Body"]
    digest = hashlib.sha256()
    size = 0
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as handle:
        while True:
            chunk = body.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_EVIDENCE_BYTES:
                raise RemoteOperatorError("evidence_oversized")
            digest.update(chunk)
            handle.write(chunk)
    if digest.hexdigest() != EXPECTED_EVIDENCE_SHA256:
        output.unlink(missing_ok=True)
        raise RemoteOperatorError("evidence_sha_mismatch")
    return size


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(value) + "\n", encoding="utf-8")


def remote_failure_code(exc: Exception) -> str:
    if isinstance(exc, RemoteOperatorError):
        return exc.code
    code = getattr(exc, "code", None)
    if isinstance(code, str) and re.fullmatch(r"[a-z0-9_]{1,80}", code):
        return "latency_repair_" + code
    return "bounded_unexpected_failure"


def execute(args: argparse.Namespace) -> int:
    from knowledge_engine import m23_7_r3_8_latency_repair as subject

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = output_dir / "latency-repair-receipt.json"
    lifecycle_path = output_dir / "remote-lifecycle.json"
    failure_path = output_dir / "remote-failure.json"
    started_at = subject.utc_now()
    actual_head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    worker_name = ""
    worker_version_id = ""
    worker_deployed = False
    stage = "entry"
    evidence_size = 0
    receipt_exit = 23
    try:
        if args.confirmation != "RUN_R3_8_REMOTE_ONCE":
            raise RemoteOperatorError("confirmation_mismatch")
        expected_head = validate_expected_head(args.expected_head, actual_head)
        worker_name = derive_worker_name(args.run_id, args.run_attempt)
        key = validate_evidence_key(args.evidence_key)
        env = os.environ.copy()
        for name in (
            "CLOUDFLARE_ACCOUNT_ID",
            "CLOUDFLARE_API_TOKEN",
            "QDRANT_URL",
            "QDRANT_API_KEY",
            "R2_ACCESS_KEY_ID",
            "R2_SECRET_ACCESS_KEY",
            "R2_BUCKET",
            "R2_ENDPOINT_URL",
        ):
            required_env(name)

        with tempfile.TemporaryDirectory(prefix="m23-r3-8-remote-") as temp_name:
            temp = Path(temp_name)
            evidence = temp / "frozen-evidence.zip"
            stage = "evidence_read"
            evidence_size = _download_evidence(evidence, key)

            worker_dir = Path("workers/m23-7-r3-8-latency-repair").resolve()
            config = worker_dir / f"wrangler.remote.{args.run_id}.jsonc"
            placement = generate_wrangler_config(
                required_env("QDRANT_URL"), worker_name, config
            )

            wrangler = ["npx", "--yes", f"wrangler@{WRANGLER_VERSION}"]
            stage = "wrangler_version"
            version = _run_command(wrangler + ["--version"], cwd=worker_dir, env=env)
            if version.returncode != 0 or WRANGLER_VERSION not in version.stdout + version.stderr:
                raise RemoteOperatorError("wrangler_version_mismatch")

            deploy_output = temp / "wrangler-deploy.jsonl"
            deploy_env = {**env, "WRANGLER_OUTPUT_FILE_PATH": str(deploy_output)}
            stage = "worker_deploy"
            deployed = _run_command(
                wrangler + ["deploy", "--config", str(config)],
                cwd=worker_dir,
                env=deploy_env,
            )
            if deployed.returncode != 0:
                raise RemoteOperatorError(
                    "deploy_" + classify_wrangler_error(deployed.stdout + deployed.stderr)
                )
            worker_deployed = True
            identity = parse_deploy_identity(deploy_output, worker_name)
            worker_version_id = identity["worker_version_id"]
            worker_origin = identity["worker_origin"]

            operator_token = secrets.token_hex(32)
            for secret_name, secret_value in (
                ("QDRANT_URL", required_env("QDRANT_URL")),
                ("QDRANT_API_KEY", required_env("QDRANT_API_KEY")),
                ("M23_R3_8_OPERATOR_TOKEN", operator_token),
            ):
                stage = "worker_secret_" + secret_name.casefold()
                result = _run_command(
                    wrangler
                    + ["secret", "put", secret_name, "--config", str(config)],
                    cwd=worker_dir,
                    env=env,
                    input_text=secret_value,
                )
                if result.returncode != 0:
                    raise RemoteOperatorError(
                        "secret_" + classify_wrangler_error(result.stdout + result.stderr)
                    )

            stage = "worker_readiness"
            import httpx

            endpoint = worker_origin + WORKER_ROUTE
            ready = False
            for _ in range(30):
                try:
                    response = httpx.get(endpoint, timeout=5.0)
                    if response.status_code == 405 and response.json() == {
                        "status": "error",
                        "code": "method-not-allowed",
                    }:
                        ready = True
                        break
                except (httpx.HTTPError, ValueError):
                    pass
                time.sleep(2)
            if not ready:
                raise RemoteOperatorError("worker_not_ready")

            stage = "live_observation"
            candidate = subject.r35.build_calibration_candidate(evidence)
            with subject.HttpWorkerInvoker(endpoint, operator_token, 60.0) as invoker:
                receipt = subject.run_latency_repair(candidate, invoker, placement)
            receipt["started_at"] = started_at
            receipt["completed_at"] = subject.utc_now()
            receipt["remote_operator"] = {
                "schema_version": REMOTE_RECEIPT_SCHEMA,
                "github_run_id": args.run_id,
                "github_run_attempt": args.run_attempt,
                "engine_sha": expected_head,
                "worker_name": worker_name,
                "worker_version_id": worker_version_id,
                "worker_retained": True,
                "local_terminal_operator_used": False,
                "evidence_sha256": EXPECTED_EVIDENCE_SHA256,
                "evidence_key_sha256": hashlib.sha256(key.encode()).hexdigest(),
                "evidence_size_bytes": evidence_size,
            }
            receipt.pop("receipt_sha256", None)
            receipt["receipt_sha256"] = subject.canonical_sha256(receipt)
            _write_json(receipt_path, receipt)
            receipt_exit = 0 if receipt["status"] == "pass_placed_worker_latency_repair" else 30
            stage = "complete"

        lifecycle = {
            "schema_version": LIFECYCLE_SCHEMA,
            "status": "observation_complete",
            "github_run_id": args.run_id,
            "github_run_attempt": args.run_attempt,
            "engine_sha": actual_head,
            "worker_name": worker_name,
            "worker_version_id": worker_version_id,
            "worker_deployed": worker_deployed,
            "worker_retained": True,
            "deletion_authorization_required": True,
            "receipt_file_sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            "production_retrieval": "lexical",
            "protected_mutations_dispatched": False,
            "blockers_cleared": False,
        }
        lifecycle["lifecycle_sha256"] = canonical_sha256(lifecycle)
        _write_json(lifecycle_path, lifecycle)
        return receipt_exit
    except Exception as exc:
        code = remote_failure_code(exc)
        failure = {
            "schema_version": REMOTE_RECEIPT_SCHEMA,
            "status": "rejected_incomplete_remote_observation",
            "failure_code": code,
            "failure_stage": stage,
            "github_run_id": args.run_id,
            "github_run_attempt": args.run_attempt,
            "engine_sha": actual_head,
            "worker_name": worker_name or None,
            "worker_version_id": worker_version_id or None,
            "worker_deployed": worker_deployed,
            "worker_retained": worker_deployed,
            "evidence_size_bytes": evidence_size,
            "arbitrary_exception_text_persisted": False,
            "credentials_persisted": False,
            "service_url_persisted": False,
            "production_retrieval": "lexical",
            "protected_mutations_dispatched": False,
            "blockers_cleared": False,
        }
        failure["failure_sha256"] = canonical_sha256(failure)
        _write_json(failure_path, failure)
        lifecycle = {
            "schema_version": LIFECYCLE_SCHEMA,
            "status": "observation_incomplete",
            "github_run_id": args.run_id,
            "github_run_attempt": args.run_attempt,
            "engine_sha": actual_head,
            "worker_name": worker_name or None,
            "worker_version_id": worker_version_id or None,
            "worker_deployed": worker_deployed,
            "worker_retained": worker_deployed,
            "deletion_authorization_required": worker_deployed,
            "failure_code": code,
            "failure_stage": stage,
            "production_retrieval": "lexical",
            "protected_mutations_dispatched": False,
            "blockers_cleared": False,
        }
        lifecycle["lifecycle_sha256"] = canonical_sha256(lifecycle)
        _write_json(lifecycle_path, lifecycle)
        return 23


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run R3.8 via GitHub Actions")
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", required=True, type=int)
    parser.add_argument("--confirmation", required=True)
    parser.add_argument("--evidence-key", default=DEFAULT_EVIDENCE_KEY)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return execute(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
