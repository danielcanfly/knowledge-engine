from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

FAILURE_CLUSTER_IDENTITY_VERSION = "qa-failure-cluster-semantic-intent/v1"
FAILURE_CLUSTER_LEXICAL_FALLBACK_VERSION = "qa-failure-cluster-lexical-fallback/v1"
FAILURE_INTENT_TASKS = frozenset(
    {
        "compare",
        "explain",
        "how_to",
        "enumerate",
        "diagnose",
        "design",
        "evaluate",
        "locate",
        "summarize",
        "other",
    }
)
_FAILURE_INTENT_TASK_ALIASES = {
    "comparison": "compare",
    "difference": "compare",
    "explanation": "explain",
    "howto": "how_to",
    "procedure": "how_to",
    "process": "how_to",
    "list": "enumerate",
    "listing": "enumerate",
    "diagnosis": "diagnose",
    "troubleshoot": "diagnose",
    "troubleshooting": "diagnose",
    "architecture": "design",
    "assessment": "evaluate",
    "find": "locate",
    "search": "locate",
    "summary": "summarize",
}
MAX_FAILURE_INTENT_SUBJECTS = 8
MAX_FAILURE_INTENT_QUALIFIERS = 8
MAX_FAILURE_INTENT_ATOM_CHARS = 120
MAX_FAILURE_INTENT_INPUT_ITEMS = 64

_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "do",
    "does",
    "for",
    "from",
    "how",
    "i",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "to",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "with",
    "you",
    "your",
}


@dataclass(frozen=True)
class FailureIntentFamily:
    """Bounded semantic identity of the visitor's question, independent of answer quality."""

    task: str
    subjects: tuple[str, ...]
    qualifiers: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "subjects": list(self.subjects),
            "qualifiers": list(self.qualifiers),
        }


@dataclass(frozen=True)
class FailureClusterIdentity:
    cluster_id: str
    intent_family: Mapping[str, Any]
    match_method: str
    identity_version: str


def _normalize_atom(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = re.sub(r"[^\w\u3400-\u9fff]+", " ", text, flags=re.UNICODE)
    return " ".join(text.split())[:MAX_FAILURE_INTENT_ATOM_CHARS]


def normalize_failure_intent(value: Any) -> FailureIntentFamily | None:
    """Normalize provider metadata without letting it influence the AQ score/verdict."""
    if not isinstance(value, Mapping):
        return None
    task = _normalize_atom(value.get("task") or value.get("intent_type")).replace(" ", "_")
    task = _FAILURE_INTENT_TASK_ALIASES.get(task, task)
    if task not in FAILURE_INTENT_TASKS:
        return None

    def atoms(raw: Any, limit: int) -> tuple[str, ...]:
        if not isinstance(raw, (list, tuple)):
            return ()
        normalized = {
            atom
            for item in list(raw)[:MAX_FAILURE_INTENT_INPUT_ITEMS]
            if (atom := _normalize_atom(item))
        }
        return tuple(sorted(normalized)[:limit])

    subjects = atoms(value.get("subjects"), MAX_FAILURE_INTENT_SUBJECTS)
    if not subjects:
        return None
    qualifiers = atoms(value.get("qualifiers", []), MAX_FAILURE_INTENT_QUALIFIERS)
    return FailureIntentFamily(task=task, subjects=subjects, qualifiers=qualifiers)


def _lexical_family(question: str) -> dict[str, Any]:
    text = unicodedata.normalize("NFKC", str(question)).casefold()
    tokens = re.findall(r"[\w\u3400-\u9fff]+", text, flags=re.UNICODE)
    content = sorted({token for token in tokens if token not in _STOPWORDS and len(token) > 1})
    if not content:
        content = tokens[:24]
    return {
        "task": "lexical_fallback",
        "subjects": content[:24],
        "qualifiers": [],
    }


def build_failure_cluster_identity(
    *,
    question: str,
    failure_stage: str,
    failure_signature: str,
    intent_family: FailureIntentFamily | None,
) -> FailureClusterIdentity:
    """Hash semantic question family + failure phenotype; never exact question text alone."""
    if intent_family is not None:
        family: Mapping[str, Any] = intent_family.to_payload()
        method = "semantic_evaluator"
        version = FAILURE_CLUSTER_IDENTITY_VERSION
    else:
        family = _lexical_family(question)
        method = "lexical_fallback"
        version = FAILURE_CLUSTER_LEXICAL_FALLBACK_VERSION
    payload = {
        "identity_version": version,
        "intent_family": family,
        "failure_stage": str(failure_stage),
        "failure_signature": str(failure_signature),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return FailureClusterIdentity(
        cluster_id=f"aqc_{hashlib.sha256(encoded).hexdigest()[:20]}",
        intent_family=family,
        match_method=method,
        identity_version=version,
    )


__all__ = [
    "FAILURE_CLUSTER_IDENTITY_VERSION",
    "FAILURE_CLUSTER_LEXICAL_FALLBACK_VERSION",
    "FAILURE_INTENT_TASKS",
    "FailureClusterIdentity",
    "FailureIntentFamily",
    "build_failure_cluster_identity",
    "normalize_failure_intent",
]
