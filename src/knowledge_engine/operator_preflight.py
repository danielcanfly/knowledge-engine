from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence

from .batch_registry import load_batch_registry, validate_batch_registry
from .batch_spec import REGISTRY_PATH, BatchSpec, load_batch_spec
from .errors import IntegrityError
from .promotion_request import load_promotion_request_spec

PRODUCTION_WORKFLOW = Path(".github/workflows/m5-production-promotion.yml")
NEXT_ACTION = {
    "planned": "open_source_review",
    "source_reviewed": "run_source_validation",
    "source_validated": "build_candidate",
    "candidate_built": "run_runtime_acceptance",
    "runtime_accepted": "commit_production_request_spec",
    "request_spec_committed": "review_production_promotion",
    "production_promoted": "run_idempotent_replay_and_close",
    "closed": "start_next_batch",
}
_INPUT_RE = re.compile(r"^      ([A-Za-z0-9_-]+):\s*$", re.MULTILINE)


def _git_is_clean(root: Path) -> bool:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return not result.stdout.strip()


def _workflow_inputs(path: Path) -> list[str]:
    if not path.is_file():
        raise IntegrityError(f"production workflow does not exist: {path}")
    text = path.read_text(encoding="utf-8")
    start = text.find("  workflow_dispatch:")
    if start < 0:
        raise IntegrityError("production workflow must use workflow_dispatch")
    end = len(text)
    for match in re.finditer(r"^[A-Za-z][^:\n]*:\s*$", text[start:], re.MULTILINE):
        absolute = start + match.start()
        if absolute > start:
            end = absolute
            break
    return _INPUT_RE.findall(text[start:end])


def _selected_entry(registry_result: dict[str, Any], batch_id: str) -> None:
    if not any(entry["batch_id"] == batch_id for entry in registry_result["batches"]):
        raise IntegrityError(f"batch is not registered: {batch_id}")


def _validate_request_identity(spec: BatchSpec) -> dict[str, Any] | None:
    if spec.request_path is None:
        return None
    request = load_promotion_request_spec(
        request_path=Path(spec.request_path),
        control_plane_sha="0" * 40,
    )
    if request.request.operation_id != spec.operation_id:
        raise IntegrityError("batch operation_id does not match promotion request")
    candidate = spec.raw["candidate"]
    expected = {
        "candidate_channel": candidate["channel"],
        "release_id": candidate["release_id"],
        "manifest_sha256": candidate["manifest_sha256"],
    }
    actual = {
        "candidate_channel": request.request.candidate_channel,
        "release_id": request.request.expected_release_id,
        "manifest_sha256": request.request.expected_manifest_sha256,
    }
    if actual != expected:
        raise IntegrityError("batch candidate identity does not match promotion request")
    return {
        "status": "valid",
        "request_path": spec.request_path,
        "operation_id": spec.operation_id,
    }


def _validate_pointer(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    if not path.is_file():
        raise IntegrityError(f"production pointer evidence does not exist: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise IntegrityError("production pointer evidence is invalid JSON") from exc
    if not isinstance(payload, dict):
        raise IntegrityError("production pointer evidence must be an object")
    release_id = payload.get("release_id")
    manifest = payload.get("manifest_sha256")
    if not isinstance(release_id, str) or not release_id:
        raise IntegrityError("production pointer release_id is required")
    if not isinstance(manifest, str) or len(manifest) != 64:
        raise IntegrityError("production pointer manifest_sha256 is invalid")
    return {"release_id": release_id, "manifest_sha256": manifest}


def run_operator_preflight(
    *,
    spec_path: Path,
    root: Path = Path("."),
    registry_path: Path = REGISTRY_PATH,
    required_env: Sequence[str] = (),
    environ: Mapping[str, str] | None = None,
    allow_dirty: bool = False,
    production_pointer_path: Path | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    if Path.cwd().resolve() != root:
        raise IntegrityError("operator preflight must run from the repository root")

    registry_result = validate_batch_registry(load_batch_registry(registry_path))
    spec = load_batch_spec(spec_path)
    _selected_entry(registry_result, spec.batch_id)

    clean = _git_is_clean(root)
    if not clean and not allow_dirty:
        raise IntegrityError("Git worktree is dirty")

    inputs = _workflow_inputs(PRODUCTION_WORKFLOW)
    if inputs != ["request_path"]:
        raise IntegrityError(
            "production workflow inputs must be exactly ['request_path']"
        )

    values = os.environ if environ is None else environ
    missing_env = [name for name in required_env if not values.get(name)]
    if missing_env:
        raise IntegrityError(
            "required environment variables are missing: " + ", ".join(missing_env)
        )

    return {
        "status": "ready",
        "batch_id": spec.batch_id,
        "lifecycle_state": spec.lifecycle_state,
        "next_action": NEXT_ACTION[spec.lifecycle_state],
        "git_worktree_clean": clean,
        "production_workflow_inputs": inputs,
        "required_environment": list(required_env),
        "request": _validate_request_identity(spec),
        "production_pointer": _validate_pointer(production_pointer_path),
        "mutations_performed": [],
    }


def write_preflight_evidence(result: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
