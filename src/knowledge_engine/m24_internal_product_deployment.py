from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from .m24_product_surface_integration import (
    CANONICAL_MANIFEST_SHA256,
    CANONICAL_RELEASE_ID,
    CANONICAL_SOURCE_SHA,
    canonical_concept_wiki_page,
    canonical_graph_navigation_state,
    canonical_obsidian_export,
    canonical_runtime_search,
    load_canonical_release,
)
from .m24_query_answer_acceptance import build_p5_query_answer_acceptance_report
from .storage import sha256_bytes

P6_SCHEMA = "knowledge-engine-m24-p6-internal-product-deployment/v1"
P6_ISSUE_NUMBER = 997
DEPLOYMENT_ROOT = Path("pilot/m24/internal-product-deployment")
SITE_ROOT = DEPLOYMENT_ROOT / "site"
SurfaceName = Literal[
    "concept_wiki",
    "lexical_search",
    "sigma_graph_explorer",
    "provenance_source_viewer",
    "citation_grounded_internal_answers",
    "release_viewer",
    "obsidian_export",
]
CSP = (
    "default-src 'none'; "
    "style-src 'self'; "
    "img-src 'self'; "
    "connect-src 'none'; "
    "font-src 'none'; "
    "base-uri 'none'; "
    "form-action 'none'; "
    "frame-ancestors 'none'"
)
SECRET_PATTERNS = (
    re.compile(r"(?i)\b(?:api[_-]?key|secret|token|password)\s*[:=]\s*['\"][^'\"]{8,}"),
    re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/-]{20,}"),
    re.compile(r"CFPAT-[A-Za-z0-9_-]{20,}"),
)


class P6AuthorityBoundary(BaseModel):
    product_audience: Literal["authenticated_internal"] = "authenticated_internal"
    browser_authority: Literal["read_only"] = "read_only"
    production_retrieval: Literal["lexical"] = "lexical"
    semantic_promotion_enabled: bool = False
    semantic_serving_enabled: bool = False
    hybrid_retrieval_enabled: bool = False
    production_answer_serving_enabled: bool = False
    source_mutation: bool = False
    production_pointer_mutation: bool = False
    production_r2_mutation: bool = False
    qdrant_mutation: bool = False
    credential_mutation: bool = False
    traffic_mutation: bool = False
    permanent_ledger_mutation: bool = False
    raw_evidence_exposed: bool = False


class P6AuthContract(BaseModel):
    provider: Literal["cloudflare_access_or_equivalent"] = "cloudflare_access_or_equivalent"
    required: bool = True
    anonymous_access: bool = False
    unauthenticated_behavior: Literal["403"] = "403"
    identity_sources: list[str]
    live_url_status: Literal["pending_cloudflare_access_binding"] = (
        "pending_cloudflare_access_binding"
    )
    manual_daniel_acceptance: Literal["pending_authenticated_url"] = (
        "pending_authenticated_url"
    )


class P6SurfaceDescriptor(BaseModel):
    surface: SurfaceName
    path: str
    release_id: str
    ready: bool
    fallback: str
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class P6DeploymentArtifact(BaseModel):
    path: str
    bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class P6SecurityChecks(BaseModel):
    csp: str
    csp_inline_script_allowed: bool = False
    csp_remote_network_allowed: bool = False
    secret_scan_passed: bool
    secret_scan_patterns: int = Field(ge=1)
    read_only_browser_authority: bool = True
    mutation_routes: list[str] = []
    observability_events: list[str]
    error_states: list[str]
    rollback_plan: list[str]


class P6InternalDeploymentReport(BaseModel):
    schema_version: str = P6_SCHEMA
    status: Literal["internal_product_deployment_package_complete"]
    issue_number: int
    release_id: str
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    deployment_package: str
    auth: P6AuthContract
    surfaces: list[P6SurfaceDescriptor]
    artifacts: list[P6DeploymentArtifact]
    security: P6SecurityChecks
    authority: P6AuthorityBoundary
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


def _write_text(path: Path, text: str) -> P6DeploymentArtifact:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    data = path.read_bytes()
    return P6DeploymentArtifact(
        path=path.as_posix(),
        bytes=len(data),
        sha256=sha256_bytes(data),
    )


def _surface(
    *,
    surface: SurfaceName,
    path: str,
    payload: Any,
    fallback: str,
) -> P6SurfaceDescriptor:
    return P6SurfaceDescriptor(
        surface=surface,
        path=path,
        release_id=CANONICAL_RELEASE_ID,
        ready=True,
        fallback=fallback,
        digest=_digest(payload),
    )


