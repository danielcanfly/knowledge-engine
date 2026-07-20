from __future__ import annotations

import json
from pathlib import Path

from scripts.m23_7_r3_8_remote_operator import canonical_sha256

MANIFEST_PATH = Path("pilot/m24/m24-sigma-internal-deployment.json")
PACKAGE_PATH = Path("packages/graph-explorer/package.json")
EXPLORER_PATH = Path("packages/graph-explorer/src/index.ts")
ACCEPTANCE_PATH = Path("packages/graph-explorer/src/acceptance.ts")


def _manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def test_sigma_internal_deployment_manifest_is_digest_bound() -> None:
    manifest = _manifest()
    unsigned = dict(manifest)
    digest = unsigned.pop("manifest_sha256")

    assert digest != "TO_BE_FILLED"
    assert canonical_sha256(unsigned) == digest


def test_sigma_internal_deployment_keeps_non_serving_authority() -> None:
    manifest = _manifest()

    assert manifest["status"] == "internal_deployment_ready"
    assert manifest["deployment_target"] == {
        "surface": "internal_review",
        "audience": "internal",
        "production_serving": False,
        "public_indexing": False,
        "shareable_public_url": False,
    }
    assert manifest["production_state"] == {
        "retrieval": "lexical",
        "semantic_promotion_enabled": False,
        "semantic_answer_serving_enabled": False,
        "hybrid_retrieval_enabled": False,
    }
    assert manifest["access_boundary"]["credential_rotation_authorized"] is False
    assert manifest["access_boundary"]["production_mutation_authorized"] is False
    assert manifest["graph_data_contract"]["mutation_routes"] == []
    assert "production_semantic_retrieval" in manifest["forbidden"]
    assert "client_side_acl_broadening" in manifest["forbidden"]


def test_sigma_package_and_checks_are_pinned_for_internal_review() -> None:
    manifest = _manifest()
    package = json.loads(PACKAGE_PATH.read_text(encoding="utf-8"))

    assert package["private"] is True
    assert package["dependencies"]["sigma"] == manifest["package"]["sigma_version"]
    assert package["dependencies"]["graphology"] == manifest["package"][
        "graphology_version"
    ]
    assert package["engines"]["node"] == manifest["package"]["node_engine"]
    assert manifest["package"]["runtime_cdn"] is False
    for command in manifest["performance_checks"]["commands"]:
        assert command.startswith("npm --prefix packages/graph-explorer ")


def test_sigma_existing_code_matches_manifest_boundaries() -> None:
    explorer = EXPLORER_PATH.read_text(encoding="utf-8")
    acceptance = ACCEPTANCE_PATH.read_text(encoding="utf-8")

    assert "Sigma explorer accepts only a read-only graph" in explorer
    assert "Sigma explorer accepts only a renderer-neutral graph" in explorer
    assert "runtimeCdn: false" in acceptance
    assert "browserNetworkClients: []" in acceptance
    assert "writeBackTargets: []" in acceptance
