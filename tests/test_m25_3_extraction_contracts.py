from __future__ import annotations

import ast
import json
from pathlib import Path

from knowledge_engine.m25_extraction_common import _digest

ROOT = Path(__file__).resolve().parents[1]


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def assert_signed(path: Path, field: str) -> None:
    value = load(path)
    unsigned = dict(value)
    claimed = unsigned.pop(field)
    assert claimed == _digest(unsigned)


def test_frozen_contracts_are_digest_bound() -> None:
    contracts = {
        "m25-3-prompt-contract.json": "prompt_contract_sha256",
        "m25-3-model-policy.json": "model_policy_sha256",
        "m25-3-candidate-policy.json": "candidate_policy_sha256",
        "m25-3-provider-registry.json": "provider_registry_sha256",
        "m25-3-authority-envelope.json": "authority_sha256",
        "m25-3-entry-contract.json": "entry_contract_sha256",
        "m25-3-contract-registry.json": "contract_registry_sha256",
    }
    for name, field in contracts.items():
        assert_signed(ROOT / "pilot" / "m25" / name, field)


def test_entry_contract_binds_exact_predecessor() -> None:
    value = load(ROOT / "pilot" / "m25" / "m25-3-entry-contract.json")
    assert value["engine_main_sha"] == "cc83a1e6bae1dce45fca50d3fdb515c26a70d0f9"
    assert value["predecessor_status"] == "m25_2_intake_orchestrator_accepted"
    assert value["predecessor_acceptance_path"] == "pilot/m25/m25-2-acceptance.json"
    assert value["implementation_issue"] == 1043


def test_all_m25_3_schemas_are_closed_and_parseable() -> None:
    expected = {
        "m25-prompt-contract-v1.schema.json",
        "m25-model-policy-v1.schema.json",
        "m25-candidate-policy-v1.schema.json",
        "m25-provider-request-v1.schema.json",
        "m25-provider-response-v1.schema.json",
        "m25-extraction-receipt-v1.schema.json",
        "m25-recorded-response-set-v1.schema.json",
    }
    paths = [ROOT / "schemas" / name for name in sorted(expected)]
    assert all(path.is_file() for path in paths)
    for path in paths:
        value = load(path)
        assert value["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert value["type"] == "object"
        assert value["additionalProperties"] is False
        assert value["required"]


def test_runtime_has_no_live_provider_or_process_imports() -> None:
    forbidden = {"boto3", "httpx", "requests", "socket", "subprocess", "openai", "anthropic"}
    for path in sorted((ROOT / "src" / "knowledge_engine").glob("m25_extraction_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        observed = {
            node.names[0].name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
        }
        observed.update(
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        )
        assert not (observed & forbidden), (path, observed & forbidden)


def test_provider_registry_permits_recorded_replay_only() -> None:
    value = load(ROOT / "pilot" / "m25" / "m25-3-provider-registry.json")
    assert value["live_provider_calls_permitted"] is False
    assert {provider["mode"] for provider in value["providers"]} == {"recorded_replay"}
    assert all(provider["network_access"] is False for provider in value["providers"])
    assert all(provider["credentials_required"] is False for provider in value["providers"])


def test_authority_envelope_preserves_all_protected_boundaries() -> None:
    value = load(ROOT / "pilot" / "m25" / "m25-3-authority-envelope.json")
    assert value["authority"] == "candidate_only"
    assert value["canonical_knowledge"] is False
    assert value["production_authority"] is False
    for key in (
        "source_mutation_permitted",
        "foundation_mutation_permitted",
        "release_mutation_permitted",
        "production_pointer_mutation_permitted",
        "live_provider_calls_permitted",
        "credentials_permitted",
        "daniel_gate_required",
        "codex_required",
    ):
        assert value[key] is False


def test_documentation_contains_required_stop_lines() -> None:
    text = (ROOT / "docs" / "architecture" / "m25" / "m25-3-extraction-worker.md").read_text()
    for phrase in (
        "recorded-response replay",
        "direct model writes to Source",
        "model output treated as trusted truth",
        "raw private source content",
        "separate Daniel authority decision",
    ):
        assert phrase in text
