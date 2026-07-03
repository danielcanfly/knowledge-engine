from __future__ import annotations

import json
import re
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from .errors import IntegrityError, ReleaseConflictError
from .storage import ObjectStore, sha256_bytes

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,119}$")
TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u3400-\u9fff]")
AUDIENCE_RANK = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}
NEGATION_TERMS = {
    "not",
    "no",
    "never",
    "cannot",
    "can't",
    "mustn't",
    "without",
    "不",
    "無",
    "未",
    "非",
    "禁",
}
RESOLUTION_ACTIONS = {"create", "update", "alias", "merge", "conflict", "no-op"}


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


def _split_frontmatter(text: str, path: Path) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        raise IntegrityError(f"concept frontmatter is required: {path}")
    marker = text.find("\n---\n", 4)
    if marker < 0:
        raise IntegrityError(f"concept frontmatter is not terminated: {path}")
    try:
        metadata = yaml.safe_load(text[4:marker])
    except yaml.YAMLError as exc:
        raise IntegrityError(f"invalid concept frontmatter: {path}") from exc
    if not isinstance(metadata, dict):
        raise IntegrityError(f"concept frontmatter must be a mapping: {path}")
    return metadata, text[marker + 5 :]


def _normalize_text(value: str) -> str:
    value = value.casefold()
    value = re.sub(r"`{1,3}.*?`{1,3}", " ", value, flags=re.DOTALL)
    value = re.sub(r"\[[^\]]+\]\([^\)]+\)", " ", value)
    value = re.sub(r"https?://\S+", " ", value)
    value = re.sub(r"[^\w\u3400-\u9fff]+", " ", value)
    return " ".join(value.split())


def _tokens(value: str) -> set[str]:
    return {token.casefold() for token in TOKEN_RE.findall(value)}


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _has_negation(value: str) -> bool:
    normalized = value.casefold()
    return any(term in normalized for term in NEGATION_TERMS)


def _sentences(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[\n.!?。！？]+", value) if item.strip()]


def _without_negation(tokens: set[str]) -> set[str]:
    return {token for token in tokens if token not in NEGATION_TERMS}


def _concept_id(bundle_root: Path, path: Path) -> str:
    return path.relative_to(bundle_root).with_suffix("").as_posix()


@dataclass(frozen=True)
class ResolveRequest:
    synthesis_id: str
    source_repository: str
    source_commit_sha: str
    requested_audience: str
    resolver_version: str
    actor: str
    resolved_at: str

    def validate(self) -> None:
        if not SAFE_ID_RE.fullmatch(self.synthesis_id) or not self.synthesis_id.startswith(
            "syn_"
        ):
            raise IntegrityError("synthesis_id is invalid")
        if self.source_repository != "danielcanfly/knowledge-source":
            raise IntegrityError("unexpected source repository")
        if not SHA_RE.fullmatch(self.source_commit_sha):
            raise IntegrityError("source_commit_sha must be an exact lowercase SHA")
        if self.requested_audience not in AUDIENCE_RANK:
            raise IntegrityError("requested_audience is invalid")
        for label, value in (
            ("resolver_version", self.resolver_version),
            ("actor", self.actor),
        ):
            if not SAFE_ID_RE.fullmatch(value):
                raise IntegrityError(f"{label} must contain 3-120 safe characters")
        _validate_timestamp(self.resolved_at, "resolved_at")

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class ResolutionResult:
    resolution_id: str
    synthesis_id: str
    action: str
    status: str
    idempotent: bool
    target_concept_ids: tuple[str, ...]
    source_snapshot_sha256: str
    requested_audience: str
    effective_audience: str
    acl_downgrade_blocked: bool
    resolution_prefix: str
    canonical_write_permitted: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["target_concept_ids"] = list(self.target_concept_ids)
        return payload


def _verify_source(root: Path, expected_sha: str) -> tuple[Path, str]:
    root = root.resolve()
    if not root.is_dir():
        raise IntegrityError(f"source root does not exist: {root}")
    actual_sha = _run_git(root, "rev-parse", "HEAD").lower()
    if actual_sha != expected_sha:
        raise IntegrityError(
            f"source SHA mismatch: expected {expected_sha}, got {actual_sha}"
        )
    if _run_git(root, "status", "--porcelain"):
        raise IntegrityError("source checkout is dirty")
    bundle_root = root / "bundle"
    if not bundle_root.is_dir():
        raise IntegrityError("source bundle directory is required")

    files = []
    for path in sorted(bundle_root.rglob("*.md")):
        if path.is_symlink():
            raise IntegrityError(f"source symlink is not allowed: {path}")
        data = path.read_bytes()
        files.append(
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": len(data),
                "sha256": sha256_bytes(data),
            }
        )
    if not files:
        raise IntegrityError("source bundle contains no Markdown files")
    snapshot = {
        "schema_version": "1.0",
        "repository": "danielcanfly/knowledge-source",
        "commit_sha": expected_sha,
        "files": files,
    }
    return bundle_root, sha256_bytes(_canonical_json(snapshot))


