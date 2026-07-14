from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .errors import IntegrityError
from .intake import IntakeRequest, IntakeResult, intake_markdown
from .m23_real_data_baseline import validate_corpus_manifest
from .storage import FileObjectStore, sha256_bytes

ENGINE_ENTRY_SHA = "3e69058e94b3ba039601e64895d3d17265391750"
SOURCE_SHA = "a6ba738d910d01d2ae99b1968f0831989934c549"
FOUNDATION_SHA = "e5ef644053d34e89c70d2ceb37521e1c59234832"
M23_1_MANIFEST_DIGEST = "ad63e9fa78780b1c8774a66fe6d3d1d20b3fd52b62adc559d80cc9ac4fa38cae"
MAX_BATCH_ITEMS = 25
MAX_ITEM_ATTEMPTS = 2
MAX_HTTPS_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 3
ALLOWED_MEDIA_TYPES = {"text/markdown", "text/plain", "text/x-markdown"}
CHECKPOINT_STATES = {"pending", "running", "completed", "failed"}
PROTECTED_STATE = {
    "source_write": False,
    "r2_write": False,
    "production_pointer_update": False,
    "provider_call": False,
    "extraction": False,
    "embedding_generation": False,
    "candidate_publication": False,
    "production_publication": False,
    "traffic_change": False,
    "multi_hop_activation": False,
    "graph_neural_retrieval": False,
}
_SOURCE_ID_SAFE = re.compile(r"[^a-z0-9_]+")


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _payload_digest(value: Mapping[str, Any], digest_key: str) -> str:
    return _digest({key: item for key, item in value.items() if key != digest_key})


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(_canonical_bytes(value))
    temporary.replace(path)


def _immutable_json(path: Path, value: Mapping[str, Any]) -> bool:
    data = _canonical_bytes(value)
    if path.exists():
        if path.read_bytes() != data:
            raise IntegrityError(f"M23-INTAKE-101 immutable evidence collision: {path.name}")
        return True
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return False


def _safe_child(root: Path, filename: str) -> Path:
    root = root.resolve()
    path = (root / filename).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise IntegrityError("M23-INTAKE-102 source path escapes source root") from exc
    if path.parent != root:
        raise IntegrityError("M23-INTAKE-102 source path must be a direct child")
    return path


def _source_id(document_id: str) -> str:
    value = _SOURCE_ID_SAFE.sub("_", document_id.lower().replace("-", "_")).strip("_")
    return f"source_m23_{value}"[:80]


def _batch_plan(corpus: Mapping[str, Any], *, retrieved_at: str) -> dict[str, Any]:
    if corpus["manifest_digest"] != M23_1_MANIFEST_DIGEST:
        raise IntegrityError("M23-INTAKE-103 M23.1 manifest identity mismatch")
    documents = list(corpus["documents"])
    if not 1 <= len(documents) <= MAX_BATCH_ITEMS or len(documents) != 6:
        raise IntegrityError("M23-INTAKE-104 pilot batch must contain exactly six items")
    items = []
    for document in documents:
        items.append(
            {
                "document_id": document["document_id"],
                "upload_id": document["upload_id"],
                "original_filename": document["original_filename"],
                "raw_sha256": document["sha256"],
                "raw_bytes": document["byte_length"],
                "language": document["language"],
                "title": document["title"],
                "audience": document["audience"],
                "source_id": _source_id(document["document_id"]),
                "source_uri": f"urn:chatgpt-upload:{document['upload_id']}",
            }
        )
    plan = {
        "schema_version": "knowledge-engine-m23-live-intake-plan/v1",
        "authority": "evidence_only",
        "canonical_knowledge": False,
        "production_authority": False,
        "engine_sha": ENGINE_ENTRY_SHA,
        "source_sha": SOURCE_SHA,
        "foundation_sha": FOUNDATION_SHA,
        "corpus_manifest_digest": corpus["manifest_digest"],
        "retrieved_at": retrieved_at,
        "batch_size": len(items),
        "items": items,
    }
    plan["batch_id"] = "m23batch_" + _digest(plan)[:32]
    plan["plan_sha256"] = _digest(plan)
    return plan


def _initial_checkpoint(plan: Mapping[str, Any]) -> dict[str, Any]:
    checkpoint = {
        "schema_version": "knowledge-engine-m23-live-intake-checkpoint/v1",
        "batch_id": plan["batch_id"],
        "plan_sha256": plan["plan_sha256"],
        "revision": 0,
        "items": [
            {
                "document_id": item["document_id"],
                "status": "pending",
                "attempts": 0,
                "failure_code": None,
                "result_sha256": None,
            }
            for item in plan["items"]
        ],
    }
    checkpoint["checkpoint_sha256"] = _digest(checkpoint)
    return checkpoint


