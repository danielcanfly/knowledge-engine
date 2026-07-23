from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BATCH = ROOT / "pilot" / "m25" / "m25-6-review-batch.json"
PLAN = ROOT / "pilot" / "m25" / "m25-6-browser-acceptance-plan.json"
USERNAME = "browser-reviewer"
PASSWORD = "browser-acceptance-secret"


def _port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _wait(url: str) -> None:
    for _ in range(100):
        try:
            response = httpx.get(
                f"{url}/v1/review/capabilities",
                auth=(USERNAME, PASSWORD),
                timeout=1,
            )
            if response.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.1)
    raise RuntimeError("review server did not become ready")


def run(output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    screenshots = output / "screenshots"
    screenshots.mkdir(exist_ok=True)
    ledger = Path(tempfile.mkdtemp(prefix="m25-6-ledger-"))
    port = _port()
    url = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(ROOT / "src"),
            "M25_REVIEW_BATCH": str(BATCH),
            "M25_REVIEW_LEDGER": str(ledger),
            "M25_REVIEW_USERNAME": USERNAME,
            "M25_REVIEW_PASSWORD": PASSWORD,
        }
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "knowledge_engine.m25_review_demo:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=ROOT,
        env=env,
    )
    try:
        _wait(url)
        unauthenticated = httpx.get(f"{url}/review", timeout=5)
        if unauthenticated.status_code != 401:
            raise AssertionError("review UI did not require authentication")
        plan = json.loads(PLAN.read_text(encoding="utf-8"))
        evidence: list[dict[str, Any]] = []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(
                http_credentials={"username": USERNAME, "password": PASSWORD},
                viewport={"width": 1440, "height": 1050},
            )
            page = context.new_page()
            page.goto(f"{url}/review", wait_until="networkidle")
            if "M25.6 Human Review Console" not in page.title() and (
                page.locator("text=M25.6 Human Review Console").count() == 0
            ):
                raise AssertionError("review console did not render")
            for index, scenario in enumerate(plan["scenarios"], start=1):
                page.locator(f'[data-item-key="{scenario["item_id"]}"]').click()
                page.wait_for_timeout(150)
                page.select_option("#action", scenario["action"])
                page.fill("#rationale", f"Browser acceptance: {scenario['scenario_id']}")
                if scenario["action"] == "map":
                    page.fill("#mapping", scenario["mapping_target"])
                if scenario["action"] == "edit":
                    page.fill("#edited", json.dumps(scenario["edited_payload"]))
                if scenario["action"] == "split":
                    page.fill("#split", json.dumps(scenario["split_payload"]))
                for checkbox in ("#ack-evidence", "#ack-comparison", "#ack-diff"):
                    page.check(checkbox)
                before = screenshots / f"{index:02d}-{scenario['scenario_id']}-before.png"
                page.screenshot(path=str(before), full_page=True)
                page.click("button.submit")
                page.locator("#decision-status").wait_for(state="visible")
                page.wait_for_function(
                    "document.querySelector('#decision-status').textContent.includes('Recorded')"
                )
                after = screenshots / f"{index:02d}-{scenario['scenario_id']}-after.png"
                page.screenshot(path=str(after), full_page=True)
                evidence.append(
                    {
                        "scenario_id": scenario["scenario_id"],
                        "item_id": scenario["item_id"],
                        "action": scenario["action"],
                        "before_screenshot": before.name,
                        "before_sha256": _sha(before),
                        "after_screenshot": after.name,
                        "after_sha256": _sha(after),
                        "result": "passed",
                    }
                )
            browser.close()
        audit = httpx.get(
            f"{url}/v1/review/audit",
            auth=(USERNAME, PASSWORD),
            timeout=10,
        ).json()
        if audit["decision_count"] != 6 or audit["admission_ready"] is not False:
            raise AssertionError("browser decisions did not preserve incomplete-review blocking")
        report = {
            "schema_version": "knowledge-engine-m25-6-browser-evidence/v1",
            "status": "browser_candidate_verified",
            "unauthenticated_review_status": unauthenticated.status_code,
            "authenticated_route": "/review",
            "scenario_count": len(evidence),
            "scenarios": evidence,
            "audit_summary": {
                "decision_count": audit["decision_count"],
                "terminal_item_count": audit["terminal_item_count"],
                "deferred_item_count": audit["deferred_item_count"],
                "pending_item_count": audit["pending_item_count"],
                "review_complete": audit["review_complete"],
                "admission_ready": audit["admission_ready"],
                "source_write_permitted": audit["source_write_permitted"],
                "github_pr_creation_permitted": audit["github_pr_creation_permitted"],
                "m25_7_authorized": audit["m25_7_authorized"],
                "audit_sha256": audit["audit_sha256"],
            },
            "candidate_only": True,
            "daniel_browser_acceptance_recorded": False,
        }
        (output / "browser-evidence.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (output / "audit-export.json").write_text(
            json.dumps(audit, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return report
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/m25-6-browser-evidence")
    print(json.dumps(run(target), indent=2, sort_keys=True))
