# M11.7 Closure and Production Baseline Reconciliation

Status: implementation candidate
Parent milestone: #146
Slice issue: #157
Depends on: #156
Engine baseline before closure: `2e4bbb445b4762ae9cde191edc121ae82b9914d0`
Canonical Source baseline: `2126db2ed4d372d3d61464fe31a86fc0243a1f24`

## Closure objective

M11 closes only after the complete compiler path is demonstrably review-ready and governed:

```text
M10 admitted immutable evidence
-> deterministic structure and source maps
-> bounded extraction candidates
-> evidence validation and Source-aware resolution
-> provider-neutral synthesis proposals
-> compiler-wide validation and reviewer packet
-> explicit immutable human decisions
-> review-only Source PR package
-> closure reconciliation
```

The final package remains a proposal artifact. It is not canonical Source, a GitHub pull request, a candidate, a release request, or a production release.

## Machine-verifiable closure

The M11 closure reconciler validates:

- the exact Source PR package manifest, decision set, file plan, exclusions, validation report, result, and adjacent event chain;
- the complete underlying reviewer packet, proposal, resolution, candidate, and evidence chain;
- only explicitly approved proposals are included;
- quarantined or unsupported content is absent;
- audience and ACL restriction never broaden;
- the exact canonical Source checkout remains clean and byte-identical to the reviewed snapshot;
- Source PR creation, direct apply, canonical write, GitHub write, production write, and ledger write remain forbidden;
- deterministic replay remains idempotent and immutable collisions fail hard.

The output includes a reconciliation report and invariant matrix. The machine status is `closure_ready`; GitHub issue closure occurs only after the exact reviewed branch head passes CI, R2 Canary, and R2 Release Integration and is merged.

## Production reconciliation

The closure contract locks the production baseline to:

```text
release: 20260708T040116Z-69a9f445699a
manifest: 2b2630cfe3e8a6e25a8f210d68c70f3b9a31b3b26f33c6e3e41b8cc1676fc0bb
pointer: 38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5
```

Any mismatch produces typed rejection evidence. M11 does not append issue #30 because no production promotion or rollback occurs.

## Immutable layout

```text
compiler/v1/m11-closures/{closure_id}/reconciliation-report.json
compiler/v1/m11-closures/{closure_id}/invariant-matrix.json
compiler/v1/m11-closures/{closure_id}/events/{ordinal}-{event_sha256}.json
compiler/v1/m11-closures/{closure_id}/result.json
compiler/v1/m11-closure-rejections/{attempt_id}/evidence.json
compiler/v1/m11-closure-rejections/{attempt_id}/result.json
```

The state sequence is:

```text
package_validated
-> baselines_reconciled
-> closure_ready
```

## Exit criteria

M11 is complete when:

- M11.1 through M11.6 are closed with exact evidence;
- this closure implementation and end-to-end tests are merged from an exact green head;
- canonical Source remains at `2126db2ed4d372d3d61464fe31a86fc0243a1f24`;
- the production release, manifest, and pointer remain unchanged;
- permanent ledger #30 remains open;
- parent issue #146 is reconciled and closed;
- M12 Runtime Query Quality and Evaluation becomes the next milestone.
