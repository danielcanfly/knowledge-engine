from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import m23_7_r3_8_deploy_target as subject

WORKER = "knowledge-engine-m23-7-r3-8-latency"
VALID_TARGET = f"https://{WORKER}.daniel-lab.workers.dev"


def _write(path: Path, records: list[object]) -> None:
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )


def _deploy_record(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "type": "deploy",
        "version": 1,
        "worker_name": WORKER,
        "worker_tag": "tag",
        "version_id": "version-1",
        "targets": [VALID_TARGET],
        "worker_name_overridden": False,
        "wrangler_environment": None,
    }
    record.update(overrides)
    return record


def test_parses_one_exact_workers_dev_target(tmp_path: Path) -> None:
    output = tmp_path / "wrangler-output.jsonl"
    _write(
        output,
        [
            {"type": "wrangler-session", "version": 1},
            _deploy_record(),
        ],
    )

    assert subject.parse_deploy_target(output, WORKER) == VALID_TARGET


@pytest.mark.parametrize(
    "records",
    (
        [],
        [_deploy_record(), _deploy_record(version_id="version-2")],
        [_deploy_record(worker_name="other-worker")],
        [_deploy_record(worker_name_overridden=True)],
        [_deploy_record(version=2)],
        [_deploy_record(version_id=None)],
        [_deploy_record(targets=[])],
        [_deploy_record(targets=[VALID_TARGET, "https://other.example.com"])],
        [_deploy_record(targets=["https://example.com"])],
        [_deploy_record(targets=[f"http://{WORKER}.daniel-lab.workers.dev"])],
        [_deploy_record(targets=[f"https://user@{WORKER}.daniel-lab.workers.dev"])],
        [_deploy_record(targets=[f"https://{WORKER}.daniel-lab.workers.dev/path"])],
        [_deploy_record(targets=[f"https://{WORKER}.daniel-lab.workers.dev?x=1"])],
        [_deploy_record(targets=[f"https://{WORKER}.foo.bar.workers.dev"])],
    ),
)
def test_rejects_ambiguous_or_noncanonical_targets(
    tmp_path: Path,
    records: list[object],
) -> None:
    output = tmp_path / "wrangler-output.jsonl"
    _write(output, records)

    with pytest.raises(subject.DeployTargetError):
        subject.parse_deploy_target(output, WORKER)


def test_rejects_missing_and_malformed_output(tmp_path: Path) -> None:
    with pytest.raises(subject.DeployTargetError, match="missing"):
        subject.parse_deploy_target(tmp_path / "missing.jsonl", WORKER)

    malformed = tmp_path / "malformed.jsonl"
    malformed.write_text("{not-json}\n", encoding="utf-8")
    with pytest.raises(subject.DeployTargetError, match="malformed"):
        subject.parse_deploy_target(malformed, WORKER)


def test_rejects_oversized_output(tmp_path: Path) -> None:
    output = tmp_path / "oversized.jsonl"
    output.write_text("x" * (subject.MAX_OUTPUT_BYTES + 1), encoding="utf-8")

    with pytest.raises(subject.DeployTargetError, match="size"):
        subject.parse_deploy_target(output, WORKER)


@pytest.mark.parametrize(
    "worker_name",
    (
        "Worker With Spaces",
        "../worker",
        "worker;touch-pwned",
        "$(touch-pwned)",
    ),
)
def test_rejects_invalid_worker_name(tmp_path: Path, worker_name: str) -> None:
    output = tmp_path / "wrangler-output.jsonl"
    _write(output, [_deploy_record()])

    with pytest.raises(subject.DeployTargetError, match="Worker name"):
        subject.parse_deploy_target(output, worker_name)
