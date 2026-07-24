from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from src.knowledge_engine.errors import IntegrityError
from src.knowledge_engine.m23_cloudflare_qdrant import (
    CLOUDFLARE_MODEL,
    QDRANT_VECTOR_NAME,
    VECTOR_DIMENSION,
    CloudflareConfig,
    QdrantConfig,
    build_execution_plan,
    build_qdrant_points,
    build_receipt,
    deterministic_point_id,
    embed_sections,
    parse_cloudflare_embeddings,
    preflight_qdrant_collection,
    upsert_qdrant_points,
    validate_qdrant_collection_response,
    validate_sections,
)
from src.knowledge_engine.m23_cloudflare_qdrant_cli import main


def _sections():
    return validate_sections(
        [
            {
                "section_id": "doc-1#0001",
                "text": "Cloudflare Workers AI produces embeddings.",
                "payload": {"document_id": "doc-1", "audience": "private"},
            },
            {
                "section_id": "doc-2#0001",
                "text": "Qdrant stores derived vectors.",
                "payload": {"document_id": "doc-2", "audience": "private"},
            },
        ]
    )


def _vectors(count: int = 2):
    return [[0.0] * (VECTOR_DIMENSION - 1) + [1.0] for _ in range(count)]


def _collection_response(*, points_count: int = 0):
    return {
        "status": "ok",
        "result": {
            "status": "green",
            "points_count": points_count,
            "indexed_vectors_count": 0,
            "config": {
                "params": {
                    "vectors": {
                        "default": {
                            "size": 1024,
                            "distance": "Cosine",
                            "datatype": "float32",
                        }
                    },
                    "sparse_vectors": None,
                }
            },
        },
    }


def test_plan_is_bounded_and_non_authoritative():
    plan = build_execution_plan(_sections(), collection_name="m23-pilot")
    assert plan["model"] == CLOUDFLARE_MODEL
    assert plan["vector_dimension"] == 1024
    assert plan["qdrant"]["point_count"] == 2
    assert plan["qdrant"]["vector_name"] == "default"
    assert plan["authority"] == {
        "canonical_knowledge": False,
        "candidate_release_eligible": False,
        "production_authority": False,
        "r2_mutation": False,
        "pointer_mutation": False,
        "source_write": False,
    }
    assert len(plan["plan_sha256"]) == 64


def test_cloudflare_response_validation_order_and_normalization():
    response = {"success": True, "result": {"data": _vectors()}}
    assert parse_cloudflare_embeddings(response, expected_count=2) == _vectors()
    with pytest.raises(IntegrityError, match="dimension"):
        parse_cloudflare_embeddings(
            {"success": True, "result": {"data": [[1.0, 2.0]]}},
            expected_count=1,
        )


def test_cloudflare_client_uses_model_and_bearer_token():
    observed = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["url"] = str(request.url)
        observed["authorization"] = request.headers.get("Authorization")
        observed["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"success": True, "result": {"data": _vectors()}}
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        vectors = embed_sections(
            _sections(),
            CloudflareConfig(account_id="account", api_token="secret"),
            client=client,
        )
    assert vectors == _vectors()
    assert observed["url"].endswith("/ai/run/@cf/baai/bge-m3")
    assert observed["authorization"] == "Bearer secret"
    assert observed["body"]["text"] == [section.text for section in _sections()]


def test_qdrant_points_use_named_default_vector_and_derived_payload():
    points = build_qdrant_points(_sections(), _vectors())
    assert points[0]["id"] == deterministic_point_id("doc-1#0001")
    assert points[0]["vector"] == {QDRANT_VECTOR_NAME: _vectors()[0]}
    assert points[0]["payload"]["canonical_knowledge"] is False
    assert points[0]["payload"]["candidate_release_eligible"] is False
    assert points[0]["payload"]["production_authority"] is False
    assert points[0]["payload"]["vector_dimension"] == 1024
    assert points[0]["payload"]["vector_name"] == "default"


def test_qdrant_collection_schema_requires_named_default():
    result = validate_qdrant_collection_response(_collection_response())
    assert result["vector_name"] == "default"
    assert result["vector_dimension"] == 1024
    broken = _collection_response()
    broken["result"]["config"]["params"]["vectors"] = {
        "other": {"size": 1024, "distance": "Cosine"}
    }
    with pytest.raises(IntegrityError, match="named vector default"):
        validate_qdrant_collection_response(broken)


def test_qdrant_preflight_is_read_only():
    observed = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["method"] = request.method
        observed["url"] = str(request.url)
        return httpx.Response(200, json=_collection_response())

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = preflight_qdrant_collection(
            QdrantConfig(
                base_url="https://example.qdrant.io",
                api_key="secret",
                collection_name="m23-pilot",
            ),
            client=client,
        )
    assert observed["method"] == "GET"
    assert observed["url"].endswith("/collections/m23-pilot")
    assert result["read_only"] is True


def test_qdrant_write_requires_explicit_permission():
    with pytest.raises(IntegrityError, match="explicit allow_write"):
        upsert_qdrant_points(
            [],
            QdrantConfig(
                base_url="https://example.qdrant.io",
                api_key="secret",
                collection_name="m23-pilot",
            ),
            allow_write=False,
        )


def test_qdrant_upsert_contract_preflights_before_write():
    observed = {"methods": []}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["methods"].append(request.method)
        observed["api_key"] = request.headers.get("api-key")
        if request.method == "GET":
            return httpx.Response(200, json=_collection_response())
        observed["url"] = str(request.url)
        observed["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "result": {"status": "acknowledged", "operation_id": 1},
            },
        )

    points = build_qdrant_points(_sections(), _vectors())
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = upsert_qdrant_points(
            points,
            QdrantConfig(
                base_url="https://example.qdrant.io",
                api_key="secret",
                collection_name="m23-pilot",
            ),
            allow_write=True,
            client=client,
        )
    assert result["status"] == "ok"
    assert observed["methods"] == ["GET", "PUT"]
    assert "/collections/m23-pilot/points" in observed["url"]
    assert "wait=true" in observed["url"]
    assert "ordering=strong" in observed["url"]
    assert observed["api_key"] == "secret"
    assert len(observed["body"]["points"]) == 2
    assert "default" in observed["body"]["points"][0]["vector"]


