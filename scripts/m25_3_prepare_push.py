from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAFFOLD = [
    ".github/workflows/m25-3-bootstrap.yml",
    "scripts/m25_3_materialize.py",
    "scripts/m25_3_payload_00.hex",
    "scripts/m25_3_payload_01.hex",
    "scripts/m25_3_payload_02.hex",
    "scripts/m25_3_payload_03.hex",
    "scripts/m25_3_payload_04.hex",
    "scripts/m25_3_prepare_push.py",
]


def main() -> None:
    subprocess.run(
        ["git", "restore", "--source=HEAD", "--", *SCAFFOLD],
        cwd=ROOT,
        check=True,
    )
    (ROOT / ".github" / "workflows" / "m25-3-extraction-worker.yml").unlink(
        missing_ok=True
    )


if __name__ == "__main__":
    main()
