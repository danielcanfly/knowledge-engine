from __future__ import annotations

import copy
import hashlib
import json
import shutil
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import httpx
import pytest

from knowledge_engine.m26_real_corpus_binding import (
    CONTRACT_SCHEMA_PATH,
    ENTRY_PATH,
    FAILURE_SCHEMA_PATH,
    POLICY_PATH,
    RECEIPT_SCHEMA_PATH,
    REGISTRY_PATH,
    HttpxReadOnlyQdrantClient,
    ReadResponse,
    RealCorpusBindingError,
    bind_real_corpus,
    build_sanitized_failure_receipt,
    canonical_sha256,
    load_json,
    receipt_bytes,
    verify_failure_receipt,
    verify_receipt,
)

ROOT = Path(__file__).resolve().parents[1]
GENERATED_AT = "2026-07-27T06:00:00Z"
WORKFLOW = {
    "repository": "danielcanfly/knowledge-engine",
    "workflow_name": "M26.PA.2 exact live read-only evidence",
    "run_id": "123456789",
    "run_attempt": "1",
    "head_sha": "a" * 40,
    "environment": "m23-r3-diagnostic",
    "query_id": "m26-pa-2-production-binding-v1",
    "evidence_mode": "live_read_only",
}


def pretty(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_bytes(pretty(dict(value)))


def resign(value: dict[str, Any]) -> None:
    value["self_sha256"] = ""
    value["self_sha256"] = canonical_sha256(value)


def fixture_manifest(entry: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, Any]:
    release_id = entry["production_identity"]["release_id"]
    kinds = policy["manifest"]["artifact_inventory"]["required_kinds"]
    artifacts = [
        {
            "kind": kind,
            "key": f"releases/{release_id}/artifacts/{index:02d}-{kind}.json",
            "sha256": hashlib.sha256(kind.encode()).hexdigest(),
            "bytes": index + 1,
            "media_type": "application/json",
            "audiences": ["authenticated_internal"],
            "required": True,
        }
        for index, kind in enumerate(kinds, start=1)
    ]
    identity = entry["production_identity"]
    return {
        "schema_version": "knowledge-engine-release/v1",
        "release_id": release_id,
        "status": "production",
        "authority": {
            "source_admitted": True,
            "candidate_release_authorized": True,
            "semantic_serving_authorized": True,
            "production_pointer_authorized": True,
            "public_production_traffic_authorized": False,
        },
        "identities": {
            "engine_commit_sha": identity["engine_sha"],
            "source_commit_sha": identity["source_sha"],
            "foundation_commit_sha": identity["foundation_sha"],
            "admission_sha256": identity["admission_sha256"],
        },
        "counts": copy.deepcopy(policy["expected_counts"]),
        "artifacts": artifacts,
        "production_promotion": {
            "schema_version": "knowledge-engine-m25-10-production-promotion/v1",
            "status": "production_pointer_authorized",
            "source_candidate_channel": "candidate-blog-m25-10",
            "source_candidate_manifest_sha256": identity["candidate_manifest_sha256"],
            "accepted_owner_smoke": True,
            "production_pointer_authorized": True,
            "public_production_traffic_authorized": False,
            "public_production_traffic_target": None,
            "qdrant_candidate_collection": identity["qdrant_collection"],
            "qdrant_candidate_authority_filter": {
                "candidate_release_eligible": True,
                "production_authority": False,
            },
        },
    }


def fixture_pointer(entry: Mapping[str, Any], manifest_sha: str) -> dict[str, Any]:
    identity = entry["production_identity"]
    return {
        "schema_version": "1.0",
        "channel": "production",
        "release_id": identity["release_id"],
        "manifest_key": identity["manifest_key"],
        "manifest_sha256": manifest_sha,
        "promoted_at": "2026-07-24T12:00:00Z",
        "promotion_schema_version": "knowledge-engine-m25-10-production-promotion/v1",
        "source_candidate_channel": "candidate-blog-m25-10",
        "source_candidate_manifest_sha256": identity["candidate_manifest_sha256"],
        "production_authority": True,
        "public_production_traffic_mutated": False,
    }


def rebind_root(root: Path, pointer_bytes: bytes, manifest_bytes: bytes) -> None:
    entry = load_json(root / ENTRY_PATH)
    policy = load_json(root / POLICY_PATH)
    pointer_sha = hashlib.sha256(pointer_bytes).hexdigest()
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    identity = entry["production_identity"]
    identity["pointer_sha256"] = pointer_sha
    identity["manifest_sha256"] = manifest_sha
    resign(entry)
    write_json(root / ENTRY_PATH, entry)
    contract_schema = load_json(root / CONTRACT_SCHEMA_PATH)
    identity_schema = contract_schema["oneOf"][0]["properties"]["production_identity"]["properties"]
    identity_schema["pointer_sha256"] = {"const": pointer_sha}
    identity_schema["manifest_sha256"] = {"const": manifest_sha}
    write_json(root / CONTRACT_SCHEMA_PATH, contract_schema)
    receipt_schema = load_json(root / RECEIPT_SCHEMA_PATH)
    release_schema = receipt_schema["properties"]["release"]["properties"]
    release_schema["pointer_sha256"] = {"const": pointer_sha}
    release_schema["manifest_sha256"] = {"const": manifest_sha}
    write_json(root / RECEIPT_SCHEMA_PATH, receipt_schema)
    registry = load_json(root / REGISTRY_PATH)
    registry["artifacts"]["entry_contract_sha256"] = canonical_sha256(entry)
    registry["artifacts"]["retrieval_policy_sha256"] = canonical_sha256(policy)
    registry["schemas"] = {
        "contracts_schema_sha256": hashlib.sha256(
            (root / CONTRACT_SCHEMA_PATH).read_bytes()
        ).hexdigest(),
        "receipt_schema_sha256": hashlib.sha256(
            (root / RECEIPT_SCHEMA_PATH).read_bytes()
        ).hexdigest(),
        "failure_schema_sha256": hashlib.sha256(
            (root / FAILURE_SCHEMA_PATH).read_bytes()
        ).hexdigest(),
    }
    resign(registry)
    write_json(root / REGISTRY_PATH, registry)


def bound_root(tmp_path: Path) -> tuple[Path, bytes, bytes]:
    root = tmp_path / "repo"
    shutil.copytree(ROOT, root)
    entry = load_json(root / ENTRY_PATH)
    policy = load_json(root / POLICY_PATH)
    manifest = fixture_manifest(entry, policy)
    manifest_bytes = pretty(manifest)
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    pointer = fixture_pointer(entry, manifest_sha)
    pointer_bytes = pretty(pointer)
    rebind_root(root, pointer_bytes, manifest_bytes)
    return (root, pointer_bytes, manifest_bytes)


class FakeStore:
    capabilities = frozenset({"get"})
    credential_scope = "read_only"

    def __init__(self, root: Path, pointer: bytes, manifest: bytes) -> None:
        policy = load_json(root / POLICY_PATH)
        self.credential_contract_sha256 = policy["read_only"]["r2"]["credential_contract_sha256"]
        identity = load_json(root / ENTRY_PATH)["production_identity"]
        self.objects = {identity["pointer_key"]: pointer, identity["manifest_key"]: manifest}
        self.calls: list[str] = []

    def get(self, key: str) -> bytes:
        self.calls.append(key)
        return self.objects[key]


class FakeQdrant:
    capabilities = frozenset({"count", "scroll"})
    credential_scope = "read_only"

    def __init__(
        self,
        root: Path,
        *,
        total: int = 4197,
        count_value: int | None = None,
        mutate_row: Callable[[int, dict[str, Any]], None] | None = None,
        repeated_offset: bool = False,
        empty_partial: bool = False,
        oversized_page: bool = False,
        non_ok_count: bool = False,
        non_ok_scroll: bool = False,
        duplicate_point: bool = False,
        duplicate_section: bool = False,
        incomplete_population: bool = False,
    ) -> None:
        policy = load_json(root / POLICY_PATH)
        self.policy = policy
        self.credential_contract_sha256 = policy["read_only"]["qdrant"][
            "credential_contract_sha256"
        ]
        self.total = total
        self.count_value = total if count_value is None else count_value
        self.mutate_row = mutate_row
        self.repeated_offset = repeated_offset
        self.empty_partial = empty_partial
        self.oversized_page = oversized_page
        self.non_ok_count = non_ok_count
        self.non_ok_scroll = non_ok_scroll
        self.duplicate_point = duplicate_point
        self.duplicate_section = duplicate_section
        self.incomplete_population = incomplete_population
        self.count_calls: list[dict[str, Any]] = []
        self.scroll_calls: list[dict[str, Any]] = []

    def count(
        self, *, collection: str, query_filter: Mapping[str, Any], timeout_seconds: float
    ) -> ReadResponse:
        self.count_calls.append(
            {
                "collection": collection,
                "query_filter": copy.deepcopy(query_filter),
                "timeout_seconds": timeout_seconds,
            }
        )
        if self.non_ok_count:
            return ReadResponse({"status": "error", "result": {"count": 0}})
        return ReadResponse({"status": "ok", "result": {"count": self.count_value}})

    def _row(self, index: int) -> dict[str, Any]:
        identity = load_json(ROOT / ENTRY_PATH)["production_identity"]
        point = {
            "id": f"point-{index:05d}",
            "payload": {
                "section_id": f"section-{index:05d}",
                "source_id": f"source-{index % 156:03d}",
                "article_id": f"article-{index % 156:03d}",
                "release_id": identity["release_id"],
                "source_commit_sha": identity["source_sha"],
                "admission_sha256": identity["admission_sha256"],
                "candidate_release_eligible": True,
                "production_authority": False,
                "text_sha256": hashlib.sha256(f"text-{index}".encode()).hexdigest(),
            },
        }
        if self.duplicate_point and index == 1:
            point["id"] = "point-00000"
        if self.duplicate_section and index == 1:
            point["payload"]["section_id"] = "section-00000"
        if self.mutate_row is not None and index == 0:
            self.mutate_row(index, point)
        return point

    def scroll(
        self, *, collection: str, request: Mapping[str, Any], timeout_seconds: float
    ) -> ReadResponse:
        self.scroll_calls.append(
            {
                "collection": collection,
                "request": copy.deepcopy(dict(request)),
                "timeout_seconds": timeout_seconds,
            }
        )
        if self.non_ok_scroll:
            return ReadResponse({"status": "error", "result": {}})
        start = int(request.get("offset", 0))
        limit = int(request["limit"])
        if self.empty_partial and start == 0:
            return ReadResponse({"status": "ok", "result": {"points": [], "next_page_offset": 1}})
        stop = min(start + limit, self.total)
        if self.oversized_page and start == 0:
            stop = min(start + limit + 1, self.total)
        rows = [self._row(index) for index in range(start, stop)]
        next_offset: int | None = stop if stop < self.total else None
        if self.repeated_offset and start > 0:
            next_offset = start
        if self.incomplete_population and next_offset is None and rows:
            rows.pop()
        return ReadResponse(
            {"status": "ok", "result": {"points": rows, "next_page_offset": next_offset}}
        )


def successful_binding(tmp_path: Path) -> tuple[dict[str, Any], FakeStore, FakeQdrant, Path]:
    root, pointer, manifest = bound_root(tmp_path)
    store = FakeStore(root, pointer, manifest)
    qdrant = FakeQdrant(root)
    receipt = bind_real_corpus(
        root=root, store=store, qdrant=qdrant, generated_at=GENERATED_AT, workflow=WORKFLOW
    )
    return (receipt, store, qdrant, root)


def test_successful_binding_is_metadata_only_and_deterministic(tmp_path: Path) -> None:
    receipt, store, qdrant, root = successful_binding(tmp_path)
    verify_receipt(root, receipt)
    assert store.calls == [
        "channels/production.json",
        load_json(root / ENTRY_PATH)["production_identity"]["manifest_key"],
    ]
    assert len(qdrant.count_calls) == 1
    assert len(qdrant.scroll_calls) == 17
    assert receipt["qdrant"]["observed_point_count"] == 4197
    assert receipt["qdrant"]["sample_size"] == 5
    assert receipt["authority"]["r2_write_operations"] == 0
    assert receipt["authority"]["qdrant_write_operations"] == 0
    assert receipt["authority"]["provider_calls"] == 0
    assert receipt["authority"]["answer_generation_operations"] == 0
    serialized = receipt_bytes(receipt).decode().lower()
    for forbidden in ("heading", "origin_path", "raw body", "bearer "):
        assert forbidden not in serialized
    assert receipt_bytes(receipt) == receipt_bytes(copy.deepcopy(receipt))


def test_repeated_runs_produce_identical_receipt(tmp_path: Path) -> None:
    root, pointer, manifest = bound_root(tmp_path)
    first = bind_real_corpus(
        root=root,
        store=FakeStore(root, pointer, manifest),
        qdrant=FakeQdrant(root),
        generated_at=GENERATED_AT,
        workflow=WORKFLOW,
    )
    second = bind_real_corpus(
        root=root,
        store=FakeStore(root, pointer, manifest),
        qdrant=FakeQdrant(root),
        generated_at=GENERATED_AT,
        workflow=WORKFLOW,
    )
    assert first == second
    assert receipt_bytes(first) == receipt_bytes(second)


def test_exact_qdrant_selector_and_filter_are_used(tmp_path: Path) -> None:
    receipt, _, qdrant, root = successful_binding(tmp_path)
    policy = load_json(root / POLICY_PATH)
    assert receipt["qdrant"]["with_payload"] == policy["payload"]["allowlist"]
    for call in qdrant.scroll_calls:
        request = call["request"]
        assert request["with_payload"] == policy["payload"]["allowlist"]
        assert request["with_vector"] is False
        assert request["filter"] == qdrant.count_calls[0]["query_filter"]


class WriteCapableStore(FakeStore):
    def put(self, *_: Any, **__: Any) -> None:
        raise AssertionError("must never be called")


class WriteCapableQdrant(FakeQdrant):
    def upsert(self, *_: Any, **__: Any) -> None:
        raise AssertionError("must never be called")


@pytest.mark.parametrize("surface", ["store", "qdrant"])
def test_write_capable_surface_is_rejected(surface: str, tmp_path: Path) -> None:
    root, pointer, manifest = bound_root(tmp_path)
    store: Any = FakeStore(root, pointer, manifest)
    qdrant: Any = FakeQdrant(root)
    if surface == "store":
        store = WriteCapableStore(root, pointer, manifest)
    else:
        qdrant = WriteCapableQdrant(root)
    with pytest.raises(RealCorpusBindingError, match="mutation method"):
        bind_real_corpus(
            root=root, store=store, qdrant=qdrant, generated_at=GENERATED_AT, workflow=WORKFLOW
        )


@pytest.mark.parametrize("surface", ["store", "qdrant"])
def test_wrong_credential_scope_is_rejected(surface: str, tmp_path: Path) -> None:
    root, pointer, manifest = bound_root(tmp_path)
    store = FakeStore(root, pointer, manifest)
    qdrant = FakeQdrant(root)
    target: Any = store if surface == "store" else qdrant
    target.credential_scope = "read_write"
    with pytest.raises(RealCorpusBindingError, match="credential is not read-only"):
        bind_real_corpus(
            root=root, store=store, qdrant=qdrant, generated_at=GENERATED_AT, workflow=WORKFLOW
        )


@pytest.mark.parametrize("surface", ["store", "qdrant"])
def test_wrong_credential_contract_is_rejected(surface: str, tmp_path: Path) -> None:
    root, pointer, manifest = bound_root(tmp_path)
    store = FakeStore(root, pointer, manifest)
    qdrant = FakeQdrant(root)
    target: Any = store if surface == "store" else qdrant
    target.credential_contract_sha256 = "0" * 64
    with pytest.raises(RealCorpusBindingError, match="credential contract mismatch"):
        bind_real_corpus(
            root=root, store=store, qdrant=qdrant, generated_at=GENERATED_AT, workflow=WORKFLOW
        )


def run_with_manifest_mutation(
    tmp_path: Path, mutation: Callable[[dict[str, Any]], None], match: str
) -> None:
    root, pointer_bytes, manifest_bytes = bound_root(tmp_path)
    manifest = json.loads(manifest_bytes)
    mutation(manifest)
    mutated = pretty(manifest)
    store = FakeStore(root, pointer_bytes, mutated)
    with pytest.raises(RealCorpusBindingError, match=match):
        bind_real_corpus(
            root=root,
            store=store,
            qdrant=FakeQdrant(root),
            generated_at=GENERATED_AT,
            workflow=WORKFLOW,
        )


def test_pointer_digest_drift_rejected(tmp_path: Path) -> None:
    root, pointer, manifest = bound_root(tmp_path)
    store = FakeStore(root, pointer + b" ", manifest)
    with pytest.raises(RealCorpusBindingError, match="pointer digest drift"):
        bind_real_corpus(
            root=root,
            store=store,
            qdrant=FakeQdrant(root),
            generated_at=GENERATED_AT,
            workflow=WORKFLOW,
        )


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (lambda value: value.__setitem__("schema_version", "wrong"), "manifest digest drift"),
        (lambda value: value.__setitem__("release_id", "wrong"), "manifest digest drift"),
        (lambda value: value.__setitem__("status", "candidate"), "manifest digest drift"),
        (
            lambda value: value["authority"].__setitem__("production_pointer_authorized", False),
            "manifest digest drift",
        ),
        (
            lambda value: value["authority"].__setitem__(
                "public_production_traffic_authorized", True
            ),
            "manifest digest drift",
        ),
        (
            lambda value: value["identities"].__setitem__("engine_commit_sha", "0" * 40),
            "manifest digest drift",
        ),
        (
            lambda value: value["counts"].__setitem__("semantic_documents", 4198),
            "manifest digest drift",
        ),
        (lambda value: value["artifacts"].pop(), "manifest digest drift"),
    ],
)
def test_manifest_byte_drift_fails_before_parsing(
    tmp_path: Path, mutation: Callable[[dict[str, Any]], None], match: str
) -> None:
    run_with_manifest_mutation(tmp_path, mutation, match)


