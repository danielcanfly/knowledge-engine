# Knowledge Engine

Production-shaped Builder and Runtime for Daniel's Knowledge OS.

```text
reviewed OKF bundle
  -> deterministic compiler
  -> immutable release artifacts
  -> Cloudflare R2
  -> atomic channel pointer
  -> ACL-aware Runtime API
```

The normative contracts live in `danielcanfly/knowledge-os-foundation`. This repository implements those contracts.

## Current M2 slice

- Validates a release-ready OKF bundle.
- Compiles graph, lexical index, provenance aggregate, and build report.
- Produces deterministic release artifacts and SHA-256 manifest.
- Supports filesystem and Cloudflare R2 object stores.
- Uploads immutable release objects before changing the channel pointer.
- Verifies every artifact before Runtime activation.
- Exposes health, current release, refresh, and query endpoints.
- Verifies Supabase JWTs through JWKS.
- Applies ACL filters before retrieval and response serialization.
- Provides Docker, systemd, CI, live R2 canary, and manual Oracle deployment workflows.

## Local development

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
ruff check .
pytest -q
python -m compileall -q src tests scripts
```

Build and query the example with the filesystem store:

```bash
export OBJECT_STORE_BACKEND=filesystem
export FILESYSTEM_STORE_ROOT=.artifacts/store
export AUTH_MODE=disabled
export APP_ENV=development
knowledge-engine build --bundle examples/okf-bundle --channel staging --release-time 2026-07-02T12:00:00Z
knowledge-engine query --channel staging --query 'knowledge compiler' --audiences public,internal
```

Run the API:

```bash
uvicorn knowledge_engine.api:app --host 0.0.0.0 --port 8080
```

Production values are supplied through GitHub Actions and the Oracle VM `.env`; no production credential belongs in this repository.

## Publishing rule

1. Upload every immutable release object.
2. Download and verify every hash and byte count.
3. Upload the manifest.
4. Verify the manifest hash.
5. Update the channel pointer last using compare-and-swap semantics.

Rollback only changes the channel pointer to an already verified release.
