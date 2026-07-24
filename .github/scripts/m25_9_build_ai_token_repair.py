# ruff: noqa: E501
#!/usr/bin/env python3
"""Build an unreachable, exact-boundary M25.9 Workers AI credential repair commit."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import urllib.request
from pathlib import Path
from typing import Any

WORKFLOW = Path(".github/workflows/m25-9-blog-full-population-pilot.yml")
DOCS = Path("docs/architecture/m25/m25-9-live-preflight-repair.md")
PREFLIGHT_SCRIPT = "scripts/m25_9_cloudflare_live_preflight.py"
PREFLIGHT_TEST = "tests/test_m25_9_cloudflare_live_preflight.py"
CHANGED_PATHS = [
    str(WORKFLOW),
    str(DOCS),
    PREFLIGHT_SCRIPT,
    PREFLIGHT_TEST,
]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one replacement, found {count}")
    path.write_text(text.replace(old, new, 1))


def apply_repair() -> None:
    replace_once(
        WORKFLOW,
        """      QDRANT_URL: ${{ secrets.QDRANT_URL }}
      QDRANT_API_KEY: ${{ secrets.QDRANT_API_KEY }}
      CLOUDFLARE_ACCOUNT_ID: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}
      CLOUDFLARE_PAGES_TOKEN: ${{ secrets.CLOUDFLARE_PAGES_TOKEN }}
""",
        """      QDRANT_URL: ${{ secrets.QDRANT_URL }}
      QDRANT_API_KEY: ${{ secrets.QDRANT_API_KEY }}
      CLOUDFLARE_ACCOUNT_ID: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}
      CLOUDFLARE_AI_TOKEN: ${{ secrets.CLOUDFLARE_API_TOKEN }}
      CLOUDFLARE_PAGES_TOKEN: ${{ secrets.CLOUDFLARE_PAGES_TOKEN }}
""",
    )
    replace_once(
        WORKFLOW,
        """            QDRANT_URL QDRANT_API_KEY CLOUDFLARE_ACCOUNT_ID \\
            CLOUDFLARE_PAGES_TOKEN CLOUDFLARE_WORKERS_TOKEN \\
""",
        """            QDRANT_URL QDRANT_API_KEY CLOUDFLARE_ACCOUNT_ID \\
            CLOUDFLARE_AI_TOKEN CLOUDFLARE_PAGES_TOKEN CLOUDFLARE_WORKERS_TOKEN \\
""",
    )
    replace_once(
        WORKFLOW,
        """          mkdir -p "$WORK_DIR/evidence"
      - name: Install runtime dependencies
""",
        """          mkdir -p "$WORK_DIR/evidence"
      - name: Verify explicit Workers AI embedding capability
        run: |
          set -euo pipefail
          python - <<'PYAI'
          import json
          import os
          import urllib.error
          import urllib.parse
          import urllib.request

          account = os.environ['CLOUDFLARE_ACCOUNT_ID']
          token = os.environ['CLOUDFLARE_AI_TOKEN']
          model = '@cf/baai/bge-m3'
          query = urllib.parse.urlencode({'model': model})
          request = urllib.request.Request(
              url=(
                  'https://api.cloudflare.com/client/v4/accounts/'
                  f'{account}/ai/models/schema?{query}'
              ),
              method='GET',
              headers={
                  'Authorization': f'Bearer {token}',
                  'Accept': 'application/json',
                  'User-Agent': 'knowledge-engine-m25.9-workers-ai-preflight/1',
              },
          )
          try:
              with urllib.request.urlopen(request, timeout=20) as response:
                  body = response.read(524288)
                  status = response.status
          except urllib.error.HTTPError as exc:
              status = exc.code
              body = exc.read(524288)
          try:
              payload = json.loads(body.decode('utf-8'))
          except Exception as exc:
              raise SystemExit(
                  f'Workers AI model-schema preflight returned invalid JSON (HTTP {status})'
              ) from exc
          if (
              status != 200
              or not isinstance(payload, dict)
              or payload.get('success') is not True
              or not isinstance(payload.get('result'), dict)
          ):
              code = None
              errors = payload.get('errors') if isinstance(payload, dict) else None
              if isinstance(errors, list) and errors and isinstance(errors[0], dict):
                  code = errors[0].get('code')
              raise SystemExit(
                  f'Workers AI model-schema preflight failed (HTTP {status}, code {code})'
              )
          print('workers_ai_embedding_capability=pass')
          PYAI
      - name: Install runtime dependencies
