# Promotion, Rollback, and Recovery

Return to the [Operator Runbook Index](../README.md).

This companion runbook applies when candidate acceptance, production promotion, post-promotion
verification, rollback, object restoration, Source reconstruction, or control-plane reconstruction
does not follow the happy path.

## Before any production mutation

Require all of the following:

- exact target release, manifest, Source, Builder, Foundation, and request identities;
- exact current and expected-previous production pointer identities;
- unique operation ID and replay status;
- explicit bounded approval;
- verified candidate artifacts and acceptance evidence;
- post-action public query, citation, ACL-negative, cache, and health checks;
- a rollback target and executable governed rollback path;
- an evidence location that contains no secrets or raw private content.

Missing any item means stop before mutation.

## Candidate failure

When candidate build or acceptance fails, leave production untouched. Preserve candidate evidence,
mark the candidate rejected or blocked, and correct the cause through a new reviewed Source or
Engine change. Do not repair an immutable candidate in place.

## Failed or uncertain promotion

When the workflow reports a failed mutation, ambiguous result, identity drift, or post-promotion
verification failure:

1. stop all new promotion attempts;
2. preserve request, approval, intent, pointer, manifest, workflow, and verification evidence;
3. determine whether production still equals the expected previous pointer, equals the target, or is
   unknown;
4. use the M16 containment contract to classify contained, compensation-required, uncompensated, or
   unknown state;
5. execute rollback only through the governed rollback surface with a new bounded authorization when
   required;
6. verify exact pointer bytes, runtime release, cache, public query, citations, and ACL-negative
   behavior after rollback;
7. record incident and recovery evidence without inventing missing state.

Never repeat a mutation merely because a client timed out. Replays are idempotent only when operation
ID, payload, expected previous pointer, resulting pointer, action kind, and prior terminal result all
match.

## R2 object loss

Use retained immutable release inventory only after manifest, Source, object digest, size, and trust
verification. Restoration requires explicit bounded authorization and per-object post-restore
verification. Do not copy from an untrusted candidate, rebuild history, or repair the production
pointer as a side effect.

## Source or control-plane loss

Choose a restoration point only when it equals the canonical Source identity, is reachable from
trusted Git history, and retains complete review and signature evidence. Reconstruct registry,
approvals, lifecycle, production identity, pointer identity, artifact inventory, and ledger
continuity from trusted evidence. Mark unrecoverable ephemeral state as unknown rather than
fabricating it.

## Rollback completion

Rollback is complete only when the previous pointer bytes are restored, the runtime loads the exact
previous release and manifest, cache binding is correct, required query and citation checks pass,
ACL-negative behavior passes, replay protections remain intact, and the incident evidence is
closed.

## Escalation and stop conditions

Stop and escalate when current production identity is unknown, approval scope is ambiguous, retained
objects fail digest verification, trusted Git ancestry is missing, replay history conflicts,
credentials may be compromised, RTO or RPO evidence is absent, or rollback verification fails.
