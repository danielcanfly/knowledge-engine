from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from .errors import IntegrityError, ReleaseConflictError
from .resolution import _split_frontmatter, _verify_source
from .storage import ObjectStore, sha256_bytes

SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,119}$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DECISIONS = {"approved", "rejected", "needs_changes"}
ACTIONS = {"create", "update", "alias", "merge", "conflict", "no-op"}
AUDIENCE_RANK = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}
CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _canonical_json(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _validate_timestamp(value: str, label: str) -> None:
    if not value.endswith("Z"):
        raise IntegrityError(f"{label} must be an exact UTC timestamp ending in Z")
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise IntegrityError(f"{label} must be a valid ISO-8601 timestamp") from exc


def _load_json(store: ObjectStore, key: str) -> dict[str, Any]:
    try:
        payload = json.loads(store.get(key))
    except FileNotFoundError as exc:
        raise IntegrityError(f"required object does not exist: {key}") from exc
    except json.JSONDecodeError as exc:
        raise IntegrityError(f"invalid JSON object: {key}") from exc
    if not isinstance(payload, dict):
        raise IntegrityError(f"JSON object must be a mapping: {key}")
    return payload


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IntegrityError(f"invalid JSON: {label}: {path}") from exc
    if not isinstance(payload, dict):
        raise IntegrityError(f"{label} must be a JSON object")
    return payload


def _put_immutable(
    store: ObjectStore,
    key: str,
    data: bytes,
    *,
    content_type: str = "application/json",
) -> bool:
    current = store.head(key)
    if current is not None:
        if store.get(key) != data:
            raise IntegrityError(f"immutable object collision: {key}")
        return True
    try:
        store.put(
            key,
            data,
            content_type=content_type,
            sha256=sha256_bytes(data),
            only_if_absent=True,
        )
        return False
    except ReleaseConflictError:
        if store.get(key) != data:
            raise IntegrityError(f"immutable object collision: {key}") from None
        return True


def _stable_kos_id(seed: bytes) -> str:
    value = int.from_bytes(hashlib.sha256(seed).digest()[:17], "big") >> 6
    encoded = []
    for _ in range(26):
        encoded.append(CROCKFORD[value & 31])
        value >>= 5
    return "ko_" + "".join(reversed(encoded))


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    if not slug:
        slug = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    return slug[:80]


def _yaml_document(metadata: dict[str, Any], body: str) -> bytes:
    frontmatter = yaml.safe_dump(
        metadata,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    ).strip()
    return f"---\n{frontmatter}\n---\n{body.rstrip()}\n".encode("utf-8")


def _load_resolution(store: ObjectStore, resolution_id: str) -> dict[str, Any]:
    prefix = f"review/resolutions/{resolution_id}"
    record = _load_json(store, f"{prefix}/resolution-record.json")
    proposal = _load_json(store, f"{prefix}/proposed-action.json")
    candidates = _load_json(store, f"{prefix}/candidate-index.json")
    if record.get("resolution_id") != resolution_id:
        raise IntegrityError("resolution record identity mismatch")
    if proposal.get("resolution_id") != resolution_id:
        raise IntegrityError("resolution proposal identity mismatch")
    if record.get("canonical_write_permitted") is not False:
        raise IntegrityError("resolution violates canonical-write boundary")
    action = proposal.get("action")
    if action not in ACTIONS:
        raise IntegrityError("resolution action is invalid")
    return {"record": record, "proposal": proposal, "candidates": candidates}


@dataclass(frozen=True)
class ReviewDecisionRequest:
    resolution_id: str
    decision: str
    reviewer: str
    reviewed_at: str
    notes: str
    approved_audience: str | None = None

    def validate(self) -> None:
        if not SAFE_ID_RE.fullmatch(self.resolution_id) or not self.resolution_id.startswith(
            "res_"
        ):
            raise IntegrityError("resolution_id is invalid")
        if self.decision not in DECISIONS:
            raise IntegrityError("decision must be approved, rejected, or needs_changes")
        if not SAFE_ID_RE.fullmatch(self.reviewer):
            raise IntegrityError("reviewer must contain 3-120 safe characters")
        _validate_timestamp(self.reviewed_at, "reviewed_at")
        if not self.notes.strip() or len(self.notes) > 4000:
            raise IntegrityError("review notes must contain 1-4000 characters")
        if self.approved_audience is not None and self.approved_audience not in AUDIENCE_RANK:
            raise IntegrityError("approved_audience is invalid")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReviewDecisionResult:
    decision_id: str
    resolution_id: str
    decision: str
    action: str
    idempotent: bool
    source_package_permitted: bool
    decision_key: str
    canonical_write_permitted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SourcePackageRequest:
    decision_id: str
    source_repository: str
    source_commit_sha: str
    package_version: str
    actor: str
    packaged_at: str

    def validate(self) -> None:
        if not SAFE_ID_RE.fullmatch(self.decision_id) or not self.decision_id.startswith(
            "dec_"
        ):
            raise IntegrityError("decision_id is invalid")
        if self.source_repository != "danielcanfly/knowledge-source":
            raise IntegrityError("unexpected source repository")
        if not SHA_RE.fullmatch(self.source_commit_sha):
            raise IntegrityError("source_commit_sha must be an exact lowercase SHA")
        for label, value in (
            ("package_version", self.package_version),
            ("actor", self.actor),
        ):
            if not SAFE_ID_RE.fullmatch(value):
                raise IntegrityError(f"{label} must contain 3-120 safe characters")
        _validate_timestamp(self.packaged_at, "packaged_at")

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class SourcePackageResult:
    package_id: str
    decision_id: str
    action: str
    status: str
    idempotent: bool
    source_file_count: int
    package_prefix: str
    package_manifest_sha256: str
    direct_apply_permitted: bool = False
    canonical_write_permitted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def record_review_decision(
    *,
    store: ObjectStore,
    request: ReviewDecisionRequest,
    output_dir: Path,
) -> ReviewDecisionResult:
    request.validate()
    resolution = _load_resolution(store, request.resolution_id)
    proposal = resolution["proposal"]
    action = str(proposal["action"])
    status = str(proposal.get("status", ""))
    effective_audience = proposal.get("effective_audience")
    if effective_audience not in AUDIENCE_RANK:
        raise IntegrityError("resolution effective audience is invalid")

    source_package_permitted = False
    if request.decision == "approved":
        if status != "pending_human_review":
            raise IntegrityError(
                "only pending_human_review resolutions may be approved; "
                "conflict and security findings require a new resolution"
            )
        if action == "conflict":
            raise IntegrityError("conflict resolutions cannot be approved")
        if request.approved_audience is None:
            raise IntegrityError("approved decisions require approved_audience")
        if AUDIENCE_RANK[request.approved_audience] < AUDIENCE_RANK[effective_audience]:
            raise IntegrityError("approved audience cannot downgrade resolution audience")
        source_package_permitted = action in {"create", "update", "alias", "merge"}
    elif request.approved_audience is not None:
        raise IntegrityError("non-approved decisions cannot set approved_audience")

    identity = {
        "schema_version": "1.0",
        "request": request.to_dict(),
        "resolution_record_sha256": sha256_bytes(
            _canonical_json(resolution["record"])
        ),
        "resolution_proposal_sha256": sha256_bytes(
            _canonical_json(proposal)
        ),
    }
    decision_id = "dec_" + sha256_bytes(_canonical_json(identity))[:32]
    decision_key = f"review/decisions/{decision_id}/decision.json"
    record = {
        **identity,
        "decision_id": decision_id,
        "resolution_id": request.resolution_id,
        "synthesis_id": proposal.get("synthesis_id"),
        "action": action,
        "decision": request.decision,
        "status": "recorded",
        "effective_audience": effective_audience,
        "approved_audience": request.approved_audience,
        "source_package_permitted": source_package_permitted,
        "canonical_write_permitted": False,
        "github_write_permitted": False,
        "production_write_permitted": False,
    }
    record_bytes = _canonical_json(record)
    idempotent = _put_immutable(store, decision_key, record_bytes)

    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "decision.json").write_bytes(record_bytes)
    result = ReviewDecisionResult(
        decision_id=decision_id,
        resolution_id=request.resolution_id,
        decision=request.decision,
        action=action,
        idempotent=idempotent,
        source_package_permitted=source_package_permitted,
        decision_key=decision_key,
    )
    (output_dir / "decision-result.json").write_bytes(_canonical_json(result.to_dict()))
    return result


