# M25 Production Admission Pipeline

M25 starts from the accepted M24.14.6 baseline and builds a governed production admission
pipeline without changing production retrieval authority.

## M25.1 accepted design boundary

- Engine entry SHA: `25a119e428bb202ebbed4b5a73a4209c41f9ce27`
- Source SHA: `acf78596ace8a7366688ccef72b507204d09d9f9`
- Foundation SHA: `e5ef644053d34e89c70d2ceb37521e1c59234832`
- Release: `20260720T160000Z-46137c97263e`
- Production retrieval: lexical
- Large-scale ingestion: disabled
- Production answer serving: disabled

`intake/v1` remains the immutable evidence plane. M25 adds `admission/v1` as a control plane
that references M10, M11, M21, and M24 artifacts. It does not duplicate raw or normalized
payloads and does not create a parallel ingestion stack.

The M25.1 files freeze architecture only. M25.2 is the first implementation stage.

## Documents

- `m25-1-admission-architecture-freeze.md`
- `reuse-map.md`
- `state-machine.md`
- `authority-matrix.md`
- `adapter-boundaries.md`
- `schema-version-plan.md`

## Machine-readable evidence

The `pilot/m25/m25-1-*.json` records are digest-bound. The architecture freeze record binds
the baseline, reuse map, state machine, authority matrix, schema registry, adapter map, and
M25.2 example inputs.