def _validate_checkpoint(plan: Mapping[str, Any], checkpoint: Mapping[str, Any]) -> None:
    if checkpoint.get("schema_version") != "knowledge-engine-m23-live-intake-checkpoint/v1":
        raise IntegrityError("M23-INTAKE-105 invalid checkpoint schema")
    if checkpoint.get("checkpoint_sha256") != _payload_digest(checkpoint, "checkpoint_sha256"):
        raise IntegrityError("M23-INTAKE-106 checkpoint digest mismatch")
    identity_drift = (
        checkpoint.get("batch_id") != plan["batch_id"]
        or checkpoint.get("plan_sha256") != plan["plan_sha256"]
    )
    if identity_drift:
        raise IntegrityError("M23-INTAKE-107 checkpoint identity mismatch")
    expected = [item["document_id"] for item in plan["items"]]
    states = checkpoint.get("items")
    if not isinstance(states, list) or [item.get("document_id") for item in states] != expected:
        raise IntegrityError("M23-INTAKE-108 checkpoint coverage mismatch")
    for state in states:
        if state.get("status") not in CHECKPOINT_STATES:
            raise IntegrityError("M23-INTAKE-109 invalid checkpoint state")
        attempts = state.get("attempts")
        valid_attempts = (
            isinstance(attempts, int)
            and not isinstance(attempts, bool)
            and 0 <= attempts <= MAX_ITEM_ATTEMPTS
        )
        if not valid_attempts:
            raise IntegrityError("M23-INTAKE-110 invalid checkpoint attempts")


def _commit_checkpoint(path: Path, checkpoint: dict[str, Any]) -> None:
    checkpoint["checkpoint_sha256"] = _payload_digest(checkpoint, "checkpoint_sha256")
    _atomic_json(path, checkpoint)


def _verify_source(path: Path, item: Mapping[str, Any]) -> bytes:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise IntegrityError("M23-INTAKE-111 source file is unavailable") from exc
    if len(raw) != item["raw_bytes"]:
        raise IntegrityError("M23-INTAKE-112 source byte length mismatch")
    if sha256_bytes(raw) != item["raw_sha256"]:
        raise IntegrityError("M23-INTAKE-113 source SHA-256 mismatch")
    return raw


def _result_record(item: Mapping[str, Any], result: IntakeResult) -> dict[str, Any]:
    record = {
        "schema_version": "knowledge-engine-m23-live-intake-item/v1",
        "document_id": item["document_id"],
        "upload_id": item["upload_id"],
        "source_id": item["source_id"],
        "source_uri": item["source_uri"],
        "raw_sha256": result.raw_sha256,
        "normalized_sha256": result.normalized_sha256,
        "capture_id": result.capture_id,
        "capture_metadata_key": result.capture_metadata_key,
        "normalized_key": result.normalized_key,
        "raw_blob_key": result.raw_blob_key,
        "review_packet_prefix": result.review_packet_prefix,
        "review_packet_sha256": result.review_packet_sha256,
        "machine_finding_count": result.machine_finding_count,
        "status": result.status,
        "canonical_write_permitted": result.canonical_write_permitted,
    }
    record["item_result_sha256"] = _digest(record)
    return record


def _load_item_result(path: Path, item: Mapping[str, Any]) -> dict[str, Any]:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IntegrityError("M23-INTAKE-114 completed item result is unavailable") from exc
    if record.get("item_result_sha256") != _payload_digest(record, "item_result_sha256"):
        raise IntegrityError("M23-INTAKE-115 item result digest mismatch")
    identity_drift = (
        record.get("document_id") != item["document_id"]
        or record.get("raw_sha256") != item["raw_sha256"]
    )
    if identity_drift:
        raise IntegrityError("M23-INTAKE-116 item result identity mismatch")
    authority_drift = (
        record.get("canonical_write_permitted") is not False
        or record.get("status") != "review_required"
    )
    if authority_drift:
        raise IntegrityError("M23-INTAKE-117 item result authority drift")
    return record


def _verify_completed(store: FileObjectStore, record: Mapping[str, Any]) -> None:
    checks = {
        record["raw_blob_key"]: record["raw_sha256"],
        record["normalized_key"]: record["normalized_sha256"],
    }
    for key, expected in checks.items():
        metadata = store.head(key)
        invalid_object = (
            metadata is None
            or metadata.sha256 != expected
            or sha256_bytes(store.get(key)) != expected
        )
        if invalid_object:
            raise IntegrityError("M23-INTAKE-118 immutable object verification failed")