def _merge_registry_record(
    records: list[Any],
    *,
    key: str,
    record: dict[str, Any],
) -> list[dict[str, Any]]:
    result = []
    matched = False
    for current in records:
        if not isinstance(current, dict):
            raise IntegrityError("registry contains a non-object record")
        if current.get(key) == record[key]:
            if current != record:
                raise IntegrityError(f"registry identity collision: {key}={record[key]}")
            matched = True
        result.append(current)
    if not matched:
        result.append(record)
    return sorted(result, key=lambda item: str(item.get(key, "")))


def _candidate_path(candidates: dict[str, Any], concept_id: str) -> str:
    records = candidates.get("candidates")
    if not isinstance(records, list):
        raise IntegrityError("resolution candidate index is malformed")
    for record in records:
        if isinstance(record, dict) and record.get("concept_id") == concept_id:
            path = record.get("path")
            if isinstance(path, str) and path.startswith("bundle/concepts/"):
                return path
    raise IntegrityError(f"resolution target path is missing: {concept_id}")


def _claim_section(
    *,
    decision_id: str,
    summary: str,
    claims: list[dict[str, Any]],
) -> str:
    lines = [
        f"## Reviewed synthesis {decision_id}",
        "",
        summary.strip(),
        "",
        "### Approved claims",
        "",
    ]
    for claim in claims:
        lines.append(f"- {str(claim.get('text', '')).strip()}")
    return "\n".join(lines).rstrip()


