# M23.7-R3.8.10 Full Deletion Identity Set

## Decision

The R3.8 deletion authorization and receipt schemas are upgraded to v2. A single
representative Worker version is not sufficient because the reconciled orphan has
four versions and four deployments.

The authorization must now bind:

- exact Worker name;
- affected observation run and successful recovery run;
- successful recovery receipt digest;
- Worker-present evidence seal digest;
- independent reconciliation digest;
- all sorted unique version identities;
- all sorted unique deployment identities;
- exact deny-by-default authority object.

Unexpected top-level keys, empty identity arrays, malformed UUIDs, duplicate IDs and
non-canonical ordering are rejected before any deletion command.

## Receipt

The deletion receipt carries the same complete identity sets and evidence chain.
The deletion command remains limited to the exact Worker name and must prove
control-plane absence before returning success.

## Authority

This implementation does not delete the Worker. After exact-head CI and independent
reconciliation, a separate committed authorization record may be created. Deletion
still requires a manual exact-head workflow dispatch.

Production remains lexical, the `1200 ms` gate is unchanged and both blockers remain
active.
