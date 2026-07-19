from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts import m23_7_r3_8_remote_operator as base
from scripts import m23_7_r3_8_remote_operator_region_v3 as subject


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://cluster.us-east-1-1.aws.cloud.qdrant.io:6333",
            "aws:us-east-1",
        ),
        (
            "https://cluster.europe-west3-0.gcp.cloud.qdrant.io:6333",
            "gcp:europe-west3",
        ),
        (
            "https://cluster.eastus2-0.azure.cloud.qdrant.io:6333",
            "azure:eastus2",
        ),
    ],
)
def test_derives_region_without_persisting_hostname(url: str, expected: str) -> None:
    assert subject.derive_cloudflare_region(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "http://cluster.us-east-1-1.aws.cloud.qdrant.io:6333",
        "https://cluster.example.com",
        "https://cluster.us-east-1-1.other.cloud.qdrant.io:6333",
        "https://cluster.not-a-region.aws.cloud.qdrant.io:6333",
    ],
)
def test_unresolved_or_unsupported_region_fails_closed(url: str) -> None:
    with pytest.raises(base.RemoteOperatorError):
        subject.derive_cloudflare_region(url)


def test_generated_config_uses_region_hint_and_no_hostname(tmp_path: Path) -> None:
    output = tmp_path / "wrangler.jsonc"
    identity = subject.generate_wrangler_config(
        "https://cluster.us-east-1-1.aws.cloud.qdrant.io:6333",
        "knowledge-engine-r3-8-12345",
        output,
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["placement"] == {"region": "aws:us-east-1"}
    assert "hostname" not in payload["placement"]
    assert "cluster.us-east-1-1.aws.cloud.qdrant.io" not in output.read_text(
        encoding="utf-8"
    )
    assert identity["placement_target_type"] == "region"
    assert identity["placement_region_sha256"] == identity[
        "placement_hostname_sha256"
    ]


def test_receipt_records_region_target_without_region_value() -> None:
    value = {
        "remote_operator": {},
        "receipt_sha256": "0" * 64,
    }
    bounded = subject.normalise_region_receipt(value)
    operator = bounded["remote_operator"]
    assert operator["placement_target_type"] == "region"
    assert operator["placement_region_persisted"] is False
    assert operator["placement_hostname_persisted"] is False
    assert operator["region_contract_sha256"] == subject.REGION_CONTRACT_SHA256
    encoded = json.dumps(bounded)
    assert "aws:us-east-1" not in encoded
    assert "cloud.qdrant.io" not in encoded


def test_adapter_restores_base_functions(monkeypatch: pytest.MonkeyPatch) -> None:
    original_generate = base.generate_wrangler_config
    original_write = base._write_json
    monkeypatch.setattr(subject.placement_v2, "execute", lambda args: 23)
    assert subject.execute(object()) == 23
    assert base.generate_wrangler_config is original_generate
    assert base._write_json is original_write
