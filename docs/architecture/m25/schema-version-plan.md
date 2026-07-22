# M25 Schema Version Plan

The machine-readable registry is `pilot/m25/m25-1-schema-registry.json`.

## Frozen v1 schemas

- `knowledge-engine-m25-admission-plan/v1`
- `knowledge-engine-m25-admission-state/v1`
- `knowledge-engine-m25-authority-envelope/v1`
- `knowledge-engine-m25-adapter-envelope/v1`

All schemas use JSON Schema Draft 2020-12, reject unknown fields, reject cross-release identity
mismatch, and require digest-bound objects. Major-version mismatch and downgrade are fail-closed.

## Compatibility

M10, M11, M21, and M24 artifacts remain in their existing namespaces. M25 envelopes reference
those schema versions rather than renaming or copying them. Legacy modules with embedded Source
identities require a versioned adapter and cannot be silently patched at runtime.

## M25.2 input

The examples under `docs/architecture/m25/examples/` are the frozen implementation inputs for
M25.2. They demonstrate a candidate-only authority envelope, one declared intake adapter, and a
bounded admission plan.
