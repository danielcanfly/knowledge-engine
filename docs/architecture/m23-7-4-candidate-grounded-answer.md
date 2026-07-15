# M23.7.4 Candidate-Only Grounded Answer Composition

Parent: #408. Issue: #423.

## Scope

M23.7.4 closes the legacy M22 query-time composition gap with a provider-neutral,
deterministic offline adapter. Candidate answers are composed only from authorised,
fresh and prompt-injection-isolated evidence emitted by the accepted M23.7.3 replay.
They are validated, reduced to digests for durable evidence and discarded. They are
never response-authoritative and are never served.

Production mutation dispatched: false.

## Entry identities

- Engine entry: `0f7e667b5e7e434434e136c5db999761f6d2d4b8`
- M23.7.1 contract: `7dbaca446fa7a7eccd5f072ab71ffaa8bd601ba8c3140afae3d80d81ce0ad8c1`
- M23.7.2 evaluation: `9d39f4c90392a0ae56f758b26b7b080bd03872aa1ccce596e8762087896f08ce`
- M23.7.3 replay: `47df7595ffc27d320c3a70d00c90fcb3a682b315f6b67eefb57497c99865fbf3`
- Candidate release: `m23cand-c7fbec7e945e79d05d3263b0`
- Candidate manifest: `3303a1d54d448c96c724178b482dc73daed2712ba8d09b0e34fa96eb8761e560`

## Provider-neutral contract

The exact adapter, provider fixture, model revision, prompt SHA, response schema SHA,
temperature, seed, token ceilings, timeout, retry ceiling, pricing and per-case/total
cost ceilings are part of the canonical composition identity. The accepted implementation
makes no network provider call. A later provider may implement the same protocol only
through a separately governed milestone.

## Grounding and citations

Each positive candidate answer contains one or more structured claims. Every claim must
match an exact `supported_claim` from authorised evidence and must reference a citation
whose section, parent, release, manifest, evidence digest and byte span exactly match the
evidence record. The human-readable citation marker is deterministic and appears in the
answer text.

The validator rejects:

- unsupported or altered claim text;
- missing or mismatched citations;
- provenance, release, manifest or byte-span drift;
- unauthorised, stale or injection-unsafe evidence;
- prompt-injection obedience;
- response-schema, model, prompt, cost, retry or timeout identity drift.

## Negative and failure behaviour

All near-domain, out-of-domain, keyword-trap, stale-source, ACL-denied and
prompt-injection cases abstain without invoking the provider. Failure probes cover provider
timeout, malformed schema, cost and retry ceilings, unsupported claims, citation mismatch
and prompt-injection obedience. Every failure is isolated, the candidate answer is
discarded and authoritative output remains unchanged.

## Privacy and authority

Durable reports contain identities, metrics, validation evidence and answer digests, not
raw user queries or raw candidate answers. Production retrieval remains lexical. No live
traffic, production mirroring, deployment, Source/R2/Qdrant mutation, public Explorer,
promotion decision or Graph Neural Retrieval is authorised.

M23.7.5 remains blocked until M23.7.4 implementation and independent reconciliation are
merged, issue #423 is closed completed, and bounded live shadow observation receives an
explicit privacy-safe approval.

Production mutation dispatched: false.
