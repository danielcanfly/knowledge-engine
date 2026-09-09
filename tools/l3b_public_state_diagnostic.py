from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

MAIN = "68fa4b437b778e6f44a885bafd0f42016bbf7142"
CANDIDATE = "543926766f85f0938ec5fe9b60c65a70c33d754d"
FAIL_NODE = "tests/test_m26_public_api_acceptance_edges.py::test_public_model_audit_distinguishes_synthesizer_from_reviewer"


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(args), flush=True)
    return subprocess.run(args, text=True, check=check)


def out(*args: str) -> str:
    return subprocess.check_output(args, text=True).strip()


def reconstruct(root: Path) -> None:
    os.chdir(root)
    run("git", "config", "user.name", "l3b-public-state-diagnostic")
    run("git", "config", "user.email", "l3b-public-state-diagnostic@invalid.local")
    assert out("git", "rev-parse", "HEAD") == MAIN
    run("git", "fetch", "--no-tags", "origin", CANDIDATE)
    result = run("git", "merge", "--no-commit", "--no-ff", CANDIDATE, check=False)
    assert result.returncode == 1
    assert sorted(out("git", "diff", "--name-only", "--diff-filter=U").splitlines()) == [
        "Dockerfile",
        "src/knowledge_engine/m26_public_api.py",
    ]

    run("git", "checkout", "--ours", "Dockerfile")
    docker = root / "Dockerfile"
    s = docker.read_text()
    old = 'CMD ["uvicorn", "knowledge_engine.m26_public_api:app", "--host", "0.0.0.0", "--port", "8080"]'
    new = 'CMD ["uvicorn", "knowledge_engine.m26_console_api:app", "--host", "0.0.0.0", "--port", "8080"]'
    assert old in s
    docker.write_text(s.replace(old, new, 1))

    run("git", "checkout", "--ours", "src/knowledge_engine/m26_public_api.py")
    p = root / "src/knowledge_engine/m26_public_api.py"
    s = p.read_text()
    anchor = 'PUBLIC_HEALTH_SCHEMA = "danielcanfly-answers-health/v1"\nOWNER_BYPASS_HEADER = "x-m26-owner-bypass"\n'
    repl = 'PUBLIC_HEALTH_SCHEMA = "danielcanfly-answers-health/v1"\n_QA_INTERNAL_CONTEXT_TTL_SECONDS = 300\n_QA_INTERNAL_CONTEXT_LIMIT = 256\n_qa_internal_context_lock = threading.Lock()\n_qa_internal_contexts: dict[str, tuple[float, dict[str, Any]]] = {}\nOWNER_BYPASS_HEADER = "x-m26-owner-bypass"\n'
    assert anchor in s
    s = s.replace(anchor, repl, 1)
    anchor = '                dto = dict(item.get("dto") if isinstance(item.get("dto"), Mapping) else {})\n                for event in _model_events_from_dto(dto):\n'
    repl = '                dto = dict(item.get("dto") if isinstance(item.get("dto"), Mapping) else {})\n                _publish_qa_internal_context(admission.request_id, dto)\n                for event in _model_events_from_dto(dto):\n'
    assert anchor in s
    s = s.replace(anchor, repl, 1)
    fanchor = '\ndef _public_citations(value: Any) -> list[dict[str, Any]]:\n'
    funcs = '''

def _publish_qa_internal_context(request_id: str, dto: Mapping[str, Any]) -> None:
    allowed = {"selected_evidence", "evidence_utilization_trace", "semantic_closure", "retrieval", "integrity", "identities", "canonical_runtime", "reason_codes", "safe_abstention", "status"}
    context = {key: dto[key] for key in allowed if key in dto}
    now = time.monotonic()
    with _qa_internal_context_lock:
        expired = [key for key, (created, _) in _qa_internal_contexts.items() if now - created > _QA_INTERNAL_CONTEXT_TTL_SECONDS]
        for key in expired:
            _qa_internal_contexts.pop(key, None)
        while len(_qa_internal_contexts) >= _QA_INTERNAL_CONTEXT_LIMIT:
            oldest = min(_qa_internal_contexts, key=lambda key: _qa_internal_contexts[key][0])
            _qa_internal_contexts.pop(oldest, None)
        _qa_internal_contexts[request_id] = (now, context)


def consume_qa_internal_context(request_id: str) -> dict[str, Any]:
    with _qa_internal_context_lock:
        item = _qa_internal_contexts.pop(request_id, None)
    if item is None or time.monotonic() - item[0] > _QA_INTERNAL_CONTEXT_TTL_SECONDS:
        return {}
    return item[1]
'''
    assert fanchor in s
    p.write_text(s.replace(fanchor, funcs + fanchor, 1))
    run("git", "add", "Dockerfile", "src/knowledge_engine/m26_public_api.py")
    run("git", "checkout", MAIN, "--", "tests/test_m26_pa7_final_web_readiness.py")
    run("git", "add", "tests/test_m26_pa7_final_web_readiness.py")
    stale = root / "tests/test_m26_sm95_release_runtime_contract.py"
    if stale.exists():
        run("git", "rm", "-f", str(stale.relative_to(root)))
    assert not out("git", "diff", "--name-only", "--diff-filter=U")
    print("RECONSTRUCTED_MERGE_STATE=PASS")


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: diagnostic.py WORKTREE")
    root = Path(sys.argv[1]).resolve()
    reconstruct(root)
    run(sys.executable, "-m", "pip", "install", "-e", ".[dev]")

    # Control: failing node alone.
    alone = run(sys.executable, "-m", "pytest", "-q", FAIL_NODE, check=False)
    print(f"FAIL_NODE_ALONE_RC={alone.returncode}")

    # B: whole acceptance_edges file alone.
    same_file = run(sys.executable, "-m", "pytest", "-q", "tests/test_m26_public_api_acceptance_edges.py", check=False)
    print(f"ACCEPTANCE_EDGES_FILE_RC={same_file.returncode}")

    # A: first public file and failing node in the SAME pytest process.
    cross_file = run(
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "tests/test_m26_public_api.py",
        FAIL_NODE,
        check=False,
    )
    print(f"PUBLIC_API_THEN_FAIL_NODE_SAME_PROCESS_RC={cross_file.returncode}")

    # Independent subprocess control: first file then failing node in separate processes.
    first = run(sys.executable, "-m", "pytest", "-q", "tests/test_m26_public_api.py", check=False)
    second = run(sys.executable, "-m", "pytest", "-q", FAIL_NODE, check=False)
    print(f"PUBLIC_API_SEPARATE_RC={first.returncode}")
    print(f"FAIL_NODE_AFTER_SEPARATE_PROCESS_RC={second.returncode}")

    if alone.returncode != 0 or second.returncode != 0:
        raise SystemExit("standalone product behavior is not stable")
    print("DIAGNOSTIC_COMPLETE=YES")
    print("PRODUCTION_MUTATION=0")
    print("SUCCESSOR_BRANCH_MUTATION=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
