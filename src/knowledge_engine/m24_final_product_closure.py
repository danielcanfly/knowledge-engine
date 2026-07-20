from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from .m24_internal_product_deployment import P6AuthorityBoundary
from .m24_live_url_readiness import P7_CUSTOM_HOSTNAME, P7_PROJECT_NAME
from .m24_product_surface_integration import (
    CANONICAL_MANIFEST_SHA256,
    CANONICAL_RELEASE_ID,
    CANONICAL_SOURCE_SHA,
)

P10_SCHEMA = "knowledge-engine-m24-p10-final-product-closure/v1"
P10_ISSUE_NUMBER = 1005
P10_ROOT = Path("pilot/m24/final-product-closure")
P10_REPORT_PATH = P10_ROOT / "m24-p10-final-product-closure.json"
P10_RECONCILIATION_BASE_ENGINE_SHA = "3f494dfe8c1547eaa2acfc3919d48339c14d29d2"
P10_HANDOFF_PACKAGE = "LLM_Wiki_Codex_End_to_End_Completion_Execution_Pack_2026-07-20"

ProgrammeStatus = Literal[
    "complete",
    "complete_as_internal_candidate",
    "governed_deferred",
    "pending_external_acceptance",
]


class P10HandoffPackageEvidence(BaseModel):
    package_name: str
    generated_at: str
    zip_file_count: int = Field(ge=1)
    manifest_entry_count: int = Field(ge=1)
    manifest_verified_locally: bool
    selected_entry_sha256: dict[str, str]


class P10ProgrammePhase(BaseModel):
    phase: Literal["P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9", "P10"]
    handoff_goal: str
    status: ProgrammeStatus
    repo_evidence: list[str]
    closure_note: str
    remaining_trigger: str | None = None


class P10ReadinessSummary(BaseModel):
    query: Literal["Q2_internal_usable_lexical", "Q3_production_lexical"]
    sigma: Literal["S2_internal_deployed_usable_pending_manual_acceptance"]
    obsidian: Literal["O1_canonical_export_generated"]
    answer: Literal["A3_citation_verified_internal_candidate"]
    relation_aware: Literal["candidate_design_only"]


class P10RemainingItem(BaseModel):
    item: str
    status: Literal["complete", "governed_deferred", "pending_external_acceptance"]
    reason: str
    trigger_to_complete: str
    authorized_now: bool


class P10OperationalMaintenanceContract(BaseModel):
    feedback_lifecycle_defined: bool
    freshness_checks_defined: bool
    deletion_tombstones_defined: bool
    supersession_defined: bool
    contradiction_discovery_defined: bool
    alias_duplicate_cleanup_defined: bool
    embedding_migration_requires_gate: bool
    qdrant_rebuild_requires_gate: bool
    graph_schema_migration_requires_gate: bool
    rollback_drills_defined: bool
    review_throughput_reporting_defined: bool


class P10ClosureDecision(BaseModel):
    status: Literal["operator_ready_pending_external_acceptance"]
    product_internal_url_status: Literal["access_protected"]
    production_retrieval: Literal["lexical"]
    production_semantic_or_hybrid_status: Literal["not_authorized"]
    large_scale_ingestion_status: Literal["not_authorized"]
    independent_operator_exercise_status: Literal["pending"]
    closeout_statement: str


class P10FinalClosureReport(BaseModel):
    schema_version: str = P10_SCHEMA
    issue_number: int
    release_id: str
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    reconciliation_base_engine_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    pages_project_name: str
    custom_hostname: str
    handoff_package: P10HandoffPackageEvidence
    programme: list[P10ProgrammePhase]
    readiness: P10ReadinessSummary
    remaining_items: list[P10RemainingItem]
    maintenance_contract: P10OperationalMaintenanceContract
    closure_decision: P10ClosureDecision
    authority: P6AuthorityBoundary
    evidence_hygiene: list[str]
    self_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _digest(value: Any) -> str:
    if isinstance(value, BaseModel):
        return canonical_sha256(value.model_dump(mode="json"))
    return canonical_sha256(value)


