#!/usr/bin/env python3
"""Apply the deterministic M25.9 Pages exact-project preflight repair."""

from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one replacement, found {count}")
    file.write_text(text.replace(old, new, 1))


def main() -> None:
    script = "scripts/m25_9_cloudflare_live_preflight.py"
    replace_once(
        script,
        '''        records, pages_projects_payload = request_json(
            label="pages_dedicated",
            endpoint="pages_projects",
            url=f"{API_ROOT}/accounts/{account_id}/pages/projects?per_page=100",
            token=pages_token,
            requester=requester,
            timeout=timeout,
            max_attempts=max_attempts,
        )
        evidence["probes"].extend(records)
        require_pass(records, "pages_projects")
        projects = result_list(pages_projects_payload, "pages_projects")
        project_found = any(item.get("name") == pages_project for item in projects)
        evidence["resource_checks"]["target_pages_project_found"] = project_found
        if not project_found:
            raise PreflightFailure("target_pages_project_not_found")
''',
        '''        encoded_project = urllib.parse.quote(pages_project, safe="")
        records, pages_project_payload = request_json(
            label="pages_dedicated",
            endpoint="pages_project",
            url=f"{API_ROOT}/accounts/{account_id}/pages/projects/{encoded_project}",
            token=pages_token,
            requester=requester,
            timeout=timeout,
            max_attempts=max_attempts,
        )
        evidence["probes"].extend(records)
        require_pass(records, "pages_project")
        project = result_object(pages_project_payload, "pages_project")
        project_found = project.get("name") == pages_project
        evidence["resource_checks"]["target_pages_project_found"] = project_found
        if not project_found:
            raise PreflightFailure("target_pages_project_not_found")
''',
    )
    replace_once(
        script,
        '''
        encoded_project = urllib.parse.quote(pages_project, safe="")
        records, deployments_payload = request_json(
''',
        '''
        records, deployments_payload = request_json(
''',
    )

    tests = "tests/test_m25_9_cloudflare_live_preflight.py"
    replace_once(
        tests,
        '''    if "/pages/projects?" in url:
        return "pages_projects"
''',
        '''    if url.endswith(f"/pages/projects/{PROJECT}"):
        return "pages_project"
''',
    )
    replace_once(
        tests,
        '''    if endpoint == "pages_projects":
        return {"success": True, "result": [{"name": PROJECT}]}
''',
        '''    if endpoint == "pages_project":
        return {"success": True, "result": {"name": PROJECT}}
''',
    )
    replace_once(
        tests,
        '''    for endpoint in ("pages_projects", "pages_deployments"):
''',
        '''    for endpoint in ("pages_project", "pages_deployments"):
''',
    )
    replace_once(
        tests,
        '''    outcomes[("pages-token", "pages_projects")] = [
''',
        '''    outcomes[("pages-token", "pages_project")] = [
''',
    )
    replace_once(
        tests,
        '''if item["endpoint"] == "pages_projects"][-1]
''',
        '''if item["endpoint"] == "pages_project"][-1]
''',
    )

    workflow = ".github/workflows/m25-9-blog-full-population-pilot.yml"
    replace_once(
        workflow,
        '''          expected="$(printf '%s\\n' \\
            '.github/workflows/m25-9-blog-full-population-pilot.yml' \\
            'docs/architecture/m25/m25-9-live-preflight-repair.md' \\
            'scripts/m25_9_cloudflare_live_preflight.py' \\
            'tests/test_m25_9_cloudflare_live_preflight.py' | sort)"
''',
        '''          expected="$(printf '%s\\n' \\
            '.github/workflows/m25-9-blog-full-population-pilot.yml' \\
            'scripts/m25_9_cloudflare_live_preflight.py' \\
            'tests/test_m25_9_cloudflare_live_preflight.py' | sort)"
''',
    )


if __name__ == "__main__":
    main()