def _index_html() -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="{CSP}">
  <title>LLM Wiki Internal Product</title>
  <link rel="stylesheet" href="styles.css">
</head>
<body>
  <header>
    <p class="eyebrow">Authenticated internal preview</p>
    <h1>LLM Wiki</h1>
    <p class="release">Release {CANONICAL_RELEASE_ID}</p>
    <p class="digest">Manifest {CANONICAL_MANIFEST_SHA256}</p>
  </header>
  <main>
    <section>
      <h2>Surfaces</h2>
      <ul>
        <li><a href="data/concept-wiki-harness.json">Concept Wiki</a></li>
        <li><a href="data/search-harness.json">Lexical Search</a></li>
        <li><a href="data/graph-navigation.json">Sigma Graph Explorer Payload</a></li>
        <li><a href="data/source-viewers.json">Provenance Source Viewer</a></li>
        <li><a href="data/query-answer-acceptance.json">Citation-Grounded Answers</a></li>
        <li><a href="data/release-viewer.json">Release Viewer</a></li>
        <li><a href="data/obsidian-export-manifest.json">Obsidian Export Manifest</a></li>
      </ul>
    </section>
    <section>
      <h2>Authority</h2>
      <p>Read-only internal product. Production retrieval remains lexical. Semantic
      promotion, semantic serving, hybrid retrieval, and production answer serving
      remain disabled.</p>
    </section>
    <section>
      <h2>Error States</h2>
      <ul>
        <li>Unauthenticated requests must return 403.</li>
        <li>Release identity mismatch must block rendering.</li>
        <li>Missing canonical artifact must show a release unavailable state.</li>
        <li>Source/provenance viewer mismatch must show citation unavailable.</li>
      </ul>
    </section>
  </main>
</body>
</html>
"""


def _styles() -> str:
    return """html {
  color-scheme: light;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
    "Segoe UI", sans-serif;
  background: #f8fafc;
  color: #111827;
}

body {
  margin: 0;
}

header,
main {
  margin: 0 auto;
  max-width: 960px;
  padding: 32px 20px;
}

header {
  border-bottom: 1px solid #d1d5db;
}

h1 {
  font-size: 40px;
  line-height: 1.1;
  margin: 8px 0;
}

h2 {
  font-size: 20px;
  margin: 0 0 12px;
}

section {
  border-bottom: 1px solid #e5e7eb;
  padding: 24px 0;
}

ul {
  display: grid;
  gap: 8px;
  list-style: none;
  margin: 0;
  padding: 0;
}

a {
  color: #075985;
}

.eyebrow,
.release,
.digest {
  color: #4b5563;
  margin: 4px 0;
}

