from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

import yaml

from .compiler_contract_v1 import CompilerFailure, json_bytes, put_immutable
from .compiler_resolution_contract_v1 import digest_object, load_json_object
from .compiler_review_decision_contract_v1 import (
    CompilerSourcePRPackageRequest,
    CompilerSourcePRPackageResult,
)
from .compiler_review_decision_v1 import (
    validate_reviewer_packet,
    verify_review_decision_event,
)
from .compiler_source_v1 import AUDIENCE_RANK, verify_source_checkout
from .intake_v1 import canonical_json_bytes
from .storage import ObjectStore, sha256_bytes


def _event(
    package_id: str,
    ordinal: int,
    occurred_at: str,
    before: str | None,
    after: str,
    inputs: list[str],
    outputs: list[str],
    previous: str | None,
) -> dict[str, Any]:
    payload = {
        "schema_version": "knowledge-compiler-source-pr-package-event/v1",
        "source_pr_package_id": package_id,
        "ordinal": ordinal,
        "from_state": before,
        "to_state": after,
        "event_at": occurred_at,
        "input_artifact_refs": inputs,
        "output_artifact_refs": outputs,
        "previous_event_hash": previous,
        "mutations_performed": ["compiler_review_object_write"],
    }
    return {**payload, "event_sha256": sha256_bytes(canonical_json_bytes(payload))}


def verify_source_pr_package_event(event: Mapping[str, Any]) -> bool:
    payload = dict(event)
    expected = payload.pop("event_sha256", None)
    return isinstance(expected, str) and expected == sha256_bytes(canonical_json_bytes(payload))


def _write_output(root: Path | None, relative: str, data: bytes) -> None:
    if root is None:
        return
    path = root.resolve() / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _validate_decision_events(store: ObjectStore, prefix: str, event_keys: Any) -> None:
    if not isinstance(event_keys, list) or not event_keys:
        raise CompilerFailure(
            "SOURCE_PR_DECISION_EVENT_CHAIN_INVALID",
            "validate",
            "decision event chain missing",
        )
    previous = None
    final_state = None
    for ordinal, key in enumerate(event_keys, 1):
        if not isinstance(key, str) or not key.startswith(f"{prefix}/events/"):
            raise CompilerFailure(
                "SOURCE_PR_DECISION_EVENT_CHAIN_INVALID",
                "validate",
                "decision event key invalid",
            )
        event = load_json_object(store, key, "decision event")
        if not verify_review_decision_event(event):
            raise CompilerFailure(
                "SOURCE_PR_DECISION_EVENT_CHAIN_INVALID",
                "validate",
                "decision event hash invalid",
            )
        if event.get("ordinal") != ordinal or event.get("previous_event_hash") != previous:
            raise CompilerFailure(
                "SOURCE_PR_DECISION_EVENT_CHAIN_INVALID",
                "validate",
                "decision event chain not adjacent",
            )
        event_hash = event.get("event_sha256")
        if not isinstance(event_hash, str) or not key.endswith(f"-{event_hash}.json"):
            raise CompilerFailure(
                "SOURCE_PR_DECISION_EVENT_CHAIN_INVALID",
                "validate",
                "decision event key mismatch",
            )
        previous = event_hash
        final_state = event.get("to_state")
    if final_state != "review_complete":
        raise CompilerFailure(
            "SOURCE_PR_DECISION_EVENT_CHAIN_INVALID",
            "validate",
            "decision terminal state invalid",
        )


