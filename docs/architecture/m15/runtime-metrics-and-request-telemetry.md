# M15.2 Runtime Metrics and Request Telemetry

Parent: #204  
Slice: #207

## Baseline

- Engine: `252e345a7ee01af10d9151a33a318531629c8eda`
- Canonical Source: `2126db2ed4d372d3d61464fe31a86fc0243a1f24`
- Production release: `20260708T040116Z-69a9f445699a`
- Manifest: `2b2630cfe3e8a6e25a8f210d68c70f3b9a31b3b26f33c6e3e41b8cc1676fc0bb`
- Pointer: `38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5`

## Runtime event surface

M15.2 implements a closed event-name registry for request start, retrieval completion, ACL filtering, citation assembly, answer completion, feedback intake, security rejection, and telemetry drops. Unknown names fail closed.

Events use the M15.1 `ObservabilityEvent` and `ObservabilityIdentity` contracts. Release-bound events carry exact Engine, canonical Source, release, manifest, pointer, and request or operation identity.

## Privacy and cardinality

Only M15.1-approved dimensions are accepted. Runtime attributes are restricted to bounded buckets and sanitized drop reasons. Raw query, raw answer, prompts, tokens, JWT claims, IPs, hostnames, private excerpts, URLs, private object locations, source IDs, concept IDs, and arbitrary exception text are never written.

Metric snapshots contain only fixed counter names and integer values. Request, operation, release, source, and concept identities cannot become metric labels.

## Failure behavior

Telemetry is deliberately outside the product decision path. Sink exceptions are converted to `sink_failure`, increment a bounded dropped-event counter, and never alter the answer object or raise through the caller. A failed write cannot be represented as recorded evidence.

Duplicate canonical events are dropped deterministically. Ordinary request events may be sampled using a stable SHA-256 decision over a correlation key. Security rejection events bypass ordinary sampling and are always attempted.

## Sinks

- `InMemoryTelemetrySink` supports deterministic tests and bounded process-local inspection.
- `JsonlTelemetrySink` appends canonical, sorted UTF-8 JSON lines to an explicitly configured local path.

No external vendor, network exporter, R2 writer, production repair, Source write, or ledger append is introduced.

## Bucketing

Counts and latency values are transformed into closed buckets before becoming attributes. Buckets are stable and prevent uncontrolled series expansion or accidental fine-grained behavioral fingerprints.

## Governance boundary

M15.2 observes runtime behavior only. It cannot change retrieval, ACL, citation, answer, feedback, Source, release, pointer, cache, R2, promotion, rollback, deletion, or correction state. Permanent ledger #30 remains unchanged.
