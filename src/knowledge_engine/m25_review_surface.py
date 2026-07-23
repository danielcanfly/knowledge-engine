from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import tempfile
from collections import Counter
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field

from .errors import AuthorizationError, IntegrityError
from .m25_identity_governance import build_governance_packet, sign

BATCH_SCHEMA = "knowledge-engine-m25-6-review-batch/v1"
DECISION_REQUEST_SCHEMA = "knowledge-engine-m25-6-decision-request/v1"
DECISION_RECORD_SCHEMA = "knowledge-engine-m25-6-decision-record/v1"
AUDIT_EXPORT_SCHEMA = "knowledge-engine-m25-6-audit-export/v1"
READINESS_STATUS = "m25_6_awaiting_daniel_browser_acceptance"
ACTIONS = {"approve", "map", "edit", "split", "reject", "defer"}
TERMINAL_ACTIONS = ACTIONS - {"defer"}
REVIEWER_RE = re.compile(r"^[A-Za-z0-9._@-]{3,128}$")
MAX_RATIONALE = 4_000
MAX_EDIT = 20_000


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _verify_signed(value: Mapping[str, Any], field: str, code: str) -> str:
    unsigned = dict(value)
    claimed = unsigned.pop(field, None)
    actual = digest(unsigned)
    if not isinstance(claimed, str) or not hmac.compare_digest(claimed, actual):
        raise IntegrityError(code)
    return claimed


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IntegrityError(f"M25-REVIEW-101 cannot load {path}") from exc
    if not isinstance(value, dict):
        raise IntegrityError(f"M25-REVIEW-102 {path.name} must be an object")
    return value


def _synthetic_resolution(item: Mapping[str, Any], result: Mapping[str, Any]) -> dict[str, Any]:
    candidate_ids = sorted(
        candidate["candidate_id"]
        for candidate in item["case"]["candidates"]
        if candidate["kind"] in {"concept", "entity", "alias", "term"}
    )
    resolutions = [
        {
            "resolution_id": f"m25_6_{item['item_id']}_{index}",
            "candidate_ids": candidate_ids,
            "outcome": outcome,
            "strong_signals": list(result["actual_explanation_signals"]),
            "weak_signals": [],
            "authority": "candidate_only",
            "canonical_knowledge": False,
            "production_authority": False,
        }
        for index, outcome in enumerate(result["actual_resolution_outcomes"])
    ]
    packet = {
        "schema": "knowledge-engine-resolution-candidates/v1",
        "authority": "candidate_only",
        "canonical_knowledge": False,
        "production_authority": False,
        "review_required": True,
        "resolution_count": len(resolutions),
        "contradiction_count": result.get("actual_contradiction_count", 0),
        "packaging_blocked": result.get("actual_packaging_blocked", False),
        "resolutions": resolutions,
        "contradictions": [
            {"contradiction_id": f"m25_6_{item['item_id']}_{index}"}
            for index in range(result.get("actual_contradiction_count", 0))
        ],
    }
    return sign(packet, "packet_sha256")


def _allowed_actions(outcomes: list[str]) -> list[str]:
    values = set(outcomes)
    if values & {"ambiguous", "reject"}:
        return ["edit", "split", "reject", "defer"]
    if "probable_duplicate" in values:
        return ["map", "edit", "split", "reject", "defer"]
    if "distinct_new_candidate" in values:
        return ["approve", "edit", "split", "reject", "defer"]
    return ["approve", "map", "edit", "reject", "defer"]


def _candidate_summary(case: Mapping[str, Any]) -> list[dict[str, Any]]:
    output = []
    for candidate in case["candidates"]:
        output.append(
            {
                "candidate_id": candidate["candidate_id"],
                "kind": candidate["kind"],
                "label": candidate.get("label")
                or candidate.get("target_label")
                or candidate.get("subject_label")
                or candidate["candidate_id"],
                "language": candidate.get("language"),
                "confidence": candidate.get("confidence"),
                "aliases": candidate.get("aliases", []),
                "controlled_tags": candidate.get("controlled_tags", []),
                "evidence_spans": candidate.get("evidence_spans", []),
                "authority": "candidate_only",
            }
        )
    return sorted(output, key=lambda item: item["candidate_id"])