def mutate_payload(key: str, value: Any) -> Callable[[int, dict[str, Any]], None]:

    def apply(_: int, row: dict[str, Any]) -> None:
        row["payload"][key] = value

    return apply


@pytest.mark.parametrize(
    ("key", "value", "match"),
    [
        ("text", "raw corpus sentence", "raw-text-like key"),
        ("body", "raw corpus sentence", "raw-text-like key"),
        ("content", "raw corpus sentence", "raw-text-like key"),
        ("markdown", "# raw", "raw-text-like key"),
        ("document", "raw", "raw-text-like key"),
        ("api_key", "not-even-needed", "secret-like key"),
        ("authorization", "Bearer abcdefghijk", "secret-like key"),
        ("unknown_field", "value", "unexpected field"),
        ("origin_path", "sources/a.md", "unexpected field"),
        ("heading", "Heading text", "unexpected field"),
    ],
)
def test_malicious_or_unknown_payload_key_rejected(
    key: str, value: Any, match: str, tmp_path: Path
) -> None:
    root, pointer, manifest = bound_root(tmp_path)
    with pytest.raises(RealCorpusBindingError, match=match):
        bind_real_corpus(
            root=root,
            store=FakeStore(root, pointer, manifest),
            qdrant=FakeQdrant(root, mutate_row=mutate_payload(key, value)),
            generated_at=GENERATED_AT,
            workflow=WORKFLOW,
        )


