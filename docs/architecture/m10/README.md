# M10.1 Immutable Intake Architecture

Status: proposed
Milestone: M10 — Immutable Intake and Source Connectors
Baseline Engine: `3a17593eb1b2cd549e84b9287679023350b4f5b1`
Production mutation: forbidden

This package defines the production intake plane that generalizes the M5.1 Markdown vertical slice without replacing its proven object-store primitives.

## Documents

1. `ADR-001-immutable-intake-plane.md`
2. `connector-protocol-v1.md`
3. `intake-state-machine.md`
4. `r2-key-layout.md`
5. `acl-and-audience-invariants.md`
6. `threat-model.md`
7. `test-strategy-and-acceptance.md`
8. `m5-to-m10-migration-map.md`
9. `../../../schemas/intake-snapshot-v1.schema.json`
10. `examples/snapshot-v1.example.json`

## Governing outcome

M10.1 is architecture-only. It does not acquire external content, change canonical Source, build a candidate, change `channels/production.json`, dispatch a promotion, or append a production ledger entry.

The first implementation slice after acceptance should be M10.2, a local-file/Markdown reference connector using the contracts in this package.
