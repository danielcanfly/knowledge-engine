from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace(relative: str, old: str, new: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"forward-compat repair anchor missing: {relative}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    replace(
        "src/knowledge_engine/m25_intake_adapters.py",
        "from pathlib import Path\n\nfrom .intake_v1 import (",
        "from pathlib import Path\nfrom typing import Any\n\nfrom .errors import IntegrityError\nfrom .intake_v1 import (",
    )
    replace(
        "src/knowledge_engine/m25_intake_persistence.py",
        "        except ReleaseConflictError:\n            current = store.head(head_key)\n            if current is None:\n                raise IntegrityError(\"M25-INTAKE-143 checkpoint head disappeared\")",
        "        except ReleaseConflictError as exc:\n            current = store.head(head_key)\n            if current is None:\n                raise IntegrityError(\"M25-INTAKE-143 checkpoint head disappeared\") from exc",
    )
    replace(
        "src/knowledge_engine/m25_intake_state.py",
        "    _parse_time,\n    _signed,\n)",
        "    _parse_time,\n)",
    )
    replace(
        "tests/test_m25_2_intake_orchestrator_contracts.py",
        "    first = resume_orchestrator(\n",
        "    resume_orchestrator(\n",
    )
    paths = [
        "src/knowledge_engine/m25_intake_adapters.py",
        "src/knowledge_engine/m25_intake_batch.py",
        "src/knowledge_engine/m25_intake_compat.py",
        "src/knowledge_engine/m25_intake_inventory.py",
        "src/knowledge_engine/m25_intake_orchestrator.py",
        "src/knowledge_engine/m25_intake_persistence.py",
        "src/knowledge_engine/m25_intake_registry.py",
        "src/knowledge_engine/m25_intake_state.py",
        "tests/test_m25_2_intake_orchestrator.py",
        "tests/test_m25_2_intake_orchestrator_contracts.py",
    ]
    subprocess.run(
        ["python", "-m", "ruff", "check", "--fix", *paths],
        cwd=ROOT,
        check=True,
    )
    Path(__file__).unlink()


if __name__ == "__main__":
    main()
