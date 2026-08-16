from __future__ import annotations

import pytest

from knowledge_engine.m26_multilingual_provider_adapter import (
    LanguageProviderTelemetry,
    PurposeRecordingAdapter,
)


@pytest.mark.parametrize(
    "purpose",
    [
        "multilingual_canonicalization",
        "multilingual_requested_language_realization",
        "multilingual_equivalence_review",
    ],
)
def test_language_provider_purpose_is_recorded_without_prompt_body(
    purpose: str,
) -> None:
    telemetry = LanguageProviderTelemetry()
    adapter = PurposeRecordingAdapter(
        purpose=purpose,  # type: ignore[arg-type]
        callable_=lambda request: {"ok": True, "request": request},
        telemetry=telemetry,
        provider="internal-test-provider",
        model="internal-test-model",
    )

    assert adapter({"secret_prompt_body": "not persisted"})["ok"] is True

    payload = telemetry.as_dict()
    assert payload["provider_call_purposes"] == [purpose]
    assert payload["provider_calls"][0]["provider"] == "internal-test-provider"
    assert payload["provider_calls"][0]["model"] == "internal-test-model"
    assert "secret_prompt_body" not in str(payload)
