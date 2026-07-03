from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from knowledge_engine.config import Settings
from knowledge_engine.errors import IntegrityError
from knowledge_engine.intake import IntakeRequest, intake_markdown
from knowledge_engine.resolution import ResolveRequest, resolve_synthesis
from knowledge_engine.storage import create_object_store, sha256_bytes
from knowledge_engine.synthesis import (
    SynthesisRequest,
    prepare_synthesis,
    validate_synthesis,
)


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IntegrityError(f"invalid JSON: {label}: {path}") from exc
    if not isinstance(payload, dict):
        raise IntegrityError(f"{label} must be a JSON object")
    return payload


def _require_mapping(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise IntegrityError(f"batch spec {key} must be an object")
    return value


def _require_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise IntegrityError(f"batch spec {key} must be non-empty text")
    return value


def _run_git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise IntegrityError(f"git command failed: {' '.join(args)}: {detail}")
    return completed.stdout.strip()


def _verify_checkout(
    root: Path,
    *,
    expected_sha: str,
    expected_repository: str,
) -> None:
    root = root.resolve()
    actual_sha = _run_git(root, "rev-parse", "HEAD").lower()
    if actual_sha != expected_sha:
        raise IntegrityError(
            f"{expected_repository} SHA mismatch: expected {expected_sha}, got {actual_sha}"
        )
    if _run_git(root, "status", "--porcelain"):
        raise IntegrityError(f"{expected_repository} checkout is dirty")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-spec", type=Path, required=True)
    parser.add_argument("--content-root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()

    spec = _load_json(args.batch_spec, "batch spec")
    if spec.get("schema_version") != "1.0":
        raise IntegrityError("batch spec schema_version must be 1.0")
    batch_id = _require_text(spec, "batch_id")
    content = _require_mapping(spec, "content_source")
    knowledge_source = _require_mapping(spec, "knowledge_source")
    synthesis = _require_mapping(spec, "synthesis")
    resolution = _require_mapping(spec, "resolution")

    content_repository = _require_text(content, "repository")
    content_sha = _require_text(content, "commit_sha")
    content_path = _require_text(content, "path")
    expected_blob_sha = _require_text(content, "git_blob_sha")
    source_repository = _require_text(knowledge_source, "repository")
    source_sha = _require_text(knowledge_source, "commit_sha")

    _verify_checkout(
        args.content_root,
        expected_sha=content_sha,
        expected_repository=content_repository,
    )
    _verify_checkout(
        args.source_root,
        expected_sha=source_sha,
        expected_repository=source_repository,
    )
    article_path = (args.content_root.resolve() / content_path).resolve()
    try:
        article_path.relative_to(args.content_root.resolve())
    except ValueError as exc:
        raise IntegrityError("batch content path escapes the content checkout") from exc
    if not article_path.is_file():
        raise IntegrityError(f"batch content file does not exist: {content_path}")
    actual_blob_sha = _run_git(args.content_root, "hash-object", content_path)
    if actual_blob_sha != expected_blob_sha:
        raise IntegrityError(
            f"content blob mismatch: expected {expected_blob_sha}, got {actual_blob_sha}"
        )

    evidence_dir = args.evidence_dir.resolve()
    if evidence_dir.exists():
        shutil.rmtree(evidence_dir)
    evidence_dir.mkdir(parents=True)
    shutil.copy2(args.batch_spec, evidence_dir / "batch-spec.json")

    store = create_object_store(Settings.from_env())
    production_before = store.get("channels/production.json")

    intake = intake_markdown(
        store=store,
        request=IntakeRequest(
            source_id=_require_text(content, "source_id"),
            source_uri=_require_text(content, "canonical_uri"),
            title=_require_text(content, "title"),
            kind=_require_text(content, "kind"),
            audience=_require_text(content, "audience"),
            retrieved_at=_require_text(content, "retrieved_at"),
            owner=_require_text(content, "owner"),
            license=_require_text(content, "license"),
            content_type="text/markdown",
        ),
        input_path=article_path,
        output_dir=evidence_dir / "01-intake",
    )
    if intake.canonical_write_permitted:
        raise IntegrityError("intake unexpectedly permits canonical writes")

    prepared = prepare_synthesis(
        store=store,
        request=SynthesisRequest(
            capture_id=intake.capture_id,
            provider=_require_text(synthesis, "provider"),
            model=_require_text(synthesis, "model"),
            model_version=_require_text(synthesis, "model_version"),
            prompt_version=_require_text(synthesis, "prompt_version"),
            harness_version=_require_text(synthesis, "harness_version"),
            seed=int(synthesis.get("seed")),
            temperature=float(synthesis.get("temperature")),
            requested_at=_require_text(synthesis, "requested_at"),
            actor=_require_text(synthesis, "actor"),
        ),
        output_dir=evidence_dir / "02-synthesis-request",
    )
    if prepared.canonical_write_permitted:
        raise IntegrityError("synthesis request unexpectedly permits canonical writes")

    normalized_text = store.get(intake.normalized_key).decode("utf-8")
    raw_claims = synthesis.get("claims")
    if not isinstance(raw_claims, list) or not raw_claims:
        raise IntegrityError("batch synthesis claims must be a non-empty list")
    claims = []
    for index, raw_claim in enumerate(raw_claims):
        if not isinstance(raw_claim, dict):
            raise IntegrityError(f"batch claim {index} must be an object")
        quote = _require_text(raw_claim, "evidence_quote")
        if normalized_text.count(quote) != 1:
            raise IntegrityError(
                f"batch claim {index} evidence quote must occur exactly once"
            )
        start = normalized_text.index(quote)
        claims.append(
            {
                "claim_id": _require_text(raw_claim, "claim_id"),
                "text": _require_text(raw_claim, "text"),
                "evidence": [
                    {
                        "start_char": start,
                        "end_char": start + len(quote),
                        "quote": quote,
                    }
                ],
            }
        )
    unsupported = synthesis.get("unsupported_claims")
    if not isinstance(unsupported, list):
        raise IntegrityError("batch unsupported_claims must be a list")
    model_output = {
        "schema_version": "1.0",
        "title": _require_text(synthesis, "title"),
        "summary": _require_text(synthesis, "summary"),
        "claims": claims,
        "unsupported_claims": unsupported,
    }
    model_output_path = evidence_dir / "model-output.json"
    _write_json(model_output_path, model_output)

    validated = validate_synthesis(
        store=store,
        request_id=prepared.request_id,
        model_output_path=model_output_path,
        output_dir=evidence_dir / "03-synthesis-review",
    )
    if validated.canonical_write_permitted:
        raise IntegrityError("validated synthesis unexpectedly permits canonical writes")

    resolved = resolve_synthesis(
        store=store,
        request=ResolveRequest(
            synthesis_id=validated.synthesis_id,
            source_repository=source_repository,
            source_commit_sha=source_sha,
            requested_audience=_require_text(resolution, "requested_audience"),
            resolver_version=_require_text(resolution, "resolver_version"),
            actor=_require_text(resolution, "actor"),
            resolved_at=_require_text(resolution, "resolved_at"),
        ),
        source_root=args.source_root,
        output_dir=evidence_dir / "04-resolution-review",
    )
    expected_action = _require_text(resolution, "expected_action")
    expected_status = _require_text(resolution, "expected_status")
    if resolved.action != expected_action:
        raise IntegrityError(
            f"resolution action mismatch: expected {expected_action}, got {resolved.action}"
        )
    if resolved.status != expected_status:
        raise IntegrityError(
            f"resolution status mismatch: expected {expected_status}, got {resolved.status}"
        )
    if resolved.canonical_write_permitted:
        raise IntegrityError("resolution unexpectedly permits canonical writes")
    if _run_git(args.source_root, "status", "--porcelain"):
        raise IntegrityError("resolution modified the Source checkout")

    production_after = store.get("channels/production.json")
    if production_after != production_before:
        raise IntegrityError("M5 review batch changed the production pointer")

    summary = {
        "schema_version": "1.0",
        "batch_id": batch_id,
        "status": "awaiting_human_approval",
        "content_source": {
            "repository": content_repository,
            "commit_sha": content_sha,
            "path": content_path,
            "git_blob_sha": actual_blob_sha,
            "raw_sha256": intake.raw_sha256,
            "normalized_sha256": intake.normalized_sha256,
        },
        "knowledge_source": {
            "repository": source_repository,
            "commit_sha": source_sha,
            "snapshot_sha256": resolved.source_snapshot_sha256,
        },
        "capture_id": intake.capture_id,
        "synthesis_request_id": prepared.request_id,
        "synthesis_id": validated.synthesis_id,
        "resolution_id": resolved.resolution_id,
        "resolution_action": resolved.action,
        "resolution_status": resolved.status,
        "supported_claim_count": validated.supported_claim_count,
        "unsupported_claim_count": validated.unsupported_claim_count,
        "effective_audience": resolved.effective_audience,
        "canonical_write_permitted": False,
        "github_write_permitted": False,
        "production_write_permitted": False,
        "production_pointer_unchanged": True,
        "production_pointer_sha256": sha256_bytes(production_before),
    }
    _write_json(evidence_dir / "batch-summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
