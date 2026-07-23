from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .errors import AuthorizationError, IntegrityError
from .m25_controlled_pilot_common import (
    ALLOWED_TRAITS,
    AUDIENCES,
    AUTHORITY_SCHEMA,
    BLOCKED_STATUS,
    GATE_SCHEMA,
    INVENTORY_SCHEMA,
    LANGUAGES,
    LICENCE_CLASSES,
    MAX_SOURCES,
    MIN_SOURCES,
    M25_8_BLOCKED_STATUS,
    M25_8_ENGINE_MERGE_SHA,
    M25_8_GATE_SCHEMA,
    REQUIRED_TRAITS,
    SOURCE_ID_RE,
    SOURCE_TYPES,
    YIELDS,
    _actor,
    _hex,
    _nonnegative_int,
    _number,
    _positive_int,
    sign,
    verify_signed,
)


def evaluate_readiness(predecessor: Mapping[str, Any]) -> dict[str, Any]:
    if predecessor.get("schema_version") != M25_8_GATE_SCHEMA:
        raise IntegrityError("M25-PILOT-009 unsupported M25.8 predecessor schema")
    verify_signed(predecessor, "gate_sha256", "M25-PILOT-010 M25.8 gate digest mismatch")
    if predecessor.get("status") != M25_8_BLOCKED_STATUS:
        raise IntegrityError("M25-PILOT-011 unexpected M25.8 live disposition")
    if (
        predecessor.get("source_pr_merge_permitted") is not False
        or predecessor.get("candidate_release_build_permitted") is not False
        or predecessor.get("production_pointer_mutation_permitted") is not False
        or predecessor.get("production_release_mutation_permitted") is not False
    ):
        raise AuthorizationError("M25-PILOT-012 M25.8 protected boundary drift")
    gate = {
        "schema_version": GATE_SCHEMA,
        "status": BLOCKED_STATUS,
        "predecessor_status": predecessor["status"],
        "predecessor_gate_sha256": predecessor["gate_sha256"],
        "m25_8_engine_merge_sha": M25_8_ENGINE_MERGE_SHA,
        "blockers": [
            "m25_8_live_adoption_release_rollback_acceptance_missing",
            "exact_50_100_source_inventory_manifest_missing",
            "exact_inventory_digest_authority_missing",
            "pilot_cost_and_stop_threshold_authority_missing",
        ],
        "benchmark_fixtures_reusable_as_pilot_sources": False,
        "pilot_execution_permitted": False,
        "provider_calls_permitted": False,
        "source_write_permitted": False,
        "candidate_release_build_permitted": False,
        "production_pointer_mutation_permitted": False,
        "production_release_mutation_permitted": False,
        "m25_9b_authorized": False,
        "m25_9c_authorized": False,
        "m25_10_authorized": False,
        "next_legal_action": "curate_exact_inventory_and_present_daniel_inventory_start_gate",
    }
    return sign(gate, "gate_sha256")