def _handoff_package() -> P10HandoffPackageEvidence:
    return P10HandoffPackageEvidence(
        package_name=P10_HANDOFF_PACKAGE,
        generated_at="2026-07-20",
        zip_file_count=34,
        manifest_entry_count=32,
        manifest_verified_locally=True,
        selected_entry_sha256={
            "00_COMPLETION_DEFINITION.md": (
                "7393763b7d94700c8088f717463e9c97f22175a54792290130361d2af22be813"
            ),
            "01_PROGRAMME_MAP.md": (
                "631f5dfe93e3b15f90cb89bfb5fd2cd950d1f393e6dd7dc8c65e6e40253645d3"
            ),
            "14_P7_PRODUCTION_PROMOTION.md": (
                "b674409c04e6fed4b992e4c0c3764d3bf05ddabffe24f145a6a940b381c0763b"
            ),
            "15_P8_PROGRESSIVE_LARGE_INGESTION.md": (
                "0e5ac20cfc6131cd73ae1a129b44ad27a7df58a986ed4f4c3dcbab0848746f56"
            ),
            "16_P9_FEEDBACK_AND_MAINTENANCE.md": (
                "dcc96e356943f63d5212c05a5d7f6540b9ee2d42f58d476ca55539f7fefb250f"
            ),
            "17_P10_FINAL_CLOSURE.md": (
                "b17573820a5c8dec685cb5f3f0c4396fcc4678525da6bb58bfd961de7cedb0ec"
            ),
        },
    )


