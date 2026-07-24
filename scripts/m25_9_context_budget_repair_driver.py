from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import m25_9_context_budget_repair_builder as base

WORKFLOW = Path(".github/workflows/m25-9-blog-full-population-pilot.yml")


def _find(lines: list[str], value: str, *, start: int = 0) -> int:
    for index in range(start, len(lines)):
        if lines[index] == value:
            return index
    raise RuntimeError(f"line not found after {start}: {value!r}")


def _find_prefix(lines: list[str], value: str, *, start: int = 0) -> int:
    for index in range(start, len(lines)):
        if lines[index].startswith(value):
            return index
    raise RuntimeError(f"line prefix not found after {start}: {value!r}")


def _replace_in_range(
    lines: list[str], *, start: int, stop: int, old: str, new: str
) -> None:
    indexes = [index for index in range(start, stop) if lines[index] == old]
    if len(indexes) != 1:
        raise RuntimeError(
            f"expected one line in range {start}:{stop}: {old!r}; "
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
            f"expected one anchor in range {start}:{stop}: {anchor!r}; "
            f"found {len(indexes)}"
        )
    lines.insert(indexes[0] + 1, value)


def repair_module() -> None:
    lines = base.MODULE.read_text().splitlines()

    imports = _find(
        lines, "from collections.abc import Iterable, Mapping, Sequence"
    )
    lines[imports] = "from collections.abc import Mapping, Sequence"

    batch_size = _find(lines, "MAX_BATCH_SIZE = 100")
    constants = [
        "MAX_BATCH_TEXT_CHARACTERS = 16_000",
        "CLOUDFLARE_CONTEXT_ERROR_CODE = 3030",
    ]
    if constants[0] not in lines:
        lines[batch_size + 1 : batch_size + 1] = constants

    provider_start = _find_prefix(lines, "def build_provider_contract(")
    plan_start = _find_prefix(
        lines, "def build_execution_plan(", start=provider_start + 1
    )
    batching_start = _find(
        lines, '        "batching": {', start=provider_start
    )
    if not batching_start < plan_start:
        raise RuntimeError("provider batching block escaped provider contract")
    batching_stop = _find(lines, "        },", start=batching_start + 1)
    lines[batching_start : batching_stop + 1] = [
        '        "batching": {',
        '            "maximum_batch_size": MAX_BATCH_SIZE,',
        '            "maximum_batch_text_characters": MAX_BATCH_TEXT_CHARACTERS,',
        '            "context_limit_split": "recursive-halves",',
        '            "preserve_input_order": True,',
        '            "deterministic": True,',
        "        },",
    ]

    chunks_start = _find_prefix(lines, "def _chunks(")
    validation_start = _find_prefix(
        lines,
        "def validate_qdrant_collection_response(",
        start=chunks_start + 1,
    )
    embedding_code = dedent(
        '''
        def _batches_by_character_budget(
            values: Sequence[SectionInput],
        ) -> list[Sequence[SectionInput]]:
            batches: list[Sequence[SectionInput]] = []
            batch: list[SectionInput] = []
            characters = 0
            for value in values:
                text_characters = len(value.text)
                if batch and (
                    len(batch) >= MAX_BATCH_SIZE
                    or characters + text_characters > MAX_BATCH_TEXT_CHARACTERS
                ):
                    batches.append(tuple(batch))
                    batch = []
                    characters = 0
                batch.append(value)
                characters += text_characters
            if batch:
                batches.append(tuple(batch))
            return batches


        def _is_context_limit_response(response: httpx.Response) -> bool:
            if response.status_code != 400:
                return False
            try:
                payload = response.json()
            except ValueError:
                return False
            if not isinstance(payload, Mapping):
                return False
            errors = payload.get("errors")
            if not isinstance(errors, list):
                return False
            for item in errors:
                if not isinstance(item, Mapping):
                    continue
                if str(item.get("code")) == str(CLOUDFLARE_CONTEXT_ERROR_CODE):
                    return True
                message = item.get("message")
                if isinstance(message, str):
                    lowered = message.lower()
                    if (
                        "max context reached" in lowered
                        and "model supports only" in lowered
                    ):
                        return True
            return False


        def _embed_batch(
            http: httpx.Client,
            *,
            url: str,
            token: str,
            batch: Sequence[SectionInput],
        ) -> list[list[float]]:
            response = http.post(
                url,
                headers={"Authorization": f"Bearer {token}"},
                json=build_cloudflare_request(
                    [section.text for section in batch]
                ),
            )
            if response.is_error:
                if _is_context_limit_response(response) and len(batch) > 1:
                    midpoint = len(batch) // 2
                    return _embed_batch(
                        http,
                        url=url,
                        token=token,
                        batch=batch[:midpoint],
                    ) + _embed_batch(
                        http,
                        url=url,
                        token=token,
                        batch=batch[midpoint:],
                    )
                response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, Mapping):
                raise IntegrityError(
                    "M23-EMBED-120 provider response must be an object"
                )
            return parse_cloudflare_embeddings(
                payload, expected_count=len(batch)
            )


        def embed_sections(
            sections: Sequence[SectionInput],
            config: CloudflareConfig,
            *,
            client: httpx.Client | None = None,
        ) -> list[list[float]]:
            account_id = quote(
                _required_string(config.account_id, "account_id", 100), safe=""
            )
            token = _required_string(config.api_token, "api_token", 10_000)
            model = quote(
                _required_string(config.model, "model", 300), safe="@/"
            )
            url = (
                "https://api.cloudflare.com/client/v4/accounts/"
                f"{account_id}/ai/run/{model}"
            )
            owned_client = client is None
            http = client or httpx.Client(timeout=config.timeout_seconds)
            vectors: list[list[float]] = []
            try:
                for batch in _batches_by_character_budget(list(sections)):
                    vectors.extend(
                        _embed_batch(http, url=url, token=token, batch=batch)
                    )
            finally:
                if owned_client:
                    http.close()
            return vectors
        '''
    ).strip().splitlines()
    lines[chunks_start:validation_start] = embedding_code + ["", ""]

    base.MODULE.write_text("\n".join(lines) + "\n")


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
    repair_module()
    base.repair_tests()
    repair_workflow()
    base.repair_docs()
    for path in base.EXPECTED_PATHS:
        if not Path(path).is_file():
            raise RuntimeError(f"missing repaired path: {path}")


if __name__ == "__main__":
    main()
