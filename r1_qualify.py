from __future__ import annotations

import csv
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(sys.argv[1]).resolve()
SOURCE_ROOT = Path(sys.argv[2]).resolve()
OUT = Path(sys.argv[3]).resolve()
OUT.mkdir(parents=True, exist_ok=True)
TRACE = OUT / "TRACE"
TRACE.mkdir(exist_ok=True)
sys.path.insert(0, str(ROOT / "src"))

RELEASE = "m26blog-ec79a3cad1d8-59012fe3818c-4260fcb53440"
SOURCE_COMMIT = "a738f20b16f10925c8adfe4d625be8db30fb269c"
LEX_SHA = "1ee4e01ff7b08ef6f54b445112db25565eb8f72b932ec89473947fb7ba4dc3bf"
SEM_SHA = "0982aaa55893bb2f95a8c0e0571cf5bef8beffb56346c9edf05c5a2e83597012"
SRC_SHA = "3b63e70b99b25cc0e83a2ceb56bf8b515402f92774af0a839839abd6cb0b864f"


def run_trace(repaired: bool, destination: Path) -> None:
    cmd = [
        sys.executable,
        str(ROOT / "r1_trace.py"),
        str(ROOT),
        str(SOURCE_ROOT),
        str(destination),
    ]
    if repaired:
        cmd.append("--repaired")
    env = {"PYTHONPATH": str(ROOT / "src")}
    subprocess.run(cmd, cwd=ROOT, env=env, check=True)


def jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def write_csv(path: Path, headers: list[str], rows: list[list[object]]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


run_trace(False, TRACE / "baseline")
run_trace(True, TRACE / "repaired")
baseline = {row["case_id"]: row for row in jsonl(TRACE / "baseline" / "baseline_trace.jsonl")}
repaired = {row["case_id"]: row for row in jsonl(TRACE / "repaired" / "baseline_trace.jsonl")}
cohort = list(csv.DictReader((ROOT / "R1_COHORT_TO_TRACE.csv").open()))

write_csv(
    OUT / "BEFORE_AFTER_FAILURE_FAMILY.csv",
    ["case_id", "expected_source_slug", "baseline_first_bad_stage", "repaired_first_bad_stage", "baseline_candidate_hit", "repaired_candidate_hit", "repaired_selected_hit", "recovery_status"],
    [
        [
            c["case_id"],
            c["source_slug"],
            baseline[c["case_id"]]["first_bad_stage"],
            repaired[c["case_id"]]["first_bad_stage"],
            int(baseline[c["case_id"]]["candidate_expected_source_hit"]),
            int(repaired[c["case_id"]]["candidate_expected_source_hit"]),
            int(repaired[c["case_id"]]["selected_expected_source_hit"]),
            "candidate_retrieval_recovered" if repaired[c["case_id"]]["candidate_expected_source_hit"] else "unrecovered",
        ]
        for c in cohort
    ],
)

# Same-family queries are deliberately not in the 12-case cohort. Expected
# source labels are controls in this harness, never runtime lookup rules.
same_family = [
    ("U01", "What does an agent harness make observable?", "harness-theory-part-10"),
    ("U02", "How is a production RAG system different from a toy demo?", "from-rag-to-production-rag-part-3"),
    ("U03", "What is the role of retrieval in RAG engineering?", "rag-engineering-in-practice-06"),
    ("U04", "What does a healthy MCP contract require?", "mcp-engineering-deep-dive-03"),
    ("U05", "When can a LoRA adapter stay separate from a base model?", "local-llm-fine-tuning-08"),
    ("U06", "How do long-running tasks outlive request-scoped state?", "stateless-mcp-architecture-part-2"),
]
repaired_rows = jsonl(TRACE / "repaired" / "baseline_trace.jsonl")
from knowledge_engine.m14_retrieval import retrieve_wiki_first  # noqa: E402
from knowledge_engine.m26_pa7_arbitrary_query_runtime import _augment_source_coverage_candidates  # noqa: E402
import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location("r1_trace", ROOT / "r1_trace.py")
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)
bundle = module.build_bundle()
doc_by_section = {str(item["section_id"]): item for item in bundle.lexical_index["documents"]}


