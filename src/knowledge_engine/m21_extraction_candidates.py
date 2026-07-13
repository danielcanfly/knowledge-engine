from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Any

from .errors import IntegrityError

MAX_DERIVATIVES = 100
MAX_TEXT_CHARS = 1_000_000
MAX_PROPOSALS = 1_000
MAX_SPANS = 16
MAX_ALIASES = 32
MAX_TAGS = 16
MAX_ALLOWED_TAGS = 200
MAX_LABEL_CHARS = 200
MAX_BODY_CHARS = 4_000
AUDIENCES = {"public", "internal", "restricted"}
KINDS = {
    "concept",
    "entity",
    "alias",
    "definition",
    "claim",
    "term",
    "duplicate_hint",
    "relation_hint",
}
COMMON = {"kind", "label", "language", "confidence", "evidence", "aliases", "tags"}
EXTRA = {
    "concept": {"definition"},
    "entity": {"entity_type", "definition"},
    "alias": {"target_label"},
    "definition": {"target_label", "body"},
    "claim": {"subject_label", "body"},
    "term": {"counterpart_label", "counterpart_language"},
    "duplicate_hint": {"target_label"},
    "relation_hint": {"source_label", "target_label", "predicate"},
}
FORBIDDEN = {
    "approved",
    "canonical",
    "canonical_knowledge",
    "production_authority",
    "relation_type",
    "source_write",
    "status",
    "system_prompt",
    "tool_call",
}
SECRETS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)bearer\s+[a-z0-9._-]{20,}"),
    re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*\S{8,}"),
)
LANG = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def _digest(value: Any) -> str:
    return hashlib.sha256(_bytes(value)).hexdigest()


def _text(value: Any, label: str, maximum: int = MAX_LABEL_CHARS) -> str:
    if not isinstance(value, str):
        raise IntegrityError(f"M21-EXTRACT-101 invalid {label}")
    normalized = " ".join(unicodedata.normalize("NFKC", value).split())
    if not normalized or len(normalized) > maximum:
        raise IntegrityError(f"M21-EXTRACT-101 invalid {label}")
    return normalized


def _language(value: Any, label: str = "language") -> str:
    if not isinstance(value, str) or len(value) > 35 or LANG.fullmatch(value) is None:
        raise IntegrityError(f"M21-EXTRACT-102 invalid {label}")
    return value


def _hex(value: Any, size: int, label: str) -> str:
    pattern = HEX40 if size == 40 else HEX64
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise IntegrityError(f"M21-EXTRACT-103 invalid {label}")
    return value


def _signed(value: dict[str, Any], field: str, code: str) -> str:
    unsigned = dict(value)
    claimed = unsigned.pop(field, None)
    if not isinstance(claimed, str) or _digest(unsigned) != claimed:
        raise IntegrityError(code)
    return claimed


