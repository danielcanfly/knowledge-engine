from __future__ import annotations

from scripts import m23_7_r3_8_remote_recovery_probe as base

AUTHORIZED_RUN_ID = "29636761264"
AUTHORIZED_ENGINE_SHA = "fc1dca7186fa66db153489a90a7b369ca053db61"
AUTHORIZED_WORKER_NAME = "knowledge-engine-r3-8-29636761264"


def authorized_identity() -> dict[str, str]:
    return {
        "engine_sha": AUTHORIZED_ENGINE_SHA,
        "worker_name": AUTHORIZED_WORKER_NAME,
    }


def main(argv: list[str] | None = None) -> int:
    base.AUTHORIZED_RUNS[AUTHORIZED_RUN_ID] = authorized_identity()
    return base.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
