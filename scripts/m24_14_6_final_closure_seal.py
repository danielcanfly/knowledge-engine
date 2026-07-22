#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from knowledge_engine.m24_14_6_final_closure_seal import (
    validate_committed_closure_artifacts,
    validate_portable_benchmark_file,
    write_portable_benchmark_evidence,
    write_post_merge_attestation_artifacts,
)


def _emit(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _git_output(args: list[str]) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="M24.14.6 final closure seal utilities")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate-evidence")
    validate.add_argument("--benchmark-path", type=Path, required=True)

    write = subparsers.add_parser("write-evidence")
    write.add_argument("--benchmark-path", type=Path, required=True)

    committed = subparsers.add_parser("validate-committed")
    committed.set_defaults(command="validate-committed")

    attest = subparsers.add_parser("post-merge-attest")
    attest.add_argument("--output-dir", type=Path, required=True)
    attest.add_argument("--issue-number", type=int, required=True)
    attest.add_argument("--pr-number", type=int, required=True)
    attest.add_argument("--pr-head-sha", required=True)
    attest.add_argument("--merge-sha")
    attest.add_argument("--tag-name", default="m24-14-6-final-closure")
    attest.add_argument("--final-surface-deployment-id", required=True)
    attest.add_argument("--ci-run", action="append", default=[])

    args = parser.parse_args()
    if args.command == "validate-evidence":
        _emit(validate_portable_benchmark_file(args.benchmark_path))
        return 0
    if args.command == "write-evidence":
        _emit(write_portable_benchmark_evidence(args.benchmark_path))
        return 0
    if args.command == "validate-committed":
        _emit(validate_committed_closure_artifacts())
        return 0

    merge_sha = args.merge_sha or _git_output(["rev-parse", "HEAD"])
    tag_target = _git_output(["rev-parse", f"refs/tags/{args.tag_name}^{{}}"])
    _emit(
        write_post_merge_attestation_artifacts(
            args.output_dir,
            issue_number=args.issue_number,
            pr_number=args.pr_number,
            pr_head_sha=args.pr_head_sha,
            merge_sha=merge_sha,
            tag_target_sha=tag_target,
            final_surface_deployment_id=args.final_surface_deployment_id,
            ci_runs=args.ci_run,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
