from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections import Counter
from collections.abc import Callable, Mapping
from copy import deepcopy
from difflib import SequenceMatcher
from typing import Any

from .errors import IntegrityError

POLICY_SCHEMA = "knowledge-engine-m25-identity-calibration-policy/v1"
PACKET_SCHEMA = "knowledge-engine-m25-calibrated-identity-governance/v1"
REPORT_SCHEMA = "knowledge-engine-m25-calibrated-identity-report/v1"
GATE_SCHEMA = "knowledge-engine-m25-identity-governance-gate/v1"
PREDECESSOR_STATUS = "m25_4_gold_benchmark_accepted"
EXIT_STATUS = "m25_5_identity_governance_accepted"
READY_STATUS = "m25_5_identity_governance_ready"
M25_4_SUITE_ID = "m25-concept-identity-gold-v1"

MERGE_OUTCOMES = {"exact_existing_match", "attach_alias_candidate"}
BLOCKING_OUTCOMES = {"probable_duplicate", "ambiguous", "reject"}
DISTINCT_CLASSES = {
    "near_match_distinct",
    "parent_child_distinct",
    "polysemy_ambiguous",
    "supersession_without_identity_collapse",
    "ambiguous_insufficient_evidence",
    "blocked_policy",
}
EXACT_SIGNALS = {
    "exact_x_kos_id",
    "exact_concept_path",
    "exact_normalized_title",
    "exact_approved_alias",
    "exact_bilingual_term",
}
VERSION_RE = re.compile(r"(?i)(?<!\w)v\d+(?:\.\d+)*\b|\b(?:19|20)\d{2}\b")
TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
STOPWORDS = {
    "a",
    "an",
    "and",
    "for",
    "in",
    "of",
    "on",
    "the",
    "to",
}
NARROWING_RELATIONS = {
    "analytics": {"analysis", "metric", "reporting"},
    "governance": {"control", "policy", "review"},
    "monitoring": {"alerting", "detection", "drift", "observability"},
    "retrieval": {"index", "maintenance", "ranking"},
    "review": {"daily", "monthly", "quarterly", "weekly"},
}

Runner = Callable[[Mapping[str, Any]], dict[str, Any]]


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sign(value: dict[str, Any], field: str) -> dict[str, Any]:
    unsigned = dict(value)
    unsigned.pop(field, None)
    value[field] = digest(unsigned)
    return value


def _verify_signed(value: Mapping[str, Any], field: str, code: str) -> None:
    claimed = value.get(field)
    unsigned = dict(value)
    unsigned.pop(field, None)
    if not isinstance(claimed, str) or claimed != digest(unsigned):
        raise IntegrityError(code)


def _norm(value: Any) -> str:
    if not isinstance(value, str):
        raise IntegrityError("M25-GOV-101 invalid text")
    normalized = " ".join(unicodedata.normalize("NFKC", value).split()).casefold()
    if not normalized or len(normalized) > 500:
        raise IntegrityError("M25-GOV-102 invalid normalized text")
    return normalized


def _tokens(value: str, *, strip_versions: bool = False) -> tuple[str, ...]:
    normalized = _norm(value)
    if strip_versions:
        normalized = VERSION_RE.sub(" ", normalized)
    return tuple(
        token
        for token in TOKEN_RE.findall(normalized)
        if token not in STOPWORDS and not token.isdigit()
    )


def _version_markers(value: str) -> tuple[str, ...]:
    return tuple(sorted(match.group(0).casefold() for match in VERSION_RE.finditer(_norm(value))))


def _jaccard(left: tuple[str, ...], right: tuple[str, ...]) -> float:
    left_set, right_set = set(left), set(right)
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / len(left_set | right_set)


def _containment(left: tuple[str, ...], right: tuple[str, ...]) -> float:
    left_set, right_set = set(left), set(right)
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / min(len(left_set), len(right_set))


