from __future__ import annotations

from pathlib import Path


SOURCE = Path(__file__).with_name("m26_phase3a_reviewer_shadow.py")
FROZEN_LITERAL = 'CANDIDATE_REVIEWER_MODEL = "MiniMax-M2.7-highspeed"'
CANDIDATE_LITERAL = 'CANDIDATE_REVIEWER_MODEL = "MiniMax-M2.1-highspeed"'


def main() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    if source.count(FROZEN_LITERAL) != 1:
        raise SystemExit("Phase 3A reviewer-shadow source drift")
    candidate_source = source.replace(FROZEN_LITERAL, CANDIDATE_LITERAL, 1)
    namespace = {
        "__name__": "__main__",
        "__file__": str(SOURCE),
        "__package__": None,
    }
    exec(compile(candidate_source, str(SOURCE), "exec"), namespace, namespace)


if __name__ == "__main__":
    main()