def _graph_neighborhood(
    item: Mapping[str, Any], governance: Mapping[str, Any]
) -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    for candidate in item["case"]["candidates"]:
        candidate_id = candidate["candidate_id"]
        nodes[candidate_id] = {
            "id": candidate_id,
            "kind": "candidate",
            "label": candidate.get("label")
            or candidate.get("target_label")
            or candidate_id,
            "authority": "candidate_only",
        }
    for concept in item["case"]["source_concepts"]:
        concept_id = concept["x_kos_id"]
        nodes[concept_id] = {
            "id": concept_id,
            "kind": "source_concept",
            "label": concept["title"],
            "path": concept["concept_path"],
            "audience": concept["audience"],
        }
    for resolution in governance["governed_resolutions"]:
        for ranking in resolution["ranked_targets"]:
            for target in ranking.get("targets", [])[:5]:
                target_id = target["x_kos_id"]
                if target_id not in nodes:
                    nodes[target_id] = {
                        "id": target_id,
                        "kind": "source_concept",
                        "label": target.get("title", target_id),
                    }
                edges.append(
                    {
                        "source": ranking["candidate_id"],
                        "target": target_id,
                        "type": "identity_candidate",
                        "score": target["score"],
                        "automatic_write_permitted": False,
                    }
                )
    for relation in governance["relation_candidates"]:
        edges.append(
            {
                "source": relation["source_candidate_id"],
                "target": relation["target_x_kos_id"],
                "type": relation["relation_type"],
                "automatic_write_permitted": False,
            }
        )
    return {
        "nodes": [nodes[key] for key in sorted(nodes)],
        "edges": sorted(
            edges,
            key=lambda edge: (edge["type"], edge["source"], edge["target"]),
        ),
        "read_only": True,
        "production_graph_mutation_permitted": False,
    }


def _structured_diff(
    item: Mapping[str, Any], governance: Mapping[str, Any]
) -> dict[str, Any]:
    before = [
        {
            "x_kos_id": concept["x_kos_id"],
            "concept_path": concept["concept_path"],
            "title": concept["title"],
            "aliases": concept.get("aliases", []),
            "bilingual_terms": concept.get("bilingual_terms", []),
            "tags": concept.get("tags", []),
            "audience": concept["audience"],
            "source_sha256": concept["source_sha256"],
        }
        for concept in item["case"]["source_concepts"]
    ]
    after = {
        "candidate_labels": [candidate["label"] for candidate in _candidate_summary(item["case"])],
        "proposed_relations": [
            {
                "source_candidate_id": relation["source_candidate_id"],
                "relation_type": relation["relation_type"],
                "target_x_kos_id": relation["target_x_kos_id"],
            }
            for relation in governance["relation_candidates"]
        ],
        "proposed_tags": governance["governed_tag_candidates"],
        "review_required": True,
        "automatic_write_permitted": False,
    }
    lines = ["--- current Source context", "+++ candidate admission proposal"]
    for concept in before:
        lines.append(f"- {concept['concept_path']}: {concept['title']}")
    for label in after["candidate_labels"]:
        lines.append(f"+ candidate: {label}")
    for relation in after["proposed_relations"]:
        lines.append(
            "+ relation: "
            f"{relation['source_candidate_id']} {relation['relation_type']} "
            f"{relation['target_x_kos_id']}"
        )
    return {"before": before, "after": after, "unified_lines": lines}


