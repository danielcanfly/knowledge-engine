from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from .candidate import run_source_candidate_gate
from .compiler import compile_release
from .config import Settings
from .ledger import build_production_ledger_comment
from .promotion import (
    PromotionRequest,
    promote_release,
    rollback_release,
    verify_already_promoted,
    verify_promotion_candidate,
)
from .promotion_request import (
    load_promotion_request_spec,
    write_github_env,
    write_request_evidence,
)
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


def _add_promotion_request_args(command: argparse.ArgumentParser) -> None:
    command.add_argument("--operation-id", required=True)
    command.add_argument("--candidate-channel", required=True)
    command.add_argument("--release-id", required=True)
    command.add_argument("--manifest-sha256", required=True)
    command.add_argument(
        "--source-repository", default="danielcanfly/knowledge-source"
    )
    command.add_argument("--source-sha", required=True)
    command.add_argument("--builder-sha", required=True)
    command.add_argument("--foundation-sha", required=True)
    command.add_argument("--expected-previous-release-id", required=True)
    command.add_argument("--expected-previous-manifest-sha256", required=True)
    command.add_argument("--control-plane-sha", required=True)
    command.add_argument("--reason", required=True)
    command.add_argument("--actor", required=True)


def _promotion_request_from_args(args: argparse.Namespace) -> PromotionRequest:
    return PromotionRequest(
        operation_id=args.operation_id,
        candidate_channel=args.candidate_channel,
        expected_release_id=args.release_id,
        expected_manifest_sha256=args.manifest_sha256,
        expected_source_repository=args.source_repository,
        expected_source_sha=args.source_sha,
        expected_builder_sha=args.builder_sha,
        expected_foundation_sha=args.foundation_sha,
        expected_previous_release_id=args.expected_previous_release_id,
        expected_previous_manifest_sha256=(
            args.expected_previous_manifest_sha256
        ),
        control_plane_sha=args.control_plane_sha,
        reason=args.reason,
        actor=args.actor,
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

    gate_source = commands.add_parser("gate-source-candidate")
    gate_source.add_argument("--source-url", required=True)
    gate_source.add_argument(
        "--source-repository", default="danielcanfly/knowledge-source"
    )
    gate_source.add_argument("--source-sha", required=True)
    gate_source.add_argument("--foundation-sha", required=True)
    gate_source.add_argument("--channel", required=True)
    gate_source.add_argument("--release-time", required=True)
    gate_source.add_argument("--query", required=True)
    gate_source.add_argument(
        "--work-dir", type=Path, default=Path(".artifacts/candidate-gates")
    )

    promote = commands.add_parser("promote-release")
    _add_promotion_request_args(promote)
    promote.add_argument("--promoted-at")

    verify_candidate = commands.add_parser("verify-promotion-candidate")
    _add_promotion_request_args(verify_candidate)

    verify_replay = commands.add_parser("verify-already-promoted")
    _add_promotion_request_args(verify_replay)

    render_ledger = commands.add_parser("render-production-ledger")
    render_ledger.add_argument("--evidence-dir", type=Path, required=True)
    render_ledger.add_argument("--run-id", required=True)
    render_ledger.add_argument("--run-url", required=True)
    render_ledger.add_argument("--workflow-name", required=True)
    render_ledger.add_argument("--event-name", required=True)
    render_ledger.add_argument("--head-sha", required=True)
    render_ledger.add_argument("--output", type=Path, required=True)

    validate_promotion = commands.add_parser("validate-promotion-request")
    validate_promotion.add_argument("--request-path", type=Path, required=True)
    validate_promotion.add_argument("--control-plane-sha", required=True)
    validate_promotion.add_argument("--github-env", type=Path)
    validate_promotion.add_argument(
        "--evidence-dir",
        type=Path,
        default=Path("evidence"),
    )

    rollback = commands.add_parser("rollback-release")
    rollback.add_argument("--operation-id", required=True)
    rollback.add_argument("--reason", required=True)
    rollback.add_argument("--actor", required=True)

    query = commands.add_parser("query")
    query.add_argument("--channel", default=None)
    query.add_argument("--query", required=True)
    query.add_argument("--audiences", default="public,internal")
    query.add_argument("--limit", type=int, default=10)

    refresh = commands.add_parser("refresh")
    refresh.add_argument("--channel", default=None)

    args = parser.parse_args()

    if args.command == "render-production-ledger":
        comment = build_production_ledger_comment(
            evidence_dir=args.evidence_dir,
            run_id=args.run_id,
            run_url=args.run_url,
            workflow_name=args.workflow_name,
            event_name=args.event_name,
            head_sha=args.head_sha,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(comment, encoding="utf-8")
        print(
            json.dumps(
                {
                    "status": "rendered",
                    "output": str(args.output),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if args.command == "validate-promotion-request":
        spec = load_promotion_request_spec(
            request_path=args.request_path,
            control_plane_sha=args.control_plane_sha,
        )
        result = write_request_evidence(spec=spec, evidence_dir=args.evidence_dir)
        if args.github_env is not None:
            write_github_env(args.github_env, spec.env())
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

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

    if args.command == "gate-source-candidate":
        result = run_source_candidate_gate(
            store=store,
            repository_url=args.source_url,
            repository=args.source_repository,
            source_commit_sha=args.source_sha,
            foundation_commit_sha=args.foundation_sha,
            channel=args.channel,
            release_time=_utc(args.release_time),
            query=args.query,
            work_root=args.work_dir,
        )
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
        return 0

    if args.command == "promote-release":
        result = promote_release(
            store=store,
            request=_promotion_request_from_args(args),
            promoted_at=(
                _promoted_at(_utc(args.promoted_at))
                if args.promoted_at is not None
                else None
            ),
        )
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
        return 0

    if args.command == "verify-promotion-candidate":
        result = verify_promotion_candidate(
            store=store,
            request=_promotion_request_from_args(args),
        )
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
        return 0

    if args.command == "verify-already-promoted":
        result = verify_already_promoted(
            store=store,
            request=_promotion_request_from_args(args),
        )
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
        return 0

    if args.command == "rollback-release":
        result = rollback_release(
            store=store,
            operation_id=args.operation_id,
            reason=args.reason,
            actor=args.actor,
        )
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
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
