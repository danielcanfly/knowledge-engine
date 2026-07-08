from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from runpy import run_path

import pytest

module = run_path("scripts/governed_runtime_acceptance.py")
verify_acceptance = module["verify_acceptance"]

CANDIDATE_RELEASE = "20260708T040116Z-69a9f445699a"
CANDIDATE_MANIFEST = "b" * 64
PRODUCTION_RELEASE = "20260707T111252Z-aebf06593f89"
PRODUCTION_MANIFEST = "a" * 64


def _pointer_bytes() -> bytes:
    return (
        json.dumps(
            {
                "release_id": PRODUCTION_RELEASE,
                "manifest_sha256": PRODUCTION_MANIFEST,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()


def _contract() -> dict:
    pointer = _pointer_bytes()
    return {
        "schema_version": "governed-runtime-acceptance-contract/v1",
        "batch_id": "m9-001-agent-planning-strategies",
        "candidate": {
            "channel": "candidate-source-" + "c" * 40,
            "release_id": CANDIDATE_RELEASE,
            "manifest_sha256": CANDIDATE_MANIFEST,
        },
        "production_baseline": {
            "pointer_key": "channels/production.json",
            "release_id": PRODUCTION_RELEASE,
            "manifest_sha256": PRODUCTION_MANIFEST,
            "pointer_sha256": hashlib.sha256(pointer).hexdigest(),
        },
        "queries": [
            {
                "name": "m9_public_query",
                "query": "m9",
                "audiences": "public",
                "expected_status": "answered",
                "expected_concept_id": "concepts/m9",
                "expected_x_kos_id": "ko_m9",
                "expected_citation": "https://example.com/m9",
            },
            {
                "name": "m8_regression_query",
                "query": "m8",
                "audiences": "public",
                "expected_status": "answered",
                "expected_concept_id": "concepts/m8",
                "expected_x_kos_id": "ko_m8",
                "expected_citation": "https://example.com/m8",
            },
            {
                "name": "m6_regression_query",
                "query": "m6",
                "audiences": "public",
                "expected_status": "answered",
                "expected_concept_id": "concepts/m6",
                "expected_x_kos_id": "ko_m6",
                "expected_citation": "https://example.com/m6",
            },
        ],
        "boundary_query": {
            "name": "m9_acl_boundary_query",
            "query": "secret",
            "audiences": "public",
            "expected_status": "not_found",
            "minimum_acl_filtered_count": 1,
        },
        "requirements": {
            "raw_fallback_allowed": False,
            "minimum_result_count": 1,
            "require_exact_candidate_identity_on_every_query": True,
            "require_byte_exact_production_pointer_invariant": True,
            "production_mutation_authorized": False,
        },
    }


def _answered(concept_id: str, x_kos_id: str, citation: str) -> dict:
    return {
        "status": "answered",
        "release": {
            "release_id": CANDIDATE_RELEASE,
            "manifest_sha256": CANDIDATE_MANIFEST,
        },
        "results": [
            {
                "concept_id": concept_id,
                "x_kos_id": x_kos_id,
                "citations": [{"uri": citation}],
            }
        ],
        "retrieval": {
            "raw_fallback_used": False,
            "acl_filtered_count": 0,
        },
    }


def _outputs() -> dict:
    return {
        "m9_public_query": _answered(
            "concepts/m9", "ko_m9", "https://example.com/m9"
        ),
        "m8_regression_query": _answered(
            "concepts/m8", "ko_m8", "https://example.com/m8"
        ),
        "m6_regression_query": _answered(
            "concepts/m6", "ko_m6", "https://example.com/m6"
        ),
        "m9_acl_boundary_query": {
            "status": "not_found",
            "release": {
                "release_id": CANDIDATE_RELEASE,
                "manifest_sha256": CANDIDATE_MANIFEST,
            },
            "results": [],
            "retrieval": {
                "raw_fallback_used": False,
                "acl_filtered_count": 1,
            },
        },
    }


def test_governed_runtime_acceptance_passes() -> None:
    pointer = _pointer_bytes()
    summary = verify_acceptance(
        contract=_contract(),
        outputs=_outputs(),
        production_before=pointer,
        production_after=pointer,
    )
    assert summary["status"] == "passed"
    assert summary["candidate"]["release_id"] == CANDIDATE_RELEASE
    assert summary["production_pointer"]["byte_exact_unchanged"] is True
    assert summary["production_mutated"] is False
    assert summary["next_legal_action"] == "reconcile_runtime_acceptance"


def test_governed_runtime_acceptance_rejects_candidate_identity_drift() -> None:
    outputs = _outputs()
    outputs["m8_regression_query"]["release"]["release_id"] = "wrong"
    pointer = _pointer_bytes()
    with pytest.raises(SystemExit, match="candidate identity mismatch"):
        verify_acceptance(
            contract=_contract(),
            outputs=outputs,
            production_before=pointer,
            production_after=pointer,
        )


def test_governed_runtime_acceptance_rejects_acl_or_fallback() -> None:
    outputs = _outputs()
    outputs["m9_acl_boundary_query"]["retrieval"]["acl_filtered_count"] = 0
    pointer = _pointer_bytes()
    with pytest.raises(SystemExit, match="did not prove ACL filtering"):
        verify_acceptance(
            contract=_contract(),
            outputs=outputs,
            production_before=pointer,
            production_after=pointer,
        )

    outputs = deepcopy(_outputs())
    outputs["m9_public_query"]["retrieval"]["raw_fallback_used"] = True
    with pytest.raises(SystemExit, match="used raw fallback"):
        verify_acceptance(
            contract=_contract(),
            outputs=outputs,
            production_before=pointer,
            production_after=pointer,
        )


def test_governed_runtime_acceptance_rejects_production_pointer_change() -> None:
    pointer = _pointer_bytes()
    changed = pointer.replace(PRODUCTION_RELEASE.encode(), b"changed-release")
    with pytest.raises(SystemExit, match="production pointer changed"):
        verify_acceptance(
            contract=_contract(),
            outputs=_outputs(),
            production_before=pointer,
            production_after=changed,
        )