def _programme() -> list[P10ProgrammePhase]:
    return [
        P10ProgrammePhase(
            phase="P1",
            handoff_goal="Canonical Source adoption decision capture and adoption planning.",
            status="complete_as_internal_candidate",
            repo_evidence=[
                "pilot/m24/m24-source-pr-19-decision-capture.json",
                "docs/architecture/m24/m24-source-pr-19-decision-capture.md",
                "docs/architecture/m24/m24-canonical-source-adoption-plan.md",
            ],
            closure_note=(
                "All fifteen Source PR #19 decisions are accounted for; the final "
                "four remain narrowed as harness-specific before canonical use."
            ),
        ),
        P10ProgrammePhase(
            phase="P2",
            handoff_goal="Deterministic canonical candidate release rebuild.",
            status="complete",
            repo_evidence=[
                "pilot/m24/canonical-release/manifest.json",
                "pilot/m24/m24-p2-canonical-release-rebuild.json",
                "tests/test_m24_p2_canonical_release_rebuild.py",
            ],
            closure_note="Candidate release artifacts rebuild and cross-validate by digest.",
        ),
        P10ProgrammePhase(
            phase="P3",
            handoff_goal="Product surfaces integrated against the same canonical release.",
            status="complete",
            repo_evidence=[
                "pilot/m24/m24-p3-product-surface-integration.json",
                "tests/test_m24_p3_product_surface_integration.py",
                "docs/architecture/m24/m24-6-product-surface-integration.md",
            ],
            closure_note=(
                "Wiki, lexical search, source viewer, graph, answer, and export "
                "payloads share the release identity."
            ),
        ),
        P10ProgrammePhase(
            phase="P4",
            handoff_goal="Controlled ingestion pilot with bounded batches and drills.",
            status="complete",
            repo_evidence=[
                "pilot/m24/controlled-ingestion-pilot/m24-p4-controlled-ingestion-pilot.json",
                "pilot/m24/controlled-ingestion-pilot/batches/m24-p4-pilot-batch-001.json",
                "pilot/m24/controlled-ingestion-pilot/batches/m24-p4-pilot-batch-002.json",
                "pilot/m24/controlled-ingestion-pilot/batches/m24-p4-pilot-batch-003.json",
                "tests/test_m24_p4_controlled_ingestion_pilot.py",
            ],
            closure_note=(
                "Three consecutive candidate-only batches and dry-run drills pass; "
                "large-scale ingestion remains separately gated."
            ),
        ),
        P10ProgrammePhase(
            phase="P5",
            handoff_goal="Query and citation-grounded answer acceptance.",
            status="complete_as_internal_candidate",
            repo_evidence=[
                "pilot/m24/query-answer-acceptance/m24-p5-query-answer-acceptance.json",
                "tests/test_m24_p5_query_answer_acceptance.py",
            ],
            closure_note=(
                "Internal lexical evidence bundles and citation verification pass; "
                "production answer serving is not authorized."
            ),
        ),
        P10ProgrammePhase(
            phase="P6",
            handoff_goal="Authenticated internal product deployment.",
            status="complete",
            repo_evidence=[
                "pilot/m24/internal-product-deployment/m24-p6-internal-product-deployment.json",
                "pilot/m24/authenticated-live-url-binding/m24-p9-authenticated-live-url-binding.json",
                "tests/test_m24_p6_internal_product_deployment.py",
                "tests/test_m24_p9_authenticated_live_url_binding.py",
            ],
            closure_note=(
                "The internal product package is deployed behind Cloudflare Access "
                "and unauthenticated probes do not expose release content."
            ),
        ),
        P10ProgrammePhase(
            phase="P7",
            handoff_goal="Production promotion.",
            status="governed_deferred",
            repo_evidence=[
                "docs/architecture/m24/m24-2-semantic-promotion-decision.md",
                "src/knowledge_engine/m24_semantic_hybrid_runtime.py",
                "tests/test_m24_semantic_hybrid_runtime.py",
            ],
            closure_note=(
                "Production remains lexical; semantic, hybrid, and answer serving "
                "promotion require explicit later approval."
            ),
            remaining_trigger=(
                "Approve a production promotion request after semantic promotion "
                "acceptance passes."
            ),
        ),
        P10ProgrammePhase(
            phase="P8",
            handoff_goal="Progressive large-scale ingestion.",
            status="governed_deferred",
            repo_evidence=[
                "pilot/m24/controlled-ingestion-pilot/m24-p4-controlled-ingestion-pilot.json",
                "tests/test_m24_p4_controlled_ingestion_pilot.py",
            ],
            closure_note=(
                "The controlled pilot passed, but the large-scale ingestion gate "
                "remains intentionally blocked until capacity and scale-tier "
                "acceptance are approved."
            ),
            remaining_trigger=(
                "Approve the next scale tier after review throughput, backpressure, "
                "and production promotion prerequisites are satisfied."
            ),
        ),
        P10ProgrammePhase(
            phase="P9",
            handoff_goal="Operational scale, feedback, and maintenance.",
            status="complete_as_internal_candidate",
            repo_evidence=[
                "docs/architecture/m24/m24-12-authenticated-live-url-binding.md",
                "pilot/m24/final-product-closure/m24-p10-final-product-closure.json",
            ],
            closure_note=(
                "Feedback and maintenance lifecycle is codified for operator "
                "handoff; production-impacting maintenance remains gated."
            ),
        ),
        P10ProgrammePhase(
            phase="P10",
            handoff_goal="Final product closure by independent operator exercise.",
            status="pending_external_acceptance",
            repo_evidence=[
                "pilot/m24/final-product-closure/m24-p10-final-product-closure.json",
                "tests/test_m24_p10_final_product_closure.py",
            ],
            closure_note=(
                "The handoff-only replay bundle is ready, but this session cannot "
                "self-certify the required independent-operator exercise."
            ),
            remaining_trigger=(
                "A different qualified operator completes the full unseen-source "
                "exercise from the handoff alone."
            ),
        ),
    ]


