from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Literal

TRANSLATION_INVARIANTS_SCHEMA = "m26-translation-invariants/v1"
PLACEHOLDER_PREFIX = "__M26TG"
MAX_TRANSLATED_QUERY_CHARS = 4_000

DetectedLanguage = Literal["en", "zh-TW", "mixed"]


@dataclass(frozen=True)
class ProtectedSpan:
    placeholder: str
    value: str
    kind: str


@dataclass(frozen=True)
class ProtectionResult:
    original_text: str
    protected_text: str
    spans: tuple[ProtectedSpan, ...]


@dataclass(frozen=True)
class RoleBindingResult:
    original_text: str
    rewritten_text: str
    applied: bool
    bound_components: tuple[str, ...] = ()
    failure_code: str = ""
    failure_detail: str = ""

    @property
    def ok(self) -> bool:
        return not self.failure_code


@dataclass(frozen=True)
class InvariantCheckResult:
    ok: bool
    failure_code: str = ""
    failure_detail: str = ""
    checks: dict[str, bool] = field(default_factory=dict)


_URL_RE = re.compile(r"https?://[^\s<>()\]\}]+", re.I)
_HASH_RE = re.compile(r"\b[a-f0-9]{7,64}\b", re.I)
_VERSION_RE = re.compile(r"\bv\d+(?:\.\d+){1,5}(?:[-+][A-Za-z0-9_.-]+)?\b")
_MODEL_ID_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9_-]*/[A-Za-z0-9][A-Za-z0-9_.-]*\b")
_PATH_RE = re.compile(
    r"(?:(?:\./|\../|/)[A-Za-z0-9._~@%+=:,/-]+|"
    r"\b[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+\b)"
)
_FUNCTION_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\s*\(")
_TECH_ID_RE = re.compile(r"\b[A-Z][A-Z0-9]+-\d+(?:[-A-Z0-9_]+)?\b")
_SNAKE_IDENTIFIER_RE = re.compile(r"\b_?[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+\b")
_CODE_IDENTIFIER_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+\b")
_PERCENT_RE = re.compile(r"(?<![A-Za-z0-9_])[-+]?\d+(?:\.\d+)?\s*%")
_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9_.-])[-+]?\d+(?:\.\d+)?(?![A-Za-z0-9_.-])")
_COMPARISON_RE = re.compile(r"<=|>=|<|>|=")
_PLACEHOLDER_RE = re.compile(r"__M26TG\d+__")

_NEGATION_SOURCE = ("不", "非", "沒有", "無", "未", "不能", "不可")
_NEGATION_EN = re.compile(
    r"\b(?:not|no|never|without|cannot|can't|won't|mustn't|isn't|aren't|doesn't|don't|didn't)\b",
    re.I,
)
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_LATIN_WORD_RE = re.compile(r"[A-Za-z]{2,}")

APPROVED_TECHNICAL_COMPONENT_NOUNS = frozenset(
    {
        "answerability policy",
        "canonicalizer",
        "citation gate",
        "dense channel",
        "evidence selector",
        "gateway",
        "graph runtime",
        "invariant guard",
        "language envelope",
        "m26",
        "provider",
        "retrieval adapter",
        "retriever",
        "semantic contract",
        "semantic runtime",
        "synthesis",
        "translation gateway",
        "translation llm",
        "verifier",
    }
)

_ROLE_BINDING_PREDICATES = (
    "判斷",
    "評估",
    "驗證",
    "檢查",
    "決定",
    "選擇",
    "拒絕",
    "引用",
    "支援",
    "比較",
    "回答",
)


def detect_input_language(question: str) -> DetectedLanguage:
    has_cjk = bool(_CJK_RE.search(question))
    has_latin_word = bool(_LATIN_WORD_RE.search(question))
    if has_cjk and has_latin_word:
        return "mixed"
    if has_cjk:
        return "zh-TW"
    return "en"


def bind_mixed_language_component_roles(text: str) -> RoleBindingResult:
    if detect_input_language(text) != "mixed":
        return RoleBindingResult(original_text=text, rewritten_text=text, applied=False)
    rewritten = text
    bound: list[str] = []
    for component in sorted(APPROVED_TECHNICAL_COMPONENT_NOUNS, key=len, reverse=True):
        pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(component)}(?![A-Za-z0-9_])", re.I)
        match = pattern.search(rewritten)
        if match is None:
            continue
        if not _component_has_zh_tw_predicate_context(rewritten, match.start(), match.end()):
            continue
        original = match.group(0)
        clarifier = f"technical component named {original}"
        rewritten = rewritten[: match.start()] + clarifier + rewritten[match.end() :]
        bound.append(original)
    return RoleBindingResult(
        original_text=text,
        rewritten_text=rewritten,
        applied=bool(bound),
        bound_components=tuple(bound),
    )


