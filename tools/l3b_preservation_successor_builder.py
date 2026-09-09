from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

MAIN = "68fa4b437b778e6f44a885bafd0f42016bbf7142"
CANDIDATE = "543926766f85f0938ec5fe9b60c65a70c33d754d"
SUCCESSOR_BRANCH = "p0/qa-answer-quality-inbox-production-successor-20260909"
EXPECTED_CONFLICTS = ["Dockerfile", "src/knowledge_engine/m26_public_api.py"]


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(args), flush=True)
    return subprocess.run(args, text=True, check=check, capture_output=False)


def out(*args: str) -> str:
    return subprocess.check_output(args, text=True).strip()


def resolve_dockerfile(root: Path) -> None:
    run("git", "checkout", "--ours", "Dockerfile")
    p = root / "Dockerfile"
    s = p.read_text()
    old = (
        '# The standard compose runtime and the public API use the same canonical app.\n'
        '# Deploy workflow identity gates still bind the immutable release SHA.\n'
        'CMD ["uvicorn", "knowledge_engine.m26_public_api:app", "--host", "0.0.0.0", "--port", "8080"]\n'
    )
    new = (
        '# Production serves the current public runtime plus the accepted owner-only Admin app.\n'
        '# Public /v1/answers* remains available; /v1/admin/* stays fail-closed behind Admin controls.\n'
        'CMD ["uvicorn", "knowledge_engine.m26_console_api:app", "--host", "0.0.0.0", "--port", "8080"]\n'
    )
    if old not in s:
        raise SystemExit("Dockerfile resolution anchor missing")
    p.write_text(s.replace(old, new, 1))


