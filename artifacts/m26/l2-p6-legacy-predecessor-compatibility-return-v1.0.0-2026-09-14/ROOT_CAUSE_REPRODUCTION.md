# Root Cause Reproduction

The handoff premise was only valid for the generic M23 CLI path. M23 commit
`99ac8516a5ce4f9254d7141b39cf6377e5a1993d` normalizes through `validate_sections()` before
`build_qdrant_points()`, so that path hashes normalized text.

The active predecessor was built by M25 engine
`fe499db2e043209bfa4c2390d513c5dc579727a2`. Its blog candidate wrapper directly constructs
`SectionInput` from raw semantic rows, bypassing validation. `embed_sections()` normalizes
the provider request, while `build_qdrant_points()` hashes the still-raw `SectionInput.text`.

Reproduction with a whitespace/fullwidth input proves the divergence. The generic validated
M23 path remains normalized; the exact M25 wrapper lineage is raw payload identity plus a
normalized provider input.
