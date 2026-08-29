from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from knowledge_engine import (
    m26_aq_semantic_contract,
    m26_cloudflare_provider_router,
    m26_pa7_arbitrary_query_runtime,
    m26_public_api,
)
from knowledge_engine.m26_public_api import PublicQuotaLedger, create_app

ROOT = Path(__file__).resolve().parents[1]


def _problem_code(body: bytes) -> str:
    parsed, problem = m26_public_api._parse_public_request(body)  # noqa: SLF001
    assert parsed is None
    assert problem is not None
    return problem.code


def test_answers_health_alias_matches_public_health(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(m26_public_api, "_readiness_problem", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        m26_public_api,
        "build_health_dto",
        lambda **_kwargs: {
            "canonical_runtime": {
                "build_sha": "520aed9e92269a5096773858828457764fbbfa51",
                "entrypoint": "knowledge_engine.m26_public_api:app",
            }
        },
    )
    app = create_app(
        root=ROOT,
        gate_path=ROOT / "pilot/m26/m26-pa-7-resolved-production-gate.json",
        quota_ledger=PublicQuotaLedger(tmp_path / "quota.sqlite3"),
    )
    client = TestClient(app)

    canonical = client.get("/v1/health").json()
    alias = client.get("/v1/answers/health").json()

    for payload in (canonical, alias):
        payload.pop("request_id")
    assert alias == canonical
    assert alias["answers_url"] == "/v1/answers"


def test_public_request_accepts_direct_browser_question_payload() -> None:
    parsed, problem = m26_public_api._parse_public_request(  # noqa: SLF001
        json.dumps({"question": "  What   does the archive say?  "}).encode()
    )

    assert problem is None
    assert parsed == {"question": "What does the archive say?"}


def test_public_request_accepts_worker_query_lang_payload_without_rewrite() -> None:
    parsed, problem = m26_public_api._parse_public_request(  # noqa: SLF001
        json.dumps({"query": "  What   does the archive say?  ", "lang": "en"}).encode()
    )

    assert problem is None
    assert parsed == {"question": "What does the archive say?"}


def test_public_request_rejects_provider_selection_and_conflicting_aliases() -> None:
    assert _problem_code(json.dumps({"query": "What?", "provider": "x"}).encode()) == (
        "PROVIDER_SELECTION_FORBIDDEN"
    )
    assert _problem_code(json.dumps({"query": "What?", "model": "x"}).encode()) == (
        "PROVIDER_SELECTION_FORBIDDEN"
    )
    assert _problem_code(
        json.dumps({"question": "What?", "query": "Something else?"}).encode()
    ) == "QUESTION_CONFLICT"
    assert _problem_code(json.dumps({"query": "What?", "language": "en"}).encode()) == (
        "UNSUPPORTED_FIELD"
    )


def test_canonical_public_api_does_not_import_translation_gateway() -> None:
    from knowledge_engine import m26_production_api

    public_source = inspect.getsource(m26_public_api)
    production_source = inspect.getsource(m26_production_api)
    assert "m26_translation_gateway_public_api" not in public_source
    assert "m26_translation_gateway import" not in public_source
    assert "m26_translation_gateway_public_api" not in production_source
    assert "from .api import app" in production_source


def test_r0_current_regressions_are_not_reintroduced() -> None:
    contract_source = inspect.getsource(m26_aq_semantic_contract)
    router_source = inspect.getsource(m26_cloudflare_provider_router)
    provider_evidence_signature = inspect.signature(
        m26_pa7_arbitrary_query_runtime._provider_evidence_item  # noqa: SLF001
    )

    assert "allow_deterministic_recovery=False" in contract_source
    assert not hasattr(m26_pa7_arbitrary_query_runtime, "_career_query_passage_text")
    assert "question" not in provider_evidence_signature.parameters
    assert "CLOUDFLARE_WORKER_AI_RESTFUL_API_KEY" in router_source
    assert "CLOUDFLARE_AI_TOKEN" in router_source
    assert "CLOUDFLARE_API_TOKEN" not in router_source