def _source_names(concept: Mapping[str, Any]) -> list[tuple[str, str]]:
    values = [("title", concept["title"])]
    values.extend(("alias", item) for item in concept.get("aliases", []))
    values.extend(("term", item) for item in concept.get("bilingual_terms", []))
    return [(kind, _norm(value)) for kind, value in values]


def _candidate_names(candidate: Mapping[str, Any]) -> list[str]:
    values = [candidate["label"], *candidate.get("aliases", [])]
    for field in ("counterpart_label", "target_label"):
        counterpart = candidate.get(field)
        if isinstance(counterpart, str):
            values.append(counterpart)
    return sorted({_norm(value) for value in values})


def _endpoint_candidates(case: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        deepcopy(candidate)
        for candidate in case.get("candidates", [])
        if candidate.get("kind") in {"concept", "entity", "alias", "term"}
    ]


def _case_authority(case: Mapping[str, Any]) -> None:
    candidates = case.get("candidates")
    concepts = case.get("source_concepts")
    audiences = case.get("candidate_audiences")
    if not isinstance(candidates, list) or not isinstance(concepts, list):
        raise IntegrityError("M25-GOV-103 malformed case")
    candidate_ids = {candidate.get("candidate_id") for candidate in candidates}
    if not isinstance(audiences, dict) or set(audiences) != candidate_ids:
        raise IntegrityError("M25-GOV-104 candidate audience coverage mismatch")
    for candidate in candidates:
        if (
            candidate.get("authority") != "candidate_only"
            or candidate.get("canonical_knowledge") is not False
            or candidate.get("production_authority") is not False
        ):
            raise IntegrityError("M25-GOV-105 candidate authority drift")


def _governed_tags(case: Mapping[str, Any]) -> list[dict[str, Any]]:
    values = case.get("governed_tags", [])
    if not isinstance(values, list) or len(values) > 1000:
        raise IntegrityError("M25-GOV-106 invalid governed tag population")
    candidate_ids = {candidate["candidate_id"] for candidate in case.get("candidates", [])}
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, dict):
            raise IntegrityError("M25-GOV-107 malformed governed tag")
        tag_id = value.get("tag_candidate_id")
        if not isinstance(tag_id, str) or not tag_id or tag_id in seen:
            raise IntegrityError("M25-GOV-108 duplicate governed tag identity")
        seen.add(tag_id)
        if value.get("source_candidate_id") not in candidate_ids:
            raise IntegrityError("M25-GOV-109 governed tag source missing")
        if (
            value.get("authority") != "candidate_only"
            or value.get("status") != "pending_review"
            or value.get("canonical_knowledge") is not False
            or value.get("production_authority") is not False
        ):
            raise IntegrityError("M25-GOV-109 governed tag authority drift")
        output.append(deepcopy(value))
    return sorted(output, key=lambda item: item["tag_candidate_id"])


