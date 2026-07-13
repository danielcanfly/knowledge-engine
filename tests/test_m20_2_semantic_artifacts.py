from __future__ import annotations

import json
import math
from copy import deepcopy
from pathlib import Path

import pytest

from knowledge_engine.m20_embedding_contract import (
    ContractError,
    load_json,
    validate_benchmark_suite,
    validate_provider_contract,
)
from knowledge_engine.m20_semantic_artifacts import (
    SEMANTIC_METADATA_FILENAME,
    SEMANTIC_METADATA_SCHEMA,
    SEMANTIC_VECTOR_FILENAME,
    SemanticArtifactError,
    build_semantic_artifacts,
    flat_cosine_rank,
    load_verified_semantic_artifacts,
    verify_semantic_artifacts,
)

BENCHMARK_PATH = Path("benchmarks/m20/bilingual-blog-benchmark-v1.json")
CONTRACT_PATH = Path("benchmarks/m20/provider-contract.fixture.json")
BUILDER_ENGINE_SHA = "d6cd1dd613ad4675aab216356956c9abdf6e4053"


def _suite() -> dict:
    return load_json(BENCHMARK_PATH)


def _contract() -> dict:
    return load_json(CONTRACT_PATH)


def _vectors() -> dict[str, list[float]]:
    suite = validate_benchmark_suite(_suite())
    contract = validate_provider_contract(_contract())
    dimension = contract["model"]["vector_dimension"]
    result: dict[str, list[float]] = {}
    for index, document in enumerate(suite["documents"]):
        vector = [0.0] * dimension
        vector[index] = 1.0
        result[document["section_id"]] = vector
    return result


def _build(tmp_path: Path, name: str = "semantic") -> Path:
    root = tmp_path / name
    build_semantic_artifacts(
        _suite(),
        _contract(),
        _vectors(),
        root,
        builder_engine_sha=BUILDER_ENGINE_SHA,
    )
    return root


def test_build_is_byte_identical_and_immutable(tmp_path: Path) -> None:
    first = _build(tmp_path, "first")
    second = _build(tmp_path, "second")
    assert (first / SEMANTIC_METADATA_FILENAME).read_bytes() == (
        second / SEMANTIC_METADATA_FILENAME
    ).read_bytes()
    assert (first / SEMANTIC_VECTOR_FILENAME).read_bytes() == (
        second / SEMANTIC_VECTOR_FILENAME
    ).read_bytes()
    assert (first / SEMANTIC_METADATA_FILENAME).stat().st_mode & 0o777 == 0o444
    assert (first / SEMANTIC_VECTOR_FILENAME).stat().st_mode & 0o777 == 0o444


def test_metadata_maps_exact_rows_and_identities(tmp_path: Path) -> None:
    root = _build(tmp_path)
    metadata = verify_semantic_artifacts(
        root / SEMANTIC_METADATA_FILENAME,
        root / SEMANTIC_VECTOR_FILENAME,
        _suite(),
        _contract(),
        expected_builder_engine_sha=BUILDER_ENGINE_SHA,
    )
    suite = validate_benchmark_suite(_suite())
    assert metadata["schema_version"] == SEMANTIC_METADATA_SCHEMA
    assert metadata["vectors"]["row_count"] == len(suite["documents"]) == 8
    assert metadata["vectors"]["dimension"] == 64
    assert [item["row"] for item in metadata["documents"]] == list(range(8))
    assert [item["section_id"] for item in metadata["documents"]] == [
        item["section_id"] for item in suite["documents"]
    ]
    assert metadata["identities"] == {
        "builder_engine_commit_sha": BUILDER_ENGINE_SHA,
        "provider_contract_engine_commit_sha": (
            "b33d06a8f2b9896a8be29009f36cbbde4b5cb5c1"
        ),
        "source_commit_sha": "a6ba738d910d01d2ae99b1968f0831989934c549",
        "foundation_commit_sha": "e5ef644053d34e89c70d2ceb37521e1c59234832",
    }


def test_vector_coverage_must_be_exact(tmp_path: Path) -> None:
    vectors = _vectors()
    vectors.pop(next(iter(vectors)))
    vectors["unknown#section"] = [1.0] + [0.0] * 63
    with pytest.raises(SemanticArtifactError, match="coverage mismatch"):
        build_semantic_artifacts(
            _suite(),
            _contract(),
            vectors,
            tmp_path / "semantic",
            builder_engine_sha=BUILDER_ENGINE_SHA,
        )


def test_duplicate_section_ids_fail_closed(tmp_path: Path) -> None:
    suite = deepcopy(_suite())
    suite["documents"][1]["section_id"] = suite["documents"][0]["section_id"]
    with pytest.raises(ContractError, match="section IDs must be unique"):
        build_semantic_artifacts(
            suite,
            _contract(),
            _vectors(),
            tmp_path / "semantic",
            builder_engine_sha=BUILDER_ENGINE_SHA,
        )


