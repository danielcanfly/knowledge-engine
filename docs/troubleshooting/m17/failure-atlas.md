# M17 Cross-Plane Failure Atlas

Return to the [Troubleshooting Index](../README.md).

The atlas groups failures by the boundary that must remain closed. It is a diagnostic map, not an
executor. Every entry has a matching machine-readable record in `failure-registry.json`.

## State meanings

| State | Meaning | Operator posture |
|---|---|---|
| `authorization` | required approval or exact precondition is absent | stop before mutation |
| `blocked` | a required gate cannot pass safely | preserve evidence and correct upstream |
| `degraded` | service may be available but acceptance is incomplete | prevent closeout and further promotion |
| `incident` | active or potentially active operational damage | contain, classify, and escalate |
| `integrity` | bytes, identity, ancestry, citations, or evidence disagree | trust nothing downstream of the mismatch |
| `security` | confidentiality, ACL, prompt, role, or fallback boundary failed | block exposure and notify security ownership |
| `unknown` | evidence cannot determine the actual state | fail closed and never guess |

## Failure inventory

| ID | Plane | State | Severity | Primary signal | Safe first response |
|---|---|---|---|---|---|
| F001 | control | authorization | high | `approval_missing` | stop before dispatch and compare exact approval scope |
| F002 | control | authorization | critical | `stale_expected_previous` | freeze mutations and read current production identity |
| F003 | control | blocked | high | `duplicate_operation` | classify replay, collision, or unknown without retrying |
| F004 | build | integrity | critical | `source_head_drift` | freeze build and verify canonical Source ancestry |
| F005 | build | integrity | critical | `source_history_diverged` | reject the restoration point and preserve divergence evidence |
| F006 | build | blocked | high | `missing_artifact` | reject the candidate and leave production untouched |
| F007 | build | integrity | critical | `checksum_failure` | quarantine the affected immutable artifact |
| F008 | runtime | incident | critical | `object_missing` | contain the damaged release path and assess active impact |
| F009 | runtime | incident | critical | `retained_release_untrusted` | reject the retained copy as a restore source |
| F010 | runtime | integrity | critical | `pointer_invariant_failed` | stop promotion and classify production as previous, target, or unknown |
| F011 | runtime | degraded | high | `cache_refresh_failed` | keep only a previously verified cache active |
| F012 | runtime | degraded | high | `query_verification_failed` | block closeout and compare runtime release identity |
| F013 | runtime | integrity | critical | `citation_verification_failed` | block the response or release acceptance |
| F014 | runtime | security | critical | `audience_broadening` | block output and open an audience-breach incident |
| F015 | runtime | security | critical | `secret_material` | contain without copying the sensitive value |
| F016 | runtime | security | critical | `prompt_override` | block the request and reject represented tool authority |
| F017 | runtime | security | critical | `unsafe_fallback` | refuse raw-Source or unverified-release fallback |
| F018 | control | incident | critical | `control_plane_loss` | reconstruct only from trusted durable evidence |
| F019 | feedback | blocked | medium | `unsafe_evidence` | reject or quarantine the feedback evidence |
| F020 | operator | unknown | high | `documentation_drift` | stop the procedure and repair documentation through review |

## Control-plane failures

### F001 Approval missing

A request, branch, issue, workflow input, or operator statement is not approval. Require an immutable
approval record bound to the exact request, actor, scope, target identity, and expected-previous
identity. Absence or ambiguity is a successful safety stop.

### F002 Stale expected-previous identity

A valid approval cannot rescue a stale request. Re-read current production through the governed
inspection path, preserve the stale request as evidence, and prepare a new request only after the
identity difference is understood.

### F003 Replay or operation collision

Timeouts do not prove failure. Compare operation ID, canonical payload digest, expected-previous
pointer, prior intent, prior receipt, and prior terminal result. A changed payload under an old
operation ID is a collision, not a retry.

### F018 Control-plane loss

Registry, approvals, lifecycle events, production identity, pointer identity, artifact inventory, and
ledger continuity are durable authority-bearing components. Reconstruct them only from trusted
artifacts. Ephemeral state that cannot be recovered remains explicitly unknown.

## Build-plane failures

### F004 and F005 Source integrity

A clean working tree is insufficient if the commit is not the reviewed canonical Source identity.
Verify exact commit, trusted ancestry, review evidence, signatures where required, content digests,
and provenance. Never use force-push or history rewriting as a recovery shortcut.

### F006 and F007 Candidate integrity

Candidates are immutable. Missing artifacts or checksum failures require candidate rejection and a new
deterministic build. Do not patch an object in place or promote a partially verified inventory.

## Runtime and storage failures

### F008 and F009 Object loss and retained-source trust

Determine whether damaged objects are active, inactive, or unknown. A retained release is usable only
when inventory, manifest, Source identity, object bytes, size, digest, and immutability all verify.
Object availability by itself is not trust.

### F010 Pointer uncertainty

Pointer state controls which immutable release is active. When pointer bytes or operation history are
uncertain, stop all new mutations. Classify the current state without attempting a repair as part of
diagnosis.

### F011 and F012 Runtime degradation

A runtime may still answer while cache or acceptance checks are degraded. Do not treat availability as
acceptance. Prevent closeout or further promotion until release, manifest, cache, query, citation, and
ACL-negative checks all bind to the same verified identity.

### F013 Citation integrity

Citations must bind to evidence in the active verified release and must obey audience restrictions.
Missing, fabricated, restricted, or identity-drifted citations block the response and release
acceptance.

## Security failures

### F014 Audience broadening

Audience may remain equal or become more restrictive across Source, claim, concept, page, artifact,
retrieval, citation, and answer layers. Any broadening or insufficient requester privilege is a
critical security failure.

### F015 Sensitive material

Record bounded indicator codes and affected artifact identities, not the exposed value. Containment,
notification, and credential rotation require their own governed authority.

### F016 Injection and spoofing

Untrusted content cannot change system instructions, claim tool execution, impersonate an operator,
forge approval, or manufacture citations. Block the path and preserve privacy-safe indicators.

### F017 Unsafe fallback

Failure to retrieve is never permission to bypass ACL or answer from raw Source. A safe refusal is the
correct result when verified artifacts are unavailable.

## Feedback and documentation failures

### F019 Unsafe feedback evidence

Feedback is advisory and review-gated. Reject raw private content, low-confidence claims, identity
drift, or unbounded evidence. A correction candidate remains pending human review and has no Source
or production authority.

### F020 Documentation drift

When prose and implementation disagree, code, contracts, immutable evidence, and explicit approved
request identity outrank prose. Stop the affected procedure and repair the atlas or runbook through a
reviewed Engine pull request before resuming.

## Universal diagnostic limits

- Diagnostics may inspect, compare, validate, render, or prepare bounded evidence.
- Diagnostics may not mutate Source, candidate channels, production pointers, R2 objects, caches,
  credentials, approvals, permanent ledger entries, lifecycle state, or batch closeout.
- Never turn an unknown state into a presumed healthy state.
- Never collect more sensitive evidence than the decision requires.
- Resume only after the original failure signal is absent and every downstream gate affected by the
  failure has been independently re-verified.