def _rank_sources(
    case: Mapping[str, Any], candidate: Mapping[str, Any], policy: Mapping[str, Any]
) -> list[dict[str, Any]]:
    candidate_names = _candidate_names(candidate)
    candidate_tokens = _tokens(candidate["label"])
    candidate_audience = case["candidate_audiences"][candidate["candidate_id"]]
    candidate_tags = {_norm(item) for item in candidate.get("controlled_tags", [])}
    ranking: list[dict[str, Any]] = []
    weights = policy["ranking_weights"]
    for concept in case.get("source_concepts", []):
        components: dict[str, float] = {}
        source_names = _source_names(concept)
        for kind, source_name in source_names:
            if source_name in candidate_names:
                components[f"exact_{kind}"] = float(weights[f"exact_{kind}"])
        source_tokens = _tokens(concept["title"])
        token_jaccard = _jaccard(candidate_tokens, source_tokens)
        token_containment = _containment(candidate_tokens, source_tokens)
        sequence = SequenceMatcher(None, _norm(candidate["label"]), _norm(concept["title"])).ratio()
        if token_jaccard:
            components["token_jaccard"] = round(
                token_jaccard * float(weights["token_jaccard"]), 6
            )
        if token_containment:
            components["token_containment"] = round(
                token_containment * float(weights["token_containment"]), 6
            )
        if sequence:
            components["sequence_similarity"] = round(
                sequence * float(weights["sequence_similarity"]), 6
            )
        source_tags = {_norm(item) for item in concept.get("tags", [])}
        if candidate_tags & source_tags:
            components["governed_tag_overlap"] = round(
                len(candidate_tags & source_tags) * float(weights["governed_tag_overlap"]),
                6,
            )
        audience_match = concept.get("audience") == candidate_audience
        if not audience_match:
            components["audience_mismatch"] = -float(weights["audience_mismatch_penalty"])
        candidate_versions = _version_markers(candidate["label"])
        source_versions = _version_markers(concept["title"])
        if candidate_versions and source_versions and candidate_versions != source_versions:
            components["version_mismatch"] = -float(weights["version_mismatch_penalty"])
        score = round(sum(components.values()), 6)
        ranking.append(
            {
                "x_kos_id": concept["x_kos_id"],
                "concept_path": concept["concept_path"],
                "score": score,
                "components": dict(sorted(components.items())),
                "audience_match": audience_match,
                "exact_identity_signal": bool(
                    {key for key in components if key.startswith("exact_")}
                ),
                "token_jaccard": round(token_jaccard, 6),
                "token_containment": round(token_containment, 6),
                "sequence_similarity": round(sequence, 6),
            }
        )
    return sorted(ranking, key=lambda item: (-item["score"], item["x_kos_id"]))


def _polysemy_targets(case: Mapping[str, Any], candidate: Mapping[str, Any]) -> list[str]:
    candidate_names = set(_candidate_names(candidate))
    targets = {
        concept["x_kos_id"]
        for concept in case.get("source_concepts", [])
        if candidate_names & {name for _kind, name in _source_names(concept)}
    }
    return sorted(targets) if len(targets) > 1 else []


def _supersession_target(
    case: Mapping[str, Any], candidate: Mapping[str, Any]
) -> dict[str, Any] | None:
    candidate_versions = _version_markers(candidate["label"])
    if not candidate_versions:
        return None
    candidate_stem = _tokens(candidate["label"], strip_versions=True)
    matches: list[tuple[float, str, dict[str, Any]]] = []
    for concept in case.get("source_concepts", []):
        source_versions = _version_markers(concept["title"])
        if not source_versions or source_versions == candidate_versions:
            continue
        source_stem = _tokens(concept["title"], strip_versions=True)
        score = max(
            _jaccard(candidate_stem, source_stem),
            _containment(candidate_stem, source_stem),
        )
        if score >= 0.5:
            matches.append((score, concept["x_kos_id"], concept))
    if not matches:
        return None
    return max(matches, key=lambda item: (item[0], item[1]))[2]


def _parent_child_target(
    case: Mapping[str, Any], candidate: Mapping[str, Any]
) -> dict[str, Any] | None:
    if _version_markers(candidate["label"]):
        return None
    candidate_tokens = set(_tokens(candidate["label"]))
    matches: list[tuple[float, str, dict[str, Any]]] = []
    for concept in case.get("source_concepts", []):
        source_tokens = set(_tokens(concept["title"]))
        shared = candidate_tokens & source_tokens
        if not shared:
            continue
        containment = source_tokens < candidate_tokens
        semantic_narrowing = any(
            parent in source_tokens and bool(children & candidate_tokens)
            for parent, children in NARROWING_RELATIONS.items()
        )
        if not containment and not semantic_narrowing:
            continue
        score = len(shared) / max(1, len(source_tokens))
        matches.append((score, concept["x_kos_id"], concept))
    if not matches:
        return None
    return max(matches, key=lambda item: (item[0], item[1]))[2]


def _near_match_target(
    case: Mapping[str, Any], candidate: Mapping[str, Any], ranking: list[dict[str, Any]]
) -> dict[str, Any] | None:
    if not ranking:
        return None
    best = ranking[0]
    if best["exact_identity_signal"]:
        return None
    threshold = 0.18
    if (
        best["token_jaccard"] >= threshold
        or best["token_containment"] >= 0.34
        or best["sequence_similarity"] >= 0.5
    ):
        return next(
            concept
            for concept in case.get("source_concepts", [])
            if concept["x_kos_id"] == best["x_kos_id"]
        )
    return None