def build_review_batch(
    suite: Mapping[str, Any],
    baseline: Mapping[str, Any],
    policy: Mapping[str, Any],
    report: Mapping[str, Any],
    acceptance: Mapping[str, Any],
) -> dict[str, Any]:
    if acceptance.get("status") != "m25_5_identity_governance_accepted":
        raise IntegrityError("M25-REVIEW-103 predecessor not accepted")
    if acceptance.get("implementation", {}).get("merge_sha") != (
        "8ae3e77b8f9ffbd3df5ec820cca04b0b47413e02"
    ):
        raise IntegrityError("M25-REVIEW-104 predecessor identity drift")
    if report.get("status") != "m25_5_identity_governance_candidate":
        raise IntegrityError("M25-REVIEW-105 governance report status drift")
    if report.get("policy_sha256") != policy.get("policy_sha256"):
        raise IntegrityError("M25-REVIEW-106 policy/report mismatch")
    _verify_signed(policy, "policy_sha256", "M25-REVIEW-107 policy digest mismatch")
    _verify_signed(report, "report_sha256", "M25-REVIEW-108 report digest mismatch")
    if suite.get("approval_status") != "approved_by_daniel":
        raise IntegrityError("M25-REVIEW-109 gold suite lacks Daniel approval")
    if suite.get("item_count") != 30 or report.get("denominators", {}).get("total") != 30:
        raise IntegrityError("M25-REVIEW-110 review denominator mismatch")
    baseline_by_id = {row["item_id"]: row for row in baseline["results"]}
    report_by_id = {row["item_id"]: row for row in report["results"]}
    items: list[dict[str, Any]] = []
    for item in suite["items"]:
        item_id = item["item_id"]
        if item_id not in baseline_by_id or item_id not in report_by_id:
            raise IntegrityError("M25-REVIEW-111 incomplete predecessor coverage")
        result = report_by_id[item_id]
        inherited = _synthetic_resolution(item, result)
        governance = build_governance_packet(item["case"], inherited, policy)
        outcomes = list(result["actual_resolution_outcomes"])
        review_item = {
            "schema_version": "knowledge-engine-m25-6-review-item/v1",
            "item_id": item_id,
            "class_label": item["class_label"],
            "split": item["split"],
            "semantic_family_id": item["semantic_family_id"],
            "rationale": item["rationale"],
            "candidate_summary": _candidate_summary(item["case"]),
            "source_reader": {
                "source_concepts": item["case"]["source_concepts"],
                "evidence_spans": [
                    span
                    for candidate in item["case"]["candidates"]
                    for span in candidate.get("evidence_spans", [])
                ],
                "excerpt_text_available": False,
                "fabricated_excerpt_permitted": False,
            },
            "candidate_comparison": {
                "actual_resolution_outcomes": outcomes,
                "required_explanation_signals": result["required_explanation_signals"],
                "actual_explanation_signals": result["actual_explanation_signals"],
                "governed_resolutions": governance["governed_resolutions"],
                "critical_false_merge_risk_count": governance[
                    "critical_false_merge_risk_count"
                ],
            },
            "graph_neighborhood": _graph_neighborhood(item, governance),
            "proposals": {
                "aliases": [
                    candidate
                    for candidate in _candidate_summary(item["case"])
                    if candidate["kind"] == "alias"
                ],
                "relations": governance["relation_candidates"],
                "tags": governance["governed_tag_candidates"],
                "automatic_write_permitted": False,
            },
            "explicit_diff": _structured_diff(item, governance),
            "allowed_actions": _allowed_actions(outcomes),
            "required_acknowledgements": [
                "evidence_reviewed",
                "comparison_reviewed",
                "diff_reviewed",
            ],
            "queue_state": "pending_review",
            "authority": "admission_review_only",
            "canonical_knowledge": False,
            "production_authority": False,
            "source_write_permitted": False,
            "github_pr_creation_permitted": False,
        }
        review_item["review_state_sha256"] = digest(review_item)
        review_item["review_item_id"] = f"m25review_{review_item['review_state_sha256'][:32]}"
        items.append(review_item)
    items.sort(key=lambda value: (value["split"], value["class_label"], value["item_id"]))
    class_counts = Counter(item["class_label"] for item in items)
    split_counts = Counter(item["split"] for item in items)
    batch = {
        "schema_version": BATCH_SCHEMA,
        "status": READINESS_STATUS,
        "predecessor_status": acceptance["status"],
        "predecessor_main_seal_sha": "d68be491f8d07a727bcf1f521a2e5e75256eede3",
        "suite_sha256": suite["suite_sha256"],
        "baseline_report_sha256": baseline["report_sha256"],
        "policy_sha256": policy["policy_sha256"],
        "calibrated_report_sha256": report["report_sha256"],
        "item_count": len(items),
        "class_counts": dict(sorted(class_counts.items())),
        "split_counts": dict(sorted(split_counts.items())),
        "all_items_individually_reviewable": True,
        "bulk_approval_permitted": False,
        "incomplete_review_blocks_admission": True,
        "decision_actions": sorted(ACTIONS),
        "items": items,
        "authority": "admission_review_only",
        "canonical_knowledge": False,
        "production_authority": False,
        "source_write_permitted": False,
        "github_pr_creation_permitted": False,
        "m25_7_authorized": False,
    }
    batch["batch_sha256"] = digest(batch)
    return batch


def validate_review_batch(batch: Mapping[str, Any]) -> dict[str, Any]:
    if batch.get("schema_version") != BATCH_SCHEMA:
        raise IntegrityError("M25-REVIEW-120 invalid batch schema")
    _verify_signed(batch, "batch_sha256", "M25-REVIEW-121 batch digest mismatch")
    items = batch.get("items")
    if not isinstance(items, list) or batch.get("item_count") != len(items) or not items:
        raise IntegrityError("M25-REVIEW-122 batch coverage mismatch")
    if (
        batch.get("bulk_approval_permitted") is not False
        or batch.get("incomplete_review_blocks_admission") is not True
        or batch.get("source_write_permitted") is not False
        or batch.get("github_pr_creation_permitted") is not False
        or batch.get("m25_7_authorized") is not False
    ):
        raise IntegrityError("M25-REVIEW-123 batch authority drift")
    seen: set[str] = set()
    for item in items:
        claimed = item.get("review_state_sha256")
        unsigned = dict(item)
        unsigned.pop("review_item_id", None)
        unsigned.pop("review_state_sha256", None)
        if not isinstance(claimed, str) or claimed != digest(unsigned):
            raise IntegrityError("M25-REVIEW-124 review item digest mismatch")
        expected_id = f"m25review_{claimed[:32]}"
        if item.get("review_item_id") != expected_id or expected_id in seen:
            raise IntegrityError("M25-REVIEW-125 review item identity drift")
        seen.add(expected_id)
    return json.loads(json.dumps(batch))