""",
    )
    replace_once(
        WORKFLOW,
        """      - name: Build, embed, fully verify Qdrant, and publish R2 candidate
        env:
          GITHUB_TOKEN: ${{ github.token }}
""",
        """      - name: Build, embed, fully verify Qdrant, and publish R2 candidate
        env:
          GITHUB_TOKEN: ${{ github.token }}
          CLOUDFLARE_API_TOKEN: ${{ env.CLOUDFLARE_AI_TOKEN }}
""",
    )

    replace_once(
        DOCS,
        "The M25.9 pilot uses three explicit credentials and never falls back silently:",
        "The M25.9 pilot uses four explicit credential roles and never falls back silently:",
    )
    replace_once(
        DOCS,
        """| `CLOUDFLARE_PAGES_TOKEN` | Read, deploy and roll back the existing Pages project | Account `Pages Write`, scoped to the exact account |
""",
        """| `CLOUDFLARE_API_TOKEN`, exposed only as `CLOUDFLARE_AI_TOKEN` | Run BGE-M3 embedding through the Workers AI REST API | Account `Workers AI Read` and `Workers AI Edit`, scoped to the exact account |
| `CLOUDFLARE_PAGES_TOKEN` | Read, deploy and roll back the existing Pages project | Account `Pages Write`, scoped to the exact account |
""",
    )
    replace_once(
        DOCS,
        "The existing `CLOUDFLARE_ACCOUNT_ID` remains the account identity. Secret values must be entered only in GitHub Settings and must never be pasted into issues, pull requests, logs or chat.",
        "The existing `CLOUDFLARE_ACCOUNT_ID` remains the account identity. The Workers AI source secret is exposed to the candidate build only through the role-specific `CLOUDFLARE_AI_TOKEN` alias and is never used as a Pages, Workers management or Access fallback. Secret values must be entered only in GitHub Settings and must never be pasted into issues, pull requests, logs or chat.",
    )
    replace_once(
        DOCS,
        """3. lists the exact Pages project and captures the previous production deployment;
4. lists Workers scripts, resolves the exact active zone and verifies Workers route access;
5. finds the exact Access application for `m24-internal.danielcanfly.com`;
6. verifies the Access organization and auth-domain binding;
7. records HTTP status, Cloudflare success, bounded error code/category and retry attempts;
8. uploads only sanitized evidence;
9. exits before external mutation if any capability is missing.
""",
        """3. validates the BGE-M3 Workers AI model schema with the role-specific AI credential;
