from __future__ import annotations

import json
import subprocess
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from knowledge_engine.m24_14_6_authenticated_performance import (
    BENCHMARK_CASE_IDS,
    M24_14_6_ACCEPTED_VAULT_SHA256,
    validate_local_regression_result,
)
from knowledge_engine.m24_internal_product_deployment import (
    SITE_ROOT,
    build_p6_internal_product_deployment,
)
from knowledge_engine.m24_product_surface_integration import CANONICAL_RELEASE_ID


def test_m24_14_6_local_browser_regression_runs_exact_site_without_live_authority(
    tmp_path: Path,
) -> None:
    build_p6_internal_product_deployment()
    handler = partial(SimpleHTTPRequestHandler, directory=SITE_ROOT.as_posix())
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    output = tmp_path / "local-regression.json"
    try:
        base = f"http://127.0.0.1:{server.server_port}/"
        subprocess.run(
            [
                sys.executable,
                "scripts/m24_14_6_authenticated_benchmark.py",
                "--local-regression",
                "--base-url",
                base,
                "--deployment-id",
                "local-exact-site",
                "--cold-iterations",
                "1",
                "--warm-iterations",
                "1",
                "--output",
                output.as_posix(),
            ],
            check=True,
            cwd=Path.cwd(),
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    result = json.loads(output.read_text(encoding="utf-8"))
    validate_local_regression_result(result)
    assert result["authority"] == "local_exact_site_browser_regression"
    assert result["authority"] != "authenticated_live"
    assert result["deployment_id"] == "local-exact-site"
    assert result["identities"]["deployment_id"] == "local-exact-site"
    assert result["identities"]["release_id"] == CANONICAL_RELEASE_ID
    assert result["identities"]["vault_sha256"] == M24_14_6_ACCEPTED_VAULT_SHA256
    assert set(result["cases"]) == set(BENCHMARK_CASE_IDS)
    assert set(result["viewport_results"]) == {"1440x900", "1024x768", "768x900", "390x844"}
    assert "interactions" in result
    assert result["recomputed_aggregates"]["decision"] == result["decision"]
    assert result["errors"]["console_errors"] == 0
    assert result["errors"]["page_errors"] == 0
    assert result["errors"]["failed_required_same_origin_requests"] == 0
    assert result["cases"]["sigma_graph"]["evidence"]["node_count"] == 20
    assert result["cases"]["sigma_graph"]["evidence"]["node_count_source"] == "graph_payload_fetch"
    assert result["cases"]["source_full_markdown"]["evidence"]["deep_marker_present"] is True
    assert result["cases"]["source_structured_json"]["evidence"]["parseable_json"] is True
    assert result["cases"]["obsidian_vault"]["evidence"]["concept_notes"] == 20
    assert result["cases"]["obsidian_vault"]["evidence"]["source_notes"] == 7