class DecisionRequest(BaseModel):
    schema_version: str = Field(default=DECISION_REQUEST_SCHEMA)
    batch_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    review_item_id: str = Field(min_length=1, max_length=128)
    expected_review_state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_ledger_head_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    reviewer: str = Field(min_length=3, max_length=128)
    action: str
    rationale: str = Field(min_length=1, max_length=MAX_RATIONALE)
    evidence_reviewed: bool
    comparison_reviewed: bool
    diff_reviewed: bool
    mapping_target: str | None = Field(default=None, max_length=240)
    edited_payload: dict[str, Any] | None = None
    split_payload: list[dict[str, Any]] | None = None
    decided_at: str | None = None


class DecisionLedger:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.decisions_dir = root / "decisions"
        self.decisions_dir.mkdir(parents=True, exist_ok=True)
        self.head_path = root / "HEAD.json"

    def _load_head(self) -> dict[str, Any] | None:
        if not self.head_path.exists():
            return None
        value = load_json(self.head_path)
        if set(value) != {"sequence", "decision_sha256"}:
            raise IntegrityError("M25-REVIEW-130 malformed ledger head")
        return value

    def _decision_files(self) -> list[Path]:
        return sorted(self.decisions_dir.glob("*.json"))

    def _records(self) -> list[dict[str, Any]]:
        records = [load_json(path) for path in self._decision_files()]
        previous: str | None = None
        for index, record in enumerate(records, start=1):
            _verify_signed(
                record,
                "decision_sha256",
                "M25-REVIEW-131 decision digest mismatch",
            )
            if record.get("sequence") != index or record.get("previous_decision_sha256") != previous:
                raise IntegrityError("M25-REVIEW-132 ledger chain mismatch")
            previous = record["decision_sha256"]
        head = self._load_head()
        if records:
            expected = {"sequence": len(records), "decision_sha256": previous}
            if head != expected:
                raise IntegrityError("M25-REVIEW-133 ledger head mismatch")
        elif head is not None:
            raise IntegrityError("M25-REVIEW-134 orphan ledger head")
        return records

    def append(
        self,
        batch: Mapping[str, Any],
        request: DecisionRequest,
    ) -> dict[str, Any]:
        batch = validate_review_batch(batch)
        if request.schema_version != DECISION_REQUEST_SCHEMA:
            raise IntegrityError("M25-REVIEW-135 invalid decision request schema")
        if request.batch_sha256 != batch["batch_sha256"]:
            raise IntegrityError("M25-REVIEW-136 stale batch")
        if REVIEWER_RE.fullmatch(request.reviewer) is None:
            raise IntegrityError("M25-REVIEW-137 invalid reviewer identity")
        item = next(
            (value for value in batch["items"] if value["review_item_id"] == request.review_item_id),
            None,
        )
        if item is None or item["review_state_sha256"] != request.expected_review_state_sha256:
            raise IntegrityError("M25-REVIEW-138 stale review context")
        if request.action not in ACTIONS or request.action not in item["allowed_actions"]:
            raise IntegrityError("M25-REVIEW-139 action not permitted for item")
        if request.action in {"approve", "map", "edit", "split"} and not (
            request.evidence_reviewed and request.comparison_reviewed and request.diff_reviewed
        ):
            raise IntegrityError("M25-REVIEW-140 incomplete review acknowledgement")
        if request.action == "map" and not request.mapping_target:
            raise IntegrityError("M25-REVIEW-141 map target required")
        if request.action == "edit" and request.edited_payload is None:
            raise IntegrityError("M25-REVIEW-142 edited payload required")
        if request.action == "split" and (
            not request.split_payload or len(request.split_payload) < 2
        ):
            raise IntegrityError("M25-REVIEW-143 split plan requires at least two parts")
        serialized_edit = json.dumps(
            request.edited_payload or request.split_payload or {}, ensure_ascii=False
        )
        if len(serialized_edit) > MAX_EDIT:
            raise IntegrityError("M25-REVIEW-144 decision payload too large")
        records = self._records()
        head = self._load_head()
        current_head = head["decision_sha256"] if head else None
        if request.expected_ledger_head_sha256 != current_head:
            raise IntegrityError("M25-REVIEW-145 stale ledger head")
        prior_for_item = [
            record for record in records if record["review_item_id"] == request.review_item_id
        ]
        if prior_for_item and prior_for_item[-1]["action"] != "defer":
            raise IntegrityError("M25-REVIEW-146 item already has terminal decision")
        decided_at = request.decided_at or datetime.now(UTC).isoformat()
        try:
            parsed = datetime.fromisoformat(decided_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise IntegrityError("M25-REVIEW-147 invalid decision timestamp") from exc
        if parsed.tzinfo is None:
            raise IntegrityError("M25-REVIEW-148 decision timestamp must include timezone")
        evidence_ids = sorted(
            {
                f"{span['snapshot_id']}:{span['derivative_id']}:{span['start']}:{span['end']}:"
                f"{span['excerpt_sha256']}"
                for span in item["source_reader"]["evidence_spans"]
            }
        )
        candidate_ids = sorted(
            candidate["candidate_id"] for candidate in item["candidate_summary"]
        )
        record = {
            "schema_version": DECISION_RECORD_SCHEMA,
            "sequence": len(records) + 1,
            "previous_decision_sha256": current_head,
            "batch_sha256": batch["batch_sha256"],
            "review_item_id": request.review_item_id,
            "review_state_sha256": item["review_state_sha256"],
            "item_id": item["item_id"],
            "candidate_ids": candidate_ids,
            "evidence_identities": evidence_ids,
            "policy_sha256": batch["policy_sha256"],
            "calibrated_report_sha256": batch["calibrated_report_sha256"],
            "reviewer": request.reviewer,
            "reviewer_role": "internal_reviewer",
            "action": request.action,
            "rationale": request.rationale.strip(),
            "acknowledgements": {
                "evidence_reviewed": request.evidence_reviewed,
                "comparison_reviewed": request.comparison_reviewed,
                "diff_reviewed": request.diff_reviewed,
            },
            "mapping_target": request.mapping_target,
            "edited_payload": request.edited_payload,
            "split_payload": request.split_payload,
            "decided_at": parsed.astimezone(UTC).isoformat(),
            "authority": "admission_decision_only",
            "canonical_knowledge": False,
            "production_authority": False,
            "source_write_permitted": False,
            "github_pr_creation_permitted": False,
            "m25_7_authorized": False,
        }
        record["decision_sha256"] = digest(record)
        filename = f"{record['sequence']:06d}-{record['decision_sha256']}.json"
        target = self.decisions_dir / filename
        try:
            with target.open("x", encoding="utf-8") as handle:
                handle.write(json.dumps(record, indent=2, sort_keys=True) + "\n")
        except FileExistsError as exc:
            raise IntegrityError("M25-REVIEW-149 immutable decision collision") from exc
        head_value = {
            "sequence": record["sequence"],
            "decision_sha256": record["decision_sha256"],
        }
        fd, temporary = tempfile.mkstemp(prefix="HEAD.", suffix=".json", dir=self.root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(head_value, indent=2, sort_keys=True) + "\n")
            os.replace(temporary, self.head_path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return record

    def export(self, batch: Mapping[str, Any]) -> dict[str, Any]:
        batch = validate_review_batch(batch)
        records = self._records()
        latest: dict[str, dict[str, Any]] = {}
        for record in records:
            latest[record["review_item_id"]] = record
        terminal = sum(record["action"] in TERMINAL_ACTIONS for record in latest.values())
        deferred = sum(record["action"] == "defer" for record in latest.values())
        pending = batch["item_count"] - len(latest)
        complete = terminal == batch["item_count"] and deferred == 0 and pending == 0
        export = {
            "schema_version": AUDIT_EXPORT_SCHEMA,
            "batch_sha256": batch["batch_sha256"],
            "decision_count": len(records),
            "latest_item_decision_count": len(latest),
            "terminal_item_count": terminal,
            "deferred_item_count": deferred,
            "pending_item_count": pending,
            "review_complete": complete,
            "admission_ready": complete,
            "source_write_permitted": False,
            "github_pr_creation_permitted": False,
            "m25_7_authorized": False,
            "records": records,
            "authority": "audit_only",
            "canonical_knowledge": False,
            "production_authority": False,
        }
        export["audit_sha256"] = digest(export)
        return export


class ReviewSurfaceService:
    def __init__(self, batch: Mapping[str, Any], ledger: DecisionLedger) -> None:
        self.batch = validate_review_batch(batch)
        self.ledger = ledger
        self.items = {item["review_item_id"]: item for item in self.batch["items"]}

    def queue(self) -> dict[str, Any]:
        audit = self.ledger.export(self.batch)
        latest = {record["review_item_id"]: record for record in audit["records"]}
        items = []
        for item in self.batch["items"]:
            decision = latest.get(item["review_item_id"])
            items.append(
                {
                    "review_item_id": item["review_item_id"],
                    "item_id": item["item_id"],
                    "class_label": item["class_label"],
                    "split": item["split"],
                    "labels": [c["label"] for c in item["candidate_summary"]],
                    "allowed_actions": item["allowed_actions"],
                    "decision": decision["action"] if decision else None,
                    "decision_sha256": decision["decision_sha256"] if decision else None,
                }
            )
        return {
            "batch_sha256": self.batch["batch_sha256"],
            "item_count": self.batch["item_count"],
            "review_complete": audit["review_complete"],
            "bulk_approval_permitted": False,
            "items": items,
        }

    def item(self, review_item_id: str) -> dict[str, Any]:
        item = self.items.get(review_item_id)
        if item is None:
            raise KeyError(review_item_id)
        return item


class ReviewAuthenticator:
    def __init__(self, username: str, password: str) -> None:
        if len(username) < 3 or len(password) < 12:
            raise AuthorizationError("review credentials are missing or too weak")
        self.username = username
        self.password = password
        self.security = HTTPBasic(auto_error=False)

    def dependency(
        self,
        credentials: HTTPBasicCredentials | None = Depends(HTTPBasic(auto_error=False)),
    ) -> str:
        if credentials is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "M25-REVIEW-AUTH-401", "message": "review authentication required"},
                headers={"WWW-Authenticate": 'Basic realm="M25 Review"'},
            )
        valid = hmac.compare_digest(credentials.username, self.username) and hmac.compare_digest(
            credentials.password, self.password
        )
        if not valid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "M25-REVIEW-AUTH-401", "message": "invalid review credentials"},
                headers={"WWW-Authenticate": 'Basic realm="M25 Review"'},
            )
        return credentials.username