@pytest.mark.parametrize(
    ("value", "match"),
    [
        ("Bearer abcdefghijk", "secret-like value"),
        ("sk-abcdefghijklmnopqrstuvwxyz", "secret-like value"),
        ("https://user:pass@example.com/path", "credential-bearing URL"),
        ("https://example.com/?api_key=secret", "credential-bearing URL"),
        ("x" * 1025, "bounded limit"),
    ],
)
def test_malicious_payload_value_rejected(value: str, match: str, tmp_path: Path) -> None:
    root, pointer, manifest = bound_root(tmp_path)
    with pytest.raises(RealCorpusBindingError, match=match):
        bind_real_corpus(
            root=root,
            store=FakeStore(root, pointer, manifest),
            qdrant=FakeQdrant(root, mutate_row=mutate_payload("article_id", value)),
            generated_at=GENERATED_AT,
            workflow=WORKFLOW,
        )


def test_nested_payload_rejected_recursively(tmp_path: Path) -> None:
    root, pointer, manifest = bound_root(tmp_path)

    def mutation(_: int, row: dict[str, Any]) -> None:
        row["payload"]["article_id"] = {"nested": {"body": "raw"}}

    with pytest.raises(RealCorpusBindingError, match="raw-text-like key|nested material"):
        bind_real_corpus(
            root=root,
            store=FakeStore(root, pointer, manifest),
            qdrant=FakeQdrant(root, mutate_row=mutation),
            generated_at=GENERATED_AT,
            workflow=WORKFLOW,
        )


