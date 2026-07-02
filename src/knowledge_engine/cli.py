from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from .compiler import compile_release
from .config import Settings
from .publisher import publish_release
from .runtime import Runtime
from .source import build_source_release
from .storage import create_object_store


def _utc(value: str | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if not value.endswith("Z"):
        raise argparse.ArgumentTypeError("release time must end in Z")
    return datetime.fromisoformat(value[:-1] + "+00:00")


def _promoted_at(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def main() -> int:
    parser = argparse.ArgumentParser(prog="knowledge-engine")
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser("build")
    build.add_argument("--bundle", type=Path, required=True)
    build.add_argument("--channel", default=None)
    build.add_argument("--release-time")
    build.add_argument("--source-repository", default="danielcanfly/knowledge-source")
    build.add_argument("--source-sha", default="a" * 40)
    build.add_argument("--foundation-sha", default="d" * 40)
    build.add_argument("--work-dir", type=Path, default=Path(".artifacts/builds"))

    build_source = commands.add_parser("build-source")
    build_source.add_argument("--source-url", required=True)
    build_source.add_argument(
        "--source-repository", default="danielcanfly/knowledge-source"
    )
    build_source.add_argument("--source-sha", required=True)
    build_source.add_argument("--foundation-sha", required=True)
    build_source.add_argument("--channel", default="candidate")
    build_source.add_argument("--release-time")
    build_source.add_argument(
        "--work-dir", type=Path, default=Path(".artifacts/source-builds")
    )

    query = commands.add_parser("query")
    query.add_argument("--channel", default=None)
    query.add_argument("--query", required=True)
    query.add_argument("--audiences", default="public,internal")
    query.add_argument("--limit", type=int, default=10)

    refresh = commands.add_parser("refresh")
    refresh.add_argument("--channel", default=None)

    args = parser.parse_args()
    settings = Settings.from_env()
    store = create_object_store(settings)

    if args.command == "build":
        release_time = _utc(args.release_time)
        compiled = compile_release(
            bundle_root=args.bundle,
            work_root=args.work_dir,
            release_time=release_time,
            source_repository=args.source_repository,
            source_commit_sha=args.source_sha,
            foundation_commit_sha=args.foundation_sha,
        )
        result = publish_release(
            store=store,
            compiled=compiled,
            channel=args.channel or settings.channel,
            promoted_at=_promoted_at(release_time),
        )
        print(json.dumps(result.__dict__, indent=2, sort_keys=True))
        return 0

    if args.command == "build-source":
        if args.channel == "production":
            parser.error("build-source cannot promote production directly")
        release_time = _utc(args.release_time)
        compiled, snapshot = build_source_release(
            repository_url=args.source_url,
            repository=args.source_repository,
            source_commit_sha=args.source_sha,
            foundation_commit_sha=args.foundation_sha,
            work_root=args.work_dir,
            release_time=release_time,
        )
        result = publish_release(
            store=store,
            compiled=compiled,
            channel=args.channel,
            promoted_at=_promoted_at(release_time),
        )
        print(
            json.dumps(
                {
                    **result.__dict__,
                    "source_repository": args.source_repository,
                    "source_sha": args.source_sha,
                    "foundation_sha": args.foundation_sha,
                    "source_snapshot_sha256": snapshot["content_sha256"],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    runtime = Runtime(
        store,
        settings.cache_dir,
        args.channel or settings.channel,
    )
    if args.command == "refresh":
        active = runtime.refresh()
        print(
            json.dumps(
                {
                    "release_id": active.release_id,
                    "manifest_sha256": active.manifest_sha256,
                    "loaded_at": active.loaded_at,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    audiences = {item.strip() for item in args.audiences.split(",") if item.strip()}
    print(
        json.dumps(
            runtime.query(args.query, audiences, limit=args.limit),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
