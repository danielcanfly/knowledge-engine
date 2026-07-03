# Knowledge Engine

Production-shaped Builder, Runtime, release controller, and governed knowledge-production plane for Daniel's Knowledge OS.

```text
raw evidence
  -> immutable capture
  -> evidence-bound synthesis draft
  -> human review
  -> approved OKF source
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
- Validates model synthesis output against exact evidence spans.

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

Every generated intake draft is marked `draft` and `pending`, and every packet has `canonical_write_permitted: false`. Secret-like content is rejected before storage. Prompt-injection-like text is preserved as evidence but blocks downstream synthesis pending security review.

## Evidence-bound synthesis

Synthesis is deliberately split into two operations. The prepare operation creates a closed, provider-neutral prompt envelope. The validate operation accepts strict JSON and verifies every supported claim against exact normalized-source character spans.

```bash
knowledge-synthesis prepare \
  --capture-id capture_0123456789abcdef0123456789abcdef \
  --provider fixture-provider \
  --model fixture-model \
  --model-version fixture-v1 \
  --prompt-version m5-prompt-v1 \
  --harness-version m5-harness-v1 \
  --seed 17 \
  --temperature 0 \
  --requested-at 2026-07-03T10:00:00Z \
  --actor danielcanfly \
  --output-dir .artifacts/synthesis-request
```

A provider returns JSON matching this shape:

```json
{
  "schema_version": "1.0",
  "title": "Evidence separation",
  "summary": "A summary limited to supported evidence.",
  "claims": [
    {
      "claim_id": "claim_evidence_separation",
      "text": "Immutable evidence remains separate from canonical knowledge.",
      "evidence": [
        {
          "start_char": 0,
          "end_char": 64,
          "quote": "Immutable evidence remains separate from canonical knowledge."
        }
      ]
    }
  ],
  "unsupported_claims": []
}
```

Validate it with:

```bash
knowledge-synthesis validate \
  --request-id sreq_0123456789abcdef0123456789abcdef \
  --model-output model-output.json \
  --output-dir .artifacts/synthesis-review
```

The harness rejects incorrect spans, mismatched quotes, duplicate claim IDs, unknown fields, unresolved intake security findings, and outputs without supported claims. Unsupported claims are stored separately and never rendered into the synthesized draft. All synthesis artifacts remain below `review/`, with GitHub, production, and canonical writes denied.

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
