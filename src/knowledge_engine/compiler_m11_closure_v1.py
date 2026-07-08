from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from .compiler_contract_v1 import CompilerFailure, json_bytes, put_immutable
from .compiler_resolution_contract_v1 import digest_object, load_json_object
from .compiler_source_pr_package_v1 import (
    validate_decision_set,
    verify_source_pr_package_event,
)
from .compiler_source_v1 import SOURCE_REPOSITORY, verify_source_checkout
from .intake_v1 import canonical_json_bytes
from .storage import ObjectStore, sha256_bytes

M11_ENGINE_START_SHA = "2e4bbb445b4762ae9cde191edc121ae82b9914d0"
M11_SOURCE_SHA = "2126db2ed4d372d3d61464fe31a86fc0243a1f24"
PRODUCTION_RELEASE = "20260708T040116Z-69a9f445699a"
PRODUCTION_MANIFEST_SHA256 = "2b2630cfe3e8a6e25a8f210d68c70f3b9a31b3b26f33c6e3e41b8cc1676fc0bb"
PRODUCTION_POINTER_SHA256 = "38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5"
PACKAGE_ID_RE = re.compile(r"^sprp_[a-f0-9]{64}$")
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


@dataclass(frozen=True)
class M11ClosureRequest:
    source_pr_package_id: str
    source_commit_sha: str
    production_release: str
    production_manifest_sha256: str
    production_pointer_sha256: str
    reconciled_at: str

    def validate(self) -> None:
        if not PACKAGE_ID_RE.fullmatch(self.source_pr_package_id):
            raise CompilerFailure(
                "M11_CLOSURE_PACKAGE_ID_INVALID", "request", "Source PR package ID invalid"
            )
        if self.source_commit_sha != M11_SOURCE_SHA:
            raise CompilerFailure(
                "M11_CLOSURE_SOURCE_BASELINE_CHANGED",
                "request",
                "canonical Source baseline changed",
            )
        if self.production_release != PRODUCTION_RELEASE:
            raise CompilerFailure(
                "M11_CLOSURE_PRODUCTION_RELEASE_CHANGED",
                "request",
                "production release changed",
            )
        if not SHA256_RE.fullmatch(self.production_manifest_sha256):
            raise CompilerFailure(
                "M11_CLOSURE_MANIFEST_INVALID", "request", "manifest digest invalid"
            )
        if self.production_manifest_sha256 != PRODUCTION_MANIFEST_SHA256:
            raise CompilerFailure(
                "M11_CLOSURE_PRODUCTION_MANIFEST_CHANGED",
                "request",
                "production manifest changed",
            )
        if not SHA256_RE.fullmatch(self.production_pointer_sha256):
            raise CompilerFailure(
                "M11_CLOSURE_POINTER_INVALID", "request", "pointer digest invalid"
            )
        if self.production_pointer_sha256 != PRODUCTION_POINTER_SHA256:
            raise CompilerFailure(
                "M11_CLOSURE_PRODUCTION_POINTER_CHANGED",
                "request",
                "production pointer changed",
            )
        if not self.reconciled_at.endswith("Z"):
            raise CompilerFailure(
                "M11_CLOSURE_TIMESTAMP_INVALID", "request", "reconciled_at must end in Z"
            )
        try:
            datetime.fromisoformat(self.reconciled_at[:-1] + "+00:00")
        except ValueError as exc:
            raise CompilerFailure(
                "M11_CLOSURE_TIMESTAMP_INVALID",
                "request",
                "reconciled_at must be valid ISO-8601",
            ) from exc

    def identity(self) -> dict[str, Any]:
        return {
            "schema_version": "knowledge-compiler-m11-closure-request/v1",
            **asdict(self),
        }

    def attempt_id(self) -> str:
        return "m11ca_" + sha256_bytes(canonical_json_bytes(self.identity()))


@dataclass(frozen=True)
class M11ClosureResult:
    closure_id: str
    source_pr_package_id: str
    status: str
    result_key: str
    event_keys: tuple[str, ...]
    closure_prefix: str | None = None
    reconciliation_sha256: str | None = None
    rejection_key: str | None = None
    failure_code: str | None = None
    idempotent: bool = False
    canonical_write_permitted: bool = False
    github_write_permitted: bool = False
    production_write_permitted: bool = False
    ledger_write_permitted: bool = False

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["event_keys"] = list(self.event_keys)
        return value

    def evidence(self) -> dict[str, Any]:
        value = self.to_dict()
        value.pop("idempotent")
        return value