def validate_inventory(value: Mapping[str, Any]) -> dict[str, Any]:
    if value.get("schema_version") != INVENTORY_SCHEMA:
        raise IntegrityError("M25-PILOT-013 unsupported inventory schema")
    inventory_sha = verify_signed(
        value,
        "inventory_sha256",
        "M25-PILOT-014 inventory digest mismatch",
    )
    mode = value.get("mode")
    if mode not in {"live", "test_only"}:
        raise IntegrityError("M25-PILOT-015 invalid inventory mode")
    sources = value.get("sources")
    if not isinstance(sources, list) or not MIN_SOURCES <= len(sources) <= MAX_SOURCES:
        raise IntegrityError("M25-PILOT-016 inventory must contain 50-100 sources")
    if value.get("source_count") != len(sources):
        raise IntegrityError("M25-PILOT-017 source_count mismatch")

    seen_ids: set[str] = set()
    seen_origins: set[tuple[str, str]] = set()
    source_types: set[str] = set()
    languages: set[str] = set()
    yields: set[str] = set()
    traits: set[str] = set()
    audiences: set[str] = set()
    clean_sources: list[dict[str, Any]] = []

    for item in sources:
        if not isinstance(item, dict):
            raise IntegrityError("M25-PILOT-018 malformed inventory source")
        required = {
            "source_id",
            "source_type",
            "origin_locator",
            "origin_sha256",
            "language",
            "audience",
            "licence_class",
            "expected_yield",
            "traits",
        }
        if set(item) != required:
            raise IntegrityError("M25-PILOT-019 inventory source keys mismatch")
        source_id = item.get("source_id")
        if (
            not isinstance(source_id, str)
            or SOURCE_ID_RE.fullmatch(source_id) is None
            or source_id in seen_ids
        ):
            raise IntegrityError("M25-PILOT-020 duplicate or invalid source_id")
        source_type = item.get("source_type")
        language = item.get("language")
        audience = item.get("audience")
        licence = item.get("licence_class")
        expected_yield = item.get("expected_yield")
        if source_type not in SOURCE_TYPES:
            raise IntegrityError("M25-PILOT-021 invalid source_type")
        if language not in LANGUAGES:
            raise IntegrityError("M25-PILOT-022 invalid language")
        if audience not in AUDIENCES:
            raise IntegrityError("M25-PILOT-023 invalid audience")
        if licence not in LICENCE_CLASSES or (mode == "live" and licence == "test_fixture"):
            raise AuthorizationError("M25-PILOT-024 invalid live licence class")
        if expected_yield not in YIELDS:
            raise IntegrityError("M25-PILOT-025 invalid expected_yield")
        locator = item.get("origin_locator")
        if not isinstance(locator, str) or not locator.strip() or len(locator) > 2048:
            raise IntegrityError("M25-PILOT-026 invalid origin locator")
        if mode == "live" and locator.startswith("synthetic://"):
            raise AuthorizationError("M25-PILOT-027 synthetic locator cannot enter live inventory")
        origin_sha = _hex(item.get("origin_sha256"), 64, "origin digest")
        origin_key = (locator, origin_sha)
        if origin_key in seen_origins and "duplicate" not in item.get("traits", []):
            raise IntegrityError("M25-PILOT-028 repeated origin must be declared duplicate")
        item_traits = item.get("traits")
        if (
            not isinstance(item_traits, list)
            or not item_traits
            or any(
                not isinstance(trait, str) or trait not in ALLOWED_TRAITS
                for trait in item_traits
            )
            or len(set(item_traits)) != len(item_traits)
        ):
            raise IntegrityError("M25-PILOT-029 invalid source traits")
        if audience == "restricted" and "restricted_audience" not in item_traits:
            raise IntegrityError("M25-PILOT-030 restricted source lacks restricted trait")

        seen_ids.add(source_id)
        seen_origins.add(origin_key)
        source_types.add(source_type)
        languages.add(language)
        audiences.add(audience)
        yields.add(expected_yield)
        traits.update(item_traits)
        clean_sources.append(json.loads(json.dumps(item)))

    if source_types != SOURCE_TYPES:
        raise IntegrityError("M25-PILOT-031 all required source types must be represented")
    if languages != LANGUAGES:
        raise IntegrityError("M25-PILOT-032 all required languages must be represented")
    if not {"low", "dense"}.issubset(yields):
        raise IntegrityError("M25-PILOT-033 low and dense yield sources are required")
    if not {"public", "restricted"}.issubset(audiences):
        raise IntegrityError("M25-PILOT-034 public and restricted audiences are required")
    missing_traits = REQUIRED_TRAITS - traits
    if missing_traits:
        raise IntegrityError(
            "M25-PILOT-035 missing required adversarial traits: "
            + ",".join(sorted(missing_traits))
        )

    clean = json.loads(json.dumps(value))
    clean["sources"] = clean_sources
    clean["inventory_sha256"] = inventory_sha
    return clean


def validate_authority(value: Mapping[str, Any], inventory: Mapping[str, Any]) -> dict[str, Any]:
    if value.get("schema_version") != AUTHORITY_SCHEMA:
        raise AuthorizationError("M25-PILOT-036 unsupported authority schema")
    authority_sha = verify_signed(
        value,
        "authority_sha256",
        "M25-PILOT-037 authority digest mismatch",
    )
    mode = inventory["mode"]
    if value.get("mode") != mode:
        raise AuthorizationError("M25-PILOT-038 authority mode mismatch")
    _actor(value.get("actor"), mode=mode)
    if (
        value.get("actor_role") != "knowledge_owner"
        or value.get("inventory_sha256") != inventory["inventory_sha256"]
        or value.get("source_count") != inventory["source_count"]
        or value.get("inventory_approved") is not True
        or value.get("pilot_start_authorized") is not True
        or value.get("production_pointer_authorized") is not False
        or value.get("production_release_authorized") is not False
        or value.get("large_scale_ingestion_authorized") is not False
        or value.get("m25_9b_authorized") is not False
        or value.get("m25_9c_authorized") is not False
    ):
        raise AuthorizationError("M25-PILOT-039 stale or over-broad inventory authority")
    _positive_int(value.get("authority_comment_id"), "authority comment ID")
    _number(value.get("max_cost_usd"), "max_cost_usd")
    if not isinstance(value.get("provider_calls_authorized"), bool):
        raise AuthorizationError("M25-PILOT-040 provider policy must be explicit")
    thresholds = value.get("stop_thresholds")
    if not isinstance(thresholds, dict) or set(thresholds) != {
        "max_failed_sources",
        "max_unaccounted_sources",
        "max_security_failures",
    }:
        raise AuthorizationError("M25-PILOT-041 invalid stop thresholds")
    _nonnegative_int(thresholds["max_failed_sources"], "max_failed_sources")
    if thresholds["max_unaccounted_sources"] != 0 or thresholds["max_security_failures"] != 0:
        raise AuthorizationError("M25-PILOT-042 safety thresholds must fail closed")
    clean = json.loads(json.dumps(value))
    clean["authority_sha256"] = authority_sha
    return clean