def _relation_candidate(
    candidate_id: str,
    target: Mapping[str, Any],
    relation_type: str,
    evidence_spans: list[dict[str, Any]],
) -> dict[str, Any]:
    identity = {
        "candidate_id": candidate_id,
        "target_x_kos_id": target["x_kos_id"],
        "relation_type": relation_type,
    }
    return {
        "relation_candidate_id": f"m25rel_{digest(identity)[:32]}",
        "source_candidate_id": candidate_id,
        "target_x_kos_id": target["x_kos_id"],
        "target_concept_path": target["concept_path"],
        "relation_type": relation_type,
        "evidence_spans": deepcopy(evidence_spans),
        "status": "pending_review",
        "authority": "candidate_only",
        "canonical_knowledge": False,
        "production_authority": False,
        "automatic_write_permitted": False,
    }


def _resolution_signals(
    case: Mapping[str, Any],
    resolution: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> tuple[set[str], list[dict[str, Any]], list[dict[str, Any]]]:
    inherited = set(resolution.get("strong_signals", [])) | set(
        resolution.get("weak_signals", [])
    )
    candidate_lookup = {
        candidate["candidate_id"]: candidate for candidate in _endpoint_candidates(case)
    }
    rankings: list[dict[str, Any]] = []
    relations: list[dict[str, Any]] = []
    for candidate_id in resolution.get("candidate_ids", []):
        candidate = candidate_lookup.get(candidate_id)
        if candidate is None:
            continue
        ranking = _rank_sources(case, candidate, policy)
        rankings.append({"candidate_id": candidate_id, "targets": ranking[:10]})
        outcome = resolution.get("outcome")
        if outcome == "ambiguous" and _polysemy_targets(case, candidate):
            inherited.add("polysemy_collision")
        if outcome != "distinct_new_candidate":
            continue
        supersession = _supersession_target(case, candidate)
        if supersession is not None:
            inherited.add("supersession_distinction")
            relations.append(
                _relation_candidate(
                    candidate_id,
                    supersession,
                    "supersedes",
                    candidate.get("evidence_spans", []),
                )
            )
            continue
        parent = _parent_child_target(case, candidate)
        if parent is not None:
            inherited.add("parent_child_distinction")
            relations.append(
                _relation_candidate(
                    candidate_id,
                    parent,
                    "narrower_than",
                    candidate.get("evidence_spans", []),
                )
            )
            continue
        if _near_match_target(case, candidate, ranking) is not None:
            inherited.add("near_match_distinction")
    return inherited, rankings, relations


def build_calibration_policy(
    suite: Mapping[str, Any], baseline: Mapping[str, Any]
) -> dict[str, Any]:
    if (
        suite.get("suite_id") != M25_4_SUITE_ID
        or suite.get("approval_status") != "approved_by_daniel"
    ):
        raise IntegrityError("M25-GOV-110 approved M25.4 suite required")
    _verify_signed(suite, "suite_sha256", "M25-GOV-111 suite digest mismatch")
    if baseline.get("baseline_status") != "accepted_baseline":
        raise IntegrityError("M25-GOV-112 accepted M25.4 baseline required")
    _verify_signed(baseline, "report_sha256", "M25-GOV-113 baseline digest mismatch")
    if baseline.get("suite_sha256") != suite.get("suite_sha256"):
        raise IntegrityError("M25-GOV-114 suite/baseline mismatch")
    calibration_items = sorted(
        item["item_id"] for item in suite["items"] if item["split"] in {"train", "calibration"}
    )
    final_items = sorted(item["item_id"] for item in suite["items"] if item["split"] == "final")
    gap_classes = sorted(
        {
            result["class_label"]
            for result in baseline["results"]
            if result["split"] in {"train", "calibration"}
            and "explanation_signal_gap" in result["error_codes"]
        }
    )
    policy = {
        "schema_version": POLICY_SCHEMA,
        "policy_id": "m25-5-conservative-identity-governance-v1",
        "predecessor_status": PREDECESSOR_STATUS,
        "suite_id": suite["suite_id"],
        "suite_sha256": suite["suite_sha256"],
        "baseline_report_sha256": baseline["report_sha256"],
        "calibration": {
            "splits": ["calibration", "train"],
            "item_ids": calibration_items,
            "item_count": len(calibration_items),
            "observed_explanation_gap_classes": gap_classes,
            "final_split_used": False,
        },
        "held_out_evaluation": {
            "split": "final",
            "item_ids": final_items,
            "item_count": len(final_items),
            "may_change_policy": False,
        },
        "merge_gate": {
            "critical_false_merge_limit": 0,
            "minimum_exact_match_score": 0.9,
            "minimum_alias_score": 0.9,
            "lexical_or_tag_only_merge_permitted": False,
            "ambiguous_destructive_action_permitted": False,
            "automatic_canonical_write_permitted": False,
        },
        "ranking_weights": {
            "exact_title": 1.0,
            "exact_alias": 0.96,
            "exact_term": 0.92,
            "token_jaccard": 0.28,
            "token_containment": 0.22,
            "sequence_similarity": 0.12,
            "governed_tag_overlap": 0.05,
            "audience_mismatch_penalty": 2.0,
            "version_mismatch_penalty": 0.75,
        },
        "explanation_rules": {
            "near_match_distinction": "lexical proximity without an exact identity owner",
            "parent_child_distinction": "narrower scope or governed semantic hierarchy",
            "polysemy_collision": "multiple exact owners for one surface form",
            "supersession_distinction": "versioned or temporal stem match with different identity",
        },
        "relation_governance": {
            "allowed_candidate_relations": ["narrower_than", "supersedes"],
            "review_required": True,
            "automatic_write_permitted": False,
        },
        "authority": "candidate_only",
        "review_required": True,
        "canonical_knowledge": False,
        "production_authority": False,
        "m25_6_authorized": False,
    }
    return sign(policy, "policy_sha256")


def validate_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    if policy.get("schema_version") != POLICY_SCHEMA:
        raise IntegrityError("M25-GOV-120 invalid policy schema")
    _verify_signed(policy, "policy_sha256", "M25-GOV-121 policy digest mismatch")
    if (
        policy.get("authority") != "candidate_only"
        or policy.get("review_required") is not True
        or policy.get("canonical_knowledge") is not False
        or policy.get("production_authority") is not False
        or policy.get("m25_6_authorized") is not False
    ):
        raise IntegrityError("M25-GOV-122 policy authority drift")
    calibration = policy.get("calibration")
    held_out = policy.get("held_out_evaluation")
    if (
        not isinstance(calibration, dict)
        or not isinstance(held_out, dict)
        or calibration.get("final_split_used") is not False
        or held_out.get("may_change_policy") is not False
        or set(calibration.get("item_ids", [])) & set(held_out.get("item_ids", []))
    ):
        raise IntegrityError("M25-GOV-123 final split leakage")
    merge_gate = policy.get("merge_gate")
    if (
        not isinstance(merge_gate, dict)
        or merge_gate.get("critical_false_merge_limit") != 0
        or merge_gate.get("lexical_or_tag_only_merge_permitted") is not False
        or merge_gate.get("ambiguous_destructive_action_permitted") is not False
        or merge_gate.get("automatic_canonical_write_permitted") is not False
    ):
        raise IntegrityError("M25-GOV-124 unsafe merge gate")
    return deepcopy(dict(policy))


def build_governance_packet(
    case: Mapping[str, Any],
    resolution_packet: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    validated_policy = validate_policy(policy)
    _case_authority(case)
    if (
        resolution_packet.get("schema") != "knowledge-engine-resolution-candidates/v1"
        or resolution_packet.get("authority") != "candidate_only"
        or resolution_packet.get("canonical_knowledge") is not False
        or resolution_packet.get("production_authority") is not False
        or resolution_packet.get("review_required") is not True
    ):
        raise IntegrityError("M25-GOV-130 inherited resolver authority drift")
    _verify_signed(
        resolution_packet,
        "packet_sha256",
        "M25-GOV-131 inherited resolver packet digest mismatch",
    )
    governed_tags = _governed_tags(case)
    governed_resolutions: list[dict[str, Any]] = []
    relation_candidates: dict[str, dict[str, Any]] = {}
    all_signals: set[str] = set()
    critical_false_merge_risk_count = 0
    for resolution in resolution_packet.get("resolutions", []):
        signals, rankings, relations = _resolution_signals(
            case, resolution, validated_policy
        )
        all_signals.update(signals)
        for relation in relations:
            relation_candidates[relation["relation_candidate_id"]] = relation
        outcome = resolution["outcome"]
        top_score = max(
            (
                target["score"]
                for ranking in rankings
                for target in ranking.get("targets", [])
            ),
            default=0.0,
        )
        exact_signal_present = bool(signals & EXACT_SIGNALS) or outcome == "attach_alias_candidate"
        merge_gate_pass = outcome not in MERGE_OUTCOMES or (
            exact_signal_present
            and top_score >= validated_policy["merge_gate"]["minimum_exact_match_score"]
        )
        if outcome in MERGE_OUTCOMES and not merge_gate_pass:
            critical_false_merge_risk_count += 1
        governed_resolutions.append(
            {
                "resolution_id": resolution["resolution_id"],
                "candidate_ids": deepcopy(resolution["candidate_ids"]),
                "inherited_outcome": outcome,
                "governed_outcome": outcome,
                "explanation_signals": sorted(signals),
                "ranked_targets": rankings,
                "merge_gate_pass": merge_gate_pass,
                "blocks_destructive_action": outcome in BLOCKING_OUTCOMES
                or not merge_gate_pass,
                "automatic_action_allowed": False,
                "status": "pending_review",
                "authority": "candidate_only",
                "canonical_knowledge": False,
                "production_authority": False,
            }
        )
    if resolution_packet.get("contradictions"):
        all_signals.add("contradiction_candidate")
    packet = {
        "schema_version": PACKET_SCHEMA,
        "policy_sha256": validated_policy["policy_sha256"],
        "resolver_packet_sha256": resolution_packet["packet_sha256"],
        "case_sha256": digest(case),
        "resolution_count": len(governed_resolutions),
        "contradiction_count": resolution_packet.get("contradiction_count", 0),
        "critical_false_merge_risk_count": critical_false_merge_risk_count,
        "destructive_decision_count": 0,
        "packaging_blocked": bool(resolution_packet.get("packaging_blocked"))
        or bool(critical_false_merge_risk_count),
        "explanation_signals": sorted(all_signals),
        "governed_resolutions": governed_resolutions,
        "governed_tag_count": len(governed_tags),
        "governed_tag_candidates": governed_tags,
        "governed_tags_sha256": digest(governed_tags),
        "relation_candidate_count": len(relation_candidates),
        "relation_candidates": [
            relation_candidates[key] for key in sorted(relation_candidates)
        ],
        "tag_governance_preserved": True,
        "relation_governance_preserved": True,
        "authority": "candidate_only",
        "review_required": True,
        "canonical_knowledge": False,
        "production_authority": False,
    }
    return sign(packet, "governance_packet_sha256")


def _default_runner(case: Mapping[str, Any]) -> dict[str, Any]:
    from .m25_identity_benchmark import run_case

    return run_case(case)


def _wilson(successes: int, total: int, z: float = 1.959964) -> dict[str, float]:
    if total <= 0:
        return {"lower": 0.0, "upper": 0.0}
    proportion = successes / total
    denominator = 1 + z * z / total
    centre = proportion + z * z / (2 * total)
    margin = z * math.sqrt((proportion * (1 - proportion) + z * z / (4 * total)) / total)
    return {
        "lower": round(max(0.0, (centre - margin) / denominator), 6),
        "upper": round(min(1.0, (centre + margin) / denominator), 6),
    }


def run_calibrated_benchmark(
    suite: Mapping[str, Any],
    baseline: Mapping[str, Any],
    policy: Mapping[str, Any],
    *,
    runner: Runner | None = None,
) -> dict[str, Any]:
    validated_policy = validate_policy(policy)
    if suite.get("suite_sha256") != validated_policy["suite_sha256"]:
        raise IntegrityError("M25-GOV-140 policy/suite mismatch")
    _verify_signed(suite, "suite_sha256", "M25-GOV-141 suite digest mismatch")
    _verify_signed(baseline, "report_sha256", "M25-GOV-142 baseline digest mismatch")
    if baseline.get("report_sha256") != validated_policy["baseline_report_sha256"]:
        raise IntegrityError("M25-GOV-143 policy/baseline mismatch")
    baseline_by_id = {result["item_id"]: result for result in baseline["results"]}
    execute = runner or _default_runner
    results: list[dict[str, Any]] = []
    class_totals: Counter[str] = Counter()
    class_pass: Counter[str] = Counter()
    split_totals: Counter[str] = Counter()
    split_pass: Counter[str] = Counter()
    relation_counts: Counter[str] = Counter()
    for item in suite["items"]:
        base_packet = execute(item["case"])
        governed = build_governance_packet(item["case"], base_packet, validated_policy)
        baseline_result = baseline_by_id[item["item_id"]]
        actual_outcomes = sorted(
            resolution["inherited_outcome"]
            for resolution in governed["governed_resolutions"]
        )
        if actual_outcomes != baseline_result["actual_resolution_outcomes"]:
            raise IntegrityError("M25-GOV-144 inherited resolver outcome drift")
        required_signals = set(item["expected"]["required_explanation_signals"])
        actual_signals = set(governed["explanation_signals"])
        missing = sorted(required_signals - actual_signals)
        no_false_merge = not (
            item["class_label"] in DISTINCT_CLASSES
            and bool(set(actual_outcomes) & MERGE_OUTCOMES)
        )
        semantic_pass = (
            actual_outcomes == item["expected"]["resolution_outcomes"]
            and governed["contradiction_count"]
            == item["expected"]["contradiction_count"]
            and governed["packaging_blocked"] is item["expected"]["packaging_blocked"]
            and no_false_merge
        )
        explanation_pass = not missing
        class_totals[item["class_label"]] += 1
        split_totals[item["split"]] += 1
        if semantic_pass and explanation_pass:
            class_pass[item["class_label"]] += 1
            split_pass[item["split"]] += 1
        for relation in governed["relation_candidates"]:
            relation_counts[relation["relation_type"]] += 1
        results.append(
            {
                "item_id": item["item_id"],
                "class_label": item["class_label"],
                "split": item["split"],
                "actual_resolution_outcomes": actual_outcomes,
                "required_explanation_signals": sorted(required_signals),
                "actual_explanation_signals": sorted(actual_signals),
                "missing_explanation_signals": missing,
                "semantic_pass": semantic_pass,
                "explanation_pass": explanation_pass,
                "no_false_merge": no_false_merge,
                "critical_false_merge_risk_count": governed[
                    "critical_false_merge_risk_count"
                ],
                "destructive_decision_count": governed["destructive_decision_count"],
                "relation_candidate_types": sorted(
                    relation["relation_type"] for relation in governed["relation_candidates"]
                ),
            }
        )
    total = len(results)
    full_pass = sum(item["semantic_pass"] and item["explanation_pass"] for item in results)
    semantic_passes = sum(item["semantic_pass"] for item in results)
    explanation_passes = sum(item["explanation_pass"] for item in results)
    false_merge_count = sum(not item["no_false_merge"] for item in results)
    critical_risks = sum(item["critical_false_merge_risk_count"] for item in results)
    destructive_decisions = sum(item["destructive_decision_count"] for item in results)
    final_results = [item for item in results if item["split"] == "final"]
    report = {
        "schema_version": REPORT_SCHEMA,
        "status": "m25_5_identity_governance_candidate",
        "predecessor_status": PREDECESSOR_STATUS,
        "suite_id": suite["suite_id"],
        "suite_sha256": suite["suite_sha256"],
        "baseline_report_sha256": baseline["report_sha256"],
        "policy_sha256": validated_policy["policy_sha256"],
        "final_split_used_for_calibration": False,
        "denominators": {
            "total": total,
            "by_class": dict(sorted(class_totals.items())),
            "by_split": dict(sorted(split_totals.items())),
        },
        "metrics": {
            "semantic_decision_accuracy": round(semantic_passes / total, 6),
            "explanation_signal_coverage": round(explanation_passes / total, 6),
            "combined_governance_pass_rate": round(full_pass / total, 6),
            "final_split_governance_pass_rate": round(
                sum(item["semantic_pass"] and item["explanation_pass"] for item in final_results)
                / len(final_results),
                6,
            ),
            "combined_governance_pass_ci95": _wilson(full_pass, total),
            "false_merge_count": false_merge_count,
            "critical_false_merge_risk_count": critical_risks,
            "destructive_decision_count": destructive_decisions,
            "per_class_governance_pass_rate": {
                label: round(class_pass[label] / class_totals[label], 6)
                for label in sorted(class_totals)
            },
            "per_split_governance_pass_rate": {
                split: round(split_pass[split] / split_totals[split], 6)
                for split in sorted(split_totals)
            },
            "relation_candidate_count_by_type": dict(sorted(relation_counts.items())),
        },
        "gate": {
            "zero_critical_false_merges": critical_risks == 0,
            "zero_destructive_decisions": destructive_decisions == 0,
            "semantic_accuracy_one": semantic_passes == total,
            "explanation_coverage_one": explanation_passes == total,
            "final_split_pass_one": all(
                item["semantic_pass"] and item["explanation_pass"]
                for item in final_results
            ),
            "final_split_remained_held_out": True,
        },
        "results": sorted(results, key=lambda item: item["item_id"]),
        "authority": "candidate_only",
        "review_required": True,
        "canonical_knowledge": False,
        "production_authority": False,
        "m25_6_authorized": False,
    }
    return sign(report, "report_sha256")


def build_governance_gate(report: Mapping[str, Any]) -> dict[str, Any]:
    if report.get("schema_version") != REPORT_SCHEMA:
        raise IntegrityError("M25-GOV-150 invalid report schema")
    _verify_signed(report, "report_sha256", "M25-GOV-151 report digest mismatch")
    gates = report.get("gate")
    if not isinstance(gates, dict):
        raise IntegrityError("M25-GOV-152 missing gate")
    accepted = all(gates.values())
    gate = {
        "schema_version": GATE_SCHEMA,
        "status": READY_STATUS if accepted else "m25_5_identity_governance_blocked",
        "report_sha256": report["report_sha256"],
        "policy_sha256": report["policy_sha256"],
        "predecessor_status": PREDECESSOR_STATUS,
        "all_gates_passed": accepted,
        "gate_results": deepcopy(gates),
        "protected_mutations": {
            "source": False,
            "foundation": False,
            "release": False,
            "production_pointer": False,
            "r2_production": False,
            "qdrant": False,
            "serving": False,
            "canonical_identity": False,
        },
        "authority": "candidate_only",
        "canonical_knowledge": False,
        "production_authority": False,
        "m25_6_authorized": False,
    }
    return sign(gate, "gate_sha256")


__all__ = [
    "EXIT_STATUS",
    "GATE_SCHEMA",
    "PACKET_SCHEMA",
    "POLICY_SCHEMA",
    "PREDECESSOR_STATUS",
    "READY_STATUS",
    "REPORT_SCHEMA",
    "build_calibration_policy",
    "build_governance_gate",
    "build_governance_packet",
    "canonical_bytes",
    "digest",
    "run_calibrated_benchmark",
    "sign",
    "validate_policy",
]