def _event(
    closure_id: str,
    ordinal: int,
    occurred_at: str,
    before: str | None,
    after: str,
    inputs: list[str],
    outputs: list[str],
    previous: str | None,
) -> dict[str, Any]:
    payload = {
        "schema_version": "knowledge-compiler-m11-closure-event/v1",
        "closure_id": closure_id,
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


def verify_m11_closure_event(event: Mapping[str, Any]) -> bool:
    payload = dict(event)
    expected = payload.pop("event_sha256", None)
    return isinstance(expected, str) and expected == sha256_bytes(canonical_json_bytes(payload))


def _write_output(root: Path | None, relative: str, data: bytes) -> None:
    if root is None:
        return
    path = root.resolve() / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _validate_package_events(store: ObjectStore, prefix: str, event_keys: Any) -> None:
    if not isinstance(event_keys, list) or not event_keys:
        raise CompilerFailure(
            "M11_CLOSURE_PACKAGE_EVENT_CHAIN_INVALID",
            "validate",
            "Source PR package event chain missing",
        )
    previous = None
    final_state = None
    for ordinal, key in enumerate(event_keys, 1):
        if not isinstance(key, str) or not key.startswith(f"{prefix}/events/"):
            raise CompilerFailure(
                "M11_CLOSURE_PACKAGE_EVENT_CHAIN_INVALID",
                "validate",
                "Source PR package event key invalid",
            )
        event = load_json_object(store, key, "Source PR package event")
        if not verify_source_pr_package_event(event):
            raise CompilerFailure(
                "M11_CLOSURE_PACKAGE_EVENT_CHAIN_INVALID",
                "validate",
                "Source PR package event hash invalid",
            )
        if event.get("ordinal") != ordinal or event.get("previous_event_hash") != previous:
            raise CompilerFailure(
                "M11_CLOSURE_PACKAGE_EVENT_CHAIN_INVALID",
                "validate",
                "Source PR package event chain not adjacent",
            )
        event_hash = event.get("event_sha256")
        if not isinstance(event_hash, str) or not key.endswith(f"-{event_hash}.json"):
            raise CompilerFailure(
                "M11_CLOSURE_PACKAGE_EVENT_CHAIN_INVALID",
                "validate",
                "Source PR package event key mismatch",
            )
        previous = event_hash
        final_state = event.get("to_state")
    if final_state != "review_only_complete":
        raise CompilerFailure(
            "M11_CLOSURE_PACKAGE_EVENT_CHAIN_INVALID",
            "validate",
            "Source PR package terminal state invalid",
        )


def _validate_source_pr_package(store: ObjectStore, package_id: str) -> dict[str, Any]:
    prefix = f"compiler/v1/source-pr-packages/{package_id}"
    keys = {
        "manifest": f"{prefix}/package-manifest.json",
        "file_plan": f"{prefix}/file-plan.json",
        "decisions": f"{prefix}/proposal-decisions.json",
        "exclusions": f"{prefix}/exclusions.json",
        "validation": f"{prefix}/validation-report.json",
        "result": f"{prefix}/result.json",
    }
    docs = {name: load_json_object(store, key, name) for name, key in keys.items()}
    manifest = docs["manifest"]
    plan = docs["file_plan"]
    decisions = docs["decisions"]
    exclusions = docs["exclusions"]
    validation = docs["validation"]
    result = docs["result"]
    for value in (manifest, plan, decisions, exclusions, validation):
        if value.get("source_pr_package_id") != package_id:
            raise CompilerFailure(
                "M11_CLOSURE_PACKAGE_IDENTITY_MISMATCH",
                "validate",
                "Source PR package artifact identity mismatch",
            )
    if result.get("source_pr_package_id") != package_id:
        raise CompilerFailure(
            "M11_CLOSURE_PACKAGE_IDENTITY_MISMATCH",
            "validate",
            "Source PR package result identity mismatch",
        )
    if manifest.get("status") != "review_only_complete":
        raise CompilerFailure(
            "M11_CLOSURE_PACKAGE_INCOMPLETE", "validate", "Source PR package incomplete"
        )
    if result.get("status") != "review_only_complete":
        raise CompilerFailure(
            "M11_CLOSURE_PACKAGE_INCOMPLETE",
            "validate",
            "Source PR package result incomplete",
        )
    _validate_package_events(store, prefix, result.get("event_keys"))
    if validation.get("source_identity_exact") is not True:
        raise CompilerFailure(
            "M11_CLOSURE_SOURCE_NOT_EXACT", "validate", "Source identity not exact"
        )
    if validation.get("source_checkout_clean") is not True:
        raise CompilerFailure(
            "M11_CLOSURE_SOURCE_NOT_CLEAN", "validate", "Source checkout not clean"
        )
    if validation.get("source_snapshot_exact") is not True:
        raise CompilerFailure(
            "M11_CLOSURE_SOURCE_SNAPSHOT_CHANGED",
            "validate",
            "Source snapshot not exact",
        )
    if validation.get("all_included_proposals_approved") is not True:
        raise CompilerFailure(
            "M11_CLOSURE_UNAPPROVED_CONTENT",
            "validate",
            "Source package includes unapproved proposal",
        )
    if validation.get("quarantined_items_included") is not False:
        raise CompilerFailure(
            "M11_CLOSURE_QUARANTINE_LEAKAGE",
            "validate",
            "quarantined item included in Source package",
        )
    if validation.get("audience_broadening_detected") is not False:
        raise CompilerFailure(
            "M11_CLOSURE_POLICY_BROADENING",
            "validate",
            "Source package broadens audience",
        )
    for flag in (
        "source_pr_creation_permitted",
        "direct_apply_permitted",
        "canonical_write_permitted",
        "github_write_permitted",
        "production_write_permitted",
    ):
        if manifest.get(flag) is not False or result.get(flag) is not False:
            raise CompilerFailure(
                "M11_CLOSURE_MUTATION_BOUNDARY_INVALID",
                "validate",
                "Source package grants forbidden mutation",
            )
    decision_set_id = manifest.get("request", {}).get("decision_set_id")
    if not isinstance(decision_set_id, str):
        raise CompilerFailure(
            "M11_CLOSURE_PACKAGE_RECORD_INVALID",
            "validate",
            "decision set identity missing",
        )
    decision = validate_decision_set(store, decision_set_id)
    artifact_hashes = {name: digest_object(store, key) for name, key in keys.items()}
    return {
        "prefix": prefix,
        "keys": keys,
        "artifact_hashes": artifact_hashes,
        "manifest": manifest,
        "decision": decision,
    }


def _reject(
    store: ObjectStore,
    request: M11ClosureRequest,
    failure: CompilerFailure,
    output_dir: Path | None,
) -> M11ClosureResult:
    attempt_id = request.attempt_id()
    prefix = f"compiler/v1/m11-closure-rejections/{attempt_id}"
    rejection_key = f"{prefix}/evidence.json"
    result_key = f"{prefix}/result.json"
    rejection = {
        "schema_version": "knowledge-compiler-m11-closure-rejection/v1",
        "closure_attempt_id": attempt_id,
        "source_pr_package_id": request.source_pr_package_id,
        "stage": failure.stage,
        "reason_code": failure.code,
        "message": failure.message,
        "safe_context": failure.context,
        "canonical_write_permitted": False,
        "github_write_permitted": False,
        "production_write_permitted": False,
        "ledger_write_permitted": False,
    }
    states = [put_immutable(store, rejection_key, json_bytes(rejection))]
    result = M11ClosureResult(
        closure_id=attempt_id,
        source_pr_package_id=request.source_pr_package_id,
        status="rejected",
        result_key=result_key,
        event_keys=(),
        rejection_key=rejection_key,
        failure_code=failure.code,
    )
    states.append(put_immutable(store, result_key, json_bytes(result.evidence())))
    result = replace(result, idempotent=all(states))
    _write_output(output_dir, "rejection.json", json_bytes(rejection))
    _write_output(output_dir, "m11-closure-result.json", json_bytes(result.to_dict()))
    return result


def reconcile_m11_closure(
    store: ObjectStore,
    request: M11ClosureRequest,
    source_root: Path,
    output_dir: Path | None = None,
) -> M11ClosureResult:
    try:
        request.validate()
        package = _validate_source_pr_package(store, request.source_pr_package_id)
        snapshot, _ = verify_source_checkout(
            source_root,
            SOURCE_REPOSITORY,
            request.source_commit_sha,
        )
        if snapshot["source_snapshot_sha256"] != package["manifest"].get(
            "source_snapshot_sha256"
        ):
            raise CompilerFailure(
                "M11_CLOSURE_SOURCE_SNAPSHOT_CHANGED",
                "reconcile",
                "canonical Source snapshot differs from package baseline",
            )
        identity = {
            "schema_version": "knowledge-compiler-m11-closure/v1",
            "request": request.identity(),
            "package_artifact_hashes": package["artifact_hashes"],
            "decision_artifact_hashes": package["decision"]["artifact_hashes"],
            "engine_start_sha": M11_ENGINE_START_SHA,
            "canonical_source_repository": SOURCE_REPOSITORY,
            "canonical_source_sha": request.source_commit_sha,
            "canonical_source_snapshot_sha256": snapshot["source_snapshot_sha256"],
        }
        closure_id = "m11cl_" + sha256_bytes(canonical_json_bytes(identity))
        prefix = f"compiler/v1/m11-closures/{closure_id}"
        report_key = f"{prefix}/reconciliation-report.json"
        matrix_key = f"{prefix}/invariant-matrix.json"
        result_key = f"{prefix}/result.json"
        matrix = {
            "schema_version": "knowledge-compiler-m11-invariant-matrix/v1",
            "closure_id": closure_id,
            "invariants": {
                "compiler_pipeline_evidence_complete": True,
                "human_review_mandatory": True,
                "automatic_approval_permitted": False,
                "unsupported_or_quarantined_content_published": False,
                "audience_or_acl_broadened": False,
                "canonical_source_written": False,
                "source_pr_created_or_merged": False,
                "candidate_or_release_created": False,
                "production_promoted_or_rolled_back": False,
                "production_pointer_changed": False,
                "permanent_ledger_appended": False,
                "deterministic_replay_supported": True,
            },
            "all_passed": True,
        }
        report = {
            **identity,
            "closure_id": closure_id,
            "status": "closure_ready",
            "production_release": request.production_release,
            "production_manifest_sha256": request.production_manifest_sha256,
            "production_pointer_sha256": request.production_pointer_sha256,
            "m11_slice_status": {
                "M11.1": "complete",
                "M11.2": "complete",
                "M11.3": "complete",
                "M11.4": "complete",
                "M11.5": "complete",
                "M11.6": "complete",
                "M11.7": "closure_ready",
            },
            "next_milestone": "M12",
            "canonical_write_permitted": False,
            "github_write_permitted": False,
            "production_write_permitted": False,
            "ledger_write_permitted": False,
        }
        docs = {report_key: report, matrix_key: matrix}
        stages = [
            (None, "package_validated", list(package["keys"].values()), [matrix_key]),
            (
                "package_validated",
                "baselines_reconciled",
                [matrix_key],
                [report_key],
            ),
            (
                "baselines_reconciled",
                "closure_ready",
                [report_key],
                [result_key],
            ),
        ]
        events = []
        previous = None
        for ordinal, (before, after, inputs, outputs) in enumerate(stages, 1):
            event = _event(
                closure_id,
                ordinal,
                request.reconciled_at,
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
        reconciliation_sha256 = sha256_bytes(json_bytes(report))
        result = M11ClosureResult(
            closure_id=closure_id,
            source_pr_package_id=request.source_pr_package_id,
            status="closure_ready",
            result_key=result_key,
            event_keys=event_keys,
            closure_prefix=prefix,
            reconciliation_sha256=reconciliation_sha256,
        )
        states = [
            put_immutable(store, key, json_bytes(value)) for key, value in sorted(docs.items())
        ]
        for key, event in zip(event_keys, events, strict=True):
            states.append(put_immutable(store, key, json_bytes(event)))
        states.append(put_immutable(store, result_key, json_bytes(result.evidence())))
        result = replace(result, idempotent=all(states))
        for key, value in docs.items():
            _write_output(output_dir, key.removeprefix(prefix + "/"), json_bytes(value))
        _write_output(output_dir, "m11-closure-result.json", json_bytes(result.to_dict()))
        return result
    except CompilerFailure as failure:
        return _reject(store, request, failure, output_dir)
