from __future__ import annotations

import time
from typing import Any

import pytest

from knowledge_engine import m26_pa7_arbitrary_query_runtime as runtime
from m26_answer_bundle_fixture import synthetic_full_production_answer_bundle


class SlowDenseChannel:
    def __init__(self, delay_seconds: float = 0.2) -> None:
        self.delay_seconds = delay_seconds

    def search(self, **_kwargs: Any) -> dict[str, Any]:
        time.sleep(self.delay_seconds)
        return {
            "backend_identity": {"backend": "slow"},
            "candidates": [{"section_id": "late"}],
        }


def test_real_helper_lexical_primary_retrieval_no_crash_and_dense_fail_soft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("M26_DENSE_SEARCH_DEADLINE_SECONDS", "0.01")
    bundle = synthetic_full_production_answer_bundle()

    started = time.monotonic()
    lexical, dense = runtime._run_lexical_primary_retrieval(
        question="What is a skill in an AI agent architecture?",
        bundle=bundle,
        dense_channel=SlowDenseChannel(),
        require_remote_dense=False,
        top_k=4,
        event_sink=None,
        relation_aware_expansion=False,
    )
    elapsed_ms = int((time.monotonic() - started) * 1000)

    assert elapsed_ms < 500
    assert lexical["retrieval"]["relation_aware_expansion_enabled"] is False
    assert lexical["retrieval"]["relation_aware_expansion_used"] is False
    assert dense["backend_identity"]["degraded"] is True
    assert dense["backend_identity"]["reason_code"] == "DENSE_SEARCH_DEADLINE_EXCEEDED"