def _plan_items(
    plan: dict[str, Any], checkpoint: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    if plan.get("schema") != "knowledge-engine-resumable-batch/v1":
        raise IntegrityError("M21-EXTRACT-104 invalid batch plan")
    plan_sha = _signed(plan, "plan_sha256", "M21-EXTRACT-105 plan digest mismatch")
    if (
        plan.get("authority") != "evidence_only"
        or plan.get("canonical_knowledge") is not False
        or plan.get("production_authority") is not False
    ):
        raise IntegrityError("M21-EXTRACT-106 plan authority drift")
    identity = plan.get("identity")
    if not isinstance(identity, dict):
        raise IntegrityError("M21-EXTRACT-107 missing identity")
    for key in ("engine_sha", "source_sha", "foundation_sha"):
        _hex(identity.get(key), 40, key)

    if checkpoint.get("schema") != "knowledge-engine-batch-checkpoint/v1":
        raise IntegrityError("M21-EXTRACT-108 invalid checkpoint")
    _signed(checkpoint, "checkpoint_sha256", "M21-EXTRACT-109 checkpoint digest mismatch")
    if checkpoint.get("plan_sha256") != plan_sha or checkpoint.get("identity") != identity:
        raise IntegrityError("M21-EXTRACT-110 checkpoint identity mismatch")

    items: dict[str, dict[str, Any]] = {}
    for batch in plan.get("batches", []):
        if not isinstance(batch, dict) or not isinstance(batch.get("items"), list):
            raise IntegrityError("M21-EXTRACT-111 malformed batch")
        batch_id = _hex(batch.get("batch_id"), 64, "batch id")
        for item in batch["items"]:
            item_key = _hex(item.get("item_key"), 64, "item key")
            if item_key in items:
                raise IntegrityError("M21-EXTRACT-112 duplicate planned item")
            items[item_key] = {**item, "batch_id": batch_id}

    states = checkpoint.get("states")
    if not isinstance(states, list) or len(states) != len(items):
        raise IntegrityError("M21-EXTRACT-113 checkpoint coverage mismatch")
    seen: set[str] = set()
    for state in states:
        if not isinstance(state, dict):
            raise IntegrityError("M21-EXTRACT-114 malformed checkpoint state")
        item_key = state.get("item_key")
        if item_key in seen or item_key not in items:
            raise IntegrityError("M21-EXTRACT-115 invalid checkpoint item")
        if state.get("batch_id") != items[item_key]["batch_id"]:
            raise IntegrityError("M21-EXTRACT-116 checkpoint batch mismatch")
        items[item_key]["status"] = state.get("status")
        seen.add(item_key)
    return items


def _derivatives(
    values: list[dict[str, Any]], items: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    if not isinstance(values, list) or not 1 <= len(values) <= MAX_DERIVATIVES:
        raise IntegrityError("M21-EXTRACT-117 derivative count exceeds bounds")
    output: dict[str, dict[str, Any]] = {}
    seen_items: set[str] = set()
    for value in values:
        if value.get("schema") != "knowledge-engine-normalized-derivative/v1":
            raise IntegrityError("M21-EXTRACT-118 invalid derivative schema")
        derivative_id = _text(value.get("derivative_id"), "derivative id", 128)
        item_key = value.get("item_key")
        if derivative_id in output or item_key not in items or item_key in seen_items:
            raise IntegrityError("M21-EXTRACT-119 invalid derivative item binding")
        item = items[item_key]
        if item.get("status") != "completed":
            raise IntegrityError("M21-EXTRACT-120 derivative item is not completed")
        if value.get("batch_id") != item["batch_id"]:
            raise IntegrityError("M21-EXTRACT-121 derivative batch mismatch")
        audience = value.get("audience")
        if audience != item.get("audience") or audience not in AUDIENCES:
            raise IntegrityError("M21-EXTRACT-122 derivative audience mismatch")
        if _hex(value.get("source_content_sha256"), 64, "source digest") != item.get(
            "content_sha256"
        ):
            raise IntegrityError("M21-EXTRACT-123 derivative source digest mismatch")
        text = value.get("text")
        if value.get("normalized") is not True or not isinstance(text, str):
            raise IntegrityError("M21-EXTRACT-124 derivative is not normalized")
        if not text or len(text) > MAX_TEXT_CHARS:
            raise IntegrityError("M21-EXTRACT-125 invalid derivative text")
        if hashlib.sha256(text.encode()).hexdigest() != _hex(
            value.get("text_sha256"), 64, "text digest"
        ):
            raise IntegrityError("M21-EXTRACT-126 derivative text digest mismatch")
        output[derivative_id] = {
            **value,
            "derivative_id": derivative_id,
            "language": _language(value.get("language")),
        }
        seen_items.add(item_key)
    return output


def _scan(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FORBIDDEN:
                raise IntegrityError("M21-EXTRACT-127 authority escalation field")
            _scan(child)
    elif isinstance(value, list):
        for child in value:
            _scan(child)
    elif isinstance(value, str) and any(pattern.search(value) for pattern in SECRETS):
        raise IntegrityError("M21-EXTRACT-128 secret-like candidate payload")


def _strings(values: Any, label: str, maximum: int, item_maximum: int) -> list[str]:
    if values is None:
        return []
    if not isinstance(values, list) or len(values) > maximum:
        raise IntegrityError(f"M21-EXTRACT-129 invalid {label}")
    normalized = [_text(value, label, item_maximum) for value in values]
    if len(normalized) != len(set(normalized)):
        raise IntegrityError(f"M21-EXTRACT-130 duplicate {label}")
    return sorted(normalized, key=lambda value: (value.casefold(), value))


def _spans(
    values: Any,
    derivatives: dict[str, dict[str, Any]],
    plan_sha: str,
    inventory_sha: str,
) -> list[dict[str, Any]]:
    if not isinstance(values, list) or not 1 <= len(values) <= MAX_SPANS:
        raise IntegrityError("M21-EXTRACT-131 evidence span count exceeds bounds")
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, int, int]] = set()
    for value in values:
        if not isinstance(value, dict) or set(value) != {
            "derivative_id",
            "start",
            "end",
            "excerpt_sha256",
        }:
            raise IntegrityError("M21-EXTRACT-132 malformed evidence span")
        derivative_id = value["derivative_id"]
        derivative = derivatives.get(derivative_id)
        start, end = value["start"], value["end"]
        if (
            derivative is None
            or not isinstance(start, int)
            or isinstance(start, bool)
            or not isinstance(end, int)
            or isinstance(end, bool)
            or not 0 <= start < end <= len(derivative["text"])
        ):
            raise IntegrityError("M21-EXTRACT-133 evidence span out of bounds")
        excerpt_sha = _hex(value["excerpt_sha256"], 64, "excerpt digest")
        if hashlib.sha256(derivative["text"][start:end].encode()).hexdigest() != excerpt_sha:
            raise IntegrityError("M21-EXTRACT-134 evidence span digest mismatch")
        key = (derivative_id, start, end)
        if key in seen:
            raise IntegrityError("M21-EXTRACT-135 duplicate evidence span")
        seen.add(key)
        output.append(
            {
                "snapshot_id": inventory_sha,
                "plan_sha256": plan_sha,
                "derivative_id": derivative_id,
                "start": start,
                "end": end,
                "excerpt_sha256": excerpt_sha,
            }
        )
    return sorted(output, key=lambda value: (value["derivative_id"], value["start"]))


def _proposal(
    value: dict[str, Any],
    derivatives: dict[str, dict[str, Any]],
    allowed_tags: set[str],
    plan_sha: str,
    inventory_sha: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise IntegrityError("M21-EXTRACT-136 proposal must be an object")
    _scan(value)
    kind = value.get("kind")
    if kind not in KINDS:
        raise IntegrityError("M21-EXTRACT-137 unknown candidate kind")
    if set(value) - (COMMON | EXTRA[kind]):
        raise IntegrityError("M21-EXTRACT-138 unsupported proposal field")
    label = _text(value.get("label"), "candidate label")
    confidence = value.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise IntegrityError("M21-EXTRACT-139 invalid confidence")
    if not 0 <= confidence <= 1:
        raise IntegrityError("M21-EXTRACT-139 invalid confidence")
    aliases = _strings(value.get("aliases"), "alias", MAX_ALIASES, MAX_LABEL_CHARS)
    tags = _strings(value.get("tags"), "tag", MAX_TAGS, 80)
    if any(tag not in allowed_tags for tag in tags):
        raise IntegrityError("M21-EXTRACT-140 unapproved controlled tag")
    candidate = {
        "kind": kind,
        "label": label,
        "normalized_label": label.casefold(),
        "language": _language(value.get("language")),
        "confidence": round(float(confidence), 6),
        "aliases": aliases,
        "controlled_tags": tags,
        "evidence_spans": _spans(
            value.get("evidence"), derivatives, plan_sha, inventory_sha
        ),
        "status": "pending_review",
        "authority": "candidate_only",
        "canonical_knowledge": False,
        "production_authority": False,
    }
    if kind in {"concept", "entity"} and value.get("definition") is not None:
        candidate["definition"] = _text(value["definition"], "definition", MAX_BODY_CHARS)
    if kind == "entity":
        candidate["entity_type"] = _text(value.get("entity_type"), "entity type", 80)
    if kind in {"alias", "definition", "duplicate_hint"}:
        target = _text(value.get("target_label"), "target label")
        if kind == "duplicate_hint" and target.casefold() == label.casefold():
            raise IntegrityError("M21-EXTRACT-141 duplicate hint targets itself")
        candidate["target_label"] = target
    if kind in {"definition", "claim"}:
        candidate["body"] = _text(value.get("body"), f"{kind} body", MAX_BODY_CHARS)
    if kind == "claim":
        candidate["subject_label"] = _text(value.get("subject_label"), "claim subject")
    if kind == "term":
        counterpart_language = _language(
            value.get("counterpart_language"), "counterpart language"
        )
        if counterpart_language.casefold() == candidate["language"].casefold():
            raise IntegrityError("M21-EXTRACT-142 bilingual term languages must differ")
        candidate["counterpart_label"] = _text(
            value.get("counterpart_label"), "counterpart label"
        )
        candidate["counterpart_language"] = counterpart_language
    if kind == "relation_hint":
        source = _text(value.get("source_label"), "relation source")
        target = _text(value.get("target_label"), "relation target")
        if source.casefold() == target.casefold():
            raise IntegrityError("M21-EXTRACT-143 relation hint self-loop")
        candidate.update(
            {
                "source_label": source,
                "target_label": target,
                "predicate": _text(value.get("predicate"), "relation predicate", 120),
                "ontology_type": None,
            }
        )
    prefix = {
        "concept": "conceptcand",
        "entity": "entitycand",
        "alias": "aliascand",
        "definition": "defcand",
        "claim": "claimcand",
        "term": "termcand",
        "duplicate_hint": "dupcand",
        "relation_hint": "relhint",
    }[kind]
    candidate["candidate_id"] = (
        f"{prefix}_{_digest({'plan': plan_sha, 'candidate': candidate})[:32]}"
    )
    return candidate


def build_candidate_packet(
    plan: dict[str, Any],
    checkpoint: dict[str, Any],
    derivatives: list[dict[str, Any]],
    proposals: list[dict[str, Any]],
    *,
    allowed_tags: list[str],
) -> dict[str, Any]:
    items = _plan_items(plan, checkpoint)
    derivative_map = _derivatives(derivatives, items)
    tags = _strings(allowed_tags, "allowed tag", MAX_ALLOWED_TAGS, 80)
    if not isinstance(proposals, list) or not 1 <= len(proposals) <= MAX_PROPOSALS:
        raise IntegrityError("M21-EXTRACT-144 proposal count exceeds bounds")
    candidates = [
        _proposal(
            proposal,
            derivative_map,
            set(tags),
            plan["plan_sha256"],
            plan["inventory_sha256"],
        )
        for proposal in proposals
    ]
    ids = [candidate["candidate_id"] for candidate in candidates]
    if len(ids) != len(set(ids)):
        raise IntegrityError("M21-EXTRACT-145 duplicate candidate id")
    candidates.sort(key=lambda candidate: candidate["candidate_id"])
    packet = {
        "schema": "knowledge-engine-extraction-candidates/v1",
        "authority": "candidate_only",
        "canonical_knowledge": False,
        "production_authority": False,
        "review_required": True,
        "source_text_untrusted": True,
        "plan_sha256": plan["plan_sha256"],
        "checkpoint_sha256": checkpoint["checkpoint_sha256"],
        "inventory_sha256": plan["inventory_sha256"],
        "identity": plan["identity"],
        "allowed_tags": tags,
        "derivative_count": len(derivative_map),
        "candidate_count": len(candidates),
        "candidates": candidates,
    }
    packet["packet_sha256"] = _digest(packet)
    return packet


__all__ = ["build_candidate_packet"]
