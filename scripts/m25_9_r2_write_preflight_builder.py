from __future__ import annotations

from pathlib import Path
from textwrap import dedent


WORKFLOW = Path(".github/workflows/m25-9-blog-full-population-pilot.yml")
DOCS = Path("docs/architecture/m25/m25-9-live-preflight-repair.md")
SCRIPT = Path("scripts/m25_9_r2_write_preflight.py")
TESTS = Path("tests/test_m25_9_r2_write_preflight.py")
EXPECTED_PATHS = (
    WORKFLOW.as_posix(),
    DOCS.as_posix(),
    SCRIPT.as_posix(),
    TESTS.as_posix(),
)


def _find(lines: list[str], value: str, *, start: int = 0) -> int:
    for index in range(start, len(lines)):
        if lines[index] == value:
            return index
    raise RuntimeError(f"line not found after {start}: {value!r}")


def _find_prefix(lines: list[str], value: str, *, start: int = 0) -> int:
    for index in range(start, len(lines)):
        if lines[index].startswith(value):
            return index
    raise RuntimeError(f"line prefix not found after {start}: {value!r}")


def _replace_once_in_range(
    lines: list[str], *, start: int, stop: int, old: str, new: str
) -> None:
    indexes = [index for index in range(start, stop) if lines[index] == old]
    if len(indexes) != 1:
        raise RuntimeError(
            f"expected one line in range {start}:{stop}: {old!r}; "
            f"found {len(indexes)}"
        )
    lines[indexes[0]] = new


def _insert_after_once(
    lines: list[str], *, start: int, stop: int, anchor: str, values: list[str]
) -> None:
    if all(value in lines[start:stop] for value in values):
        return
    indexes = [index for index in range(start, stop) if lines[index] == anchor]
    if len(indexes) != 1:
        raise RuntimeError(
            f"expected one anchor in range {start}:{stop}: {anchor!r}; "
            f"found {len(indexes)}"
        )
    lines[indexes[0] + 1 : indexes[0] + 1] = values