def resolve_public_api(root: Path) -> None:
    run("git", "checkout", "--ours", "src/knowledge_engine/m26_public_api.py")
    p = root / "src/knowledge_engine/m26_public_api.py"
    s = p.read_text()

    constants_anchor = (
        'PUBLIC_HEALTH_SCHEMA = "danielcanfly-answers-health/v1"\n'
        'OWNER_BYPASS_HEADER = "x-m26-owner-bypass"\n'
    )
    constants_new = (
        'PUBLIC_HEALTH_SCHEMA = "danielcanfly-answers-health/v1"\n'
        '_QA_INTERNAL_CONTEXT_TTL_SECONDS = 300\n'
        '_QA_INTERNAL_CONTEXT_LIMIT = 256\n'
        '_qa_internal_context_lock = threading.Lock()\n'
        '_qa_internal_contexts: dict[str, tuple[float, dict[str, Any]]] = {}\n'
        'OWNER_BYPASS_HEADER = "x-m26-owner-bypass"\n'
    )
    if constants_anchor not in s:
        raise SystemExit("QA constants anchor missing")
    s = s.replace(constants_anchor, constants_new, 1)

    dto_anchor = (
        '                dto = dict(item.get("dto") if isinstance(item.get("dto"), Mapping) else {})\n'
        '                for event in _model_events_from_dto(dto):\n'
    )
    dto_new = (
        '                dto = dict(item.get("dto") if isinstance(item.get("dto"), Mapping) else {})\n'
        '                _publish_qa_internal_context(admission.request_id, dto)\n'
        '                for event in _model_events_from_dto(dto):\n'
    )
    if dto_anchor not in s:
        raise SystemExit("QA publish anchor missing")
    s = s.replace(dto_anchor, dto_new, 1)

    func_anchor = "\ndef _public_citations(value: Any) -> list[dict[str, Any]]:\n"
    funcs = '''

def _publish_qa_internal_context(request_id: str, dto: Mapping[str, Any]) -> None:
    """Publish evidence to the in-process QA observer without changing public SSE."""
    allowed = {
        "selected_evidence",
        "evidence_utilization_trace",
        "semantic_closure",
        "retrieval",
        "integrity",
        "identities",
        "canonical_runtime",
        "reason_codes",
        "safe_abstention",
        "status",
    }
    context = {key: dto[key] for key in allowed if key in dto}
    now = time.monotonic()
    with _qa_internal_context_lock:
        expired = [
            key
            for key, (created, _) in _qa_internal_contexts.items()
            if now - created > _QA_INTERNAL_CONTEXT_TTL_SECONDS
        ]
        for key in expired:
            _qa_internal_contexts.pop(key, None)
        while len(_qa_internal_contexts) >= _QA_INTERNAL_CONTEXT_LIMIT:
            oldest = min(_qa_internal_contexts, key=lambda key: _qa_internal_contexts[key][0])
            _qa_internal_contexts.pop(oldest, None)
        _qa_internal_contexts[request_id] = (now, context)


def consume_qa_internal_context(request_id: str) -> dict[str, Any]:
    """Consume a one-shot backend-only QA context for the completed request."""
    with _qa_internal_context_lock:
        item = _qa_internal_contexts.pop(request_id, None)
    if item is None or time.monotonic() - item[0] > _QA_INTERNAL_CONTEXT_TTL_SECONDS:
        return {}
    return item[1]
'''
    if func_anchor not in s:
        raise SystemExit("QA function anchor missing")
    s = s.replace(func_anchor, funcs + func_anchor, 1)
    p.write_text(s)


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: builder.py WORKTREE")
    root = Path(sys.argv[1]).resolve()
    os.chdir(root)

    run("git", "config", "user.name", "l3b-preservation-builder")
    run("git", "config", "user.email", "l3b-preservation-builder@invalid.local")
    if out("git", "rev-parse", "HEAD") != MAIN:
        raise SystemExit("wrong main base")
    run("git", "fetch", "--no-tags", "origin", CANDIDATE)
    merge = run("git", "merge", "--no-commit", "--no-ff", CANDIDATE, check=False)
    if merge.returncode != 1:
        raise SystemExit(f"unexpected merge exit {merge.returncode}")
    conflicts = sorted(filter(None, out("git", "diff", "--name-only", "--diff-filter=U").splitlines()))
    print("CONFLICTS=", conflicts)
    if conflicts != EXPECTED_CONFLICTS:
        raise SystemExit(f"unexpected conflict set: {conflicts}")

    resolve_dockerfile(root)
    resolve_public_api(root)
    run("git", "add", "Dockerfile", "src/knowledge_engine/m26_public_api.py")
    if out("git", "diff", "--name-only", "--diff-filter=U"):
        raise SystemExit("unmerged paths remain")
    run("git", "diff", "--cached", "--check")

    docker = (root / "Dockerfile").read_text()
    public_api = (root / "src/knowledge_engine/m26_public_api.py").read_text()
    required = [
        ("knowledge_engine.m26_console_api:app", docker),
        ('OWNER_BYPASS_HEADER = "x-m26-owner-bypass"', public_api),
        ("def consume_qa_internal_context", public_api),
        ("_publish_qa_internal_context(admission.request_id, dto)", public_api),
        ('@app.get("/v1/answers/health")', public_api),
    ]
    for needle, haystack in required:
        if needle not in haystack:
            raise SystemExit(f"required preservation seam missing: {needle}")
    print("MERGE_RESOLUTION=PASS")

    run(sys.executable, "-m", "pip", "install", "-e", ".[dev]")
    run(sys.executable, "-m", "compileall", "-q", "src")

    tests = [
        "tests/test_qa_answer_quality.py",
        "tests/test_qa_answer_quality_r1.py",
        "tests/test_qa_failure_clustering.py",
        "tests/test_qa_inbox_api_completeness.py",
        "tests/test_suggested_questions_promotion.py",
        "tests/test_m26_admin_qa.py",
        "tests/test_m26_suggested_questions_admin.py",
        "tests/test_m26_admin_openapi.py",
        "tests/test_m26_aq_production_entrypoint.py",
        "tests/test_m26_pa7_final_web_readiness.py",
        "tests/test_m26_sm95_release_runtime_contract.py",
    ]
    extra_patterns = [
        "tests/test_m26_public*.py",
        "tests/test_*daily*rate*limit*.py",
        "tests/test_m26_owner*.py",
        "tests/test_m26_production*.py",
        "tests/test_m26_*health*.py",
    ]
    extras: list[str] = []
    for pattern in extra_patterns:
        for p in sorted(root.glob(pattern)):
            rel = p.relative_to(root).as_posix()
            if rel not in tests and rel not in extras:
                extras.append(rel)
    print("EXTRA_REGRESSION_TESTS=", extras or "NONE")
    run(sys.executable, "-m", "pytest", "-q", *tests, *extras)

    changed = out("git", "diff", "--cached", "--name-only", "--diff-filter=ACMR").splitlines()
    pyfiles = [p for p in changed if p.endswith(".py") and (p.startswith("src/knowledge_engine/") or p.startswith("tests/"))]
    if not pyfiles:
        raise SystemExit("no Python changed paths for Ruff")
    run("ruff", "check", "--select", "E,F,I", "--ignore", "E501", *pyfiles)

    run("docker", "build", "-t", "l3b-preservation-successor:qualify", ".")
    run(
        "docker",
        "inspect",
        "l3b-preservation-successor:qualify",
        "--format",
        "{{json .Config.User}} {{json .Config.Healthcheck.Test}} {{json .Config.Cmd}}",
    )

    if out("git", "rev-parse", "HEAD") != MAIN:
        raise SystemExit("HEAD moved before seal")
    if out("git", "rev-parse", "MERGE_HEAD") != CANDIDATE:
        raise SystemExit("MERGE_HEAD drift")
    run("git", "commit", "-m", "merge(l3b): preserve production main and QA inbox backend")
    successor = out("git", "rev-parse", "HEAD")
    tree = out("git", "rev-parse", "HEAD^{tree}")
    p1 = out("git", "rev-parse", "HEAD^1")
    p2 = out("git", "rev-parse", "HEAD^2")
    print(f"SUCCESSOR_COMMIT={successor}")
    print(f"SUCCESSOR_TREE={tree}")
    print(f"PARENT1={p1}")
    print(f"PARENT2={p2}")
    if p1 != MAIN or p2 != CANDIDATE:
        raise SystemExit("successor parent identity mismatch")
    run("git", "push", "origin", f"HEAD:refs/heads/{SUCCESSOR_BRANCH}")
    print("SUCCESSOR_PUBLISHED=YES")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