def validate_decision_set(store: ObjectStore, decision_set_id: str) -> dict[str, Any]:
    prefix = f"compiler/v1/review-decisions/{decision_set_id}"
    keys = {
        "record": f"{prefix}/decision-record.json",
        "decisions": f"{prefix}/decisions.json",
        "validation": f"{prefix}/validation-report.json",
        "result": f"{prefix}/result.json",
    }
    docs = {name: load_json_object(store, key, name) for name, key in keys.items()}
    record = docs["record"]
    decision_set = docs["decisions"]
    validation = docs["validation"]
    result = docs["result"]
    for value in (record, decision_set, validation):
        if value.get("decision_set_id") != decision_set_id:
            raise CompilerFailure(
                "SOURCE_PR_DECISION_IDENTITY_MISMATCH",
                "validate",
                "decision artifact identity mismatch",
            )
    if result.get("decision_set_id") != decision_set_id:
        raise CompilerFailure(
            "SOURCE_PR_DECISION_IDENTITY_MISMATCH",
            "validate",
            "decision result identity mismatch",
        )
    if record.get("status") != "recorded" or result.get("status") != "recorded":
        raise CompilerFailure(
            "SOURCE_PR_DECISION_INCOMPLETE", "validate", "decision set not recorded"
        )
    if record.get("automatic_approval_permitted") is not False:
        raise CompilerFailure(
            "SOURCE_PR_AUTOMATIC_APPROVAL_FORBIDDEN",
            "validate",
            "decision record permits automatic approval",
        )
    if validation.get("all_proposals_explicitly_decided") is not True:
        raise CompilerFailure(
            "SOURCE_PR_DECISION_COVERAGE_INCOMPLETE",
            "validate",
            "decision coverage incomplete",
        )
    if validation.get("audience_broadening_detected") is not False:
        raise CompilerFailure(
            "SOURCE_PR_POLICY_BROADENING",
            "validate",
            "decision validation reports audience broadening",
        )
    if validation.get("automatic_approval_detected") is not False:
        raise CompilerFailure(
            "SOURCE_PR_AUTOMATIC_APPROVAL_FORBIDDEN",
            "validate",
            "decision validation reports automatic approval",
        )
    if record.get("source_package_permitted") is not True:
        raise CompilerFailure(
            "SOURCE_PR_PACKAGE_NOT_PERMITTED",
            "validate",
            "decision set does not permit Source package generation",
        )
    if validation.get("source_package_permitted") is not True:
        raise CompilerFailure(
            "SOURCE_PR_PACKAGE_NOT_PERMITTED",
            "validate",
            "decision validation does not permit Source package generation",
        )
    if validation.get("quarantine_count") != 0:
        raise CompilerFailure(
            "SOURCE_PR_QUARANTINE_BLOCKING",
            "validate",
            "quarantined resolutions block Source package generation",
        )
    for flag in (
        "canonical_write_permitted",
        "github_write_permitted",
        "production_write_permitted",
    ):
        if record.get(flag) is not False or result.get(flag) is not False:
            raise CompilerFailure(
                "SOURCE_PR_MUTATION_BOUNDARY_INVALID",
                "validate",
                "decision artifact grants forbidden mutation",
            )
    _validate_decision_events(store, prefix, result.get("event_keys"))
    reviewer_packet_id = record.get("reviewer_packet_id")
    if not isinstance(reviewer_packet_id, str):
        raise CompilerFailure(
            "SOURCE_PR_DECISION_RECORD_INVALID",
            "validate",
            "reviewer packet identity missing",
        )
    packet = validate_reviewer_packet(store, reviewer_packet_id)
    values = decision_set.get("decisions")
    if not isinstance(values, list):
        raise CompilerFailure(
            "SOURCE_PR_DECISION_SET_INVALID", "validate", "decision list invalid"
        )
    decision_map: dict[str, dict[str, Any]] = {}
    for item in values:
        if not isinstance(item, dict):
            raise CompilerFailure(
                "SOURCE_PR_DECISION_SET_INVALID",
                "validate",
                "decision item must be an object",
            )
        proposal_id = item.get("proposal_id")
        if not isinstance(proposal_id, str) or proposal_id in decision_map:
            raise CompilerFailure(
                "SOURCE_PR_DECISION_DUPLICATE",
                "validate",
                "decision proposal identity missing or duplicated",
            )
        proposal = packet["proposal_map"].get(proposal_id)
        if proposal is None:
            raise CompilerFailure(
                "SOURCE_PR_ORPHAN_DECISION", "validate", "decision proposal missing"
            )
        for field in (
            "proposal_kind",
            "resolution_id",
            "candidate_id",
            "evidence_refs",
            "source_snapshot_sha256",
        ):
            if item.get(field) != proposal.get(field):
                raise CompilerFailure(
                    "SOURCE_PR_DECISION_EVIDENCE_MISMATCH",
                    "validate",
                    "decision evidence mismatch",
                )
        decision = item.get("decision")
        if decision not in {"approved", "rejected", "needs_changes"}:
            raise CompilerFailure(
                "SOURCE_PR_DECISION_VALUE_INVALID", "validate", "decision value invalid"
            )
        if decision == "approved":
            approved_audience = item.get("approved_audience")
            proposal_audience = proposal.get("effective_audience")
            if approved_audience not in AUDIENCE_RANK or proposal_audience not in AUDIENCE_RANK:
                raise CompilerFailure(
                    "SOURCE_PR_AUDIENCE_INVALID", "validate", "decision audience invalid"
                )
            if AUDIENCE_RANK[approved_audience] < AUDIENCE_RANK[proposal_audience]:
                raise CompilerFailure(
                    "SOURCE_PR_POLICY_BROADENING",
                    "validate",
                    "approved audience broadens proposal audience",
                )
        decision_map[proposal_id] = item
    if set(decision_map) != set(packet["proposal_map"]):
        raise CompilerFailure(
            "SOURCE_PR_DECISION_COVERAGE_INCOMPLETE",
            "validate",
            "decision coverage does not match reviewer packet",
        )
    artifact_hashes = {name: digest_object(store, key) for name, key in keys.items()}
    return {
        "prefix": prefix,
        "keys": keys,
        "artifact_hashes": artifact_hashes,
        "record": record,
        "packet": packet,
        "decision_map": decision_map,
    }


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    if not slug:
        slug = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    return slug[:80]