def _receipt(
    plan: Mapping[str, Any],
    checkpoint: Mapping[str, Any],
    results: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    completed = sum(item["status"] == "completed" for item in checkpoint["items"])
    failed = sum(item["status"] == "failed" for item in checkpoint["items"])
    receipt = {
        "schema_version": "knowledge-engine-m23-live-intake-receipt/v1",
        "batch_id": plan["batch_id"],
        "plan_sha256": plan["plan_sha256"],
        "checkpoint_sha256": checkpoint["checkpoint_sha256"],
        "corpus_manifest_digest": plan["corpus_manifest_digest"],
        "engine_sha": plan["engine_sha"],
        "source_sha": plan["source_sha"],
        "foundation_sha": plan["foundation_sha"],
        "status": "completed" if completed == len(plan["items"]) else "partial",
        "item_count": len(plan["items"]),
        "completed_count": completed,
        "failed_count": failed,
        "filesystem_evidence_written": True,
        "canonical_knowledge": False,
        "production_authority": False,
        "results": list(results),
        "protected_state": dict(PROTECTED_STATE),
    }
    receipt["receipt_sha256"] = _digest(receipt)
    return receipt


def validate_execution_receipt(receipt: Mapping[str, Any]) -> dict[str, Any]:
    if receipt.get("schema_version") != "knowledge-engine-m23-live-intake-receipt/v1":
        raise IntegrityError("M23-INTAKE-119 invalid receipt schema")
    if receipt.get("receipt_sha256") != _payload_digest(receipt, "receipt_sha256"):
        raise IntegrityError("M23-INTAKE-120 receipt digest mismatch")
    expected_identity = {
        "engine_sha": ENGINE_ENTRY_SHA,
        "source_sha": SOURCE_SHA,
        "foundation_sha": FOUNDATION_SHA,
        "corpus_manifest_digest": M23_1_MANIFEST_DIGEST,
    }
    if any(receipt.get(key) != value for key, value in expected_identity.items()):
        raise IntegrityError("M23-INTAKE-121 receipt identity mismatch")
    authority_drift = (
        receipt.get("canonical_knowledge") is not False
        or receipt.get("production_authority") is not False
    )
    if authority_drift:
        raise IntegrityError("M23-INTAKE-122 receipt authority drift")
    if receipt.get("protected_state") != PROTECTED_STATE:
        raise IntegrityError("M23-INTAKE-123 protected-state drift")
    results = receipt.get("results")
    if not isinstance(results, list):
        raise IntegrityError("M23-INTAKE-124 receipt results missing")
    if receipt.get("status") == "completed":
        complete_coverage = (
            len(results) == 6
            and receipt.get("completed_count") == 6
            and receipt.get("failed_count") == 0
        )
        if not complete_coverage:
            raise IntegrityError("M23-INTAKE-125 completed receipt coverage mismatch")
        if len({item.get("capture_id") for item in results}) != 6:
            raise IntegrityError("M23-INTAKE-126 duplicate capture identity")
        if any(item.get("canonical_write_permitted") is not False for item in results):
            raise IntegrityError("M23-INTAKE-127 canonical write was permitted")
    return dict(receipt)


def execute_live_intake(
    *,
    corpus_manifest: Mapping[str, Any],
    source_root: Path,
    evidence_root: Path,
    retrieved_at: str,
    owner: str,
    license_name: str,
    retry_failed: bool = False,
    intake_fn: Callable[..., IntakeResult] = intake_markdown,
) -> dict[str, Any]:
    corpus = validate_corpus_manifest(corpus_manifest)
    plan = _batch_plan(corpus, retrieved_at=retrieved_at)
    evidence_root = evidence_root.resolve()
    batch_root = evidence_root / "batches" / plan["batch_id"]
    plan_path = batch_root / "plan.json"
    checkpoint_path = batch_root / "checkpoint.json"
    receipt_path = batch_root / "execution-receipt.json"
    _immutable_json(plan_path, plan)

    if checkpoint_path.exists():
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        _validate_checkpoint(plan, checkpoint)
    else:
        checkpoint = _initial_checkpoint(plan)
        _commit_checkpoint(checkpoint_path, checkpoint)

    states = {item["document_id"]: item for item in checkpoint["items"]}
    store = FileObjectStore(evidence_root / "object-store")
    results: list[dict[str, Any]] = []

    for item in plan["items"]:
        state = states[item["document_id"]]
        result_path = batch_root / "items" / f"{item['document_id']}.json"
        if state["status"] == "completed":
            record = _load_item_result(result_path, item)
            _verify_completed(store, record)
            results.append(record)
            continue
        if state["status"] == "running":
            state["status"] = "failed"
            state["failure_code"] = "interrupted_previous_run"
        if state["status"] == "failed" and not retry_failed:
            continue
        if state["attempts"] >= MAX_ITEM_ATTEMPTS:
            continue

        state.update({"status": "running", "attempts": state["attempts"] + 1, "failure_code": None})
        checkpoint["revision"] += 1
        _commit_checkpoint(checkpoint_path, checkpoint)
        try:
            source_path = _safe_child(source_root, item["original_filename"])
            _verify_source(source_path, item)
            output_dir = evidence_root / "review-packets" / item["document_id"]
            result = intake_fn(
                store=store,
                request=IntakeRequest(
                    source_id=item["source_id"],
                    source_uri=item["source_uri"],
                    title=item["title"],
                    kind="markdown",
                    audience=item["audience"],
                    retrieved_at=retrieved_at,
                    owner=owner,
                    license=license_name,
                    content_type="text/markdown",
                ),
                input_path=source_path,
                output_dir=output_dir,
            )
            if result.raw_sha256 != item["raw_sha256"]:
                raise IntegrityError("M23-INTAKE-128 intake raw digest mismatch")
            record = _result_record(item, result)
            _immutable_json(result_path, record)
            _verify_completed(store, record)
            state.update(
                {
                    "status": "completed",
                    "failure_code": None,
                    "result_sha256": record["item_result_sha256"],
                }
            )
            results.append(record)
        except Exception as exc:
            state.update(
                {
                    "status": "failed",
                    "failure_code": type(exc).__name__,
                    "result_sha256": None,
                }
            )
        checkpoint["revision"] += 1
        _commit_checkpoint(checkpoint_path, checkpoint)

    ordered_results = []
    by_document = {item["document_id"]: item for item in results}
    for item in plan["items"]:
        if item["document_id"] in by_document:
            ordered_results.append(by_document[item["document_id"]])
    receipt = _receipt(plan, checkpoint, ordered_results)
    if receipt_path.exists():
        existing = json.loads(receipt_path.read_text(encoding="utf-8"))
        if existing.get("status") == "completed" and existing != receipt:
            raise IntegrityError("M23-INTAKE-129 final receipt collision")
        if existing.get("status") != "completed":
            _atomic_json(receipt_path, receipt)
    else:
        _atomic_json(receipt_path, receipt)
    validate_execution_receipt(receipt)
    return receipt


def _validated_https_url(url: str, allowed_hosts: set[str]) -> str:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise IntegrityError("M23-INTAKE-130 HTTPS source is invalid")
    host = parsed.hostname.lower().rstrip(".")
    if host not in {item.lower().rstrip(".") for item in allowed_hosts}:
        raise IntegrityError("M23-INTAKE-131 HTTPS host is not allowlisted")
    if host == "localhost" or host.endswith(".localhost"):
        raise IntegrityError("M23-INTAKE-132 local HTTPS host is forbidden")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise IntegrityError("M23-INTAKE-133 private or reserved IP literal is forbidden")
    if parsed.port not in {None, 443}:
        raise IntegrityError("M23-INTAKE-134 non-standard HTTPS port is forbidden")
    return url


def validate_https_capture(
    *,
    initial_url: str,
    final_url: str,
    redirect_chain: Sequence[str],
    allowed_hosts: set[str],
    content_type: str,
    body: bytes,
    max_bytes: int = MAX_HTTPS_BYTES,
) -> dict[str, Any]:
    if len(redirect_chain) > MAX_REDIRECTS:
        raise IntegrityError("M23-INTAKE-135 redirect limit exceeded")
    urls = [initial_url, *redirect_chain]
    if not urls or urls[-1] != final_url:
        raise IntegrityError("M23-INTAKE-136 redirect chain/final URL mismatch")
    for url in urls:
        _validated_https_url(url, allowed_hosts)
    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type not in ALLOWED_MEDIA_TYPES:
        raise IntegrityError("M23-INTAKE-137 HTTPS media type is forbidden")
    if not body or len(body) > max_bytes:
        raise IntegrityError("M23-INTAKE-138 HTTPS body exceeds bounds or is empty")
    return {
        "initial_url": initial_url,
        "final_url": final_url,
        "redirect_chain": list(redirect_chain),
        "content_type": media_type,
        "bytes": len(body),
        "sha256": sha256_bytes(body),
        "credentials_sent": False,
    }


__all__ = [
    "execute_live_intake",
    "validate_execution_receipt",
    "validate_https_capture",
]
