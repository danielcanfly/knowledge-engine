# M10.1 Test Strategy and Acceptance

## Contract tests

### Identity

1. exact same bytes and metadata produce the same snapshot ID;
2. same bytes, different URI/source produce different snapshots and one raw blob;
3. same source, changed bytes produce a new snapshot with parent linkage;
4. same bytes, changed ACL produce a new snapshot;
5. storage location is excluded from snapshot identity;
6. canonical JSON key order does not change identity.

### Immutability

1. immutable create succeeds once;
2. identical replay is idempotent;
3. different bytes at an existing key fail;
4. missing object after write fails;
5. mutable index CAS failure cannot alter immutable evidence.

### State machine

1. all legal transitions pass;
2. skipped/reversed transitions fail;
3. rejection is terminal;
4. retry after rejection uses a new attempt;
5. terminal result is write-once;
6. event hash chain detects deletion/reordering/tampering.

### ACL and license

1. unknown ACL defaults restricted and cannot be accepted;
2. public plus internal inputs yield internal-or-more-restrictive output;
3. principal widening fails;
4. permission-only changes create new snapshots;
5. missing license blocks admission;
6. restricted bytes never enter public derivative namespaces.

### Connector behavior

Each connector must pass a shared suite for:

- deterministic canonicalization;
- credential redaction;
- timeout and transient retry;
- truncation detection;
- byte/size/hash accounting;
- typed failures;
- no canonical, GitHub, or production writes.

### Security

- SSRF fixtures;
- path traversal and symlink escape;
- oversized/decompression bomb fixtures;
- malformed PDF/binary fixtures;
- prompt-injection content retained as data;
- secret-like content rejected without durable raw storage;
- malicious MIME mismatch;
- error/log redaction.

## Reference implementation gate for M10.2

The first connector should be local-file/Markdown because it can prove all contracts deterministically without network variability. It must reuse the existing `ObjectStore` and produce compatibility evidence against M5.1 fixtures.

## M10.1 acceptance checklist

- [x] architecture decision record defined;
- [x] snapshot identity and schema defined;
- [x] connector protocol defined;
- [x] state machine and legal transitions defined;
- [x] R2 key layout defined;
- [x] ACL/audience non-broadening rules defined;
- [x] threat model defined;
- [x] test strategy defined;
- [x] M5.1 migration/reuse map defined;
- [x] no production mutation is required or authorized;
- [ ] human review of architecture PR completed;
- [ ] PR merged after CI/document/schema checks;
- [ ] M10.2 implementation issue opened from accepted design.

## CI checks for this design PR

1. parse every JSON document;
2. validate example snapshot against JSON Schema Draft 2020-12;
3. check Markdown links and relative paths;
4. scan for secrets;
5. assert no workflow, production request, governed batch, Source, or runtime code changed;
6. assert current production pointer is not written.

## Exit criterion

M10.1 is complete only when the architecture package is merged and a reviewer can answer, without relying on chat history:

- what is immutable;
- how identities are computed;
- how connectors are constrained;
- how failures are evidenced;
- how ACLs propagate;
- where objects live;
- what M5.1 code is reused;
- what M10.2 must implement.