def test_vector_field_rejected(tmp_path: Path) -> None:
    root, pointer, manifest = bound_root(tmp_path)

    def mutation(_: int, row: dict[str, Any]) -> None:
        row["vector"] = [0.0]

    with pytest.raises(RealCorpusBindingError, match="unknown fields|vector"):
        bind_real_corpus(
            root=root,
            store=FakeStore(root, pointer, manifest),
            qdrant=FakeQdrant(root, mutate_row=mutation),
            generated_at=GENERATED_AT,
            workflow=WORKFLOW,
        )


def test_required_payload_field_missing(tmp_path: Path) -> None:
    root, pointer, manifest = bound_root(tmp_path)

    def mutation(_: int, row: dict[str, Any]) -> None:
        del row["payload"]["source_id"]

    with pytest.raises(RealCorpusBindingError, match="identity field is missing"):
        bind_real_corpus(
            root=root,
            store=FakeStore(root, pointer, manifest),
            qdrant=FakeQdrant(root, mutate_row=mutation),
            generated_at=GENERATED_AT,
            workflow=WORKFLOW,
        )


def test_payload_filter_identity_drift(tmp_path: Path) -> None:
    root, pointer, manifest = bound_root(tmp_path)
    with pytest.raises(RealCorpusBindingError, match="authority identity drift"):
        bind_real_corpus(
            root=root,
            store=FakeStore(root, pointer, manifest),
            qdrant=FakeQdrant(root, mutate_row=mutate_payload("production_authority", True)),
            generated_at=GENERATED_AT,
            workflow=WORKFLOW,
        )


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"count_value": 4198}, "point count drift"),
        ({"non_ok_count": True}, "count returned non-ok"),
        ({"non_ok_scroll": True}, "scroll returned non-ok"),
        ({"empty_partial": True}, "partial empty page"),
        ({"oversized_page": True}, "exceeds the bounded page size"),
        ({"repeated_offset": True}, "pagination offset repeated"),
        ({"duplicate_point": True}, "duplicate point ID"),
        ({"duplicate_section": True}, "duplicate section ID"),
        ({"incomplete_population": True}, "paginated population is incomplete"),
    ],
)
def test_qdrant_adversarial_failures(kwargs: dict[str, Any], match: str, tmp_path: Path) -> None:
    root, pointer, manifest = bound_root(tmp_path)
    with pytest.raises(RealCorpusBindingError, match=match):
        bind_real_corpus(
            root=root,
            store=FakeStore(root, pointer, manifest),
            qdrant=FakeQdrant(root, **kwargs),
            generated_at=GENERATED_AT,
            workflow=WORKFLOW,
        )


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("repository", "other/repo", "repository identity drift"),
        ("environment", "production", "environment identity drift"),
        ("evidence_mode", "non_live", "not an exact live read-only run"),
        ("head_sha", "bad", "head SHA is invalid"),
        ("run_id", "", "workflow identity value is invalid"),
    ],
)
def test_workflow_identity_drift_rejected(
    field: str, value: str, match: str, tmp_path: Path
) -> None:
    root, pointer, manifest = bound_root(tmp_path)
    workflow = dict(WORKFLOW)
    workflow[field] = value
    with pytest.raises(RealCorpusBindingError, match=match):
        bind_real_corpus(
            root=root,
            store=FakeStore(root, pointer, manifest),
            qdrant=FakeQdrant(root),
            generated_at=GENERATED_AT,
            workflow=workflow,
        )