def write_script() -> None:
    SCRIPT.write_text(
        dedent(
            '''
            from __future__ import annotations

            import argparse
            import hashlib
            import json
            import os
            from pathlib import Path
            from typing import Any

            from botocore.exceptions import ClientError

            from knowledge_engine.config import Settings
            from knowledge_engine.errors import ReleaseConflictError
            from knowledge_engine.storage import ObjectStore, create_object_store, sha256_bytes


            SCHEMA_VERSION = "knowledge-engine-m25-9-r2-write-preflight/v1"


            def _error_details(exc: Exception) -> tuple[str, int | None, str]:
                if isinstance(exc, ClientError):
                    response = exc.response if isinstance(exc.response, dict) else {}
                    error = response.get("Error", {})
                    metadata = response.get("ResponseMetadata", {})
                    code = str(error.get("Code") or type(exc).__name__)
                    status_raw = metadata.get("HTTPStatusCode")
                    status = int(status_raw) if isinstance(status_raw, int) else None
                    if code == "AccessDenied" or status == 403:
                        category = "r2_put_object_access_denied"
                    elif code in {"Unauthorized", "InvalidAccessKeyId"} or status == 401:
                        category = "r2_authentication_failed"
                    elif code == "SignatureDoesNotMatch":
                        category = "r2_signature_mismatch"
                    else:
                        category = "r2_client_error"
                    return category, status, code
                if isinstance(exc, ReleaseConflictError):
                    return "r2_canary_key_conflict", None, type(exc).__name__
                return "r2_unexpected_error", None, type(exc).__name__


            def run_preflight(
                *,
                store: ObjectStore,
                key: str,
                payload: bytes,
                identity: dict[str, Any],
            ) -> dict[str, Any]:
                digest = sha256_bytes(payload)
                evidence: dict[str, Any] = {
                    "schema_version": SCHEMA_VERSION,
                    "key_sha256": hashlib.sha256(key.encode()).hexdigest(),
                    "payload_bytes": len(payload),
                    "payload_sha256": digest,
                    "identity": identity,
                    "put_succeeded": False,
                    "read_verified": False,
                    "delete_succeeded": False,
                    "residual_object_present": None,
                    "bounded_mutation_count": 0,
                    "secret_values_recorded": False,
                }
                created = False
                failure: Exception | None = None
                try:
                    if store.head(key) is not None:
                        raise ReleaseConflictError("R2 write-preflight canary key already exists")
                    store.put(
                        key,
                        payload,
                        content_type="application/json",
                        sha256=digest,
                        only_if_absent=True,
                    )
                    created = True
                    evidence["put_succeeded"] = True
                    evidence["bounded_mutation_count"] = 1
                    remote = store.get(key)
                    if len(remote) != len(payload) or sha256_bytes(remote) != digest:
                        raise RuntimeError("R2 write-preflight read-back digest mismatch")
                    evidence["read_verified"] = True
                except Exception as exc:
                    failure = exc
                finally:
                    if created:
                        try:
                            store.delete(key)
                            evidence["delete_succeeded"] = True
                            evidence["bounded_mutation_count"] = 2
                        except Exception as exc:
                            if failure is None:
                                failure = exc
                    try:
                        evidence["residual_object_present"] = store.head(key) is not None
                    except Exception as exc:
                        evidence["residual_object_present"] = None
                        if failure is None:
                            failure = exc

                if failure is None and evidence["residual_object_present"] is False:
                    evidence["status"] = "pass"
                    evidence["root_cause_classification"] = "r2_object_read_write_capability_pass"
                else:
                    category, http_status, error_code = _error_details(
                        failure or RuntimeError("R2 write-preflight residual object detected")
                    )
                    if evidence["residual_object_present"] is True:
                        category = "r2_canary_cleanup_failed_residual_present"
                    evidence["status"] = "fail"
                    evidence["root_cause_classification"] = category
                    evidence["http_status"] = http_status
                    evidence["error_code"] = error_code
                evidence["zero_residual_objects"] = (
                    evidence["residual_object_present"] is False
                )
                evidence["evidence_sha256"] = hashlib.sha256(
                    json.dumps(
                        evidence,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest()
                return evidence


            def _identity(settings: Settings) -> dict[str, str | bool]:
                endpoint = settings.r2_endpoint_url or ""
                bucket = settings.r2_bucket or ""
                access_key = settings.r2_access_key_id or ""
                return {
                    "backend_is_r2": settings.object_store_backend == "r2",
                    "endpoint_sha256": hashlib.sha256(endpoint.encode()).hexdigest(),
                    "bucket_sha256": hashlib.sha256(bucket.encode()).hexdigest(),
                    "access_key_id_sha256": hashlib.sha256(access_key.encode()).hexdigest(),
                }


            def main(argv: list[str] | None = None) -> int:
                parser = argparse.ArgumentParser()
                parser.add_argument("--evidence-output", type=Path, required=True)
                parser.add_argument("--key", required=True)
                parser.add_argument("--engine-sha", required=True)
                parser.add_argument("--run-id", required=True)
                args = parser.parse_args(argv)
                args.evidence_output.parent.mkdir(parents=True, exist_ok=True)

                try:
                    settings = Settings.from_env()
                    if settings.object_store_backend != "r2":
                        raise RuntimeError("R2 write-preflight requires OBJECT_STORE_BACKEND=r2")
                    payload = (
                        json.dumps(
                            {
                                "schema_version": SCHEMA_VERSION,
                                "engine_sha": args.engine_sha,
                                "run_id": args.run_id,
                                "purpose": "bounded-r2-object-write-capability-check",
                            },
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                        + "\n"
                    ).encode()
                    evidence = run_preflight(
                        store=create_object_store(settings),
                        key=args.key,
                        payload=payload,
                        identity=_identity(settings),
                    )
                except Exception as exc:
                    category, http_status, error_code = _error_details(exc)
                    evidence = {
                        "schema_version": SCHEMA_VERSION,
                        "status": "fail",
                        "root_cause_classification": category,
                        "http_status": http_status,
                        "error_code": error_code,
                        "bounded_mutation_count": 0,
                        "residual_object_present": None,
                        "zero_residual_objects": False,
                        "secret_values_recorded": False,
                    }
                    evidence["evidence_sha256"] = hashlib.sha256(
                        json.dumps(
                            evidence,
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode()
                    ).hexdigest()

                args.evidence_output.write_text(
                    json.dumps(evidence, indent=2, sort_keys=True) + "\n"
                )
                print(json.dumps(evidence, sort_keys=True))
                return 0 if evidence.get("status") == "pass" else 1


            if __name__ == "__main__":
                raise SystemExit(main())
            '''
        ).lstrip()
    )