def test_first_pilot_write_requires_empty_collection():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_collection_response(points_count=1))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(IntegrityError, match="empty collection"):
            upsert_qdrant_points(
                build_qdrant_points(_sections(), _vectors()),
                QdrantConfig(
                    base_url="https://example.qdrant.io",
                    api_key="secret",
                    collection_name="m23-pilot",
                ),
                allow_write=True,
                client=client,
            )


def test_receipt_never_contains_secrets():
    plan = build_execution_plan(_sections(), collection_name="m23-pilot")
    receipt = build_receipt(
        plan=plan,
        vectors=_vectors(),
        qdrant_response={"status": "ok"},
        executed=True,
        qdrant_write=True,
    )
    serialized = json.dumps(receipt)
    assert "api_key" not in serialized
    assert "token" not in serialized
    assert receipt["qdrant_vector_name"] == "default"
    assert receipt["secrets_recorded"] is False
    assert len(receipt["receipt_sha256"]) == 64


def test_cli_defaults_to_dry_run(tmp_path: Path):
    input_path = tmp_path / "sections.json"
    output_path = tmp_path / "evidence"
    input_path.write_text(
        json.dumps(
            {
                "sections": [
                    {
                        "section_id": "doc-1#0001",
                        "text": "Dry run only.",
                        "payload": {"audience": "private"},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    assert main(
        [
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--collection",
            "m23-pilot",
        ]
    ) == 0
    receipt = json.loads((output_path / "execution-receipt.json").read_text())
    assert receipt["executed"] is False
    assert receipt["qdrant_write"] is False
    assert not (output_path / "qdrant-points.json").exists()
def _sections_with_texts(texts: list[str]):
    return validate_sections(
        [
            {
                "section_id": f"budget-doc-{index}#0001",
                "text": text,
                "payload": {"document_id": f"budget-doc-{index}"},
            }
            for index, text in enumerate(texts)
        ]
    )


def test_cloudflare_batches_preserve_full_text_under_character_budget():
    texts = ["A" * 9000, "B" * 9000, "C" * 100]
    observed_batches = []

    def handler(request: httpx.Request) -> httpx.Response:
        selected = json.loads(request.content)["text"]
        observed_batches.append(selected)
        return httpx.Response(
            200,
            json={
                "success": True,
                "result": {"data": _vectors(len(selected))},
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        vectors = embed_sections(
            _sections_with_texts(texts),
            CloudflareConfig(account_id="account", api_token="secret"),
            client=client,
        )

    assert len(vectors) == 3
    assert [len(batch) for batch in observed_batches] == [1, 2]
    assert [text for batch in observed_batches for text in batch] == texts


def test_cloudflare_context_limit_recursively_splits_and_preserves_order():
    texts = ["one", "two", "three", "four"]
    observed_batches = []

    def handler(request: httpx.Request) -> httpx.Response:
        selected = json.loads(request.content)["text"]
        observed_batches.append(selected)
        if len(selected) > 1:
            return httpx.Response(
                400,
                json={
                    "success": False,
                    "errors": [
                        {
                            "code": 3030,
                            "message": (
                                "AiError: Max context reached 80825 tokens "
                                "but model supports only 60000"
                            ),
                        }
                    ],
                },
            )
        return httpx.Response(
            200,
            json={"success": True, "result": {"data": _vectors(1)}},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        vectors = embed_sections(
            _sections_with_texts(texts),
            CloudflareConfig(account_id="account", api_token="secret"),
            client=client,
        )

    assert len(vectors) == 4
    assert [len(batch) for batch in observed_batches] == [
        4,
        2,
        1,
        1,
        2,
        1,
        1,
    ]
    assert [
        batch[0] for batch in observed_batches if len(batch) == 1
    ] == texts


def test_cloudflare_non_context_http_error_remains_fail_closed():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content)["text"])
        return httpx.Response(
            400,
            json={
                "success": False,
                "errors": [
                    {"code": 10000, "message": "permission denied"}
                ],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            embed_sections(
                _sections(),
                CloudflareConfig(
                    account_id="account", api_token="secret"
                ),
                client=client,
            )
    assert len(calls) == 1

