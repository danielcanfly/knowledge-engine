from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMPLEMENTATION = ROOT / ".github" / "workflows" / "m26-2-retrieval-envelope.yml"
RECONCILIATION = ROOT / ".github" / "workflows" / "m26-2-reconciliation.yml"

OLD_ALLOWLIST = """          unexpected=\"$(printf '%s\\n' \"$changed\" | grep -Ev '^(\\.github/workflows/m26-2-retrieval-envelope\\.yml|docs/architecture/m26/m26-2-[^/]+\\.md|pilot/m26/m26-2-[^/]+\\.json|schemas/m26-(retrieval-[^/]+|synthetic-corpus-v1)\\.schema\\.json|src/knowledge_engine/m26_retrieval_envelope(_cli)?\\.py|tests/test_m26_2_retrieval_envelope(_contracts)?\\.py)$' || true)\"
"""
NEW_ALLOWLIST = """          unexpected=\"$(printf '%s\\n' \"$changed\" | grep -Ev '^(\\.github/workflows/m26-2-(retrieval-envelope|reconciliation)\\.yml|docs/architecture/m26/m26-2-[^/]+\\.md|pilot/m26/m26-2-[^/]+\\.json|schemas/m26-(retrieval-[^/]+|synthetic-corpus-v1)\\.schema\\.json|src/knowledge_engine/m26_retrieval_envelope(_cli)?\\.py|tests/test_m26_2_(retrieval_envelope(_contracts)?|reconciliation)\\.py)$' || true)\"
"""

OLD_SCOPE = """          expected=\"$(printf '%s\\n' \\
            '.github/workflows/m26-2-reconciliation.yml' \\
            'docs/architecture/m26/m26-2-reconciliation.md' \\
            'pilot/m26/m26-2-acceptance.json' \\
            'tests/test_m26_2_reconciliation.py' | sort)\"
"""
NEW_SCOPE = """          expected=\"$(printf '%s\\n' \\
            '.github/workflows/m26-2-reconciliation.yml' \\
            '.github/workflows/m26-2-retrieval-envelope.yml' \\
            'docs/architecture/m26/m26-2-reconciliation.md' \\
            'pilot/m26/m26-2-acceptance.json' \\
            'tests/test_m26_2_reconciliation.py' | sort)\"
"""


def replace_exact(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise AssertionError(f"expected exactly one replacement target in {path}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    replace_exact(IMPLEMENTATION, OLD_ALLOWLIST, NEW_ALLOWLIST)
    replace_exact(RECONCILIATION, OLD_SCOPE, NEW_SCOPE)


if __name__ == "__main__":
    main()
