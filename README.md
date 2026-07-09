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
  -> deterministic query evaluation gate
  -> golden query suite report
  -> golden query baseline gate
  -> release quality gate
  -> retrieval and citation metrics
  -> answer quality and performance metrics
  -> final release-blocking M12 gate
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
- Attaches deterministic query evaluation evidence and a fail-closed release-blocking gate to Runtime query responses.
- Runs deterministic golden query suites over ACL-filtered Runtime responses and emits replayable aggregate reports.
- Compares golden query suite reports to immutable quality baselines before allowing release progression.
- Bundles runtime-quality evidence into deterministic release quality gate decisions.
- Computes deterministic retrieval, citation, answer-quality, and performance metrics from explicit governed observations.
- Emits a final M12 release-blocking decision with complete boundary and regression evidence.
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

Every query response includes `evaluation` evidence with a deterministic `evaluation_id`, citation coverage, ACL-filtering metrics, fallback usage, stable failure reasons, and a `release_blocking` gate. See `docs/m12-runtime-query-evaluation.md`.

Golden query suites execute multiple Runtime queries through the same ACL-filtered surface and emit deterministic aggregate evidence with `gqsuite_`, `gqrun_`, and `gqreport_` identities. See `docs/m12-golden-query-suite.md`.

Golden query baselines compare suite reports to immutable aggregate floors and emit `gqbaseline_` / `gqbaselinecheck_` evidence. See `docs/m12-golden-query-baseline.md`.

Release quality gates bundle query evaluations, suite reports, and baseline checks into `rqgate_` / `rqdecision_` evidence. See `docs/m12-release-quality-gate.md`.

M12.5 computes `rcmetricset_` / `rcmetrics_` retrieval and citation evidence from explicit case expectations. See `docs/m12/m12-5-retrieval-citation-metrics.md`.

M12.6 computes `apmetricset_` / `apmetrics_` answer-quality and performance evidence from bounded observations. See `docs/m12/m12-6-answer-performance-metrics.md`.

M12.7 composes the final `m12gate_` / `m12closure_` release-blocking decision. See `docs/m12/m12-7-final-gate-and-closure.md`.

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
  "title": "Evidence separation"
}
```