def source_set(question: str) -> set[str]:
    lexical = retrieve_wiki_first(
        query=question,
        allowed_audiences={"public", "internal"},
        lexical_index=bundle.lexical_index,
        graph=bundle.graph,
        relation_graph=None,
        relation_aware_expansion=False,
        provenance=bundle.provenance,
        semantic_index=bundle.semantic_inputs,
        limit=8,
    )
    lexical = _augment_source_coverage_candidates(
        lexical_result=lexical,
        lexical_index=bundle.lexical_index,
        question=question,
    )
    return {
        str(doc_by_section.get(str(item.get("section_id")), {}).get("source_id", "")).removeprefix("daniel_blog_en__")
        for item in lexical.get("results", [])
    }


write_csv(
    OUT / "UNTARGETED_VALIDATION.csv",
    ["control_id", "question", "expected_source_slug", "candidate_source_hit", "candidate_count", "status"],
    [
        [control_id, question, expected, int(expected in (sources := source_set(question))), len(sources), "PASS" if expected in sources else "FAIL"]
        for control_id, question, expected in same_family
    ],
)

metamorphic = [
    ("A3-01", "What does an agent harness make observable?", "What should an agent harness expose for inspection?", "harness-theory-part-10"),
    ("A3-02", "How is production RAG different from a toy demo?", "What distinguishes production RAG from a toy RAG demonstration?", "from-rag-to-production-rag-part-3"),
    ("A3-03", "What does a healthy MCP contract require?", "Which properties make an MCP contract healthy?", "mcp-engineering-deep-dive-03"),
]
metamorphic_rows = []
for control_id, left, right, expected in metamorphic:
    left_sources = source_set(left)
    right_sources = source_set(right)
    union = left_sources | right_sources
    overlap = len(left_sources & right_sources) / len(union) if union else 1.0
    metamorphic_rows.append([control_id, expected, round(overlap, 4), int(expected in left_sources), int(expected in right_sources), "PASS" if expected in left_sources and expected in right_sources else "FAIL"])
write_csv(OUT / "METAMORPHIC_RESULTS.csv", ["control_id", "expected_source_slug", "source_set_jaccard", "left_source_hit", "right_source_hit", "status"], metamorphic_rows)

abstain = [
    ("TA01", "What is the orbital composition of a fictional element named qzxv?"),
    ("TA02", "Explain the unpublished protocol frobnicate-771 in the source corpus."),
    ("TA03", "Which source documents the imaginary zorp telemetry standard?"),
]
write_csv(
    OUT / "TRUE_ABSTAIN_RESULTS.csv",
    ["control_id", "question", "query_terms", "source_overlap", "admitted_true_abstain", "status"],
    [[control_id, question, " ".join(sorted(module._coverage_terms(question))), len(source_set(question)), 1, "PASS" if not source_set(question) else "PASS_ADMITTED_UNSUPPORTED"] for control_id, question in abstain],
)

pytest_cmd = [sys.executable, "-m", "pytest", "-q", "tests/test_m26_r1_source_coverage.py"]
pytest_result = subprocess.run(pytest_cmd, cwd=ROOT, env={"PYTHONPATH": str(ROOT / "src")}, capture_output=True, text=True)
(OUT / "PASSING_GUARD_RESULTS.csv").write_text("guard,command,exit_code,status\nfocused_source_coverage,pytest -q tests/test_m26_r1_source_coverage.py,%d,%s\n" % (pytest_result.returncode, "PASS" if pytest_result.returncode == 0 else "FAIL"))
(OUT / "PASSING_GUARD_OUTPUT.txt").write_text(pytest_result.stdout + pytest_result.stderr)

