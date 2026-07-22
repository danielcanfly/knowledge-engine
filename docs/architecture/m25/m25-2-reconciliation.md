# M25.2 Reconciliation and Acceptance

**Accepted status:** `m25_2_intake_orchestrator_accepted`  
**Implementation issue:** #1040  
**Implementation PR:** #1041

## Acceptance result

M25.2 is accepted after independent reconciliation. Engine main contains one bounded admission
orchestrator that reuses M10 `intake/v1` immutable evidence and M21.2 resumable checkpoint
semantics. Full-population inventories, byte- and source-bounded plans, explicit policy blocks,
immutable checkpoint revisions, bounded retries, approved adapter envelopes, candidate-only
normalized references, and denominator reports are present and tested.

The reconciliation workflow resolves the exact implementation head and merge commit directly from
the GitHub API, verifies that the merge commit is an ancestor of the reconciliation head, and proves
that all required workflows succeeded on that exact implementation head. The resolved identity file
is uploaded as a retained workflow artifact rather than being copied by hand.

## Preserved boundaries

- No raw, snapshot, derivative, or normalized evidence plane was duplicated.
- No inventory source was silently excluded from the denominator.
- Unresolved ACL, owner, or licence evidence fails closed.
- No live extraction or model call occurred.
- Canonical Source, Foundation, release, production pointer, R2 production, Qdrant, semantic/hybrid
  serving, production answer serving, and large-scale ingestion authority were unchanged.

## Execution model

ChatGPT completed implementation, CI diagnosis, bounded lint repair, review, merge, reconciliation,
and evidence assembly. Codex was not invoked. Daniel did not need to intervene because M25.2 made no
knowledge decision, destructive identity decision, production decision, or scale authorization.

## Next legal stage

M25.3 Provider-Neutral Model Extraction is the only next implementation stage. It must consume the
M25.2 normalized reference surface and remain candidate-only.

Machine-readable acceptance: `pilot/m25/m25-2-acceptance.json`.
