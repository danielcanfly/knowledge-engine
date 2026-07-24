from __future__ import annotations

from pathlib import Path
from textwrap import dedent


MODULE = Path("src/knowledge_engine/m23_cloudflare_qdrant.py")
TESTS = Path("tests/test_m23_5_cloudflare_qdrant.py")
WORKFLOW = Path(".github/workflows/m25-9-blog-full-population-pilot.yml")
DOCS = Path("docs/architecture/m25/m25-9-live-preflight-repair.md")
EXPECTED_PATHS = (
    WORKFLOW.as_posix(),
    DOCS.as_posix(),
    MODULE.as_posix(),
    TESTS.as_posix(),
)


def block(value: str) -> str:
    return dedent(value).lstrip("\n")


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one exact replacement, found {count}")
    path.write_text(text.replace(old, new, 1))


def repair_module() -> None:
    replace_once(
        MODULE,
        "MAX_BATCH_SIZE = 100\n",
        "MAX_BATCH_SIZE = 100\n"
        "MAX_BATCH_TEXT_CHARACTERS = 16_000\n"
        "CLOUDFLARE_CONTEXT_ERROR_CODE = 3030\n",
    )
    replace_once(
        MODULE,
        block(
            '''
            "batching": {
                "batch_size": MAX_BATCH_SIZE,
                "preserve_input_order": True,
                "deterministic": True,
            },
            '''
        ),
        block(
            '''
            "batching": {
                "maximum_batch_size": MAX_BATCH_SIZE,
                "maximum_batch_text_characters": MAX_BATCH_TEXT_CHARACTERS,
                "context_limit_split": "recursive-halves",
                "preserve_input_order": True,
                "deterministic": True,
            },
            '''
        ),
    )
    replace_once(
        MODULE,
        block(
            '''
            def _chunks(
                values: Sequence[SectionInput], size: int
            ) -> Iterable[Sequence[SectionInput]]:
                for start in range(0, len(values), size):
                    yield values[start : start + size]


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
                    for batch in _chunks(list(sections), MAX_BATCH_SIZE):
                        response = http.post(
                            url,
                            headers={"Authorization": f"Bearer {token}"},
                            json=build_cloudflare_request(
                                [section.text for section in batch]
                            ),
                        )
                        response.raise_for_status()
                        payload = response.json()
                        if not isinstance(payload, Mapping):
                            raise IntegrityError(
                                "M23-EMBED-120 provider response must be an object"
                            )
                        vectors.extend(
                            parse_cloudflare_embeddings(
                                payload, expected_count=len(batch)
                            )
                        )
                finally:
                    if owned_client:
                        http.close()
                return vectors
            '''
        ),
        block(
            '''
            def _batches_by_character_budget(
                values: Sequence[SectionInput],
            ) -> Iterable[Sequence[SectionInput]]:
                batch: list[SectionInput] = []
                characters = 0
                for value in values:
                    text_characters = len(value.text)
                    if batch and (
                        len(batch) >= MAX_BATCH_SIZE
                        or characters + text_characters > MAX_BATCH_TEXT_CHARACTERS
                    ):
                        yield tuple(batch)
                        batch = []
                        characters = 0
                    batch.append(value)
                    characters += text_characters
                if batch:
                    yield tuple(batch)


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
                    if item.get("code") == CLOUDFLARE_CONTEXT_ERROR_CODE:
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
        ),
    )


def repair_tests() -> None:
    text = TESTS.read_text()
    if "def _sections_with_texts(texts: list[str]):" in text:
        raise RuntimeError("focused context-budget tests already exist")
    addition = block(
        '''

        def _sections_with_texts(texts: list[str]):
            return validate_sections(
                [
                    {
                        "section_id": f"budget-doc-{index}#0001",
                        "text": text,
                        "payload": {"document_id": f"budget-doc-{index}"},
                    }
                    for index, text in enumerate(texts)
                ]
            )


        def test_cloudflare_batches_preserve_full_text_under_character_budget():
            texts = ["A" * 9000, "B" * 9000, "C" * 100]
            observed_batches = []

            def handler(request: httpx.Request) -> httpx.Response:
                selected = json.loads(request.content)["text"]
                observed_batches.append(selected)
                return httpx.Response(
                    200,
                    json={
                        "success": True,
                        "result": {"data": _vectors(len(selected))},
                    },
                )

            with httpx.Client(transport=httpx.MockTransport(handler)) as client:
                vectors = embed_sections(
                    _sections_with_texts(texts),
                    CloudflareConfig(account_id="account", api_token="secret"),
                    client=client,
                )

            assert len(vectors) == 3
            assert [len(batch) for batch in observed_batches] == [1, 2]
            assert [text for batch in observed_batches for text in batch] == texts


        def test_cloudflare_context_limit_recursively_splits_and_preserves_order():
            texts = ["one", "two", "three", "four"]
            observed_batches = []

            def handler(request: httpx.Request) -> httpx.Response:
                selected = json.loads(request.content)["text"]
                observed_batches.append(selected)
                if len(selected) > 1:
                    return httpx.Response(
                        400,
                        json={
                            "success": False,
                            "errors": [
                                {
                                    "code": 3030,
                                    "message": (
                                        "AiError: Max context reached 80825 tokens "
                                        "but model supports only 60000"
                                    ),
                                }
                            ],
                        },
                    )
                return httpx.Response(
                    200,
                    json={"success": True, "result": {"data": _vectors(1)}},
                )

            with httpx.Client(transport=httpx.MockTransport(handler)) as client:
                vectors = embed_sections(
                    _sections_with_texts(texts),
                    CloudflareConfig(account_id="account", api_token="secret"),
                    client=client,
                )

            assert len(vectors) == 4
            assert [len(batch) for batch in observed_batches] == [
                4,
                2,
                1,
                1,
                2,
                1,
                1,
            ]
            assert [
                batch[0] for batch in observed_batches if len(batch) == 1
            ] == texts


        def test_cloudflare_non_context_http_error_remains_fail_closed():
            calls = []

            def handler(request: httpx.Request) -> httpx.Response:
                calls.append(json.loads(request.content)["text"])
                return httpx.Response(
                    400,
                    json={
                        "success": False,
                        "errors": [
                            {"code": 10000, "message": "permission denied"}
                        ],
                    },
                )

            with httpx.Client(transport=httpx.MockTransport(handler)) as client:
                with pytest.raises(httpx.HTTPStatusError):
                    embed_sections(
                        _sections(),
                        CloudflareConfig(
                            account_id="account", api_token="secret"
                        ),
                        client=client,
                    )
            assert len(calls) == 1
        '''
    )
    TESTS.write_text(text.rstrip() + "\n" + addition + "\n")


def repair_workflow() -> None:
    replace_once(
        WORKFLOW,
        block(
            '''
            pull_request:
              paths:
                - '.github/workflows/m25-9-blog-full-population-pilot.yml'
                - 'docs/architecture/m25/m25-9-live-preflight-repair.md'
                - 'scripts/m25_9_cloudflare_live_preflight.py'
                - 'tests/test_m25_9_cloudflare_live_preflight.py'
            '''
        ),
        block(
            '''
            pull_request:
              paths:
                - '.github/workflows/m25-9-blog-full-population-pilot.yml'
                - 'docs/architecture/m25/m25-9-live-preflight-repair.md'
                - 'src/knowledge_engine/m23_cloudflare_qdrant.py'
                - 'tests/test_m23_5_cloudflare_qdrant.py'
            '''
        ),
    )
    replace_once(
        WORKFLOW,
        block(
            '''
                    python -m ruff check --output-format=concise \\
                      scripts/m25_9_cloudflare_live_preflight.py \\
                      src/knowledge_engine/m25_blog_live_candidate.py \\
                      tests/test_m25_9_cloudflare_live_preflight.py \\
                      tests/test_m25_10_blog_live_candidate.py
            '''
        ),
        block(
            '''
                    python -m ruff check --output-format=concise \\
                      scripts/m25_9_cloudflare_live_preflight.py \\
                      src/knowledge_engine/m23_cloudflare_qdrant.py \\
                      src/knowledge_engine/m25_blog_live_candidate.py \\
                      tests/test_m23_5_cloudflare_qdrant.py \\
                      tests/test_m25_9_cloudflare_live_preflight.py \\
                      tests/test_m25_10_blog_live_candidate.py
            '''
        ),
    )
    replace_once(
        WORKFLOW,
        block(
            '''
                    python -m pytest -q \\
                      tests/test_m25_9_cloudflare_live_preflight.py \\
            '''
        ),
        block(
            '''
                    python -m pytest -q \\
                      tests/test_m23_5_cloudflare_qdrant.py \\
                      tests/test_m25_9_cloudflare_live_preflight.py \\
            '''
        ),
    )
    replace_once(
        WORKFLOW,
        block(
            '''
                    python -m compileall -q \\
                      scripts/m25_9_cloudflare_live_preflight.py \\
                      src/knowledge_engine/m25_blog_live_candidate.py \\
                      tests/test_m25_9_cloudflare_live_preflight.py \\
                      tests/test_m25_10_blog_live_candidate.py
            '''
        ),
        block(
            '''
                    python -m compileall -q \\
                      scripts/m25_9_cloudflare_live_preflight.py \\
                      src/knowledge_engine/m23_cloudflare_qdrant.py \\
                      src/knowledge_engine/m25_blog_live_candidate.py \\
                      tests/test_m23_5_cloudflare_qdrant.py \\
                      tests/test_m25_9_cloudflare_live_preflight.py \\
                      tests/test_m25_10_blog_live_candidate.py
            '''
        ),
    )
    replace_once(
        WORKFLOW,
        block(
            '''
                    expected="$(printf '%s\\n' \\
                      '.github/workflows/m25-9-blog-full-population-pilot.yml' \\
                      'docs/architecture/m25/m25-9-live-preflight-repair.md' \\
                      'scripts/m25_9_cloudflare_live_preflight.py' \\
                      'tests/test_m25_9_cloudflare_live_preflight.py' | sort)"
            '''
        ),
        block(
            '''
                    expected="$(printf '%s\\n' \\
                      '.github/workflows/m25-9-blog-full-population-pilot.yml' \\
                      'docs/architecture/m25/m25-9-live-preflight-repair.md' \\
                      'src/knowledge_engine/m23_cloudflare_qdrant.py' \\
                      'tests/test_m23_5_cloudflare_qdrant.py' | sort)"
            '''
        ),
    )


def repair_docs() -> None:
    text = DOCS.read_text()
    if "## BGE-M3 context-budget repair authority" in text:
        raise RuntimeError("context-budget authority already documented")
    section = block(
        '''

        ## BGE-M3 context-budget repair authority

        Full-population inference-only scan run `30065403198` at exact SHA
        `eeaecfdfd95d6113b9d75013ccea47a3a829113b` scanned 3,975 semantic
        documents before isolating batch indexes `3950..3974`. Cloudflare returned
        HTTP `400`, code `3030`: the 25 complete inputs required 80,825 tokens while
        the managed BGE-M3 context supports 60,000. Every input in that batch passed
        individually. The scan performed zero Qdrant, R2, deployment, production
        pointer or public-traffic mutations.

        The repair preserves every admitted input without truncation. Deterministic
        initial batches are bounded by both 100 inputs and 16,000 normalized text
        characters. If Cloudflare still reports the explicit context-limit condition,
        only that batch is split into ordered halves recursively. All unrelated HTTP
        errors remain terminal, and a single-input context failure remains terminal.
        '''
    )
    DOCS.write_text(text.rstrip() + "\n" + section + "\n")


def main() -> None:
    repair_module()
    repair_tests()
    repair_workflow()
    repair_docs()
    for path in EXPECTED_PATHS:
        if not Path(path).is_file():
            raise RuntimeError(f"missing repaired path: {path}")


if __name__ == "__main__":
    main()
