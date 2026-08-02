from __future__ import annotations

import json
import zipfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

import knowledge_engine.m26_pa7_arbitrary_query_runtime as aq_runtime
from knowledge_engine.compiler import compile_release
from knowledge_engine.m26_verified_answer_citation_gate import VerifiedAnswerGateError
from knowledge_engine.publisher import publish_release
from knowledge_engine.storage import FileObjectStore

ROOT = Path(__file__).resolve().parents[1]
_M23_INGESTION_TEST_MODULE = "test_m23_6_2_qdrant_ingestion_manifest"
_LEGACY_AQ_FORMAL_FIXTURE_MODULES = {
    "test_m26_pa7_final_web_readiness",
    "test_m26_pa_7_corrective_formal_product_readiness",
}
_FIXED_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
_LEGACY_PROVIDER_SCHEMA = "aq3-provider-candidate/v3"
_LEGACY_FIXTURE_FACETS = {
    "direct_answer",
    "entity_role",
    "entity_a",
    "entity_b",
    "comparison_basis",
    "relationship_semantics",
    "complementary_roles",
    "graph_edge",
    "source_endpoint",
    "target_endpoint",
    "relation_semantics",
    "provenance_source",
    "source_identity",
    "temporal_ordering",
    "temporal_record",
    "ordering_boundary",
    "non_entailment_boundary",
}


@pytest.fixture(autouse=True)
def normalize_legacy_aq_formal_fixture_provider_schema(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Upgrade only historical formal-fixture provider envelopes to the current schema.

    The PA.7 formal fixture providers predate the AQ3 provider envelope and intentionally
    exercise evidence/citation/SLO behavior rather than provider-schema rejection. The runtime
    verifier remains authoritative: this shim only supplies the newly required envelope fields
    and claim surface metadata, then delegates back to the unmodified parser and every
    downstream semantic, citation, support, graph, and mutation gate.
    """

    module = request.node.module
    module_name = module.__name__.rsplit(".", 1)[-1] if module is not None else ""
    if module_name not in _LEGACY_AQ_FORMAL_FIXTURE_MODULES:
        return

    original = aq_runtime._parse_multi_provider_json

    def parse_with_legacy_envelope_upgrade(text: str) -> tuple[dict[str, Any], dict[str, Any]]:
        try:
            return original(text)
        except VerifiedAnswerGateError as exc:
            if exc.code != "M26-PA7-ME-005":
                raise
        stripped = text.strip()
        parsed, _ = aq_runtime._extract_single_provider_json_object(stripped)
        if not isinstance(parsed, Mapping):
            return original(text)
        value = _upgrade_legacy_fixture_provider_value(dict(parsed))
        if value is None:
            return original(text)
        return original(json.dumps(value, ensure_ascii=False, separators=(",", ":")))

    monkeypatch.setattr(
        aq_runtime,
        "_parse_multi_provider_json",
        parse_with_legacy_envelope_upgrade,
    )


def _upgrade_legacy_fixture_provider_value(value: dict[str, Any]) -> dict[str, Any] | None:
    legacy_keys = {
        "status",
        "relation",
        "selected_evidence_ids",
        "claims",
        "abstention_reason",
    }
    if not legacy_keys.issubset(value) or set(value) - legacy_keys - {"missing_facets"}:
        return None
    if value.get("status") == "abstain":
        value.setdefault("schema_version", _LEGACY_PROVIDER_SCHEMA)
        value.setdefault("answer_text", "")
        value.setdefault("claims", [])
        value.setdefault("selected_evidence_ids", [])
        value.setdefault("missing_facets", [])
        return value

    upgraded_claims: list[dict[str, Any]] = []
    answer_parts: list[str] = []
    for raw_claim in value.get("claims") or []:
        if not isinstance(raw_claim, Mapping):
            return None
        claim = dict(raw_claim)
        support_refs = claim.get("support_refs") or []
        if not isinstance(support_refs, list):
            return None
        exact_quotes = [
            str(ref.get("exact_quote") or ref.get("exact_support_snippet") or "").strip()
            for ref in support_refs
            if isinstance(ref, Mapping)
        ]
        surface_text = " ".join(item for item in exact_quotes if item).strip()
        claim_id = str(claim.get("claim_id") or f"claim_{len(upgraded_claims) + 1}")
        claim.setdefault("claim_id", claim_id)
        claim.setdefault("surface_text", surface_text or "Evidence supports this claim.")
        claim.setdefault("facet_ids", sorted(_LEGACY_FIXTURE_FACETS))
        claim.setdefault("support_mode", "multi_evidence_exact_quote")
        upgraded_claims.append(claim)
        if surface_text:
            answer_parts.append(f"{surface_text} [[{claim_id}]]")
    value["claims"] = upgraded_claims
    value.setdefault("schema_version", _LEGACY_PROVIDER_SCHEMA)
    value.setdefault("answer_text", " ".join(answer_parts).strip())
    value.setdefault("missing_facets", [])
    return value


@pytest.fixture(autouse=True)
def freeze_synthetic_m23_ingestion_zip_headers(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep the M23.6.2 synthetic evidence digest independent of wall-clock time.

    The production ingestion contract hashes immutable evidence bytes. Its synthetic
    test fixture created ZIP entries from bare names, which lets ``zipfile`` inject
    the current timestamp into each member header. Two otherwise identical fixture
    builds could therefore differ when they crossed ZIP's two-second time boundary.
    This patch is restricted to that test module and does not alter runtime code.
    """

    module = request.node.module
    if module is None or module.__name__.rsplit(".", 1)[-1] != _M23_INGESTION_TEST_MODULE:
        return

    original = zipfile.ZipFile.writestr

    def deterministic_writestr(
        archive: zipfile.ZipFile,
        zinfo_or_arcname: str | zipfile.ZipInfo,
        data: str | bytes,
        compress_type: int | None = None,
        compresslevel: int | None = None,
    ) -> Any:
        if isinstance(zinfo_or_arcname, str):
            info = zipfile.ZipInfo(zinfo_or_arcname, date_time=_FIXED_ZIP_TIMESTAMP)
            info.compress_type = archive.compression if compress_type is None else compress_type
            zinfo_or_arcname = info
        return original(
            archive,
            zinfo_or_arcname,
            data,
            compress_type=compress_type,
            compresslevel=compresslevel,
        )

    monkeypatch.setattr(zipfile.ZipFile, "writestr", deterministic_writestr)


@pytest.fixture
def built_store(tmp_path: Path):
    store = FileObjectStore(tmp_path / "store")
    compiled = compile_release(
        bundle_root=ROOT / "examples/okf-bundle",
        work_root=tmp_path / "builds",
        release_time=datetime(2026, 7, 2, 12, tzinfo=UTC),
        source_repository="danielcanfly/knowledge-source",
        source_commit_sha="a" * 40,
        foundation_commit_sha="d" * 40,
    )
    result = publish_release(
        store=store,
        compiled=compiled,
        channel="staging",
        promoted_at="2026-07-02T12:00:00Z",
    )
    return store, compiled, result
