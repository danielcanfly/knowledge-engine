from __future__ import annotations

from pathlib import Path

import m25_9_context_budget_repair_builder as base


WORKFLOW = Path(".github/workflows/m25-9-blog-full-population-pilot.yml")


def _find(lines: list[str], value: str, *, start: int = 0) -> int:
    for index in range(start, len(lines)):
        if lines[index] == value:
            return index
    raise RuntimeError(f"workflow line not found after {start}: {value!r}")


def _replace_in_range(
    lines: list[str], *, start: int, stop: int, old: str, new: str
) -> None:
    indexes = [index for index in range(start, stop) if lines[index] == old]
    if len(indexes) != 1:
        raise RuntimeError(
            f"expected one workflow line in range {start}:{stop}: {old!r}; "
            f"found {len(indexes)}"
        )
    lines[indexes[0]] = new


def _insert_after_in_range(
    lines: list[str], *, start: int, stop: int, anchor: str, value: str
) -> None:
    if value in lines[start:stop]:
        return
    indexes = [index for index in range(start, stop) if lines[index] == anchor]
    if len(indexes) != 1:
        raise RuntimeError(
            f"expected one workflow anchor in range {start}:{stop}: {anchor!r}; "
            f"found {len(indexes)}"
        )
    lines.insert(indexes[0] + 1, value)


def repair_workflow() -> None:
    lines = WORKFLOW.read_text().splitlines()

    pull_start = _find(lines, "  pull_request:")
    push_start = _find(lines, "  push:", start=pull_start + 1)
    _replace_in_range(
        lines,
        start=pull_start,
        stop=push_start,
        old="      - 'scripts/m25_9_cloudflare_live_preflight.py'",
        new="      - 'src/knowledge_engine/m23_cloudflare_qdrant.py'",
    )
    _replace_in_range(
        lines,
        start=pull_start,
        stop=push_start,
        old="      - 'tests/test_m25_9_cloudflare_live_preflight.py'",
        new="      - 'tests/test_m23_5_cloudflare_qdrant.py'",
    )

    ruff_start = _find(
        lines, "          python -m ruff check --output-format=concise \\", start=push_start
    )
    pytest_start = _find(lines, "          python -m pytest -q \\", start=ruff_start)
    _insert_after_in_range(
        lines,
        start=ruff_start,
        stop=pytest_start,
        anchor="            scripts/m25_9_cloudflare_live_preflight.py \\",
        value="            src/knowledge_engine/m23_cloudflare_qdrant.py \\",
    )
    pytest_start = _find(lines, "          python -m pytest -q \\", start=ruff_start)
    _insert_after_in_range(
        lines,
        start=ruff_start,
        stop=pytest_start,
        anchor="            src/knowledge_engine/m25_blog_live_candidate.py \\",
        value="            tests/test_m23_5_cloudflare_qdrant.py \\",
    )

    pytest_start = _find(lines, "          python -m pytest -q \\", start=ruff_start)
    compile_start = _find(lines, "          python -m compileall -q \\", start=pytest_start)
    _insert_after_in_range(
        lines,
        start=pytest_start,
        stop=compile_start,
        anchor="            tests/test_m25_9_cloudflare_live_preflight.py \\",
        value="            tests/test_m23_5_cloudflare_qdrant.py \\",
    )

    compile_start = _find(lines, "          python -m compileall -q \\", start=pytest_start)
    typecheck_start = _find(lines, "      - name: Type-check candidate Worker", start=compile_start)
    _insert_after_in_range(
        lines,
        start=compile_start,
        stop=typecheck_start,
        anchor="            scripts/m25_9_cloudflare_live_preflight.py \\",
        value="            src/knowledge_engine/m23_cloudflare_qdrant.py \\",
    )
    typecheck_start = _find(lines, "      - name: Type-check candidate Worker", start=compile_start)
    _insert_after_in_range(
        lines,
        start=compile_start,
        stop=typecheck_start,
        anchor="            src/knowledge_engine/m25_blog_live_candidate.py \\",
        value="            tests/test_m23_5_cloudflare_qdrant.py \\",
    )

    boundary_start = _find(
        lines, "      - name: Enforce exact repair changed-file boundary"
    )
    expected_start = _find(
        lines, "          expected=\"$(printf '%s\\n' \\", start=boundary_start
    )
    expected_stop = next(
        index
        for index in range(expected_start + 1, len(lines))
        if lines[index].endswith("| sort)\"")
    )
    lines[expected_start + 1 : expected_stop + 1] = [
        "            '.github/workflows/m25-9-blog-full-population-pilot.yml' \\",
        "            'docs/architecture/m25/m25-9-live-preflight-repair.md' \\",
        "            'src/knowledge_engine/m23_cloudflare_qdrant.py' \\",
        "            'tests/test_m23_5_cloudflare_qdrant.py' | sort)\"",
    ]

    WORKFLOW.write_text("\n".join(lines) + "\n")


def main() -> None:
    base.repair_module()
    base.repair_tests()
    repair_workflow()
    base.repair_docs()
    for path in base.EXPECTED_PATHS:
        if not Path(path).is_file():
            raise RuntimeError(f"missing repaired path: {path}")


if __name__ == "__main__":
    main()