@pytest.mark.parametrize(
    "value", ["2026-07-27", "2026-13-40T99:99:99Z", "2026-07-27T06:00:00.000Z"]
)
def test_invalid_generated_at_rejected(value: str, tmp_path: Path) -> None:
    root, pointer, manifest = bound_root(tmp_path)
    with pytest.raises(RealCorpusBindingError, match="generated_at"):
        bind_real_corpus(
            root=root,
            store=FakeStore(root, pointer, manifest),
            qdrant=FakeQdrant(root),
            generated_at=value,
            workflow=WORKFLOW,
        )


def test_sanitized_failure_receipt_hides_unexpected_secret(tmp_path: Path) -> None:
    root, _, _ = bound_root(tmp_path)
    receipt = build_sanitized_failure_receipt(
        root=root,
        generated_at=GENERATED_AT,
        workflow=WORKFLOW,
        error=RuntimeError("Bearer super-secret-token-value"),
        operation_counts={"r2_reads": 1, "qdrant_count_requests": 0, "qdrant_scroll_requests": 0},
    )
    verify_failure_receipt(root, receipt)
    serialized = receipt_bytes(receipt).decode()
    assert "super-secret" not in serialized
    assert receipt["error"]["code"] == "M26-PA2-UNEXPECTED"
    assert receipt["authority"]["r2_write_operations"] == 0
    assert receipt["authority"]["qdrant_write_operations"] == 0


