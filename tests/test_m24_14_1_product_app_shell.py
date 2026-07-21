from __future__ import annotations

import json
import threading
import urllib.request
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from scripts.m23_7_r3_8_remote_operator import canonical_sha256

from knowledge_engine.m24_14_product_app_shell import (
    P1_REPORT_PATH,
    P1_ROUTES,
    build_p1_product_app_shell_report,
)
from knowledge_engine.m24_internal_product_deployment import CSP, SITE_ROOT


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_m24_14_1_report_is_digest_bound() -> None:
    report = _json(P1_REPORT_PATH)
    unsigned = dict(report)
    digest = unsigned.pop("self_sha256")

    assert canonical_sha256(unsigned) == digest


def test_m24_14_1_report_matches_generated_app_shell_evidence() -> None:
    report = build_p1_product_app_shell_report()

    assert report.model_dump(mode="json") == _json(P1_REPORT_PATH)
    assert report.status == "m24_14_1_product_application_shell_implemented"


def test_m24_14_1_shell_has_required_routes_and_states() -> None:
    report = build_p1_product_app_shell_report()
    index = SITE_ROOT.joinpath("index.html").read_text(encoding="utf-8")
    app_js = SITE_ROOT.joinpath("app.js").read_text(encoding="utf-8")

    assert '<script type="module" src="app.js"></script>' in index
    assert '<main id="app-main"' in index
    assert 'id="app"' in index
    assert {item.route for item in report.route_evidence} == set(P1_ROUTES)
    assert all(item.nonblank_browser_smoke for item in report.route_evidence)
    for route in P1_ROUTES:
        assert f"{route}:" in app_js
        expected_hash = "#/wiki?concept=concepts/harness" if route == "wiki" else f"#/{route}"
        assert f'href="{expected_hash}"' in index
    for state in [
        "missing-artifact",
        "release identity mismatch",
        "acl-denied",
        "bounded-error",
        "no-match",
    ]:
        assert state in app_js


def test_m24_14_1_validates_release_identity_and_same_origin_artifacts() -> None:
    report = build_p1_product_app_shell_report()
    app_js = SITE_ROOT.joinpath("app.js").read_text(encoding="utf-8")

    assert report.release_id in app_js
    assert report.manifest_sha256 in app_js
    assert "validateIdentity" in app_js
    assert "fetch(path, { cache: \"no-store\" })" in app_js
    assert "http://" not in app_js
    assert "https://" not in app_js
    assert "semantic or hybrid serving is not authorized" in app_js


def test_m24_14_1_csp_security_and_authority_boundaries_are_preserved() -> None:
    report = build_p1_product_app_shell_report()

    assert report.security.csp == CSP
    assert "script-src 'self'" in report.security.csp
    assert "connect-src 'self'" in report.security.csp
    assert report.security.runtime_cdn_dependencies is False
    assert report.security.external_network_dependencies is False
    assert report.security.inline_script_allowed is False
    assert report.security.mutation_controls_present is False
    assert report.security.secret_scan_passed is True
    assert report.security.same_origin_artifact_fetch_only is True
    assert report.authority.production_retrieval == "lexical"
    assert report.authority.semantic_promotion_enabled is False
    assert report.authority.semantic_serving_enabled is False
    assert report.authority.hybrid_retrieval_enabled is False
    assert report.authority.production_answer_serving_enabled is False
    assert report.authority.source_mutation is False
    assert report.authority.production_pointer_mutation is False
    assert report.authority.production_r2_mutation is False
    assert report.authority.qdrant_mutation is False
    assert report.authority.credential_mutation is False
    assert report.authority.traffic_mutation is False


def test_m24_14_1_artifact_manifest_matches_site_bytes() -> None:
    report = build_p1_product_app_shell_report()

    artifact_paths = {item.path for item in report.artifacts}
    assert SITE_ROOT.joinpath("index.html").as_posix() in artifact_paths
    assert SITE_ROOT.joinpath("styles.css").as_posix() in artifact_paths
    assert SITE_ROOT.joinpath("app.js").as_posix() in artifact_paths
    for artifact in report.artifacts:
        path = Path(artifact.path)
        data = path.read_bytes()
        assert len(data) == artifact.bytes


def test_m24_14_1_local_http_smoke_serves_shell_and_same_origin_artifacts() -> None:
    handler = partial(SimpleHTTPRequestHandler, directory=SITE_ROOT.as_posix())
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        for path in [
            "/",
            "/app.js",
            "/styles.css",
            "/data/release-viewer.json",
            "/data/graph-navigation.json",
        ]:
            with urllib.request.urlopen(base + path, timeout=5) as response:
                body = response.read().decode("utf-8")
            assert response.status == 200
            assert body.strip()
    finally:
        server.shutdown()
        thread.join(timeout=5)