4. lists the exact Pages project and captures the previous production deployment;
5. lists Workers scripts, resolves the exact active zone and verifies Workers route access;
6. finds the exact Access application for `m24-internal.danielcanfly.com`;
7. verifies the Access organization and auth-domain binding;
8. records HTTP status, Cloudflare success, bounded error code/category and retry attempts;
9. uploads only sanitized evidence;
10. exits before external mutation if any capability is missing.
""",
    )
    replace_once(
        DOCS,
        "The repair pull request must remain unmerged until all three dedicated GitHub environment secrets exist.",
        "The repair pull request must remain unmerged until all four credential roles exist in the GitHub environment.",
    )


def validate_repair() -> None:
    workflow = WORKFLOW.read_text()
    docs = DOCS.read_text()
    preflight_block = workflow.split("  cloudflare-preflight:", 1)[1].split(
        "  deploy:", 1
    )[0]
    deploy_block = workflow.split("  deploy:", 1)[1]

    assert "CLOUDFLARE_AI_TOKEN" not in preflight_block
    assert "CLOUDFLARE_AI_TOKEN: ${{ secrets.CLOUDFLARE_API_TOKEN }}" in deploy_block
    assert "CLOUDFLARE_API_TOKEN: ${{ env.CLOUDFLARE_AI_TOKEN }}" in deploy_block
    assert "ai/models/schema?{query}" in deploy_block
    assert "workers_ai_embedding_capability=pass" in deploy_block
    assert "CLOUDFLARE_AI_TOKEN CLOUDFLARE_PAGES_TOKEN" in deploy_block
    assert "role-specific `CLOUDFLARE_AI_TOKEN` alias" in docs
    assert workflow.count(
        "CLOUDFLARE_AI_TOKEN: ${{ secrets.CLOUDFLARE_API_TOKEN }}"
    ) == 1
    assert workflow.count(
        "CLOUDFLARE_API_TOKEN: ${{ env.CLOUDFLARE_AI_TOKEN }}"
    ) == 1

    changed = sorted(
        subprocess.check_output(["git", "diff", "--name-only"], text=True).splitlines()
    )
    if changed != sorted([str(WORKFLOW), str(DOCS)]):
        raise SystemExit(f"unexpected content changes: {changed}")


def github_api(method: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    repository = os.environ["GITHUB_REPOSITORY"]
    token = os.environ["GH_TOKEN"]
    request = urllib.request.Request(
        url=f"https://api.github.com/repos/{repository}/{path}",
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
        data=json.dumps(payload).encode(),
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        value = json.loads(response.read().decode())
    if not isinstance(value, dict):
        raise SystemExit(f"GitHub API returned non-object for {path}")
    return value


def create_blob(path: Path) -> str:
    value = github_api(
        "POST",
        "git/blobs",
        {
            "content": base64.b64encode(path.read_bytes()).decode(),
            "encoding": "base64",
        },
    )
    return str(value["sha"])


def existing_blob(path: str) -> str:
    output = subprocess.check_output(["git", "ls-tree", "HEAD", "--", path], text=True)
    fields = output.strip().split()
    if len(fields) < 3:
        raise SystemExit(f"cannot resolve blob for {path}")
    return fields[2]


def create_repair_object() -> dict[str, Any]:
    parent = os.environ["GITHUB_SHA"]
    workflow_blob = create_blob(WORKFLOW)
    docs_blob = create_blob(DOCS)
    tree = github_api(
        "POST",
        "git/trees",
        {
            "base_tree": parent,
            "tree": [
                {
                    "path": str(WORKFLOW),
                    "mode": "100644",
                    "type": "blob",
                    "sha": workflow_blob,
                },
                {
                    "path": str(DOCS),
                    "mode": "100644",
                    "type": "blob",
                    "sha": docs_blob,
                },
                {
                    "path": PREFLIGHT_SCRIPT,
                    "mode": "100644",
                    "type": "blob",
                    "sha": existing_blob(PREFLIGHT_SCRIPT),
                },
                {
                    "path": PREFLIGHT_TEST,
                    "mode": "100644",
                    "type": "blob",
                    "sha": existing_blob(PREFLIGHT_TEST),
                },
            ],
        },
    )
    commit = github_api(
        "POST",
        "git/commits",
        {
            "message": "Repair M25.9 Workers AI credential injection",
            "tree": tree["sha"],
            "parents": [parent],
        },
    )
    return {
        "schema_version": "knowledge-engine-m25-9-ai-token-repair-object/v1",
        "parent_sha": parent,
        "tree_sha": tree["sha"],
        "commit_sha": commit["sha"],
        "changed_paths": CHANGED_PATHS,
        "workflow_content_changed": True,
        "docs_content_changed": True,
        "preflight_script_content_changed": False,
        "preflight_test_content_changed": False,
        "external_service_mutations": 0,
    }


def main() -> None:
    output_dir = Path(os.environ["OUTPUT_DIR"])
    apply_repair()
    validate_repair()
    subprocess.run(
        [
            "python",
            "-m",
            "pytest",
            "-q",
            "tests/test_m25_9_cloudflare_live_preflight.py",
            "tests/test_m25_10_blog_live_candidate.py",
        ],
        check=True,
    )
    evidence = create_repair_object()
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "repair-commit.json").write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(evidence, sort_keys=True))


if __name__ == "__main__":
    main()