def _security_headers() -> dict[str, str]:
    return {
        "Cache-Control": "no-store",
        "Content-Security-Policy": (
            "default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; "
            "connect-src 'self'; img-src 'self' data:; font-src 'none'; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
        ),
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
    }


class DecisionResponse(BaseModel):
    decision_sha256: str
    sequence: int
    action: str
    admission_ready: bool


def create_review_app(
    batch: Mapping[str, Any],
    ledger_root: Path,
    *,
    username: str,
    password: str,
) -> FastAPI:
    service = ReviewSurfaceService(batch, DecisionLedger(ledger_root))
    authenticator = ReviewAuthenticator(username, password)
    app = FastAPI(title="M25.6 Human Review Surface", version="0.1.0")

    @app.middleware("http")
    async def secure_headers(request: Request, call_next: Any) -> Response:
        response = await call_next(request)
        for key, value in _security_headers().items():
            response.headers[key] = value
        return response

    reviewer = authenticator.dependency

    @app.get("/review", response_class=HTMLResponse, include_in_schema=False)
    def review_page(subject: str = Depends(reviewer)) -> HTMLResponse:
        del subject
        return HTMLResponse(REVIEW_HTML, headers=_security_headers())

    @app.get("/review/app.js", include_in_schema=False)
    def review_script(subject: str = Depends(reviewer)) -> Response:
        del subject
        return Response(REVIEW_JAVASCRIPT, media_type="application/javascript")

    @app.get("/v1/review/capabilities")
    def capabilities(subject: str = Depends(reviewer)) -> dict[str, Any]:
        return {
            "reviewer": subject,
            "actions": sorted(ACTIONS),
            "batch_sha256": service.batch["batch_sha256"],
            "item_count": service.batch["item_count"],
            "bulk_approval_permitted": False,
            "source_write_permitted": False,
            "github_pr_creation_permitted": False,
            "m25_7_authorized": False,
        }

    @app.get("/v1/review/queue")
    def queue(subject: str = Depends(reviewer)) -> dict[str, Any]:
        del subject
        return service.queue()

    @app.get("/v1/review/items/{review_item_id}")
    def item(review_item_id: str, subject: str = Depends(reviewer)) -> dict[str, Any]:
        del subject
        try:
            return service.item(review_item_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"code": "M25-REVIEW-404"}) from exc

    @app.post("/v1/review/decisions", response_model=DecisionResponse)
    def decide(
        request: DecisionRequest,
        subject: str = Depends(reviewer),
    ) -> DecisionResponse:
        if request.reviewer != subject:
            raise HTTPException(
                status_code=403,
                detail={"code": "M25-REVIEW-403", "message": "reviewer identity mismatch"},
            )
        try:
            record = service.ledger.append(service.batch, request)
            audit = service.ledger.export(service.batch)
        except IntegrityError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "M25-REVIEW-409", "message": str(exc)},
            ) from exc
        return DecisionResponse(
            decision_sha256=record["decision_sha256"],
            sequence=record["sequence"],
            action=record["action"],
            admission_ready=audit["admission_ready"],
        )

    @app.get("/v1/review/audit")
    def audit(subject: str = Depends(reviewer)) -> JSONResponse:
        del subject
        return JSONResponse(service.ledger.export(service.batch))

    return app