def protect_spans(text: str) -> ProtectionResult:
    matches: list[tuple[int, int, str]] = []
    for kind, regex in (
        ("url", _URL_RE),
        ("path", _PATH_RE),
        ("version", _VERSION_RE),
        ("model_id", _MODEL_ID_RE),
        ("hash", _HASH_RE),
        ("function", _FUNCTION_RE),
        ("technical_identifier", _TECH_ID_RE),
        ("code_identifier", _SNAKE_IDENTIFIER_RE),
        ("code_identifier", _CODE_IDENTIFIER_RE),
        ("percentage", _PERCENT_RE),
        ("number", _NUMBER_RE),
        ("comparison_operator", _COMPARISON_RE),
    ):
        for match in regex.finditer(text):
            value = match.group(0)
            if kind == "function":
                value = value.rstrip("(").rstrip()
            end = match.start() + len(value)
            matches.append((match.start(), end, kind))

    selected: list[tuple[int, int, str]] = []
    for start, end, kind in sorted(matches, key=lambda item: (item[0], -(item[1] - item[0]))):
        if start == end:
            continue
        overlaps = any(
            not (end <= kept_start or start >= kept_end)
            for kept_start, kept_end, _ in selected
        )
        if overlaps:
            continue
        selected.append((start, end, kind))

    spans: list[ProtectedSpan] = []
    chunks: list[str] = []
    cursor = 0
    for index, (start, end, kind) in enumerate(sorted(selected)):
        placeholder = f"{PLACEHOLDER_PREFIX}{index}__"
        chunks.append(text[cursor:start])
        chunks.append(placeholder)
        spans.append(ProtectedSpan(placeholder=placeholder, value=text[start:end], kind=kind))
        cursor = end
    chunks.append(text[cursor:])
    return ProtectionResult(original_text=text, protected_text="".join(chunks), spans=tuple(spans))


def restore_protected_spans(translated_text: str, protection: ProtectionResult) -> str:
    restored = translated_text
    for span in protection.spans:
        restored = restored.replace(span.placeholder, span.value)
    return restored


def validate_translation_invariants(
    *,
    original_text: str,
    provider_text: str,
    restored_text: str,
    protection: ProtectionResult,
    provider_success: bool,
    max_output_chars: int = MAX_TRANSLATED_QUERY_CHARS,
) -> InvariantCheckResult:
    checks = {
        "provider_success": provider_success,
        "non_empty_english_output": bool(restored_text.strip()),
        "maximum_output_size": len(restored_text) <= max_output_chars,
        "placeholder_leak_absent": not bool(_PLACEHOLDER_RE.search(restored_text)),
        "protected_identifier_restoration": True,
        "url_preservation": True,
        "version_hash_preservation": True,
        "number_preservation": True,
        "comparison_boundary_preservation": True,
        "negation_token_not_obviously_lost": True,
    }
    if not provider_success:
        return _failed(
            "TRANSLATION_PROVIDER_FAILED",
            "translation provider did not succeed",
            checks,
        )
    if not restored_text.strip() or len(restored_text) > max_output_chars:
        code = "TRANSLATION_OUTPUT_INVALID"
        detail = "translated output is empty or exceeds the accepted bound"
        return _failed(code, detail, checks)

    provider_counts = Counter(_PLACEHOLDER_RE.findall(provider_text))
    for span in protection.spans:
        count = provider_counts.get(span.placeholder, 0)
        if count != 1:
            checks["protected_identifier_restoration"] = False
            return _failed(
                "TRANSLATION_INVARIANT_FAILED",
                f"protected span {span.kind} was not restored exactly once",
                checks,
            )
        if restored_text.count(span.value) != original_text.count(span.value):
            checks["protected_identifier_restoration"] = False
            return _failed(
                "TRANSLATION_INVARIANT_FAILED",
                f"protected span {span.kind} count changed after restoration",
                checks,
            )

    for kind, key in (
        ("url", "url_preservation"),
        ("version", "version_hash_preservation"),
        ("hash", "version_hash_preservation"),
        ("percentage", "number_preservation"),
        ("number", "number_preservation"),
        ("comparison_operator", "comparison_boundary_preservation"),
    ):
        original_values = [span.value for span in protection.spans if span.kind == kind]
        restored_values = [value for value in original_values if value in restored_text]
        if Counter(original_values) != Counter(restored_values):
            checks[key] = False
            return _failed(
                "TRANSLATION_INVARIANT_FAILED",
                f"{kind} invariant changed during translation",
                checks,
            )

    if _source_has_negation(original_text) and not _NEGATION_EN.search(restored_text):
        checks["negation_token_not_obviously_lost"] = False
        return _failed(
            "TRANSLATION_INVARIANT_FAILED",
            "source negation was present but no deterministic English negation token was found",
            checks,
        )

    if _PLACEHOLDER_RE.search(restored_text):
        checks["placeholder_leak_absent"] = False
        return _failed("TRANSLATION_INVARIANT_FAILED", "protected placeholder leaked", checks)
    return InvariantCheckResult(ok=True, checks=checks)


def _component_has_zh_tw_predicate_context(text: str, start: int, end: int) -> bool:
    left = text[max(0, start - 8) : start]
    right = text[end : min(len(text), end + 16)]
    if not (_CJK_RE.search(left) or _CJK_RE.search(right)):
        return False
    return any(predicate in right for predicate in _ROLE_BINDING_PREDICATES)


def _source_has_negation(text: str) -> bool:
    return any(token in text for token in _NEGATION_SOURCE)


def _failed(
    code: str,
    detail: str,
    checks: dict[str, bool],
) -> InvariantCheckResult:
    return InvariantCheckResult(
        ok=False,
        failure_code=code,
        failure_detail=detail,
        checks=dict(checks),
    )