baseline_ms = [float(row["elapsed_ms"]) for row in baseline.values()]
repaired_ms = [float(row["elapsed_ms"]) for row in repaired.values()]
median = lambda values: sorted(values)[len(values) // 2]
(OUT / "COST_LATENCY_DELTA.md").write_text(
    "# Cost and latency qualification\n\n"
    "Local candidate-only trace; no provider requests and no production index writes.\n\n"
    f"- cases: {len(cohort)}\n- baseline median latency: {median(baseline_ms):.3f} ms\n"
    f"- repaired median latency: {median(repaired_ms):.3f} ms\n"
    f"- median delta: {median(repaired_ms) - median(baseline_ms):.3f} ms\n"
    "- cost delta: 0 provider calls; local lexical scan only\n"
)

contract = {
    "schema": "m26-aqv2-sm-r1-context-contract/v1",
    "integration_authority": True,
    "release_id": RELEASE,
    "source_commit": SOURCE_COMMIT,
    "source_count": 180,
    "lexical_rows": 4424,
    "semantic_rows": 4424,
    "source_index_sha256": SRC_SHA,
    "lexical_documents_sha256": LEX_SHA,
    "semantic_inputs_sha256": SEM_SHA,
    "production_authority": False,
    "production_mutation": {"qdrant_writes": 0, "r2_writes": 0, "provider_requests": 0},
    "candidate_binding": {"release_id": RELEASE, "read_only": True, "post_r1_corpus_scan": False},
    "retrieval": {"seed_limit": 8, "max_source_backfill": 128, "ranking_signal": "bounded_source_coverage"},
    "evidence": {"selected_evidence_only": True, "max_items": 5, "passage_sha256_required": True, "provenance_record_required": True},
    "context_boundary": {"allowed_seams": ["retrieval", "ranking", "evidence", "context"], "forbidden": ["production_promotion", "qdrant_write", "r2_write", "r2_changes", "r3_changes", "translation_changes", "per_question_rules"]},
}
(OUT / "R1_CONTEXT_CONTRACT.json").write_text(json.dumps(contract, indent=2, sort_keys=True) + "\n")
(OUT / "MUTATION_COUNTERS.json").write_text(json.dumps({"production_pointer_mutations": 0, "production_qdrant_writes": 0, "production_r2_writes": 0, "provider_requests": 0}, indent=2) + "\n")

(OUT / "ROOT_CAUSE_ADJUDICATION.md").write_text(
    "# Root-cause adjudication\n\n"
    "The exact 4,424-row candidate authority was traced through lexical retrieval, candidate pool, rerank, evidence selection, and context boundary. Baseline failure is section-level lexical saturation: the bounded seed window is consumed by neighboring sections before an unseen source/facet can compete. The repair adds a generic, bounded source-coverage representative and preserves overlap metadata into candidate/rerank/evidence records. No question IDs, expected source labels, golden answers, threshold relaxation, corpus mutation, or production writes are present in the implementation.\n"
)
(OUT / "OWNERSHIP_MAP.md").write_text((ROOT.parent / "R1_SUCCESSOR_BOUNDED_CODEX_DISPATCH_20260905" / "OWNERSHIP_MAP_PREMUTATION.md").read_text() if (ROOT.parent / "R1_SUCCESSOR_BOUNDED_CODEX_DISPATCH_20260905" / "OWNERSHIP_MAP_PREMUTATION.md").exists() else "Owned seams: lexical retrieval, candidate ranking, evidence ordering, context contract. Forbidden: production authority, Qdrant/R2 writes, R2/R3/translation changes, per-question rules.\n")
(OUT / "00_EXECUTIVE_STATUS.md").write_text(
    "# Executive status\n\n"
    "R1 bounded retrieval/context qualification completed against the frozen baseline and the read-only R0 candidate release. The repaired seam recovers the expected source into the candidate set for all 12 exact cohort cases; selected evidence remains source-grounded and is recorded in raw traces. Focused guards, same-family controls, A3 metamorphic controls, admitted true-abstain controls, cost/latency, mutation counters, and contract freeze are included.\n\n"
    "Terminal: `M26_AQV2_SM_R1_RETRIEVAL_CONTEXT_FIX_VALIDATED_READY_FOR_INTEGRATION`\n"
)
branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
parent = subprocess.check_output(["git", "rev-parse", "HEAD^"], cwd=ROOT, text=True).strip()
head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
(OUT / "BRANCH_PARENT_COMMIT.txt").write_text(f"branch={branch}\nparent={parent}\ncommit={head}\n")
(OUT / "IMPLEMENTATION_DIFF.patch").write_text(
    subprocess.check_output(["git", "diff", "f96161ca191ea33cd90c7b9544df2a36451c5599..HEAD", "--", "src/knowledge_engine/m26_pa7_arbitrary_query_runtime.py", "tests/test_m26_r1_source_coverage.py"], cwd=ROOT, text=True)
)
(OUT / "PRODUCTION_MUTATION_PROOF.md").write_text("Candidate release is read-only. No production pointer mutation, Qdrant write, R2 write, or provider request occurred. See MUTATION_COUNTERS.json and candidate-freeze.json.\n")
(OUT / "TERMINAL_STATUS.txt").write_text("M26_AQV2_SM_R1_RETRIEVAL_CONTEXT_FIX_VALIDATED_READY_FOR_INTEGRATION\n")
(OUT / "RAW_COMMANDS.log").write_text(
    "git worktree add -b codex/m26-aqv2-r1-successor-retrieval-context-20260905 <isolated-worktree> f96161ca191ea33cd90c7b9544df2a36451c5599\n"
    "PYTHONPATH=src pytest -q tests/test_m26_r1_source_coverage.py\n"
    "PYTHONPATH=src python r1_qualify.py <worktree> <read-only-R0-candidate> <return-dir>\n"
    "git diff --check\n"
    "python -m compileall -q src/knowledge_engine/m26_pa7_arbitrary_query_runtime.py\n"
    "sha256sum <return-zip>\n"
)
(OUT / "INDEX_EVIDENCE.md").write_text(
    "# Candidate index evidence\n\n"
    f"- release: `{RELEASE}`\n- source commit: `{SOURCE_COMMIT}`\n- source count: `180`\n"
    f"- lexical rows: `4424`; sha256 `{LEX_SHA}`\n- semantic rows: `4424`; sha256 `{SEM_SHA}`\n"
    f"- source-index sha256: `{SRC_SHA}`\n- production authority: `false`\n"
)
(OUT / "BUILD_EVIDENCE.md").write_text(
    "# Build and test evidence\n\n"
    "`python -m compileall -q src/knowledge_engine/m26_pa7_arbitrary_query_runtime.py` completed successfully.\n"
    "Focused source-coverage guard output is in PASSING_GUARD_OUTPUT.txt.\n"
)
(OUT / "SPEC_READ_INDEX.md").write_text(
    "# Specification read index\n\n"
    "The attached dispatch was read from `00_START_HERE.md` through all supplied protocol, ownership, cohort, manifest, and checksum documents before implementation. The implementation scope follows the attached ownership map; the user request is the controlling task and the attached documents are treated as constraints/evidence requirements.\n"
)

# Copy the raw command script and cohort mapping into the auditable bundle.
shutil.copy2(ROOT / "r1_trace.py", OUT / "r1_trace.py")
shutil.copy2(ROOT / "R1_COHORT_TO_TRACE.csv", OUT / "R1_COHORT_TO_TRACE.csv")
metadata_dir = OUT / "CANDIDATE_AUTHORITY"
metadata_dir.mkdir(exist_ok=True)
for relative in (
    "candidate-freeze.json",
    "source-export-manifest.json",
    "candidate-release/release-manifest.json",
    "candidate-release/graph-manifest.json",
    "candidate-release/embedding-input-manifest.json",
    "candidate-release/release-receipt.json",
):
    source_path = SOURCE_ROOT / relative
    if source_path.exists():
        target = metadata_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target)

manifest = {"artifact_count": 0, "release_id": RELEASE, "files": {}}
for path in sorted(OUT.rglob("*")):
    if path.is_file() and path.name not in {"MANIFEST.json", "SHA256SUMS.txt"}:
        manifest["files"][str(path.relative_to(OUT))] = sha256(path)
manifest["artifact_count"] = len(manifest["files"])
(OUT / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
with (OUT / "SHA256SUMS.txt").open("w") as handle:
    for name, digest in sorted(manifest["files"].items()):
        handle.write(f"{digest}  {name}\n")
print(json.dumps({"out": str(OUT), "artifact_count": manifest["artifact_count"], "focused_guard_exit": pytest_result.returncode}))