def materialize_source_package(
    *,
    store: ObjectStore,
    request: SourcePackageRequest,
    source_root: Path,
    output_dir: Path,
) -> SourcePackageResult:
    request.validate()
    decision_key = f"review/decisions/{request.decision_id}/decision.json"
    decision = _load_json(store, decision_key)
    if decision.get("decision_id") != request.decision_id:
        raise IntegrityError("review decision identity mismatch")
    if decision.get("decision") != "approved":
        raise IntegrityError("only approved decisions may materialize a Source package")
    action = decision.get("action")
    if action not in ACTIONS:
        raise IntegrityError("review decision action is invalid")
    if action == "conflict":
        raise IntegrityError("conflict decisions cannot materialize a Source package")

    resolution_id = decision.get("resolution_id")
    if not isinstance(resolution_id, str):
        raise IntegrityError("review decision omitted resolution_id")
    resolution = _load_resolution(store, resolution_id)
    proposal = resolution["proposal"]
    resolution_request = resolution["record"].get("request")
    if not isinstance(resolution_request, dict):
        raise IntegrityError("resolution record omitted request identity")
    if resolution_request.get("source_commit_sha") != request.source_commit_sha:
        raise IntegrityError("package Source SHA differs from reviewed resolution")

    bundle_root, snapshot_sha256 = _verify_source(
        source_root, request.source_commit_sha
    )
    if snapshot_sha256 != resolution["record"].get("source_snapshot_sha256"):
        raise IntegrityError("Source snapshot differs from reviewed resolution")
    source_root = source_root.resolve()

    if action == "no-op":
        package_identity = {
            "schema_version": "1.0",
            "request": request.to_dict(),
            "decision_id": request.decision_id,
            "source_snapshot_sha256": snapshot_sha256,
            "action": action,
            "files": [],
        }
        package_id = "pkg_" + sha256_bytes(_canonical_json(package_identity))[:32]
        manifest = {
            **package_identity,
            "package_id": package_id,
            "status": "no_changes",
            "direct_apply_permitted": False,
            "canonical_write_permitted": False,
        }
        manifest_bytes = _canonical_json(manifest)
        prefix = f"review/source-packages/{package_id}"
        idempotent = _put_immutable(
            store, f"{prefix}/package-manifest.json", manifest_bytes
        )
        output_dir = output_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "package-manifest.json").write_bytes(manifest_bytes)
        return SourcePackageResult(
            package_id=package_id,
            decision_id=request.decision_id,
            action=action,
            status="no_changes",
            idempotent=idempotent,
            source_file_count=0,
            package_prefix=prefix,
            package_manifest_sha256=sha256_bytes(manifest_bytes),
        )

    if decision.get("source_package_permitted") is not True:
        raise IntegrityError("review decision does not permit Source package generation")
    approved_audience = decision.get("approved_audience")
    if approved_audience not in AUDIENCE_RANK:
        raise IntegrityError("review decision approved audience is invalid")

    synthesis_id = proposal.get("synthesis_id")
    if not isinstance(synthesis_id, str):
        raise IntegrityError("resolution proposal omitted synthesis_id")
    synthesis_prefix = f"review/syntheses/{synthesis_id}"
    synthesis = _load_json(store, f"{synthesis_prefix}/synthesis-record.json")
    model_output = _load_json(store, f"{synthesis_prefix}/model-output.json")
    claim_provenance = _load_json(
        store, f"{synthesis_prefix}/draft/claim-provenance.json"
    )
    capture_id = synthesis.get("capture_id")
    if not isinstance(capture_id, str):
        raise IntegrityError("synthesis omitted capture_id")
    capture = _load_json(store, f"raw/captures/{capture_id}.json")
    capture_request = capture.get("request")
    if not isinstance(capture_request, dict):
        raise IntegrityError("capture omitted source request")
    claims = claim_provenance.get("claims")
    if not isinstance(claims, list) or not claims:
        raise IntegrityError("synthesis contains no claims")
    title = model_output.get("title")
    summary = model_output.get("summary")
    if not isinstance(title, str) or not title.strip():
        raise IntegrityError("synthesis title is missing")
    if not isinstance(summary, str) or not summary.strip():
        raise IntegrityError("synthesis summary is missing")

    sources_path = source_root / "registry/sources.json"
    reviews_path = source_root / "registry/reviews.json"
    sources_data = _read_json(sources_path, "source registry")
    reviews_data = _read_json(reviews_path, "review registry")
    if not isinstance(sources_data.get("sources"), list):
        raise IntegrityError("source registry sources must be a list")
    if not isinstance(reviews_data.get("reviews"), list):
        raise IntegrityError("review registry reviews must be a list")

    review_id = "review_" + request.decision_id.removeprefix("dec_")
    target_ids = proposal.get("target_concept_ids")
    if not isinstance(target_ids, list):
        raise IntegrityError("resolution target_concept_ids must be a list")
    metadata: dict[str, Any]
    body: str
    existing_provenance: dict[str, Any] = {}

    if action == "create":
        slug = _slugify(title)
        concept_id = f"concepts/{slug}"
        concept_path = f"bundle/concepts/{slug}.md"
        provenance_path = f"provenance/{slug}.json"
        if (source_root / concept_path).exists() or (source_root / provenance_path).exists():
            raise IntegrityError("create package would overwrite an existing Source file")
        kos_id = _stable_kos_id(f"{request.decision_id}:{concept_id}".encode("utf-8"))
        metadata = {
            "type": "Concept",
            "title": title.strip(),
            "description": summary.strip()[:500],
            "timestamp": request.packaged_at,
            "x-kos-id": kos_id,
            "x-kos-status": "published",
            "x-kos-audience": approved_audience,
            "x-kos-confidence": 0.85,
            "x-kos-provenance": provenance_path,
            "x-kos-review": {"review_id": review_id, "status": "approved"},
        }
        body = (
            f"# {title.strip()}\n\n"
            f"{summary.strip()}\n\n"
            f"{_claim_section(decision_id=request.decision_id, summary=summary, claims=claims)}"
        )
    else:
        if len(target_ids) != 1:
            raise IntegrityError(f"{action} package requires exactly one target concept")
        concept_id = str(target_ids[0])
        concept_path = _candidate_path(resolution["candidates"], concept_id)
        concept_file = source_root / concept_path
        try:
            existing_text = concept_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise IntegrityError(f"cannot read target concept: {concept_path}") from exc
        metadata, body = _split_frontmatter(existing_text, concept_file)
        provenance_path = str(metadata.get("x-kos-provenance", ""))
        if not provenance_path.startswith("provenance/"):
            raise IntegrityError("target concept provenance path is invalid")
        provenance_file = source_root / provenance_path
        existing_provenance = _read_json(provenance_file, "target provenance")
        kos_id = str(metadata.get("x-kos-id", ""))
        if not kos_id:
            raise IntegrityError("target concept x-kos-id is missing")
        metadata["timestamp"] = request.packaged_at
        metadata["x-kos-status"] = "published"
        metadata["x-kos-audience"] = approved_audience
        metadata["x-kos-review"] = {"review_id": review_id, "status": "approved"}
        current_confidence = metadata.get("x-kos-confidence", 0.0)
        try:
            metadata["x-kos-confidence"] = max(float(current_confidence), 0.85)
        except (TypeError, ValueError) as exc:
            raise IntegrityError("target concept confidence is invalid") from exc
        if action == "alias":
            aliases = metadata.get("aliases", [])
            if aliases is None:
                aliases = []
            if not isinstance(aliases, list):
                raise IntegrityError("target concept aliases are invalid")
            existing_aliases = [str(item) for item in aliases]
            if title.strip() != str(metadata.get("title", "")).strip() and title.strip() not in existing_aliases:
                existing_aliases.append(title.strip())
            metadata["aliases"] = sorted(set(existing_aliases), key=str.casefold)
        else:
            section = _claim_section(
                decision_id=request.decision_id,
                summary=summary,
                claims=claims,
            )
            if request.decision_id not in body:
                body = body.rstrip() + "\n\n" + section + "\n"

    source_id = capture_request.get("source_id")
    source_uri = capture_request.get("source_uri")
    retrieved_at = capture_request.get("retrieved_at")
    if not all(isinstance(value, str) and value for value in (source_id, source_uri, retrieved_at)):
        raise IntegrityError("capture source identity is incomplete")
    source_record = {
        "source_id": source_id,
        "title": capture_request.get("title"),
        "uri": source_uri,
        "kind": capture_request.get("kind"),
        "trust": "reviewed",
        "status": "active",
        "audience": approved_audience,
        "owner": capture_request.get("owner"),
        "license": capture_request.get("license"),
        "content_sha256": capture.get("raw_sha256"),
    }
    sources_data = {
        **sources_data,
        "sources": _merge_registry_record(
            sources_data["sources"],
            key="source_id",
            record=source_record,
        ),
    }
    review_record = {
        "review_id": review_id,
        "concept_id": concept_id,
        "reviewer": decision["request"]["reviewer"],
        "reviewed_at": decision["request"]["reviewed_at"],
        "status": "approved",
        "approved_audience": approved_audience,
        "notes": decision["request"]["notes"],
        "resolution_id": resolution_id,
        "synthesis_id": synthesis_id,
    }
    reviews_data = {
        **reviews_data,
        "reviews": _merge_registry_record(
            reviews_data["reviews"],
            key="review_id",
            record=review_record,
        ),
    }

    provenance_sources = existing_provenance.get("sources", [])
    if not isinstance(provenance_sources, list):
        raise IntegrityError("target provenance sources are invalid")
    new_provenance_source = {
        "source_id": source_id,
        "uri": source_uri,
        "retrieved_at": retrieved_at,
        "capture_id": capture_id,
        "raw_blob_key": capture.get("raw_blob_key"),
        "raw_sha256": capture.get("raw_sha256"),
        "normalized_key": capture.get("normalized_key"),
        "normalized_sha256": capture.get("normalized_sha256"),
    }
    merged_sources = []
    seen_source_ids = set()
    for item in [*provenance_sources, new_provenance_source]:
        if not isinstance(item, dict):
            raise IntegrityError("provenance source must be an object")
        current_id = item.get("source_id")
        if not isinstance(current_id, str) or not current_id:
            raise IntegrityError("provenance source_id is required")
        if current_id in seen_source_ids:
            continue
        seen_source_ids.add(current_id)
        merged_sources.append(item)
    provenance = {
        "schema_version": "1.0",
        "subject": {"concept_id": concept_id, "x_kos_id": kos_id},
        "sources": merged_sources,
        "method": "human-reviewed-ai-assisted-synthesis",
        "confidence": float(metadata["x-kos-confidence"]),
        "claims": claims,
        "review_decision_id": request.decision_id,
        "resolution_id": resolution_id,
        "synthesis_id": synthesis_id,
    }

    payload_files = {
        concept_path: _yaml_document(metadata, body),
        provenance_path: _canonical_json(provenance),
        "registry/sources.json": _canonical_json(sources_data),
        "registry/reviews.json": _canonical_json(reviews_data),
    }
    file_entries = [
        {
            "path": path,
            "operation": "replace" if (source_root / path).exists() else "add",
            "bytes": len(data),
            "sha256": sha256_bytes(data),
        }
        for path, data in sorted(payload_files.items())
    ]
    package_identity = {
        "schema_version": "1.0",
        "request": request.to_dict(),
        "decision_id": request.decision_id,
        "resolution_id": resolution_id,
        "synthesis_id": synthesis_id,
        "source_snapshot_sha256": snapshot_sha256,
        "action": action,
        "files": file_entries,
    }
    package_id = "pkg_" + sha256_bytes(_canonical_json(package_identity))[:32]
    prefix = f"review/source-packages/{package_id}"
    manifest = {
        **package_identity,
        "package_id": package_id,
        "status": "review_ready",
        "source_validation_required": True,
        "human_pr_review_required": True,
        "direct_apply_permitted": False,
        "canonical_write_permitted": False,
        "github_write_permitted": False,
        "production_write_permitted": False,
    }
    manifest_bytes = _canonical_json(manifest)

    states = []
    for path, data in sorted(payload_files.items()):
        states.append(
            _put_immutable(
                store,
                f"{prefix}/payload/{path}",
                data,
                content_type=(
                    "text/markdown" if path.endswith(".md") else "application/json"
                ),
            )
        )
    states.append(
        _put_immutable(store, f"{prefix}/package-manifest.json", manifest_bytes)
    )

    output_dir = output_dir.resolve()
    payload_root = output_dir / "payload"
    payload_root.mkdir(parents=True, exist_ok=True)
    for path, data in payload_files.items():
        destination = payload_root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    (output_dir / "package-manifest.json").write_bytes(manifest_bytes)
    instructions = (
        "This package is review-only. Apply payload files to the exact Source SHA, "
        "run Source validation, open a pull request, and require human PR review.\n"
        "Do not push directly to Source main and do not publish production directly.\n"
    ).encode("utf-8")
    (output_dir / "APPLY_INSTRUCTIONS.txt").write_bytes(instructions)

    result = SourcePackageResult(
        package_id=package_id,
        decision_id=request.decision_id,
        action=action,
        status="review_ready",
        idempotent=all(states),
        source_file_count=len(payload_files),
        package_prefix=prefix,
        package_manifest_sha256=sha256_bytes(manifest_bytes),
    )
    (output_dir / "package-result.json").write_bytes(_canonical_json(result.to_dict()))
    return result