def write_tests() -> None:
    TESTS.write_text(
        dedent(
            '''
            from __future__ import annotations

            from typing import Any

            from botocore.exceptions import ClientError

            from knowledge_engine.storage import FileObjectStore
            from scripts.m25_9_r2_write_preflight import run_preflight


            def _identity() -> dict[str, Any]:
                return {
                    "backend_is_r2": True,
                    "endpoint_sha256": "e" * 64,
                    "bucket_sha256": "b" * 64,
                    "access_key_id_sha256": "a" * 64,
                }


            def test_r2_write_preflight_passes_and_leaves_no_residual(tmp_path):
                store = FileObjectStore(tmp_path / "store")
                evidence = run_preflight(
                    store=store,
                    key="diagnostics/m25-9/run-1.json",
                    payload=b'{"ok":true}\n',
                    identity=_identity(),
                )
                assert evidence["status"] == "pass"
                assert evidence["root_cause_classification"] == (
                    "r2_object_read_write_capability_pass"
                )
                assert evidence["put_succeeded"] is True
                assert evidence["read_verified"] is True
                assert evidence["delete_succeeded"] is True
                assert evidence["bounded_mutation_count"] == 2
                assert evidence["zero_residual_objects"] is True
                assert store.head("diagnostics/m25-9/run-1.json") is None


            class AccessDeniedStore:
                def head(self, key):
                    del key
                    return None

                def put(self, key, data, **kwargs):
                    del key, data, kwargs
                    raise ClientError(
                        {
                            "Error": {"Code": "AccessDenied", "Message": "denied"},
                            "ResponseMetadata": {"HTTPStatusCode": 403},
                        },
                        "PutObject",
                    )

                def get(self, key):
                    raise AssertionError(key)

                def delete(self, key):
                    raise AssertionError(key)


            def test_r2_write_preflight_classifies_access_denied_without_mutation():
                evidence = run_preflight(
                    store=AccessDeniedStore(),
                    key="diagnostics/m25-9/run-2.json",
                    payload=b"{}\n",
                    identity=_identity(),
                )
                assert evidence["status"] == "fail"
                assert evidence["root_cause_classification"] == (
                    "r2_put_object_access_denied"
                )
                assert evidence["http_status"] == 403
                assert evidence["error_code"] == "AccessDenied"
                assert evidence["bounded_mutation_count"] == 0
                assert evidence["residual_object_present"] is False


            class DigestMismatchStore(FileObjectStore):
                def get(self, key):
                    del key
                    return b"wrong"


            def test_r2_write_preflight_cleans_up_after_readback_mismatch(tmp_path):
                store = DigestMismatchStore(tmp_path / "store")
                key = "diagnostics/m25-9/run-3.json"
                evidence = run_preflight(
                    store=store,
                    key=key,
                    payload=b"expected\n",
                    identity=_identity(),
                )
                assert evidence["status"] == "fail"
                assert evidence["delete_succeeded"] is True
                assert evidence["bounded_mutation_count"] == 2
                assert evidence["zero_residual_objects"] is True
                assert store.head(key) is None


            def test_r2_write_preflight_does_not_delete_preexisting_key(tmp_path):
                store = FileObjectStore(tmp_path / "store")
                key = "diagnostics/m25-9/preexisting.json"
                store.put(
                    key,
                    b"existing",
                    content_type="application/json",
                )
                evidence = run_preflight(
                    store=store,
                    key=key,
                    payload=b"new",
                    identity=_identity(),
                )
                assert evidence["status"] == "fail"
                assert evidence["root_cause_classification"] == (
                    "r2_canary_cleanup_failed_residual_present"
                )
                assert evidence["bounded_mutation_count"] == 0
                assert store.get(key) == b"existing"
            '''
        ).lstrip()
    )