.digest {
  overflow-wrap: anywhere;
}
"""


def _release_viewer() -> dict[str, Any]:
    bundle = load_canonical_release()
    return {
        "schema_version": f"{P6_SCHEMA}/release-viewer",
        "release_id": CANONICAL_RELEASE_ID,
        "manifest_sha256": CANONICAL_MANIFEST_SHA256,
        "source_commit_sha": CANONICAL_SOURCE_SHA,
        "counts": bundle.manifest["counts"],
        "artifacts": {
            kind: digest for kind, digest in sorted(bundle.artifact_sha256.items())
        },
        "production_retrieval": "lexical",
        "semantic_serving_enabled": False,
        "hybrid_retrieval_enabled": False,
    }


def _source_viewers_payload() -> dict[str, Any]:
    response = canonical_runtime_search(query="harness", max_results=5)
    return {
        "schema_version": f"{P6_SCHEMA}/source-viewers",
        "release_id": response.release_id,
        "viewer_count": len(response.source_viewers),
        "source_viewers": [item.model_dump(mode="json") for item in response.source_viewers],
    }


def _obsidian_manifest_payload() -> dict[str, Any]:
    export = canonical_obsidian_export()
    return {
        "schema_version": f"{P6_SCHEMA}/obsidian-export-path",
        "release_id": export.release_id,
        "request_id": export.request_id,
        "file_count": len(export.files),
        "manifest_sha256": export.manifest_sha256,
        "concept_note_count": len(
            [item for item in export.files if item.path.startswith("concepts/")]
        ),
        "source_note_count": len(
            [item for item in export.files if item.path.startswith("sources/")]
        ),
        "write_back_authorized": False,
    }


def _secret_scan(paths: list[Path]) -> bool:
    for path in paths:
        text = path.read_text(encoding="utf-8")
        if any(pattern.search(text) for pattern in SECRET_PATTERNS):
            return False
    return True


def build_p6_internal_product_deployment(
    *,
    output_root: Path = DEPLOYMENT_ROOT,
    include_self_digest: bool = True,
) -> P6InternalDeploymentReport:
    site_root = output_root / "site"
    concept = canonical_concept_wiki_page(concept_id="concepts/harness", query="harness")
    search = canonical_runtime_search(query="harness", max_results=5)
    graph = canonical_graph_navigation_state(selected_concept_id="concepts/harness")
    answers = build_p5_query_answer_acceptance_report()
    release = _release_viewer()
    source_viewers = _source_viewers_payload()
    obsidian = _obsidian_manifest_payload()
    data_payloads: list[tuple[str, Any]] = [
        ("data/concept-wiki-harness.json", concept.model_dump(mode="json")),
        ("data/search-harness.json", search.model_dump(mode="json")),
        ("data/graph-navigation.json", graph.model_dump(mode="json")),
        ("data/source-viewers.json", source_viewers),
        ("data/query-answer-acceptance.json", answers.model_dump(mode="json")),
        ("data/release-viewer.json", release),
        ("data/obsidian-export-manifest.json", obsidian),
    ]
    artifacts = [
        _write_text(site_root / "index.html", _index_html()),
        _write_text(site_root / "styles.css", _styles()),
    ]
    for relative, payload in data_payloads:
        artifacts.append(_write_text(site_root / relative, _json(payload)))
    scanned_paths = [
        site_root / artifact.path.removeprefix(site_root.as_posix() + "/")
        for artifact in artifacts
    ]
    secret_scan_passed = _secret_scan(scanned_paths)
    surfaces = [
        _surface(
            surface="concept_wiki",
            path="site/data/concept-wiki-harness.json",
            payload=concept,
            fallback="release_unavailable_error_state",
        ),
        _surface(
            surface="lexical_search",
            path="site/data/search-harness.json",
            payload=search,
            fallback="not_found_with_release_identity",
        ),
        _surface(
            surface="sigma_graph_explorer",
            path="site/data/graph-navigation.json",
            payload=graph,
            fallback="textual_graph_fallback",
        ),
        _surface(
            surface="provenance_source_viewer",
            path="site/data/source-viewers.json",
            payload=source_viewers,
            fallback="citation_unavailable_error_state",
        ),
        _surface(
            surface="citation_grounded_internal_answers",
            path="site/data/query-answer-acceptance.json",
            payload=answers,
            fallback="safe_answer_fallbacks_from_P5",
        ),
        _surface(
            surface="release_viewer",
            path="site/data/release-viewer.json",
            payload=release,
            fallback="release_identity_mismatch_block",
        ),
        _surface(
            surface="obsidian_export",
            path="site/data/obsidian-export-manifest.json",
            payload=obsidian,
            fallback="regenerate_export_from_canonical_release",
        ),
    ]
    report = P6InternalDeploymentReport(
        status="internal_product_deployment_package_complete",
        issue_number=P6_ISSUE_NUMBER,
        release_id=CANONICAL_RELEASE_ID,
        manifest_sha256=CANONICAL_MANIFEST_SHA256,
        source_commit_sha=CANONICAL_SOURCE_SHA,
        deployment_package=site_root.as_posix(),
        auth=P6AuthContract(
            identity_sources=[
                "Cloudflare Access JWT",
                "equivalent signed internal session",
            ],
        ),
        surfaces=surfaces,
        artifacts=artifacts,
        security=P6SecurityChecks(
            csp=CSP,
            secret_scan_passed=secret_scan_passed,
            secret_scan_patterns=len(SECRET_PATTERNS),
            observability_events=[
                "authenticated_view",
                "release_identity_loaded",
                "surface_opened",
                "safe_fallback_rendered",
                "error_state_rendered",
            ],
            error_states=[
                "403_unauthenticated",
                "release_identity_mismatch",
                "release_unavailable",
                "citation_unavailable",
                "obsidian_export_unavailable",
            ],
            rollback_plan=[
                "disable internal route or Access application",
                "restore previous deployment package",
                "keep production retrieval lexical",
                "verify no Source/R2/Qdrant/pointer/traffic mutation occurred",
            ],
        ),
        authority=P6AuthorityBoundary(),
    )
    if include_self_digest:
        report.self_sha256 = _digest(report.model_dump(mode="json", exclude={"self_sha256"}))
    report_path = output_root / "m24-p6-internal-product-deployment.json"
    _write_text(report_path, _json(report.model_dump(mode="json")))
    return report
