# M10 and M5 to M11 Reuse and Migration Map

M11 generalizes proven components. It must not fork them into a second storage, identity, review, or governance system.

## 1. M10 intake reuse

| Existing capability | M11 use | Migration rule |
|---|---|---|
| `ObjectStore`, filesystem and R2 implementations | immutable compiler artifacts | reuse directly; no compiler-specific storage backend |
| `canonical_json_bytes()` | semantic identities and hash input | adopt M10 canonical JSON v1 for all new contracts |
| `source_id`, `snapshot_id`, `derivative_id` | immutable compiler input references | reference exact values; never remint or rewrite |
| `intake-snapshot/v1` | source, owner, license, ACL and content identity | verify exact object bytes and hash before compilation |
| derivative record and normalized object | structured parsing input | bind normalizer ID/version and normalized hash |
| compilation admission | legal entry gate | only `accepted_for_compilation` may enter the compiler |
| event/rejection/result pattern | compiler run evidence | preserve immutable hash-linked events and typed terminal evidence |
| ACL non-broadening | every derived artifact | use the same audience order and fail-closed unresolved policy |
| secret and prompt-like-content handling | compiler safety | secrets remain rejected; prompt-like content remains untrusted data |

M11 must not read connector-specific mutable state when an immutable snapshot or evidence record is available.

## 2. M5 synthesis reuse

### Reuse

- closed provider/harness identity;
- source text treated as untrusted data;
- strict model-output contract;
- exact character-span and quote validation;
- line ranges and quote hashes;
- supported versus unsupported claim separation;
- immutable review-only objects;
- canonical, GitHub, and production writes denied.

### Generalize

M5 synthesis reads legacy `raw/captures/{capture_id}.json`. M11 synthesis must read the generic compiler input, structured blocks, source maps, and extraction candidates derived from M10 snapshots. Legacy capture support may be provided only through an explicit compatibility adapter, never by weakening the M11 input contract.

M5 emits one concept-shaped draft. M11 may emit multiple typed proposals, but every statement must retain evidence and resolution identity.

## 3. M5 resolution reuse

### Reuse

- exact clean `knowledge-source` SHA;
- deterministic Source snapshot digest;
- stable target concept identity;
- audience ranking and downgrade blocking;
- immutable review-only resolution evidence;
- ambiguous matches fail closed.

### Replace or strengthen

The M5 actions `create`, `update`, `alias`, `merge`, `conflict`, and `no-op` are too compressed for M11. M11 uses:

```text
new_concept
existing_concept_update
alias
duplicate
contradiction
supersession
unresolved_conflict
rejected_unsupported_claim
```

Simple lexical similarity and negation detection may remain candidate-generation signals. They are not sufficient final evidence for contradiction, duplicate, or supersession. M11 records scores and reasons and requires explicit review for ambiguous or destructive changes.

## 4. M5 review reuse

### Reuse

- immutable `approved`, `rejected`, and `needs_changes` decisions;
- reviewer and timestamp identity;
- conflict/security states cannot be silently approved;
- approved audience cannot broaden effective audience;
- Source package is generated only after approval;
- direct apply, canonical write, GitHub write, and production write remain false;
- exact Source SHA and snapshot are reverified before packaging;
- Source validation and human PR review remain mandatory.

### Generalize

M11 reviewer packets may contain multiple proposals and typed contradiction or supersession records. Source package materialization must consume only an approved immutable packet and exact proposal set. The compiler itself ends before the decision and package mutation boundary.

## 5. M7-M9 governance reuse

M11 implementation slices use:

- explicit parent and child issues;
- exact baseline SHAs;
- small reviewed PRs;
- immutable evidence artifacts;
- no mutation claims backed by inspection rather than workflow color alone;
- adjacent lifecycle transitions where a governed content batch is involved;
- explicit human approval before canonical or production mutation;
- exact candidate, release, manifest, request and operation identities;
- idempotent replay before batch closure;
- permanent ledger #30 only for production evidence.

M11 architecture and compiler implementation do not create a production ledger entry because no production release changes.

## 6. Compatibility boundaries

- Historical M5 captures and review objects remain immutable and readable.
- Historical M10 snapshots and connector evidence remain immutable and are not rewritten.
- A compatibility adapter must identify both source and target schema versions and preserve original hashes.
- An adapter cannot infer missing ACL/license evidence or broaden audience.
- New compiler artifacts use only `compiler/v1/`; they do not share legacy M5 review keys.
- Canonical Source and runtime release formats remain unchanged in M11.1.

## 7. M11.2 implementation map

The local Markdown reference compiler should initially reuse:

```text
knowledge_engine.intake_v1.canonical_json_bytes
knowledge_engine.storage.ObjectStore
knowledge_engine.storage.sha256_bytes
M10 immutable collision behavior
M10 audience/access-policy validation concepts
```

It should introduce a new compiler module only for compiler-domain behavior, not duplicate intake. The executable path starts from immutable M10 object references, never from an arbitrary local path.

M11.2 does not reuse the M5 model harness yet. It proves deterministic structure, source mapping, extraction limits, policy propagation, event chaining, replay, and write boundaries first.