def patch_workflow() -> None:
    lines = WORKFLOW.read_text().splitlines()

    pull_start = _find(lines, "  pull_request:")
    push_start = _find(lines, "  push:", start=pull_start + 1)
    _replace_once_in_range(
        lines,
        start=pull_start,
        stop=push_start,
        old="      - 'src/knowledge_engine/m23_cloudflare_qdrant.py'",
        new="      - 'scripts/m25_9_r2_write_preflight.py'",
    )
    _replace_once_in_range(
        lines,
        start=pull_start,
        stop=push_start,
        old="      - 'tests/test_m23_5_cloudflare_qdrant.py'",
        new="      - 'tests/test_m25_9_r2_write_preflight.py'",
    )

    permissions_start = _find(lines, "permissions:", start=push_start)
    _insert_after_once(
        lines,
        start=push_start,
        stop=permissions_start,
        anchor="      - 'docs/architecture/m25/m25-9-live-preflight-repair.md'",
        values=[
            "      - 'scripts/m25_9_r2_write_preflight.py'",
            "      - 'tests/test_m25_9_r2_write_preflight.py'",
        ],
    )

    ruff_start = _find_prefix(
        lines, "          python -m ruff check --output-format=concise", start=permissions_start
    )
    pytest_start = _find_prefix(lines, "          python -m pytest -q", start=ruff_start)
    _insert_after_once(
        lines,
        start=ruff_start,
        stop=pytest_start,
        anchor="            scripts/m25_9_cloudflare_live_preflight.py \\",
        values=["            scripts/m25_9_r2_write_preflight.py \\"],
    )
    pytest_start = _find_prefix(lines, "          python -m pytest -q", start=ruff_start)
    _insert_after_once(
        lines,
        start=ruff_start,
        stop=pytest_start,
        anchor="            tests/test_m25_9_cloudflare_live_preflight.py \\",
        values=["            tests/test_m25_9_r2_write_preflight.py \\"],
    )

    pytest_start = _find_prefix(lines, "          python -m pytest -q", start=ruff_start)
    compile_start = _find_prefix(lines, "          python -m compileall -q", start=pytest_start)
    _insert_after_once(
        lines,
        start=pytest_start,
        stop=compile_start,
        anchor="            tests/test_m25_9_cloudflare_live_preflight.py \\",
        values=["            tests/test_m25_9_r2_write_preflight.py \\"],
    )

    compile_start = _find_prefix(lines, "          python -m compileall -q", start=pytest_start)
    typecheck_start = _find(lines, "      - name: Type-check candidate Worker", start=compile_start)
    _insert_after_once(
        lines,
        start=compile_start,
        stop=typecheck_start,
        anchor="            scripts/m25_9_cloudflare_live_preflight.py \\",
        values=["            scripts/m25_9_r2_write_preflight.py \\"],
    )
    typecheck_start = _find(lines, "      - name: Type-check candidate Worker", start=compile_start)
    _insert_after_once(
        lines,
        start=compile_start,
        stop=typecheck_start,
        anchor="            tests/test_m25_9_cloudflare_live_preflight.py \\",
        values=["            tests/test_m25_9_r2_write_preflight.py \\"],
    )

    boundary_start = _find(
        lines, "      - name: Enforce exact repair changed-file boundary"
    )
    expected_start = _find_prefix(
        lines, "          expected=\"$(printf '%s\\n'", start=boundary_start
    )
    expected_stop = next(
        index
        for index in range(expected_start + 1, len(lines))
        if lines[index].endswith("| sort)\"")
    )
    lines[expected_start + 1 : expected_stop + 1] = [
        "            '.github/workflows/m25-9-blog-full-population-pilot.yml' \\",
        "            'docs/architecture/m25/m25-9-live-preflight-repair.md' \\",
        "            'scripts/m25_9_r2_write_preflight.py' \\",
        "            'tests/test_m25_9_r2_write_preflight.py' | sort)\"",
    ]

    deploy_start = _find(lines, "  deploy:")
    _replace_once_in_range(
        lines,
        start=deploy_start,
        stop=min(len(lines), deploy_start + 20),
        old="    needs: [verify, cloudflare-preflight]",
        new="    needs: [verify, cloudflare-preflight, r2-write-preflight]",
    )

    job = dedent(
        '''

          r2-write-preflight:
            if: github.event_name == 'push'
            needs: [verify, cloudflare-preflight]
            runs-on: ubuntu-24.04
            timeout-minutes: 15
            environment: m23-r3-diagnostic
            env:
              APP_ENV: staging
              AUTH_MODE: disabled
              OBJECT_STORE_BACKEND: r2
              R2_ENDPOINT_URL: ${{ secrets.R2_ENDPOINT_URL }}
              R2_BUCKET: ${{ secrets.R2_BUCKET }}
              R2_ACCESS_KEY_ID: ${{ secrets.R2_ACCESS_KEY_ID }}
              R2_SECRET_ACCESS_KEY: ${{ secrets.R2_SECRET_ACCESS_KEY }}
              R2_REGION: auto
              EVIDENCE_DIR: /tmp/m25-9-r2-write-preflight
            steps:
              - uses: actions/checkout@v4
                with:
                  ref: ${{ github.sha }}
                  fetch-depth: 200
                  show-progress: false
              - uses: actions/setup-python@v5
                with:
                  python-version: '3.11'
              - name: Verify one-attempt bounded R2 authority
                run: |
                  set -euo pipefail
                  test "$GITHUB_RUN_ATTEMPT" = '1'
                  test "$(git rev-parse HEAD)" = "$GITHUB_SHA"
                  for name in R2_ENDPOINT_URL R2_BUCKET R2_ACCESS_KEY_ID R2_SECRET_ACCESS_KEY; do
                    test -n "${!name}"
                  done
                  mkdir -p "$EVIDENCE_DIR"
              - name: Install runtime dependencies
                run: python -m pip install -q --disable-pip-version-check -e '.[dev]'
              - name: Verify bounded R2 write, read-back, delete, and zero residual
                run: |
                  set -euo pipefail
                  key="diagnostics/m25-9/r2-write-preflight/$GITHUB_RUN_ID-$GITHUB_RUN_ATTEMPT.json"
                  set +e
                  python scripts/m25_9_r2_write_preflight.py \
                    --evidence-output "$EVIDENCE_DIR/r2-write-preflight.json" \
                    --key "$key" \
                    --engine-sha "$GITHUB_SHA" \
                    --run-id "$GITHUB_RUN_ID"
                  status=$?
                  set -e
                  test -s "$EVIDENCE_DIR/r2-write-preflight.json"
                  exit "$status"
              - name: Upload exact R2 capability evidence
                if: always()
                uses: actions/upload-artifact@v4
                with:
                  name: m25-9-r2-write-preflight-${{ github.sha }}
                  path: /tmp/m25-9-r2-write-preflight/r2-write-preflight.json
                  if-no-files-found: error
                  retention-days: 30
              - name: Record blocked R2 capability on issue 1092
                if: failure()
                env:
                  GH_TOKEN: ${{ github.token }}
                run: |
                  set -euo pipefail
                  reason='r2_write_preflight_evidence_unavailable'
                  residual='unknown'
                  mutations='unknown'
                  if test -s "$EVIDENCE_DIR/r2-write-preflight.json"; then
                    reason="$(jq -r '.root_cause_classification' \
                      "$EVIDENCE_DIR/r2-write-preflight.json")"
                    residual="$(jq -r '.residual_object_present' \
                      "$EVIDENCE_DIR/r2-write-preflight.json")"
                    mutations="$(jq -r '.bounded_mutation_count' \
                      "$EVIDENCE_DIR/r2-write-preflight.json")"
                  fi
                  gh issue comment 1092 \
                    --repo "$GITHUB_REPOSITORY" \
                    --body "M25.9 bounded R2 write preflight blocked at exact SHA \`$GITHUB_SHA\` (run \`$GITHUB_RUN_ID\`, attempt \`$GITHUB_RUN_ATTEMPT\`): \`$reason\`. Bounded mutations: \`$mutations\`; residual object present: \`$residual\`."
        '''
    ).rstrip().splitlines()
    lines[deploy_start:deploy_start] = job
    WORKFLOW.write_text("\n".join(lines) + "\n")


