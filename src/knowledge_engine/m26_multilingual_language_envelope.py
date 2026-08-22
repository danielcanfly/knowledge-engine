from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from .m26_multilingual_canonicalization import (
    CanonicalizationProvider,
    CanonicalizationResult,
    bounded_canonicalization_request,
    canonicalization_telemetry,
    explicit_failure,
    validate_canonicalization_result,
)

LANGUAGE_ENVELOPE_SCHEMA_VERSION = "m26-multilingual-language-envelope/v1"
AnswerLanguage = Literal["auto", "en", "zh-TW"]


@dataclass(frozen=True)
class LanguageEnvelope:
    original_question: str
    canonical_question_en: str
    requested_answer_language: str
    detected_input_language: str
    canonicalization_applied: bool
    canonicalization_status: str
    telemetry: dict[str, object] = field(default_factory=dict)
    failure_code: str = ""
    failure_detail: str = ""

    @property
    def ok(self) -> bool:
        return self.canonicalization_status == "ok" and bool(self.canonical_question_en)


def build_language_envelope(
    question: str,
    *,
    answer_language: AnswerLanguage = "auto",
    canonicalization_provider: CanonicalizationProvider | None = None,
) -> LanguageEnvelope:
    original_question = str(question)
    detected = detect_input_language(original_question)
    requested = requested_answer_language(
        detected_input_language=detected,
        answer_language=answer_language,
    )
    if detected == "en":
        return LanguageEnvelope(
            original_question=original_question,
            canonical_question_en=original_question,
            requested_answer_language=requested,
            detected_input_language=detected,
            canonicalization_applied=False,
            canonicalization_status="ok",
            telemetry={
                "schema_version": LANGUAGE_ENVELOPE_SCHEMA_VERSION,
                **canonicalization_telemetry(
                    detected_input_language=detected,
                    requested_answer_language=requested,
                    applied=False,
                    status="ok",
                    provider_invoked=False,
                ),
            },
        )

    request = bounded_canonicalization_request(
        original_question=original_question,
        detected_input_language=detected,
        requested_answer_language=requested,
    )
    if canonicalization_provider is None:
        failure = explicit_failure(
            "CANONICALIZATION_PROVIDER_REQUIRED",
            "non-English or mixed input requires an explicit canonicalization provider",
        )
        return _failed_envelope(
            original_question=original_question,
            detected=detected,
            requested=requested,
            failure=failure,
            provider_invoked=False,
        )

    result = validate_canonicalization_result(
        request=request,
        result=canonicalization_provider.canonicalize(request),
    )
    if not result.ok:
        return _failed_envelope(
            original_question=original_question,
            detected=detected,
            requested=requested,
            failure=result,
            provider_invoked=True,
        )
    return LanguageEnvelope(
        original_question=original_question,
        canonical_question_en=result.canonical_question_en,
        requested_answer_language=requested,
        detected_input_language=detected,
        canonicalization_applied=True,
        canonicalization_status="ok",
        telemetry={
            "schema_version": LANGUAGE_ENVELOPE_SCHEMA_VERSION,
            **canonicalization_telemetry(
                detected_input_language=detected,
                requested_answer_language=requested,
                applied=True,
                status="ok",
                provider_invoked=True,
                result=result,
            ),
        },
    )


def detect_input_language(question: str) -> str:
    has_cjk = any(_is_cjk(char) for char in question)
    has_latin_word = bool(re.search(r"[A-Za-z]{2,}", question))
    if has_cjk and has_latin_word:
        return "mixed"
    if has_cjk:
        return "zh-TW"
    return "en"


def requested_answer_language(
    *,
    detected_input_language: str,
    answer_language: AnswerLanguage = "auto",
) -> str:
    if answer_language in {"en", "zh-TW"}:
        return answer_language
    if answer_language != "auto":
        raise ValueError("answer_language must be auto, en, or zh-TW")
    if detected_input_language in {"zh-TW", "mixed"}:
        return "zh-TW"
    return "en"


def _failed_envelope(
    *,
    original_question: str,
    detected: str,
    requested: str,
    failure: CanonicalizationResult,
    provider_invoked: bool,
) -> LanguageEnvelope:
    return LanguageEnvelope(
        original_question=original_question,
        canonical_question_en="",
        requested_answer_language=requested,
        detected_input_language=detected,
        canonicalization_applied=True,
        canonicalization_status="failed",
        failure_code=failure.failure_code,
        failure_detail=failure.failure_detail,
        telemetry={
            "schema_version": LANGUAGE_ENVELOPE_SCHEMA_VERSION,
            **canonicalization_telemetry(
                detected_input_language=detected,
                requested_answer_language=requested,
                applied=True,
                status="failed",
                provider_invoked=provider_invoked,
                result=failure,
            ),
        },
    )


def _is_cjk(char: str) -> bool:
    codepoint = ord(char)
    return (
        0x3400 <= codepoint <= 0x4DBF
        or 0x4E00 <= codepoint <= 0x9FFF
        or 0xF900 <= codepoint <= 0xFAFF
    )