def test_sanitized_failure_receipt_is_deterministic(tmp_path: Path) -> None:
    root, _, _ = bound_root(tmp_path)
    kwargs = {
        "root": root,
        "generated_at": GENERATED_AT,
        "workflow": WORKFLOW,
        "error": RealCorpusBindingError("M26-PA2-TEST", "bounded safe failure"),
    }
    first = build_sanitized_failure_receipt(**kwargs)
    second = build_sanitized_failure_receipt(**kwargs)
    assert first == second
    assert receipt_bytes(first) == receipt_bytes(second)


def test_receipt_tamper_rejected(tmp_path: Path) -> None:
    receipt, _, _, root = successful_binding(tmp_path)
    receipt["authority"]["provider_calls"] = 1
    with pytest.raises(RealCorpusBindingError, match="schema validation|self digest"):
        verify_receipt(root, receipt)


def test_httpx_read_only_client_retries_429_once() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, json={"status": "error"}, request=request)
        return httpx.Response(
            200, json={"status": "ok", "result": {"count": 4197}}, request=request
        )

    client = HttpxReadOnlyQdrantClient(
        base_url="https://qdrant.example",
        api_key="secret",
        maximum_retries=1,
        sleeper=lambda _: None,
        transport=httpx.MockTransport(handler),
    )
    response = client.count(collection="collection", query_filter={"must": []}, timeout_seconds=1.0)
    assert response.attempts == 2
    assert calls == 2


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_httpx_read_only_client_rejects_4xx(status: int) -> None:

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"status": "error"}, request=request)

    client = HttpxReadOnlyQdrantClient(
        base_url="https://qdrant.example", api_key="secret", transport=httpx.MockTransport(handler)
    )
    with pytest.raises(RealCorpusBindingError, match="non-success status"):
        client.count(collection="collection", query_filter={"must": []}, timeout_seconds=1.0)


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_httpx_read_only_client_bounds_5xx_retry(status: int) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, json={"status": "error"}, request=request)

    client = HttpxReadOnlyQdrantClient(
        base_url="https://qdrant.example",
        api_key="secret",
        maximum_retries=1,
        sleeper=lambda _: None,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(RealCorpusBindingError, match="retry ceiling reached"):
        client.count(collection="collection", query_filter={"must": []}, timeout_seconds=1.0)
    assert calls == 2


def test_httpx_read_only_client_rejects_malformed_json() -> None:

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json", request=request)

    client = HttpxReadOnlyQdrantClient(
        base_url="https://qdrant.example", api_key="secret", transport=httpx.MockTransport(handler)
    )
    with pytest.raises(RealCorpusBindingError, match="malformed JSON"):
        client.count(collection="collection", query_filter={"must": []}, timeout_seconds=1.0)


def test_httpx_read_only_client_bounds_timeout_retry() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("timeout", request=request)

    client = HttpxReadOnlyQdrantClient(
        base_url="https://qdrant.example",
        api_key="secret",
        maximum_retries=1,
        sleeper=lambda _: None,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(RealCorpusBindingError, match="timed out"):
        client.count(collection="collection", query_filter={"must": []}, timeout_seconds=1.0)
    assert calls == 2


@pytest.mark.parametrize(
    "url",
    [
        "http://qdrant.example",
        "https://user:pass@qdrant.example",
        "https://qdrant.example?api_key=x",
        "https://qdrant.example/#token",
    ],
)
def test_httpx_client_rejects_credential_unsafe_url(url: str) -> None:
    with pytest.raises(RealCorpusBindingError, match="credential-safe"):
        HttpxReadOnlyQdrantClient(base_url=url, api_key="secret")


def rebound_objects(
    tmp_path: Path,
    *,
    pointer_mutation: Callable[[dict[str, Any]], None] | None = None,
    manifest_mutation: Callable[[dict[str, Any]], None] | None = None,
    malformed_manifest: bytes | None = None,
) -> tuple[Path, bytes, bytes]:
    root, pointer_bytes, manifest_bytes = bound_root(tmp_path)
    pointer = json.loads(pointer_bytes)
    if malformed_manifest is not None:
        manifest_bytes = malformed_manifest
    else:
        manifest = json.loads(manifest_bytes)
        if manifest_mutation is not None:
            manifest_mutation(manifest)
        manifest_bytes = pretty(manifest)
    pointer["manifest_sha256"] = hashlib.sha256(manifest_bytes).hexdigest()
    if pointer_mutation is not None:
        pointer_mutation(pointer)
    pointer_bytes = pretty(pointer)
    rebind_root(root, pointer_bytes, manifest_bytes)
    return (root, pointer_bytes, manifest_bytes)


def bind_rebound(root: Path, pointer: bytes, manifest: bytes) -> dict[str, Any]:
    return bind_real_corpus(
        root=root,
        store=FakeStore(root, pointer, manifest),
        qdrant=FakeQdrant(root),
        generated_at=GENERATED_AT,
        workflow=WORKFLOW,
    )


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (lambda value: value.__setitem__("channel", "candidate"), "pointer identity drift"),
        (lambda value: value.__setitem__("release_id", "other"), "pointer identity drift"),
        (lambda value: value.__setitem__("manifest_key", "wrong.json"), "pointer identity drift"),
        (lambda value: value.__setitem__("production_authority", False), "pointer identity drift"),
        (
            lambda value: value.__setitem__("public_production_traffic_mutated", True),
            "pointer identity drift",
        ),
        (lambda value: value.__setitem__("unknown", False), "unknown fields"),
    ],
)
def test_pointer_structural_drift_rejected_after_digest_rebind(
    mutation: Callable[[dict[str, Any]], None], match: str, tmp_path: Path
) -> None:
    root, pointer, manifest = rebound_objects(tmp_path, pointer_mutation=mutation)
    with pytest.raises(RealCorpusBindingError, match=match):
        bind_rebound(root, pointer, manifest)


