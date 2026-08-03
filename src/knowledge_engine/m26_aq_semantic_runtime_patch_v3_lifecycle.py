from __future__ import annotations

from . import m26_aq_semantic_runtime_patch_v3 as v3_patch

_ORIGINAL_EXPLICIT_FULL_LIFECYCLE = v3_patch._explicit_full_lifecycle


def _explicit_full_lifecycle_with_span(question: str) -> bool:
    if _ORIGINAL_EXPLICIT_FULL_LIFECYCLE(question):
        return True

    q = " ".join(question.casefold().split())
    has_start_boundary = any(
        marker in q
        for marker in (
            "from admission",
            "from intake",
        )
    )
    has_progression = " to " in q or " through " in q
    has_terminal_boundary = any(
        marker in q
        for marker in (
            "completion",
            "final status",
            "final verification",
            "final acceptance",
            "status reattachment",
            "result verification",
        )
    )
    return has_start_boundary and has_progression and has_terminal_boundary


def install() -> None:
    """Recognize bounded end-to-end lifecycle paraphrases without widening narrow queries."""
    v3_patch._explicit_full_lifecycle = _explicit_full_lifecycle_with_span
