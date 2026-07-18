from __future__ import annotations

from scripts import m23_7_r3_8_remote_recovery_probe as base

AUTHORIZED_RUN_ID = "29646853002"
AUTHORIZED_ENGINE_SHA = "a5fca48683567b48a196e67657bd7dc4a4b9c554"
AUTHORIZED_WORKER_NAME = "knowledge-engine-r3-8-29646853002"


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