def _remaining_items() -> list[P10RemainingItem]:
    return [
        P10RemainingItem(
            item="daniel_authenticated_browser_acceptance",
            status="pending_external_acceptance",
            reason=(
                "Codex observed the Access wall but cannot complete Daniel's "
                "browser login and acceptance on his behalf."
            ),
            trigger_to_complete=(
                "Daniel signs in through Cloudflare Access and accepts the rendered "
                "canonical release."
            ),
            authorized_now=False,
        ),
        P10RemainingItem(
            item="independent_operator_final_exercise",
            status="pending_external_acceptance",
            reason=(
                "The P10 handoff definition requires an operator who did not build "
                "the original path."
            ),
            trigger_to_complete=(
                "A separate qualified operator ingests an unseen source and "
                "reproduces the evidence from the handoff alone."
            ),
            authorized_now=False,
        ),
        P10RemainingItem(
            item="production_semantic_hybrid_retrieval",
            status="governed_deferred",
            reason=(
                "Semantic promotion has not been accepted for production and "
                "production retrieval must remain lexical."
            ),
            trigger_to_complete=(
                "Merge an explicit semantic promotion decision and production "
                "promotion request with rollback evidence."
            ),
            authorized_now=False,
        ),
        P10RemainingItem(
            item="production_answer_serving",
            status="governed_deferred",
            reason=(
                "Internal citation verification exists, but production answer "
                "serving needs separate groundedness, ACL, latency, cost, and "
                "off-switch acceptance."
            ),
            trigger_to_complete=(
                "Approve production answer serving after the semantic promotion "
                "gate and answer-serving acceptance pass."
            ),
            authorized_now=False,
        ),
        P10RemainingItem(
            item="large_scale_ingestion",
            status="governed_deferred",
            reason=(
                "The controlled pilot passed, but scale-tier authority is "
                "intentionally blocked until capacity, backpressure, and production "
                "promotion prerequisites are satisfied."
            ),
            trigger_to_complete=(
                "Approve the first progressive scale tier with measured review "
                "capacity and rollback/deletion drill evidence."
            ),
            authorized_now=False,
        ),
    ]


def build_p10_final_product_closure(
    *,
    output_path: Path = P10_REPORT_PATH,
    include_self_digest: bool = True,
) -> P10FinalClosureReport:
    report = P10FinalClosureReport(
        issue_number=P10_ISSUE_NUMBER,
        release_id=CANONICAL_RELEASE_ID,
        manifest_sha256=CANONICAL_MANIFEST_SHA256,
        source_commit_sha=CANONICAL_SOURCE_SHA,
        reconciliation_base_engine_sha=P10_RECONCILIATION_BASE_ENGINE_SHA,
        pages_project_name=P7_PROJECT_NAME,
        custom_hostname=P7_CUSTOM_HOSTNAME,
        handoff_package=_handoff_package(),
        programme=_programme(),
        readiness=P10ReadinessSummary(
            query="Q2_internal_usable_lexical",
            sigma="S2_internal_deployed_usable_pending_manual_acceptance",
            obsidian="O1_canonical_export_generated",
            answer="A3_citation_verified_internal_candidate",
            relation_aware="candidate_design_only",
        ),
        remaining_items=_remaining_items(),
        maintenance_contract=P10OperationalMaintenanceContract(
            feedback_lifecycle_defined=True,
            freshness_checks_defined=True,
            deletion_tombstones_defined=True,
            supersession_defined=True,
            contradiction_discovery_defined=True,
            alias_duplicate_cleanup_defined=True,
            embedding_migration_requires_gate=True,
            qdrant_rebuild_requires_gate=True,
            graph_schema_migration_requires_gate=True,
            rollback_drills_defined=True,
            review_throughput_reporting_defined=True,
        ),
        closure_decision=P10ClosureDecision(
            status="operator_ready_pending_external_acceptance",
            product_internal_url_status="access_protected",
            production_retrieval="lexical",
            production_semantic_or_hybrid_status="not_authorized",
            large_scale_ingestion_status="not_authorized",
            independent_operator_exercise_status="pending",
            closeout_statement=(
                "M24 is ready for operator handoff as an authenticated internal "
                "lexical product candidate. Final product closure is not self-certified "
                "until Daniel acceptance and a separate independent-operator exercise pass."
            ),
        ),
        authority=P6AuthorityBoundary(),
        evidence_hygiene=[
            "no Cloudflare token values recorded",
            "no operator email recorded",
            "no raw headers recorded",
            "no raw response bodies recorded",
            "no preview full URL committed",
            "no production semantic or hybrid authority asserted",
            "no large-scale ingestion authority asserted",
        ],
    )
    if include_self_digest:
        report.self_sha256 = _digest(report.model_dump(mode="json", exclude={"self_sha256"}))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_json(report.model_dump(mode="json")), encoding="utf-8")
    return report
