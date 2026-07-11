# M17 Operator Inspection and Evidence Tooling

Return to the [Operator Runbook Index](../README.md).

M17.4 provides a read-only inspection surface for qualified operators. The tools inspect
repository files, bounded evidence, local exports, and object-store state through `get` or `head`
operations only. They may write new files beneath an operator-selected local output directory, but
they never mutate Source, candidate, production, pointers, caches, R2 objects, credentials,
approvals, lifecycle state, permanent ledger records, or batch closeout state.

## Canonical command

```bash
knowledge-inspect <command> [options]
```

Every command emits deterministic JSON to standard output. Commands that produce a local artifact
also include its SHA-256 digest. Missing, stale, conflicting, privacy-unsafe, or identity-unbound
evidence is reported as `blocked` or `unknown`; it is never converted into a healthy result.

## Tool set

| Command | Purpose | Remote authority |
|---|---|---|
| `checklist` | render the canonical 18-stage lifecycle checklist and stop conditions | none |
| `doctor` | inspect Python, repository, registries, environment shape, and backend readiness | none |
| `batch-status` | summarize one bounded batch-state export | none |
| `production-status` | verify channel pointer, manifest identity, and artifact metadata | object-store `get` and `head` only |
| `artifact-fetch` | download one bounded object to a local output directory with digest verification | object-store `get` and `head` only |
| `evidence-verify` | verify canonical JSON evidence and its declared digest | none |
| `release-compare` | compare two local release manifests without modifying either | none |
| `ledger-summarize` | summarize a local bounded export of ledger entries | none |
| `incident-bundle` | create a redacted metadata-only local incident bundle | none |
| `handoff-generate` | create a local operator handoff from verified component reports | none |

## Universal safety rules

- Run inspection against exact identities, not moving branch names or remembered production values.
- Never pass secret values on the command line or place them in evidence files.
- `doctor` reports whether required environment variables are present, never their values.
- `artifact-fetch` rejects traversal, objects above the configured byte limit, and digest mismatch.
- Incident and handoff bundles contain metadata, identifiers, bounded status, and file digests only.
- Raw queries, raw answers, restricted source passages, credentials, authentication headers, cookies,
  hostnames, complete traces, and private object locations are forbidden.
- A generated local artifact is not approval, authority, permanent evidence, or permission to resume.
- Resume the canonical runbook only after the affected acceptance and recovery gates pass.

## Examples

```bash
knowledge-inspect checklist \
  --registry docs/operations/m17/runbook-registry.json

knowledge-inspect doctor --root .

knowledge-inspect evidence-verify \
  --input .artifacts/m17/failure-atlas-acceptance.json

knowledge-inspect release-compare \
  --left previous-manifest.json \
  --right candidate-manifest.json

knowledge-inspect production-status --channel production

knowledge-inspect artifact-fetch \
  --key releases/<RELEASE_ID>/manifest.json \
  --output-dir .artifacts/operator-downloads \
  --expected-sha256 <SHA256>
```

## Acceptance

Run:

```bash
python scripts/m17_operator_tooling_acceptance.py \
  --root . \
  --registry docs/operations/m17/tool-registry.json \
  --output .artifacts/m17/operator-tooling-acceptance.json
```

The report validates command coverage, documentation anchors, read-only authority, deterministic
outputs, privacy boundaries, and source-code mutation surfaces. A failed acceptance is a hard stop.
