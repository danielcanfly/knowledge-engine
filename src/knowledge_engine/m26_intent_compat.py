from __future__ import annotations

import re
from collections.abc import Callable


_COMPARISON_TERMS = {
    "boundary",
    "boundaries",
    "different",
    "difference",
    "differences",
    "differ",
    "distinction",
    "distinguish",
    "distinguishes",
    "responsibilities",
    "responsibility",
    "role",
    "roles",
    "separate",
    "separates",
    "split",
}
_ROUTER_TERMS = {"router", "routers", "routing"}
_PLANNER_TERMS = {
    "adaptive",
    "planner",
    "planners",
    "planning",
    "replan",
    "replanner",
    "replanners",
    "replanning",
}
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def classify_with_semantic_compat(
    question: str,
    *,
    legacy_classifier: Callable[[str], str],
) -> str:
    """Preserve established semantic classes for natural comparison wording.

    The historical PA.7 formal bank includes comparison questions phrased without the
    literal words compare/contrast, for example role-boundary questions about routers
    and replanners. Treat those as cross-document comparisons instead of silently
    degrading them to direct lookup. The legacy classifier remains authoritative for
    every other wording.
    """

    classified = legacy_classifier(question)
    if classified != "direct_grounded_knowledge":
        return classified
    q = " ".join(str(question).strip().split())
    implicit_comparison_patterns = (
        r"\bwhat\s+distinction\s+separates\b.+\bfrom\b",
        r"\bwhat\s+distinguishes\b.+\bfrom\b",
        r"\bhow\s+does\b.+\bdiffer\s+from\b",
        r"\bhow\s+do\b.+\bdiffer\s+from\b",
        r"\bwhat\s+(?:is\s+)?(?:the\s+)?(?:difference|boundary|role\s+boundary)\b",
        r"\b(?:responsibilities|roles)\b.+\b(?:differ|separate|split)\b",
    )
    if any(re.search(pattern, q, flags=re.I) for pattern in implicit_comparison_patterns):
        return "cross_document_comparison"
    terms = {token.casefold() for token in _TOKEN_RE.findall(q)}
    if (
        terms & _COMPARISON_TERMS
        and terms & _ROUTER_TERMS
        and terms & _PLANNER_TERMS
    ):
        return "cross_document_comparison"
    return classified
