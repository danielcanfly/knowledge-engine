from __future__ import annotations

import re
from collections.abc import Callable


def classify_with_semantic_compat(
    question: str,
    *,
    legacy_classifier: Callable[[str], str],
) -> str:
    """Preserve established semantic classes for natural comparison wording.

    The historical PA.7 formal bank includes comparison questions phrased without the
    literal words compare/contrast, for example "What distinction separates X from Y?".
    Treat those as cross-document comparisons instead of silently degrading them to a
    direct lookup. The legacy classifier remains authoritative for every other wording.
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
    )
    if any(re.search(pattern, q, flags=re.I) for pattern in implicit_comparison_patterns):
        return "cross_document_comparison"
    return classified