def test_manifest_malformed_json_rejected_after_digest_rebind(tmp_path: Path) -> None:
    root, pointer, manifest = rebound_objects(tmp_path, malformed_manifest=b"{not-json")
    with pytest.raises(RealCorpusBindingError, match="invalid JSON"):
        bind_rebound(root, pointer, manifest)


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (lambda value: value.__setitem__("schema_version", "wrong"), "manifest schema drift"),
        (lambda value: value.__setitem__("release_id", "wrong"), "manifest release drift"),
        (lambda value: value.__setitem__("status", "candidate"), "manifest status drift"),
        (
            lambda value: value["authority"].__setitem__("production_pointer_authorized", False),
            "manifest authority drift",
        ),
        (
            lambda value: value["authority"].__setitem__(
                "public_production_traffic_authorized", True
            ),
            "manifest authority drift",
        ),
        (
            lambda value: value["identities"].__setitem__("engine_commit_sha", "0" * 40),
            "manifest identity drift",
        ),
        (
            lambda value: value["identities"].__setitem__("source_commit_sha", "0" * 40),
            "manifest identity drift",
        ),
        (
            lambda value: value["identities"].__setitem__("foundation_commit_sha", "0" * 40),
            "manifest identity drift",
        ),
        (
            lambda value: value["identities"].__setitem__("admission_sha256", "0" * 64),
            "manifest identity drift",
        ),
        (lambda value: value.pop("artifacts"), "required surface is incomplete"),
        (
            lambda value: value["artifacts"][-1].__setitem__("kind", "other"),
            "required artifact kind is missing",
        ),
        (
            lambda value: value["artifacts"].append(copy.deepcopy(value["artifacts"][0])),
            "artifact key is duplicated",
        ),
        (
            lambda value: value["artifacts"][0].__setitem__("sha256", "bad"),
            "artifact digest is malformed",
        ),
        (lambda value: value["artifacts"][0].__setitem__("unknown", False), "unknown fields"),
        (
            lambda value: value["artifacts"][0].__setitem__(
                "key", f"releases/{'m25blog-5250f8422f4f-f5f01d82c7a1-fe499db2e043'}/../escape"
            ),
            "artifact key is unsafe",
        ),
    ],
)
def test_manifest_structural_drift_rejected_after_digest_rebind(
    mutation: Callable[[dict[str, Any]], None], match: str, tmp_path: Path
) -> None:
    root, pointer, manifest = rebound_objects(tmp_path, manifest_mutation=mutation)
    with pytest.raises(RealCorpusBindingError, match=match):
        bind_rebound(root, pointer, manifest)