REVIEW_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>M25.6 Review Console</title>
<style>
:root{font-family:Inter,ui-sans-serif,system-ui,sans-serif;color:#18202a;background:#eef2f7}
*{box-sizing:border-box}body{margin:0}.top{padding:16px 22px;background:#111827;color:white;display:flex;justify-content:space-between}.badge{padding:4px 9px;border-radius:999px;background:#334155;font-size:12px}.layout{display:grid;grid-template-columns:310px minmax(0,1fr) 340px;height:calc(100vh - 58px)}aside,main{overflow:auto}.queue{background:white;border-right:1px solid #d8dee8;padding:14px}.detail{padding:18px}.decision{background:white;border-left:1px solid #d8dee8;padding:16px}.item{width:100%;text-align:left;border:1px solid #d8dee8;background:white;border-radius:10px;padding:10px;margin:0 0 8px;cursor:pointer}.item:hover,.item.active{border-color:#2563eb;background:#eff6ff}.muted{color:#64748b;font-size:12px}.card{background:white;border:1px solid #d8dee8;border-radius:12px;padding:15px;margin-bottom:14px;box-shadow:0 1px 2px #0000000a}.card h2,.card h3{margin-top:0}.pill{display:inline-block;border-radius:999px;background:#e2e8f0;padding:3px 8px;margin:2px;font-size:12px}.signal{background:#dcfce7}.danger{background:#fee2e2}.evidence{font-family:ui-monospace,monospace;font-size:12px;word-break:break-all;background:#f8fafc;padding:8px;border-radius:8px;margin:6px 0}.diff{white-space:pre-wrap;font-family:ui-monospace,monospace;background:#0f172a;color:#dbeafe;padding:12px;border-radius:8px}.graph{display:flex;flex-wrap:wrap;gap:8px}.node{border:1px solid #94a3b8;border-radius:9px;padding:8px;background:#f8fafc}.controls label{display:block;margin:10px 0 4px}.controls input[type=text],.controls textarea,.controls select{width:100%;padding:8px;border:1px solid #cbd5e1;border-radius:7px}.controls textarea{min-height:90px}.checks label{display:flex;gap:8px;align-items:center}.submit{width:100%;margin-top:14px;padding:11px;border:0;border-radius:8px;background:#2563eb;color:white;font-weight:700;cursor:pointer}.submit:disabled{background:#94a3b8}.status{padding:9px;border-radius:8px;margin-top:10px;background:#f1f5f9}.empty{padding:35px;text-align:center;color:#64748b}@media(max-width:1000px){.layout{grid-template-columns:250px 1fr}.decision{grid-column:1/-1;border-left:0;border-top:1px solid #d8dee8}.layout{height:auto}}
</style>
</head>
<body>
<header class="top"><strong>M25.6 Human Review Console</strong><span><a href="/v1/review/audit" target="_blank" style="color:#bfdbfe;margin-right:12px">Audit export</a><span class="badge">candidate-only · no Source write</span></span></header>
<div class="layout">
<aside class="queue"><h2>Review queue</h2><div id="summary" class="muted"></div><div id="queue"></div></aside>
<main class="detail"><div id="detail" class="empty">Select an item to inspect evidence and comparison.</div></main>
<aside class="decision"><h2>Decision</h2><form id="decision-form" class="controls">
<label>Action</label><select id="action"></select>
<label>Rationale</label><textarea id="rationale" required></textarea>
<label>Map target</label><input id="mapping" type="text">
<label>Edit payload (JSON)</label><textarea id="edited">{}</textarea>
<label>Split payload (JSON array)</label><textarea id="split">[{"label":"Part A"},{"label":"Part B"}]</textarea>
<div class="checks"><label><input id="ack-evidence" type="checkbox"> Evidence reviewed</label><label><input id="ack-comparison" type="checkbox"> Comparison reviewed</label><label><input id="ack-diff" type="checkbox"> Diff reviewed</label></div>
<button class="submit" type="submit">Record immutable decision</button><div id="decision-status" class="status">No decision submitted.</div>
</form></aside>
</div><script src="/review/app.js"></script></body></html>"""


REVIEW_JAVASCRIPT = r"""
const state={queue:null,item:null,ledgerHead:null,reviewer:null};
const el=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function api(path,options={}){const r=await fetch(path,{...options,headers:{'Content-Type':'application/json',...(options.headers||{})}});if(!r.ok){let d={};try{d=await r.json()}catch{}throw new Error(d.detail?.message||`HTTP ${r.status}`)}return r.json()}
function renderQueue(){el('summary').textContent=`${state.queue.item_count} items · bulk approval disabled · complete: ${state.queue.review_complete}`;el('queue').innerHTML=state.queue.items.map(i=>`<button class="item ${state.item?.review_item_id===i.review_item_id?'active':''}" data-id="${esc(i.review_item_id)}" data-item-key="${esc(i.item_id)}"><strong>${esc(i.labels.join(' / '))}</strong><div class="muted">${esc(i.class_label)} · ${esc(i.split)} · ${esc(i.decision||'pending')}</div></button>`).join('');document.querySelectorAll('.item').forEach(b=>b.onclick=()=>selectItem(b.dataset.id))}
function pills(values,kind=''){return (values||[]).map(v=>`<span class="pill ${kind}">${esc(v)}</span>`).join('')}
function renderItem(){const i=state.item;if(!i)return;const evidence=i.source_reader.evidence_spans.map(s=>`<div class="evidence">snapshot ${esc(s.snapshot_id)} · derivative ${esc(s.derivative_id)} · ${s.start}-${s.end}<br>excerpt sha256 ${esc(s.excerpt_sha256)}</div>`).join('');const concepts=i.source_reader.source_concepts.map(c=>`<div class="node"><strong>${esc(c.title)}</strong><div class="muted">${esc(c.concept_path)} · ${esc(c.audience)}</div>${pills(c.aliases)}${pills(c.bilingual_terms)}</div>`).join('');const rankings=i.candidate_comparison.governed_resolutions.flatMap(r=>r.ranked_targets).map(r=>`<div class="card"><strong>${esc(r.candidate_id)}</strong>${(r.targets||[]).map(t=>`<div>${esc(t.title||t.x_kos_id)} <strong>${t.score}</strong> ${pills(Object.keys(t.components||{}).filter(k=>t.components[k]>0),'signal')}</div>`).join('')}</div>`).join('');el('detail').innerHTML=`<section class="card"><h2>${esc(i.candidate_summary.map(c=>c.label).join(' / '))}</h2><div>${pills([i.class_label,i.split])}</div><p>${esc(i.rationale)}</p></section><section class="card"><h3>Source reader</h3>${evidence}<div class="muted">Excerpt text is unavailable in this benchmark fixture; no excerpt is fabricated.</div></section><section class="card"><h3>Candidate comparison</h3>${pills(i.candidate_comparison.actual_resolution_outcomes)}<div>${pills(i.candidate_comparison.actual_explanation_signals,'signal')}</div>${rankings}</section><section class="card"><h3>Graph neighbourhood</h3><div class="graph">${concepts}</div>${i.graph_neighborhood.edges.map(e=>`<div class="muted">${esc(e.source)} → ${esc(e.type)} → ${esc(e.target)}${e.score!==undefined?' · '+e.score:''}</div>`).join('')}</section><section class="card"><h3>Aliases, relations and tags</h3><pre>${esc(JSON.stringify(i.proposals,null,2))}</pre></section><section class="card"><h3>Explicit diff</h3><div class="diff">${esc(i.explicit_diff.unified_lines.join('\n'))}</div></section>`;el('action').innerHTML=i.allowed_actions.map(a=>`<option value="${a}">${a}</option>`).join('');renderQueue()}
async function selectItem(id){state.item=await api(`/v1/review/items/${id}`);renderItem()}
async function refresh(){const caps=await api('/v1/review/capabilities');state.reviewer=caps.reviewer;state.queue=await api('/v1/review/queue');const audit=await api('/v1/review/audit');state.ledgerHead=audit.records.length?audit.records[audit.records.length-1].decision_sha256:null;renderQueue();if(!state.item&&state.queue.items.length)await selectItem(state.queue.items[0].review_item_id)}
el('decision-form').onsubmit=async e=>{e.preventDefault();if(!state.item)return;const action=el('action').value;let edited=null,split=null;try{if(action==='edit')edited=JSON.parse(el('edited').value);if(action==='split')split=JSON.parse(el('split').value)}catch(err){el('decision-status').textContent='Invalid JSON payload';return}const body={schema_version:'knowledge-engine-m25-6-decision-request/v1',batch_sha256:state.queue.batch_sha256,review_item_id:state.item.review_item_id,expected_review_state_sha256:state.item.review_state_sha256,expected_ledger_head_sha256:state.ledgerHead,reviewer:state.reviewer,action,rationale:el('rationale').value,evidence_reviewed:el('ack-evidence').checked,comparison_reviewed:el('ack-comparison').checked,diff_reviewed:el('ack-diff').checked,mapping_target:action==='map'?el('mapping').value:null,edited_payload:edited,split_payload:split};try{const result=await api('/v1/review/decisions',{method:'POST',body:JSON.stringify(body)});el('decision-status').textContent=`Recorded ${result.action} · ${result.decision_sha256.slice(0,16)}…`;state.item=null;await refresh()}catch(err){el('decision-status').textContent=err.message}};
refresh().catch(err=>el('detail').textContent=err.message);
"""


__all__ = [
    "ACTIONS",
    "AUDIT_EXPORT_SCHEMA",
    "BATCH_SCHEMA",
    "DECISION_RECORD_SCHEMA",
    "DECISION_REQUEST_SCHEMA",
    "DecisionLedger",
    "DecisionRequest",
    "ReviewSurfaceService",
    "build_review_batch",
    "create_review_app",
    "digest",
    "load_json",
    "validate_review_batch",
]
