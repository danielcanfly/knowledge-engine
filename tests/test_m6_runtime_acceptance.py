from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


def _load_runtime_acceptance_script() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "scripts" / "m6_runtime_acceptance.py"
    spec = importlib.util.spec_from_file_location("m6_runtime_acceptance", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_boundary_query_targets_internal_only_fixture_without_weakening_acl_gate() -> None:
    module = _load_runtime_acceptance_script()

    assert "M3 candidate pipeline" in module.BOUNDARY_QUERY
    assert "public users" not in module.BOUNDARY_QUERY
    assert "candidate delivery controls" not in module.BOUNDARY_QUERY.lower()


def test_source_governance_identity_accepts_concept_id_or_x_kos_id() -> None:
    module = _load_runtime_acceptance_script()

    assert module._q1_identity_matches(["concepts/source-governance"], [])
    assert module._q1_identity_matches(["source-governance"], [])
    assert module._q1_identity_matches([], [module.EXPECTED_Q1_X_KOS_ID])
    assert not module._q1_identity_matches(["concepts/other"], ["ko_other"])
