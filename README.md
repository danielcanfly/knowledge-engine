# Knowledge Engine

Production-shaped Builder, Runtime, release controller, and governed intake plane for Daniel's Knowledge OS.

```text
raw evidence
  -> immutable capture and review packet
  -> human-approved OKF source
  -> deterministic compiler
  -> immutable release artifacts
  -> Cloudflare R2
  -> atomic channel pointer
  -> ACL-aware Runtime API
```

The normative contracts live in `danielcanfly/knowledge-os-foundation`. This repository implements those contracts.

## Implemented slices

- Validates a release-ready OKF bundle.
- Compiles graph, lexical index, provenance aggregate, and build report.
- Produces deterministic release artifacts and SHA-256 manifests.
- Supports filesystem and Cloudflare R2 object stores.
- Uploads immutable release objects before changing the channel pointer.
- Verifies every artifact before Runtime activation.
- Exposes health, current release, refresh, and query endpoints.
- Verifies Supabase JWTs through JWKS.
- Applies ACL filters before retrieval and response serialization.
- Provides permanent approval-gated promotion and rollback workflows.
- Captures Markdown evidence as immutable content-addressed raw objects.
- Produces isolated normalized evidence and human-review packets.

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

## Governed Markdown intake

M5 intake stores raw evidence and generated review material outside the canonical source bundle. The command cannot publish a candidate or production release.

```bash
export OBJECT_STORE_BACKEND=filesystem
export FILESYSTEM_STORE_ROOT=.artifacts/intake-store
export AUTH_MODE=disabled
export APP_ENV=development

knowledge-intake \
  --input article.md \
  --source-id source_blog_example \
  --source-uri https://example.com/article \
  --title 'Example article' \
  --kind markdown \
  --audience public \
  --retrieved-at 2026-07-03T09:30:00Z \
  --owner Daniel \
  --license owner-provided \
  --output-dir .artifacts/review-packet
```

The output contains:

```text
raw-capture.json
normalized.md
draft/concept.md
draft/provenance.json
draft/source-record.json
review-checklist.json
review-packet.json
intake-result.json
```

Every generated draft is marked `draft` and `pending`, and every packet has `canonical_write_permitted: false`. Secret-like content is rejected before storage. Prompt-injection-like text is preserved as evidence but blocks downstream synthesis pending security review.

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
