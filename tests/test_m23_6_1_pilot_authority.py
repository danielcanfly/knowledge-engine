from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from src.knowledge_engine.errors import IntegrityError
from src.knowledge_engine.m23_pilot_authority import (
    QDRANT_COLLECTION,
    REQUIRED_CANDIDATE_IDENTITY_FIELDS,
    REQUIRED_QDRANT_PAYLOAD_FIELDS,
    SOURCE_ADOPTION_LANE,
    build_acceptance_report,
    canonical_sha256,
    load_authority_contract,
    validate_authority_contract,
)

CONTRACT_PATH = Path("pilot/m23/m23-6-1-authority-contract.json")


def _contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def _resign(contract: dict) -> dict:
    contract.pop("contract_sha256", None)
    contract["contract_sha256"] = canonical_sha256(contract)
    return contract


def test_repository_contract_is_valid_and_deterministic():
    first = load_authority_contract(CONTRACT_PATH)
    second = load_authority_contract(CONTRACT_PATH)
    assert first == second
    assert first["contract_sha256"] == canonical_sha256(
        {key: value for key, value in first.items() if key != "contract_sha256"}
    )


def test_source_pr_19_is_evaluation_only_and_cannot_claim_authority():
    contract = _contract()
    lane = contract["source_adoption"]
    assert lane["lane"] == SOURCE_ADOPTION_LANE
    assert lane["source_merge_authorized"] is False
    assert lane["pending_canonical_knowledge"] is False
    assert lane["pending_candidate_release_eligible"] is False
    assert lane["pending_production_authority"] is False
    assert lane["candidate_requires_canonical_rebuild"] is True


def test_candidate_and_qdrant_identity_fields_are_exact():
    contract = _contract()
    assert tuple(contract["candidate_identity_contract"]["required_fields"]) == (
        REQUIRED_CANDIDATE_IDENTITY_FIELDS
    )
    assert tuple(contract["qdrant"]["payload_fields"]) == REQUIRED_QDRANT_PAYLOAD_FIELDS
    assert contract["qdrant"]["collection"] == QDRANT_COLLECTION
    assert contract["qdrant"]["vector_name"] == "default"
    assert contract["qdrant"]["dimension"] == 1024
    assert contract["qdrant"]["distance"] == "Cosine"


def test_all_protected_mutations_are_false():
    authority = _contract()["authority"]
    assert authority
    assert all(value is False for value in authority.values())


def test_locked_defaults_keep_lexical_and_forbid_graph_neural_retrieval():
    defaults = _contract()["locked_defaults"]
    assert defaults == {
        "AUTO_EXTRACTION_ENABLED": False,
        "GRAPH_EXPLORER_ENABLED": False,
        "GRAPH_NEURAL_RETRIEVAL_ENABLED": False,
        "MULTIHOP_MODE": "off",
        "RETRIEVAL_MODE": "lexical",
    }


def test_tampering_or_implicit_adoption_fails_closed():
    contract = copy.deepcopy(_contract())
    contract["source_adoption"]["lane"] = "approved-canonical-adoption"
    _resign(contract)
    with pytest.raises(IntegrityError, match="source_adoption.lane"):
        validate_authority_contract(contract)


def test_qdrant_write_or_wrong_collection_fails_closed():
    contract = copy.deepcopy(_contract())
    contract["qdrant"]["first_write_authorized"] = True
    _resign(contract)
    with pytest.raises(IntegrityError, match="first_write_authorized"):
        validate_authority_contract(contract)

    contract = copy.deepcopy(_contract())
    contract["qdrant"]["collection"] = "llamaindex_demo_hybrid"
    _resign(contract)
    with pytest.raises(IntegrityError, match="qdrant.collection"):
        validate_authority_contract(contract)


def test_public_explorer_or_nonlexical_default_fails_closed():
    contract = copy.deepcopy(_contract())
    contract["graph_explorer"]["public_route_allowed"] = True
    _resign(contract)
    with pytest.raises(IntegrityError, match="public_route_allowed"):
        validate_authority_contract(contract)

    contract = copy.deepcopy(_contract())
    contract["locked_defaults"]["RETRIEVAL_MODE"] = "vector"
    _resign(contract)
    with pytest.raises(IntegrityError, match="RETRIEVAL_MODE"):
        validate_authority_contract(contract)


def test_acceptance_report_is_bounded_and_nonmutating():
    report = build_acceptance_report(_contract())
    assert report["decision"] == "accepted-for-m23.6.2-contract-work"
    assert report["qdrant_write_authorized"] is False
    assert report["production_mutation_dispatched"] is False
    assert len(report["report_sha256"]) == 64
    assert "M23.6.2" in report["next_legal_action"]