@pytest.mark.parametrize(
    "count_key",
    [
        "document_sources",
        "document_series",
        "document_articles",
        "document_sections",
        "document_graph_nodes",
        "document_graph_edges",
        "semantic_documents",
    ],
)
def test_every_manifest_count_is_frozen(count_key: str, tmp_path: Path) -> None:

    def mutation(value: dict[str, Any]) -> None:
        value["counts"][count_key] += 1

    root, pointer, manifest = rebound_objects(tmp_path, manifest_mutation=mutation)
    with pytest.raises(RealCorpusBindingError, match="population drift"):
        bind_rebound(root, pointer, manifest)


def test_mixed_case_raw_text_key_is_rejected(tmp_path: Path) -> None:
    root, pointer, manifest = bound_root(tmp_path)
    with pytest.raises(RealCorpusBindingError, match="raw-text-like key"):
        bind_real_corpus(
            root=root,
            store=FakeStore(root, pointer, manifest),
            qdrant=FakeQdrant(root, mutate_row=mutate_payload("BoDy", "raw")),
            generated_at=GENERATED_AT,
            workflow=WORKFLOW,
        )


def test_nested_list_raw_text_is_rejected(tmp_path: Path) -> None:
    root, pointer, manifest = bound_root(tmp_path)

    def mutation(_: int, row: dict[str, Any]) -> None:
        row["payload"]["article_id"] = [{"passage": "raw"}]

    with pytest.raises(RealCorpusBindingError, match="raw-text-like key"):
        bind_real_corpus(
            root=root,
            store=FakeStore(root, pointer, manifest),
            qdrant=FakeQdrant(root, mutate_row=mutation),
            generated_at=GENERATED_AT,
            workflow=WORKFLOW,
        )