def _load_concepts(bundle_root: Path) -> list[dict[str, Any]]:
    concepts_dir = bundle_root / "concepts"
    concepts = []
    if not concepts_dir.is_dir():
        return concepts
    for path in sorted(concepts_dir.rglob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise IntegrityError(f"cannot read concept: {path}") from exc
        metadata, body = _split_frontmatter(text, path)
        title = metadata.get("title")
        if not isinstance(title, str) or not title.strip():
            raise IntegrityError(f"concept title is required: {path}")
        aliases = metadata.get("aliases", [])
        if aliases is None:
            aliases = []
        if not isinstance(aliases, list) or not all(
            isinstance(item, str) and item.strip() for item in aliases
        ):
            raise IntegrityError(f"concept aliases must be strings: {path}")
        audience = metadata.get("x-kos-audience", "internal")
        if audience not in AUDIENCE_RANK:
            raise IntegrityError(f"concept audience is invalid: {path}")
        description = metadata.get("description", "")
        if not isinstance(description, str):
            raise IntegrityError(f"concept description must be text: {path}")
        searchable = "\n".join([title, description, *aliases, body])
        concepts.append(
            {
                "concept_id": _concept_id(bundle_root, path),
                "path": path.relative_to(bundle_root.parent).as_posix(),
                "title": title.strip(),
                "aliases": [item.strip() for item in aliases],
                "audience": audience,
                "description": description.strip(),
                "body": body,
                "normalized": _normalize_text(searchable),
                "tokens": _tokens(searchable),
            }
        )
    return concepts


def _load_synthesis(store: ObjectStore, synthesis_id: str) -> dict[str, Any]:
    prefix = f"review/syntheses/{synthesis_id}"
    record = _load_json(store, f"{prefix}/synthesis-record.json")
    output = _load_json(store, f"{prefix}/model-output.json")
    provenance = _load_json(store, f"{prefix}/draft/claim-provenance.json")
    if record.get("synthesis_id") != synthesis_id:
        raise IntegrityError("synthesis record identity mismatch")
    if record.get("canonical_write_permitted") is not False:
        raise IntegrityError("synthesis violates canonical-write boundary")
    if record.get("status") not in {"pending_human_review", "pending_evidence_review"}:
        raise IntegrityError("synthesis is not in a resolvable review state")
    claims = provenance.get("claims")
    if not isinstance(claims, list) or not claims:
        raise IntegrityError("synthesis contains no supported claims")
    return {
        "record": record,
        "output": output,
        "provenance": provenance,
        "claims": claims,
    }


def _capture_audience(store: ObjectStore, capture_id: str) -> str:
    capture = _load_json(store, f"raw/captures/{capture_id}.json")
    request = capture.get("request")
    audience = request.get("audience") if isinstance(request, dict) else None
    if audience not in AUDIENCE_RANK:
        raise IntegrityError("capture audience is missing or invalid")
    return str(audience)


def _coverage(claims: list[dict[str, Any]], concept: dict[str, Any]) -> tuple[int, list[str]]:
    covered = 0
    missing = []
    haystack = concept["normalized"]
    concept_tokens = concept["tokens"]
    for claim in claims:
        claim_id = claim.get("claim_id")
        text = claim.get("text")
        if not isinstance(claim_id, str) or not isinstance(text, str):
            raise IntegrityError("synthesis claim identity is malformed")
        normalized = _normalize_text(text)
        similarity = _jaccard(_tokens(text), concept_tokens)
        if normalized and (normalized in haystack or similarity >= 0.92):
            covered += 1
        else:
            missing.append(claim_id)
    return covered, missing


def _conflicts(
    claims: list[dict[str, Any]],
    concepts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    findings = []
    for claim in claims:
        claim_text = claim["text"]
        claim_tokens = _without_negation(_tokens(claim_text))
        claim_negative = _has_negation(claim_text)
        if len(claim_tokens) < 3:
            continue
        for concept in concepts:
            for sentence in _sentences(concept["body"]):
                sentence_tokens = _without_negation(_tokens(sentence))
                if len(sentence_tokens) < 3:
                    continue
                similarity = _jaccard(claim_tokens, sentence_tokens)
                if similarity >= 0.6 and claim_negative != _has_negation(sentence):
                    findings.append(
                        {
                            "code": "POSSIBLE_NEGATION_CONFLICT",
                            "draft_claim_id": claim["claim_id"],
                            "draft_claim": claim_text,
                            "existing_concept_id": concept["concept_id"],
                            "existing_path": concept["path"],
                            "existing_excerpt": sentence,
                            "similarity": round(similarity, 6),
                        }
                    )
    return findings


def _resolution_action(
    *,
    title: str,
    claims: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    conflicts: list[dict[str, Any]],
) -> tuple[str, list[str], list[dict[str, Any]]]:
    findings: list[dict[str, Any]] = []
    if conflicts:
        targets = sorted({item["existing_concept_id"] for item in conflicts})
        return "conflict", targets, findings

    title_key = title.casefold().strip()
    title_matches = [
        item
        for item in candidates
        if item["title"].casefold() == title_key
        or title_key in {alias.casefold() for alias in item["aliases"]}
    ]
    if title_matches:
        target = sorted(title_matches, key=lambda item: item["concept_id"])[0]
        covered, missing = _coverage(claims, target)
        if covered == len(claims):
            return "no-op", [target["concept_id"]], findings
        findings.append(
            {
                "code": "UNCOVERED_CLAIMS",
                "concept_id": target["concept_id"],
                "claim_ids": missing,
            }
        )
        return "update", [target["concept_id"]], findings

    full_coverage = []
    for item in candidates:
        covered, _ = _coverage(claims, item)
        if covered == len(claims):
            full_coverage.append(item)
    if len(full_coverage) == 1:
        return "alias", [full_coverage[0]["concept_id"]], findings
    if len(full_coverage) > 1:
        targets = sorted(item["concept_id"] for item in full_coverage)
        findings.append(
            {
                "code": "AMBIGUOUS_CONTENT_DUPLICATE",
                "concept_ids": targets,
            }
        )
        return "conflict", targets, findings

    ranked = sorted(
        candidates,
        key=lambda item: (-item["similarity"], item["concept_id"]),
    )
    strong = [item for item in ranked if item["similarity"] >= 0.35]
    if not strong:
        return "create", [], findings
    if len(strong) == 1:
        return "merge", [strong[0]["concept_id"]], findings
    if strong[0]["similarity"] - strong[1]["similarity"] < 0.05:
        targets = [strong[0]["concept_id"], strong[1]["concept_id"]]
        findings.append(
            {
                "code": "AMBIGUOUS_CONCEPT_MATCH",
                "concept_ids": targets,
                "scores": [strong[0]["similarity"], strong[1]["similarity"]],
            }
        )
        return "conflict", targets, findings
    return "merge", [strong[0]["concept_id"]], findings


def resolve_synthesis(
    *,
    store: ObjectStore,
    request: ResolveRequest,
    source_root: Path,
    output_dir: Path,
) -> ResolutionResult:
    request.validate()
    bundle_root, source_snapshot_sha256 = _verify_source(
        source_root, request.source_commit_sha
    )
    synthesis = _load_synthesis(store, request.synthesis_id)
    record = synthesis["record"]
    output = synthesis["output"]
    claims = synthesis["claims"]
    title = output.get("title")
    summary = output.get("summary")
    if not isinstance(title, str) or not title.strip():
        raise IntegrityError("synthesis title is missing")
    if not isinstance(summary, str):
        raise IntegrityError("synthesis summary is missing")

    concepts = _load_concepts(bundle_root)
    draft_searchable = "\n".join(
        [title, summary, *(str(claim.get("text", "")) for claim in claims)]
    )
    draft_tokens = _tokens(draft_searchable)
    candidates = []
    for concept in concepts:
        covered, missing = _coverage(claims, concept)
        candidates.append(
            {
                "concept_id": concept["concept_id"],
                "path": concept["path"],
                "title": concept["title"],
                "aliases": concept["aliases"],
                "audience": concept["audience"],
                "similarity": round(_jaccard(draft_tokens, concept["tokens"]), 6),
                "covered_claim_count": covered,
                "missing_claim_ids": missing,
            }
        )

    conflict_findings = _conflicts(claims, concepts)
    action, targets, resolution_findings = _resolution_action(
        title=title,
        claims=claims,
        candidates=[
            {
                **candidate,
                "normalized": next(
                    item["normalized"]
                    for item in concepts
                    if item["concept_id"] == candidate["concept_id"]
                ),
                "tokens": next(
                    item["tokens"]
                    for item in concepts
                    if item["concept_id"] == candidate["concept_id"]
                ),
            }
            for candidate in candidates
        ],
        conflicts=conflict_findings,
    )
    if action not in RESOLUTION_ACTIONS:
        raise IntegrityError(f"resolver produced invalid action: {action}")

    capture_id = record.get("capture_id")
    if not isinstance(capture_id, str):
        raise IntegrityError("synthesis record omitted capture_id")
    source_audience = _capture_audience(store, capture_id)
    minimum_rank = AUDIENCE_RANK[source_audience]
    target_audiences = {
        concept["concept_id"]: concept["audience"] for concept in concepts
    }
    for target in targets:
        audience = target_audiences.get(target)
        if audience is not None:
            minimum_rank = max(minimum_rank, AUDIENCE_RANK[audience])
    minimum_audience = next(
        name for name, rank in AUDIENCE_RANK.items() if rank == minimum_rank
    )
    requested_rank = AUDIENCE_RANK[request.requested_audience]
    acl_downgrade_blocked = requested_rank < minimum_rank
    effective_audience = (
        minimum_audience if acl_downgrade_blocked else request.requested_audience
    )

    status = "pending_human_review"
    if action == "conflict":
        status = "pending_conflict_review"
    if acl_downgrade_blocked:
        status = "pending_security_review"
        resolution_findings.append(
            {
                "code": "ACL_DOWNGRADE_BLOCKED",
                "requested_audience": request.requested_audience,
                "minimum_audience": minimum_audience,
            }
        )

    resolution_identity = {
        "schema_version": "1.0",
        "request": request.to_dict(),
        "source_snapshot_sha256": source_snapshot_sha256,
        "synthesis_record_sha256": sha256_bytes(
            _canonical_json(record)
        ),
    }
    resolution_id = "res_" + sha256_bytes(_canonical_json(resolution_identity))[:32]
    prefix = f"review/resolutions/{resolution_id}"
    proposal = {
        "schema_version": "1.0",
        "resolution_id": resolution_id,
        "synthesis_id": request.synthesis_id,
        "capture_id": capture_id,
        "action": action,
        "status": status,
        "title": title,
        "target_concept_ids": targets,
        "requested_audience": request.requested_audience,
        "source_audience": source_audience,
        "minimum_audience": minimum_audience,
        "effective_audience": effective_audience,
        "acl_downgrade_blocked": acl_downgrade_blocked,
        "findings": resolution_findings,
        "conflicts": conflict_findings,
        "canonical_write_permitted": False,
        "github_write_permitted": False,
        "production_write_permitted": False,
    }
    candidate_index = {
        "schema_version": "1.0",
        "resolution_id": resolution_id,
        "source_repository": request.source_repository,
        "source_commit_sha": request.source_commit_sha,
        "source_snapshot_sha256": source_snapshot_sha256,
        "candidate_count": len(candidates),
        "candidates": sorted(
            candidates,
            key=lambda item: (-item["similarity"], item["concept_id"]),
        ),
    }
    resolution_record = {
        **resolution_identity,
        "resolution_id": resolution_id,
        "action": action,
        "status": status,
        "target_concept_ids": targets,
        "canonical_write_permitted": False,
        "github_write_permitted": False,
        "production_write_permitted": False,
    }
    artifacts = {
        "resolution-record.json": _canonical_json(resolution_record),
        "proposed-action.json": _canonical_json(proposal),
        "candidate-index.json": _canonical_json(candidate_index),
        "conflicts.json": _canonical_json(
            {
                "schema_version": "1.0",
                "resolution_id": resolution_id,
                "findings": conflict_findings,
            }
        ),
    }
    states = []
    for relative, data in sorted(artifacts.items()):
        states.append(
            _put_immutable(store, f"{prefix}/{relative}", data)
        )

    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    for relative, data in artifacts.items():
        (output_dir / relative).write_bytes(data)

    result = ResolutionResult(
        resolution_id=resolution_id,
        synthesis_id=request.synthesis_id,
        action=action,
        status=status,
        idempotent=all(states),
        target_concept_ids=tuple(targets),
        source_snapshot_sha256=source_snapshot_sha256,
        requested_audience=request.requested_audience,
        effective_audience=effective_audience,
        acl_downgrade_blocked=acl_downgrade_blocked,
        resolution_prefix=prefix,
    )
    (output_dir / "resolve-result.json").write_bytes(_canonical_json(result.to_dict()))
    return result
