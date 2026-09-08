from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from knowledge_engine.m23_cloudflare_qdrant import SectionInput, validate_sections
from knowledge_engine.m26_gemini_dense_fallback import (
    GEMINI_DIMENSION,
    GEMINI_MODEL,
    GEMINI_PROVIDER,
    GEMINI_VECTOR_NAME,
    M26_BGE_PRIMARY_COLLECTION,
    M26_GEMINI_CANDIDATE_POINT_COUNT,
    M26_GEMINI_CANDIDATE_SOURCE_COUNT,
    M26_GEMINI_COLLECTION,
    M26_GEMINI_LEXICAL_DOCUMENTS_SHA256,
    M26_GEMINI_SEMANTIC_INPUTS_SHA256,
    M26_GEMINI_SOURCE_INDEX_SHA256,
    GeminiEmbeddingClient,
    GeminiEmbeddingConfig,
    build_gemini_qdrant_points,
    canonical_manifest_payload,
    qdrant_collection_create_payload,
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _assert_sha256(path: Path, expected: str, label: str) -> str:
    actual = _sha256_file(path)
    if actual != expected:
        raise SystemExit(f"{label} SHA256 mismatch: expected {expected}, got {actual}")
    return actual


def _load_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"invalid JSON artifact {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise SystemExit(f"JSON artifact must be an object: {path}")
    return raw


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise SystemExit(
                        f"invalid JSONL row {path}:{line_number}: {exc}"
                    ) from exc
                if not isinstance(row, dict):
                    raise SystemExit(
                        f"JSONL row must be an object: {path}:{line_number}"
                    )
                rows.append(row)
    except OSError as exc:
        raise SystemExit(f"cannot read JSONL artifact {path}: {exc}") from exc
    if not rows:
        raise SystemExit(f"JSONL artifact is empty: {path}")
    return rows


def _headers(api_key: str) -> dict[str, str]:
    return {"api-key": api_key, "Content-Type": "application/json"}


def _collection_url(base: str, collection: str) -> str:
    return f"{base.rstrip('/')}/collections/{quote(collection, safe='')}"


def _points_url(base: str, collection: str) -> str:
    return _collection_url(base, collection) + "/points?wait=true"


def _scroll_url(base: str, collection: str) -> str:
    return _collection_url(base, collection) + "/points/scroll"


def _count_url(base: str, collection: str) -> str:
    return _collection_url(base, collection) + "/points/count"


def _collection_info(base: str, collection: str, api_key: str) -> dict[str, Any]:
    response = httpx.get(
        _collection_url(base, collection),
        headers=_headers(api_key),
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise SystemExit("invalid Qdrant collection response")
    return payload


def _count_points(base: str, collection: str, api_key: str) -> int:
    response = httpx.post(
        _count_url(base, collection),
        headers=_headers(api_key),
        json={"exact": True},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    result = payload.get("result") if isinstance(payload, dict) else None
    value = result.get("count") if isinstance(result, dict) else None
    if isinstance(value, bool) or not isinstance(value, int):
        raise SystemExit("invalid Qdrant exact count response")
    return value


def _validate_gemini_collection_shape(payload: dict[str, Any]) -> None:
    result = payload.get("result")
    if not isinstance(result, dict):
        raise SystemExit("invalid Qdrant collection response")
    config = result.get("config")
    params = config.get("params") if isinstance(config, dict) else None
    vectors = params.get("vectors") if isinstance(params, dict) else None
    vector = vectors.get(GEMINI_VECTOR_NAME) if isinstance(vectors, dict) else None
    if not isinstance(vector, dict):
        raise SystemExit(
            "existing Gemini collection is missing the frozen named vector"
        )
    if vector.get("size") != GEMINI_DIMENSION or vector.get("distance") != "Cosine":
        raise SystemExit(
            "existing Gemini collection vector shape does not match 768/Cosine"
        )


def _ensure_isolated_collection(base: str, collection: str, api_key: str) -> None:
    response = httpx.get(
        _collection_url(base, collection),
        headers=_headers(api_key),
        timeout=30,
    )
    if response.status_code == 404:
        created = httpx.put(
            _collection_url(base, collection),
            headers=_headers(api_key),
            json=qdrant_collection_create_payload(),
            timeout=30,
        )
        created.raise_for_status()
        _validate_gemini_collection_shape(_collection_info(base, collection, api_key))
        return
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise SystemExit("invalid Qdrant collection response")
    _validate_gemini_collection_shape(payload)


def _scroll_section_ids(base: str, collection: str, api_key: str) -> set[str]:
    section_ids: set[str] = set()
    offset: Any = None
    pages = 0
    while True:
        body: dict[str, Any] = {
            "limit": 256,
            "with_payload": ["section_id"],
            "with_vector": False,
        }
        if offset is not None:
            body["offset"] = offset
        response = httpx.post(
            _scroll_url(base, collection),
            headers=_headers(api_key),
            json=body,
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        result = payload.get("result") if isinstance(payload, dict) else None
        points = result.get("points") if isinstance(result, dict) else None
        if not isinstance(points, list):
            raise SystemExit("invalid Qdrant scroll response")
        for point in points:
            point_payload = point.get("payload") if isinstance(point, dict) else None
            section_id = (
                point_payload.get("section_id")
                if isinstance(point_payload, dict)
                else None
            )
            if isinstance(section_id, str) and section_id.strip():
                section_ids.add(section_id.strip())
            else:
                raise SystemExit("Qdrant point missing canonical section_id")
        pages += 1
        if pages > 100:
            raise SystemExit("Qdrant scroll exceeded bounded page limit")
        offset = result.get("next_page_offset") if isinstance(result, dict) else None
        if offset is None:
            break
    return section_ids


def _canonical_id_digest(ids: set[str]) -> str:
    return hashlib.sha256("\n".join(sorted(ids)).encode("utf-8")).hexdigest()


def _validate_exact_inputs(
    semantic_path: Path, lexical_path: Path, source_path: Path
) -> tuple[
    list[SectionInput],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, str],
]:
    digests = {
        "semantic_inputs_sha256": _assert_sha256(
            semantic_path, M26_GEMINI_SEMANTIC_INPUTS_SHA256, "semantic-inputs"
        ),
        "lexical_documents_sha256": _assert_sha256(
            lexical_path, M26_GEMINI_LEXICAL_DOCUMENTS_SHA256, "lexical-documents"
        ),
        "source_index_sha256": _assert_sha256(
            source_path, M26_GEMINI_SOURCE_INDEX_SHA256, "source-index"
        ),
    }
    semantic_rows = _load_jsonl(semantic_path)
    lexical_rows = _load_jsonl(lexical_path)
    source_artifact = _load_json(source_path)
    source_rows = source_artifact.get("sources")
    if not isinstance(source_rows, list):
        raise SystemExit("source-index sources missing")
    article_source_count = source_artifact.get("article_source_count")
    if (
        article_source_count is not None
        and article_source_count != M26_GEMINI_CANDIDATE_SOURCE_COUNT
    ):
        raise SystemExit("source-index article_source_count mismatch")

    sections = validate_sections(semantic_rows)
    if len(sections) != M26_GEMINI_CANDIDATE_POINT_COUNT:
        raise SystemExit(
            "expected "
            f"{M26_GEMINI_CANDIDATE_POINT_COUNT} semantic rows, got {len(sections)}"
        )
    if len(lexical_rows) != M26_GEMINI_CANDIDATE_POINT_COUNT:
        raise SystemExit(
            "expected "
            f"{M26_GEMINI_CANDIDATE_POINT_COUNT} lexical rows, got {len(lexical_rows)}"
        )
    if len(source_rows) != M26_GEMINI_CANDIDATE_SOURCE_COUNT:
        raise SystemExit(
            "expected "
            f"{M26_GEMINI_CANDIDATE_SOURCE_COUNT} source rows, got {len(source_rows)}"
        )

    semantic_ids = {section.section_id for section in sections}
    lexical_ids = {
        str(item.get("section_id", "")).strip()
        for item in lexical_rows
        if (
            isinstance(item.get("section_id"), str)
            and str(item.get("section_id")).strip()
        )
    }
    if len(semantic_ids) != M26_GEMINI_CANDIDATE_POINT_COUNT:
        raise SystemExit("semantic section IDs are not unique")
    if len(lexical_ids) != M26_GEMINI_CANDIDATE_POINT_COUNT:
        raise SystemExit("lexical section IDs are not unique")
    if semantic_ids != lexical_ids:
        raise SystemExit("lexical/semantic canonical section ID parity failed")
    return sections, lexical_rows, source_rows, digests


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Materialize isolated SM-GF Gemini candidate index"
    )
    parser.add_argument("--semantic-inputs", required=True, type=Path)
    parser.add_argument("--lexical-documents", required=True, type=Path)
    parser.add_argument("--source-index", required=True, type=Path)
    parser.add_argument("--manifest-out", required=True, type=Path)
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--collection", default=M26_GEMINI_COLLECTION)
    parser.add_argument("--primary-bge-collection", default=M26_BGE_PRIMARY_COLLECTION)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--allow-isolated-candidate-write", action="store_true")
    args = parser.parse_args()

    if args.collection != M26_GEMINI_COLLECTION:
        raise SystemExit(
            "collection must remain the frozen separate Gemini candidate collection"
        )
    if args.primary_bge_collection != M26_BGE_PRIMARY_COLLECTION:
        raise SystemExit(
            "primary BGE collection must remain the frozen R0 candidate collection"
        )
    if args.collection == args.primary_bge_collection:
        raise SystemExit("Gemini and BGE collections must never be identical")
    if not 1 <= args.batch_size <= 100:
        raise SystemExit("batch-size must be within 1..100")

    sections, lexical_rows, source_rows, digests = _validate_exact_inputs(
        args.semantic_inputs, args.lexical_documents, args.source_index
    )
    semantic_ids = {section.section_id for section in sections}
    canonical_digest = _canonical_id_digest(semantic_ids)

    manifest = canonical_manifest_payload()
    manifest.update(
        {
            **digests,
            "semantic_row_count": len(sections),
            "lexical_row_count": len(lexical_rows),
            "source_count": len(source_rows),
            "canonical_section_id_count": len(semantic_ids),
            "canonical_section_id_sha256": canonical_digest,
            "canonical_section_id_parity_lexical_semantic": True,
            "primary_bge_collection": args.primary_bge_collection,
            "gemini_collection": args.collection,
            "collections_are_separate": True,
            "secret_values_persisted": False,
        }
    )

    if args.preflight_only:
        manifest.update(
            {
                "materialization_status": "offline_exact_input_preflight_passed",
                "bge_live_parity_checked": False,
                "gemini_live_materialized": False,
            }
        )
        args.manifest_out.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return 0

    if not args.allow_isolated_candidate_write:
        raise SystemExit(
            "live materialization requires --allow-isolated-candidate-write"
        )

    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    qdrant_url = os.environ.get("QDRANT_URL", "").strip()
    qdrant_key = (
        os.environ.get("QDRANT_API_KEY_WRITE")
        or os.environ.get("QDRANT_API_KEY")
        or ""
    ).strip()
    if not gemini_key:
        raise SystemExit(
            "GEMINI_API_KEY is required locally; do not place it in artifacts"
        )
    if not qdrant_url or not qdrant_key:
        raise SystemExit("isolated Qdrant URL/write key is required locally")

    _collection_info(qdrant_url, args.primary_bge_collection, qdrant_key)
    bge_count = _count_points(qdrant_url, args.primary_bge_collection, qdrant_key)
    if bge_count != M26_GEMINI_CANDIDATE_POINT_COUNT:
        raise SystemExit(
            "BGE point parity failed: expected "
            f"{M26_GEMINI_CANDIDATE_POINT_COUNT}, got {bge_count}"
        )
    bge_ids = _scroll_section_ids(qdrant_url, args.primary_bge_collection, qdrant_key)
    if bge_ids != semantic_ids:
        raise SystemExit("BGE/lexical/semantic canonical section ID parity failed")

    _ensure_isolated_collection(qdrant_url, args.collection, qdrant_key)
    _collection_info(qdrant_url, args.collection, qdrant_key)
    existing_count = _count_points(qdrant_url, args.collection, qdrant_key)
    if existing_count not in {0, M26_GEMINI_CANDIDATE_POINT_COUNT}:
        raise SystemExit(
            f"unexpected pre-existing Gemini point count: {existing_count}"
        )
    if existing_count == M26_GEMINI_CANDIDATE_POINT_COUNT:
        existing_ids = _scroll_section_ids(qdrant_url, args.collection, qdrant_key)
        if existing_ids != semantic_ids:
            raise SystemExit(
                "pre-existing Gemini collection has non-canonical section IDs"
            )

    client = GeminiEmbeddingClient(
        GeminiEmbeddingConfig(api_key=gemini_key, timeout_seconds=60.0)
    )
    written = 0
    for start in range(0, len(sections), args.batch_size):
        batch = sections[start : start + args.batch_size]
        vectors = client.embed_documents(batch)
        points = build_gemini_qdrant_points(batch, vectors)
        response = httpx.put(
            _points_url(qdrant_url, args.collection),
            headers=_headers(qdrant_key),
            json={"points": points},
            timeout=60,
        )
        response.raise_for_status()
        written += len(points)

    _collection_info(qdrant_url, args.collection, qdrant_key)
    points_count = _count_points(qdrant_url, args.collection, qdrant_key)
    if points_count != M26_GEMINI_CANDIDATE_POINT_COUNT:
        raise SystemExit(
            "Gemini collection point parity failed: "
            f"expected {M26_GEMINI_CANDIDATE_POINT_COUNT}, got {points_count}"
        )
    gemini_ids = _scroll_section_ids(qdrant_url, args.collection, qdrant_key)
    if gemini_ids != semantic_ids:
        raise SystemExit("Gemini/lexical/BGE canonical section ID parity failed")

    manifest.update(
        {
            "materialization_status": "materialized_isolated_candidate",
            "written_points": written,
            "readback_points_count": points_count,
            "bge_points_count": bge_count,
            "bge_canonical_section_id_sha256": _canonical_id_digest(bge_ids),
            "gemini_canonical_section_id_sha256": _canonical_id_digest(gemini_ids),
            "canonical_section_id_parity_bge_gemini_lexical": True,
            "bge_live_parity_checked": True,
            "gemini_live_materialized": True,
            "model": GEMINI_MODEL,
            "provider": GEMINI_PROVIDER,
            "dimension": GEMINI_DIMENSION,
            "vector_name": GEMINI_VECTOR_NAME,
        }
    )
    args.manifest_out.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