@pytest.mark.parametrize(
    ("replacement", "message"),
    [
        ([1.0, 0.0], "exactly 64"),
        ([float("nan")] + [0.0] * 63, "finite"),
        ([1.0, 1.0] + [0.0] * 62, "L2-normalized"),
    ],
)
def test_dimension_finiteness_and_norm_fail_closed(
    tmp_path: Path,
    replacement: list[float],
    message: str,
) -> None:
    vectors = _vectors()
    vectors[next(iter(vectors))] = replacement
    with pytest.raises(SemanticArtifactError, match=message):
        build_semantic_artifacts(
            _suite(),
            _contract(),
            vectors,
            tmp_path / "semantic",
            builder_engine_sha=BUILDER_ENGINE_SHA,
        )


def test_existing_artifact_directory_is_never_overwritten(tmp_path: Path) -> None:
    root = _build(tmp_path)
    with pytest.raises(SemanticArtifactError, match="already exists"):
        build_semantic_artifacts(
            _suite(),
            _contract(),
            _vectors(),
            root,
            builder_engine_sha=BUILDER_ENGINE_SHA,
        )


def test_vector_truncation_and_tampering_fail_closed(tmp_path: Path) -> None:
    root = _build(tmp_path)
    vectors_path = root / SEMANTIC_VECTOR_FILENAME
    vectors_path.chmod(0o644)
    vectors_path.write_bytes(vectors_path.read_bytes()[:-4])
    with pytest.raises(SemanticArtifactError, match="vector digest mismatch"):
        verify_semantic_artifacts(
            root / SEMANTIC_METADATA_FILENAME,
            vectors_path,
            _suite(),
            _contract(),
        )


def test_metadata_tampering_fails_closed(tmp_path: Path) -> None:
    root = _build(tmp_path)
    metadata_path = root / SEMANTIC_METADATA_FILENAME
    metadata_path.chmod(0o644)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["documents"][0]["audience"] = "internal"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(SemanticArtifactError, match="metadata digest mismatch"):
        verify_semantic_artifacts(
            metadata_path,
            root / SEMANTIC_VECTOR_FILENAME,
            _suite(),
            _contract(),
        )


def test_cross_release_identity_fails_closed(tmp_path: Path) -> None:
    contract = deepcopy(_contract())
    contract["identities"]["source_commit_sha"] = "f" * 40
    with pytest.raises(SemanticArtifactError, match="identities do not match"):
        build_semantic_artifacts(
            _suite(),
            contract,
            _vectors(),
            tmp_path / "semantic",
            builder_engine_sha=BUILDER_ENGINE_SHA,
        )


def test_wrong_expected_builder_sha_fails_closed(tmp_path: Path) -> None:
    root = _build(tmp_path)
    with pytest.raises(SemanticArtifactError, match="builder Engine SHA mismatch"):
        verify_semantic_artifacts(
            root / SEMANTIC_METADATA_FILENAME,
            root / SEMANTIC_VECTOR_FILENAME,
            _suite(),
            _contract(),
            expected_builder_engine_sha="f" * 40,
        )


def test_flat_cosine_is_deterministic_and_acl_filtered(tmp_path: Path) -> None:
    root = _build(tmp_path)
    metadata, vector_bytes = load_verified_semantic_artifacts(root, _suite(), _contract())
    documents = metadata["documents"]
    public_document = next(item for item in documents if item["audience"] == "public")
    internal_document = next(item for item in documents if item["audience"] == "internal")
    query = [0.0] * metadata["model"]["dimension"]
    query[public_document["row"]] = 1.0
    results = flat_cosine_rank(
        metadata,
        vector_bytes,
        query,
        allowed_audiences={"public"},
        limit=8,
    )
    assert results[0]["section_id"] == public_document["section_id"]
    assert internal_document["section_id"] not in {item["section_id"] for item in results}


def test_flat_cosine_ties_break_by_section_id(tmp_path: Path) -> None:
    root = _build(tmp_path)
    metadata, vector_bytes = load_verified_semantic_artifacts(root, _suite(), _contract())
    public_documents = sorted(
        [item for item in metadata["documents"] if item["audience"] == "public"],
        key=lambda item: item["section_id"],
    )
    left, right = public_documents[:2]
    query = [0.0] * metadata["model"]["dimension"]
    query[left["row"]] = 1 / math.sqrt(2)
    query[right["row"]] = 1 / math.sqrt(2)
    results = flat_cosine_rank(
        metadata,
        vector_bytes,
        query,
        allowed_audiences={"public"},
        limit=2,
    )
    assert [item["section_id"] for item in results] == [
        left["section_id"],
        right["section_id"],
    ]


def test_query_vector_and_limit_are_bounded(tmp_path: Path) -> None:
    root = _build(tmp_path)
    metadata, vector_bytes = load_verified_semantic_artifacts(root, _suite(), _contract())
    with pytest.raises(SemanticArtifactError, match="exactly 64"):
        flat_cosine_rank(
            metadata,
            vector_bytes,
            [1.0],
            allowed_audiences={"public"},
        )
    with pytest.raises(SemanticArtifactError, match="between 1 and 100"):
        flat_cosine_rank(
            metadata,
            vector_bytes,
            [1.0] + [0.0] * 63,
            allowed_audiences={"public"},
            limit=101,
        )
