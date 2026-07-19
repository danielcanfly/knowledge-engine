from __future__ import annotations

from scripts import m23_7_r3_8_remote_recovery_probe as base

AUTHORIZED_RUN_ID = "29667556969"
AUTHORIZED_ENGINE_SHA = "d0459fee41f747fb79cd32feaa673ef6fcf9e58a"
AUTHORIZED_WORKER_NAME = "knowledge-engine-r3-8-29667556969"


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
