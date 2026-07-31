# M26.PA.7 corrective arbitrary query runtime

PA.7 corrected product readiness separates the legacy health/status responder from the
operator product query path.

The canonical command, `knowledge-m26-pa7-query`, now defaults to a runtime chain that
uses the supplied natural-language question as retrieval input. The chain is owner
admission, accepted release validation, lexical plus dense candidate generation,
parent/graph/provenance expansion, bounded evidence selection, MiniMax synthesis, and
PA.4 exact-span material-claim verification.

The old fixed PA.7 status response remains available only through `--health-status`.
It is not product-readiness evidence and is superseded by the corrective reopen artifact.

The runtime response records query hashes, release identities, backend identities,
runtime-owned locators, selected evidence IDs, counters, and privacy/mutation flags. It
does not persist raw private queries, raw evidence bodies, full provider responses,
secrets, or vectors.