def patch_docs() -> None:
    text = DOCS.read_text()
    heading = "## R2 object-write capability gate"
    if heading in text:
        raise RuntimeError("R2 object-write capability gate already documented")
    section = dedent(
        '''

        ## R2 object-write capability gate

        Fresh full-pilot run `30068964353` passed Cloudflare preflight, Workers AI
        capability, production-pointer read, embedding, and Qdrant verification, then
        failed at R2 `PutObject` with `AccessDenied`. The same credentials successfully
        read `channels/production.json`, proving the endpoint, bucket and authentication
        identity were valid for reads while object-write authority was absent.

        Before any subsequent full-population embedding run, an independent bounded R2
        gate must create one unique canary under `diagnostics/m25-9/r2-write-preflight/`,
        read it back and verify its digest, delete it, and confirm that no residual object
        remains. A successful check performs exactly two bounded candidate mutations
        (one put and one delete) with zero residual objects. Production channel keys and
        public-production traffic remain untouched.

        The GitHub environment `m23-r3-diagnostic` must contain R2 S3 credentials with
        **Object Read & Write** (or Admin Read & Write) permission scoped to the exact
        bucket named by `R2_BUCKET`. Read-only credentials are not sufficient. Rotate
        both `R2_ACCESS_KEY_ID` and `R2_SECRET_ACCESS_KEY` together; the secret access key
        cannot be viewed again after token creation.
        '''
    )
    DOCS.write_text(text.rstrip() + "\n" + section + "\n")


def main() -> None:
    write_script()
    write_tests()
    patch_workflow()
    patch_docs()
    for path in EXPECTED_PATHS:
        if not Path(path).is_file():
            raise RuntimeError(f"missing generated repair path: {path}")


if __name__ == "__main__":
    main()