def _stable_kos_id(proposal_id: str) -> str:
    return "ko_" + sha256_bytes(proposal_id.encode("utf-8"))[:32]


def _split_frontmatter(text: str, path: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        raise CompilerFailure(
            "SOURCE_PR_FRONTMATTER_REQUIRED",
            "package",
            "target concept front matter missing",
            path=path,
        )
    marker = text.find("\n---\n", 4)
    if marker < 0:
        raise CompilerFailure(
            "SOURCE_PR_FRONTMATTER_INVALID",
            "package",
            "target concept front matter invalid",
            path=path,
        )
    try:
        metadata = yaml.safe_load(text[4:marker])
    except yaml.YAMLError as exc:
        raise CompilerFailure(
            "SOURCE_PR_FRONTMATTER_INVALID",
            "package",
            "target concept front matter invalid",
            path=path,
        ) from exc
    if not isinstance(metadata, dict):
        raise CompilerFailure(
            "SOURCE_PR_FRONTMATTER_INVALID",
            "package",
            "target concept front matter must be a mapping",
            path=path,
        )
    return metadata, text[marker + 5 :]


def _yaml_document(metadata: dict[str, Any], body: str) -> bytes:
    frontmatter = yaml.safe_dump(
        metadata,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    ).strip()
    return f"---\n{frontmatter}\n---\n{body.rstrip()}\n".encode("utf-8")


def _target_concept(
    concepts: dict[str, dict[str, Any]],
    target_ids: Any,
) -> dict[str, Any]:
    if not isinstance(target_ids, list) or len(target_ids) != 1:
        raise CompilerFailure(
            "SOURCE_PR_TARGET_INVALID",
            "package",
            "targeted proposal requires exactly one target",
        )
    target = concepts.get(target_ids[0])
    if target is None:
        raise CompilerFailure(
            "SOURCE_PR_TARGET_INVALID", "package", "proposal target missing from Source"
        )
    return target


def _materialize_plan(
    *,
    proposal: dict[str, Any],
    decision: dict[str, Any],
    concepts: dict[str, dict[str, Any]],
    source_root: Path,
    decision_set_id: str,
) -> tuple[dict[str, Any], bytes | None]:
    proposal_id = proposal["proposal_id"]
    kind = proposal["proposal_kind"]
    payload = proposal.get("payload")
    if not isinstance(payload, dict):
        raise CompilerFailure(
            "SOURCE_PR_PAYLOAD_INVALID", "package", "proposal payload invalid"
        )
    audience = decision.get("approved_audience")
    if audience not in AUDIENCE_RANK:
        raise CompilerFailure(
            "SOURCE_PR_AUDIENCE_INVALID", "package", "approved audience invalid"
        )
    evidence = {
        "proposal_id": proposal_id,
        "resolution_id": proposal["resolution_id"],
        "candidate_id": proposal["candidate_id"],
        "evidence_refs": proposal["evidence_refs"],
        "decision_set_id": decision_set_id,
    }
    if kind == "concept_create":
        title = payload.get("suggested_title")
        claim = payload.get("claim_text")
        if not isinstance(title, str) or not title.strip():
            raise CompilerFailure(
                "SOURCE_PR_PAYLOAD_INVALID", "package", "create title missing"
            )
        if not isinstance(claim, str) or not claim.strip():
            raise CompilerFailure(
                "SOURCE_PR_PAYLOAD_INVALID", "package", "create claim missing"
            )
        slug = _slugify(title)
        path = f"bundle/concepts/{slug}.md"
        if (source_root / path).exists():
            raise CompilerFailure(
                "SOURCE_PR_CREATE_COLLISION", "package", "create path already exists", path=path
            )
        metadata = {
            "type": "Concept",
            "title": title.strip(),
            "description": claim.strip()[:500],
            "x-kos-id": _stable_kos_id(proposal_id),
            "x-kos-audience": audience,
            "x-kos-status": "proposed",
            "x-kos-review": evidence,
        }
        content = _yaml_document(metadata, f"# {title.strip()}\n\n{claim.strip()}")
        return {
            "proposal_id": proposal_id,
            "proposal_kind": kind,
            "path": path,
            "operation": "add",
            "manual_review_required": False,
            "bytes": len(content),
            "sha256": sha256_bytes(content),
        }, content
    target = _target_concept(concepts, proposal.get("target_ids"))
    path = target["path"]
    source_file = source_root / path
    try:
        existing = source_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise CompilerFailure(
            "SOURCE_PR_TARGET_READ_FAILURE",
            "package",
            "cannot read target Source concept",
            path=path,
        ) from exc
    if kind == "concept_update":
        claim = payload.get("claim_text")
        if not isinstance(claim, str) or not claim.strip():
            raise CompilerFailure(
                "SOURCE_PR_PAYLOAD_INVALID", "package", "update claim missing"
            )
        marker = f"## Proposed compiler update {decision_set_id}"
        content_text = existing.rstrip()
        if marker not in content_text:
            content_text += f"\n\n{marker}\n\n{claim.strip()}\n"
        content = content_text.encode("utf-8")
        return {
            "proposal_id": proposal_id,
            "proposal_kind": kind,
            "path": path,
            "operation": "replace",
            "manual_review_required": False,
            "bytes": len(content),
            "sha256": sha256_bytes(content),
        }, content
    if kind == "alias_add":
        alias = payload.get("alias")
        if not isinstance(alias, str) or not alias.strip():
            raise CompilerFailure(
                "SOURCE_PR_PAYLOAD_INVALID", "package", "alias value missing"
            )
        metadata, body = _split_frontmatter(existing, path)
        aliases = metadata.get("aliases", [])
        if aliases is None:
            aliases = []
        if not isinstance(aliases, list) or not all(isinstance(item, str) for item in aliases):
            raise CompilerFailure(
                "SOURCE_PR_FRONTMATTER_INVALID", "package", "target aliases invalid", path=path
            )
        normalized = {item.casefold(): item for item in aliases}
        if alias.strip().casefold() in normalized:
            return {
                "proposal_id": proposal_id,
                "proposal_kind": kind,
                "path": path,
                "operation": "verify_no_change",
                "manual_review_required": True,
                "bytes": 0,
                "sha256": None,
            }, None
        metadata["aliases"] = sorted([*aliases, alias.strip()], key=str.casefold)
        metadata["x-kos-review"] = evidence
        content = _yaml_document(metadata, body)
        return {
            "proposal_id": proposal_id,
            "proposal_kind": kind,
            "path": path,
            "operation": "replace",
            "manual_review_required": False,
            "bytes": len(content),
            "sha256": sha256_bytes(content),
        }, content
    if kind == "supersession_update":
        return {
            "proposal_id": proposal_id,
            "proposal_kind": kind,
            "path": path,
            "operation": "manual_supersession_review",
            "manual_review_required": True,
            "bytes": 0,
            "sha256": None,
            "basis": payload.get("basis"),
        }, None
    raise CompilerFailure(
        "SOURCE_PR_PROPOSAL_KIND_INVALID", "package", "proposal kind invalid"
    )


def _reject(
    store: ObjectStore,
    request: CompilerSourcePRPackageRequest,
    failure: CompilerFailure,
    output_dir: Path | None,
) -> CompilerSourcePRPackageResult:
    attempt_id = request.attempt_id()
    prefix = f"compiler/v1/source-pr-package-rejections/{attempt_id}"
    rejection_key = f"{prefix}/evidence.json"
    result_key = f"{prefix}/result.json"
    rejection = {
        "schema_version": "knowledge-compiler-source-pr-package-rejection/v1",
        "source_pr_package_attempt_id": attempt_id,
        "decision_set_id": request.decision_set_id,
        "stage": failure.stage,
        "reason_code": failure.code,
        "message": failure.message,
        "safe_context": failure.context,
        "source_pr_creation_permitted": False,
        "direct_apply_permitted": False,
        "canonical_write_permitted": False,
        "github_write_permitted": False,
        "production_write_permitted": False,
    }
    states = [put_immutable(store, rejection_key, json_bytes(rejection))]
    result = CompilerSourcePRPackageResult(
        source_pr_package_id=attempt_id,
        decision_set_id=request.decision_set_id,
        status="rejected",
        result_key=result_key,
        event_keys=(),
        rejection_key=rejection_key,
        failure_code=failure.code,
    )
    states.append(put_immutable(store, result_key, json_bytes(result.evidence())))
    result = replace(result, idempotent=all(states))
    _write_output(output_dir, "rejection.json", json_bytes(rejection))
    _write_output(output_dir, "source-pr-package-result.json", json_bytes(result.to_dict()))
    return result


def build_source_pr_package(
    store: ObjectStore,
    request: CompilerSourcePRPackageRequest,
    source_root: Path,
    output_dir: Path | None = None,
) -> CompilerSourcePRPackageResult:
    try:
        request.validate()
        decision = validate_decision_set(store, request.decision_set_id)
        snapshot, source_concepts = verify_source_checkout(
            source_root,
            request.source_repository,
            request.source_commit_sha,
        )
        reviewed_snapshot = decision["record"].get("source_snapshot_sha256")
        if snapshot["source_snapshot_sha256"] != reviewed_snapshot:
            raise CompilerFailure(
                "SOURCE_PR_SNAPSHOT_MISMATCH",
                "source",
                "Source checkout differs from reviewed snapshot",
            )
        concepts = {item["concept_id"]: item for item in source_concepts}
        approved_ids = sorted(
            proposal_id
            for proposal_id, item in decision["decision_map"].items()
            if item["decision"] == "approved"
        )
        if not approved_ids:
            raise CompilerFailure(
                "SOURCE_PR_NO_APPROVED_PROPOSALS",
                "package",
                "Source package requires at least one approved proposal",
            )
        plans = []
        payloads: dict[str, bytes] = {}
        written_paths: set[str] = set()
        for proposal_id in approved_ids:
            proposal = decision["packet"]["proposal_map"][proposal_id]
            decision_item = decision["decision_map"][proposal_id]
            plan, content = _materialize_plan(
                proposal=proposal,
                decision=decision_item,
                concepts=concepts,
                source_root=source_root.resolve(),
                decision_set_id=request.decision_set_id,
            )
            path = plan["path"]
            if content is not None:
                if path in written_paths:
                    raise CompilerFailure(
                        "SOURCE_PR_MULTIPLE_WRITES_SAME_PATH",
                        "package",
                        "multiple approved proposals write the same Source path",
                        path=path,
                    )
                written_paths.add(path)
                payload_key = f"payloads/{proposal_id}-{sha256_bytes(content)}.md"
                plan["payload_key"] = payload_key
                payloads[payload_key] = content
            else:
                plan["payload_key"] = None
            plans.append(plan)
        excluded = [
            {
                "proposal_id": proposal_id,
                "decision": item["decision"],
                "reason": "not_approved",
            }
            for proposal_id, item in sorted(decision["decision_map"].items())
            if item["decision"] != "approved"
        ]
        manual_review_count = sum(bool(item["manual_review_required"]) for item in plans)
        identity = {
            "schema_version": "knowledge-compiler-source-pr-package-batch/v1",
            "request": request.identity(),
            "decision_artifact_hashes": decision["artifact_hashes"],
            "source_snapshot_sha256": snapshot["source_snapshot_sha256"],
            "approved_proposal_ids": approved_ids,
            "file_plans": plans,
            "excluded": excluded,
        }
        package_id = "sprp_" + sha256_bytes(canonical_json_bytes(identity))
        prefix = f"compiler/v1/source-pr-packages/{package_id}"
        manifest_key = f"{prefix}/package-manifest.json"
        plan_key = f"{prefix}/file-plan.json"
        decision_key = f"{prefix}/proposal-decisions.json"
        exclusions_key = f"{prefix}/exclusions.json"
        validation_key = f"{prefix}/validation-report.json"
        result_key = f"{prefix}/result.json"
        manifest = {
            **identity,
            "source_pr_package_id": package_id,
            "status": "review_only_complete",
            "approved_proposal_count": len(approved_ids),
            "file_plan_count": len(plans),
            "manual_review_count": manual_review_count,
            "source_pr_creation_permitted": False,
            "direct_apply_permitted": False,
            "canonical_write_permitted": False,
            "github_write_permitted": False,
            "production_write_permitted": False,
        }
        docs = {
            manifest_key: manifest,
            plan_key: {
                "schema_version": "knowledge-compiler-source-pr-file-plan/v1",
                "source_pr_package_id": package_id,
                "plans": plans,
                "direct_apply_permitted": False,
            },
            decision_key: {
                "schema_version": "knowledge-compiler-source-pr-proposal-decisions/v1",
                "source_pr_package_id": package_id,
                "decisions": [
                    decision["decision_map"][proposal_id] for proposal_id in sorted(decision["decision_map"])
                ],
            },
            exclusions_key: {
                "schema_version": "knowledge-compiler-source-pr-exclusions/v1",
                "source_pr_package_id": package_id,
                "items": excluded,
            },
            validation_key: {
                "schema_version": "knowledge-compiler-source-pr-package-validation/v1",
                "source_pr_package_id": package_id,
                "decision_set_id": request.decision_set_id,
                "source_identity_exact": True,
                "source_checkout_clean": True,
                "source_snapshot_exact": True,
                "all_included_proposals_approved": True,
                "quarantined_items_included": False,
                "audience_broadening_detected": False,
                "source_pr_creation_permitted": False,
                "direct_apply_permitted": False,
                "canonical_write_permitted": False,
                "github_write_permitted": False,
                "production_write_permitted": False,
            },
        }
        stages = [
            (None, "validated_decision", list(decision["keys"].values()), [validation_key]),
            ("validated_decision", "source_verified", [validation_key], [manifest_key]),
            ("source_verified", "package_planned", [manifest_key], [plan_key, exclusions_key]),
            (
                "package_planned",
                "review_only_complete",
                [plan_key, decision_key],
                [manifest_key, result_key],
            ),
        ]
        events = []
        previous = None
        for ordinal, (before, after, inputs, outputs) in enumerate(stages, 1):
            event = _event(
                package_id,
                ordinal,
                request.packaged_at,
                before,
                after,
                inputs,
                outputs,
                previous,
            )
            events.append(event)
            previous = event["event_sha256"]
        event_keys = tuple(
            f"{prefix}/events/{event['ordinal']:06d}-{event['event_sha256']}.json"
            for event in events
        )
        manifest_bytes = json_bytes(manifest)
        result = CompilerSourcePRPackageResult(
            source_pr_package_id=package_id,
            decision_set_id=request.decision_set_id,
            status="review_only_complete",
            result_key=result_key,
            event_keys=event_keys,
            approved_proposal_count=len(approved_ids),
            file_plan_count=len(plans),
            manual_review_count=manual_review_count,
            package_prefix=prefix,
            package_manifest_sha256=sha256_bytes(manifest_bytes),
        )
        states = [
            put_immutable(store, key, json_bytes(value)) for key, value in sorted(docs.items())
        ]
        for relative, content in sorted(payloads.items()):
            states.append(put_immutable(store, f"{prefix}/{relative}", content, content_type="text/markdown"))
        for key, event in zip(event_keys, events, strict=True):
            states.append(put_immutable(store, key, json_bytes(event)))
        states.append(put_immutable(store, result_key, json_bytes(result.evidence())))
        result = replace(result, idempotent=all(states))
        for key, value in docs.items():
            _write_output(output_dir, key.removeprefix(prefix + "/"), json_bytes(value))
        for relative, content in payloads.items():
            _write_output(output_dir, relative, content)
        _write_output(output_dir, "source-pr-package-result.json", json_bytes(result.to_dict()))
        return result
    except CompilerFailure as failure:
        return _reject(store, request, failure, output_dir)
