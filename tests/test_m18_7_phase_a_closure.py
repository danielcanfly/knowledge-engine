from __future__ import annotations

import copy
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from knowledge_engine.compiler import compile_release
from knowledge_engine.errors import IntegrityError
from knowledge_engine.m18_phase_a_closure import (
    REQUIRED_FAIL_CLOSED_CASES,
    evaluate_phase_a_closure,
    validate_phase_a_closure,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RECORD_PATH = REPOSITORY_ROOT / "docs/architecture/m18/m18-7-phase-a-closure.json"


def _record() -> dict:
    return json.loads(RECORD_PATH.read_text(encoding="utf-8"))


def test_phase_a_closure_record_is_complete_and_deterministic() -> None:
    record = _record()
    first = evaluate_phase_a_closure(record, repository_root=REPOSITORY_ROOT)
    second = evaluate_phase_a_closure(record, repository_root=REPOSITORY_ROOT)
    assert first == second
    assert first["status"] == "ready_for_reconciliation"
    assert first["fail_closed_case_count"] == 14
    assert first["completed_submilestones"] == [
        "M18.1",
        "M18.2",
        "M18.3",
        "M18.4",
        "M18.5",
        "M18.6",
    ]
    assert first["production_mutation_dispatched"] is False
    assert first["m19_started"] is False


def test_phase_a_closure_maps_every_fail_closed_case_to_tests() -> None:
    record = _record()
    assert set(record["fail_closed_coverage"]) == REQUIRED_FAIL_CLOSED_CASES
    source_prefix = (
        "danielcanfly/knowledge-source@"
        f"{record['source_acceptance']['head_sha']}:tests/"
    )
    assert all(
        path.startswith(source_prefix) or (REPOSITORY_ROOT / path).is_file()
        for path in record["fail_closed_coverage"].values()
    )


@pytest.mark.parametrize(
    ("body", "match"),
    [
        ("[Missing](does-not-exist.md)\n", "broken internal link"),
        ("[[concepts/compiler]]\n", "wikilink remains"),
    ],
)
def test_release_links_fail_closed(tmp_path: Path, body: str, match: str) -> None:
    bundle = tmp_path / "bundle"
    shutil.copytree(REPOSITORY_ROOT / "examples/okf-bundle", bundle)
    index = bundle / "index.md"
    index.write_text(index.read_text(encoding="utf-8") + body, encoding="utf-8")
    with pytest.raises(IntegrityError, match=match):
        compile_release(
            bundle_root=bundle,
            work_root=tmp_path / "build",
            release_time=datetime(2026, 7, 13, tzinfo=UTC),
            source_repository="danielcanfly/knowledge-source",
            source_commit_sha="a" * 40,
            foundation_commit_sha="b" * 40,
        )


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (lambda item: item["repositories"].update(source="short"), "full lowercase"),
        (
            lambda item: item["completed_submilestones"].pop(),
            "M18.1 through M18.6",
        ),
        (
            lambda item: item["completed_submilestones"][0].update(status="pending"),
            "M18.1 is not complete",
        ),
        (
            lambda item: item["source_acceptance"]["exact_head_workflows"][0].update(
                conclusion="failure"
            ),
            "every Source exact-head workflow",
        ),
        (
            lambda item: item["source_acceptance"]["changed_files"].append("concepts/x.md"),
            "changed-file scope",
        ),
        (
            lambda item: item["fail_closed_coverage"].pop("missing_target"),
            "fail-closed coverage",
        ),
        (
            lambda item: item["runtime"].update(relation_aware_expansion_default=True),
            "Runtime compatibility",
        ),
        (
            lambda item: item["mutation"].update(production_pointer=True),
            "protected state",
        ),
        (
            lambda item: item["forbidden"].update(graph_neural_retrieval=True),
            "forbidden M18 behavior",
        ),
        (lambda item: item.update(m19_started=True), "M19 must not start"),
    ],
)
def test_phase_a_closure_fails_closed(mutation, match: str) -> None:
    record = copy.deepcopy(_record())
    mutation(record)
    with pytest.raises(IntegrityError, match=match):
        validate_phase_a_closure(record, repository_root=REPOSITORY_ROOT)
