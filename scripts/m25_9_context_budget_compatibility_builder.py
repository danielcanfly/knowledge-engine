from __future__ import annotations

from pathlib import Path

import m25_9_context_budget_repair_driver as base


MODULE = Path("src/knowledge_engine/m23_cloudflare_qdrant.py")


def replace_once(old: str, new: str) -> None:
    text = MODULE.read_text()
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one compatibility replacement, found {count}")
    MODULE.write_text(text.replace(old, new, 1))


def main() -> None:
    base.main()
    replace_once(
        '    if response.status_code != 400:\n',
        '    if getattr(response, "status_code", None) != 400:\n',
    )
    replace_once(
        '''    if response.is_error:
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
''',
        '''    if _is_context_limit_response(response) and len(batch) > 1:
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
''',
    )


if __name__ == "__main__":
    main()
