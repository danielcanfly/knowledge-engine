# M26 Console P02 Ingestion implementation note

This branch implements the P02 admin ingestion route facade on top of the Gate-A Repair-A/B01 ancestry.

Production safety posture:

- production entrypoint installs `UnavailableIngestionAdapter` by default;
- no R2 write, Qdrant write, pointer swap, candidate activation, deploy, DNS change, or Access-policy change is performed;
- mutation routes require explicit canonical `effective_state` and `mutation_authorized` capability fields; legacy `state=enabled` is insufficient and fails closed;
- deterministic in-memory ingestion adapter is test/reference-only and is never installed by the production entrypoint;
- dry-run confirmation revalidates digest and source revision and fails with 409 when stale;
- read-only index audit evidence records zero write and zero repair attempts;
- confirmed ingestion remains queued candidate work and never implies activation.

Validation authority is recorded in the P02 RETURN package. Temporary validation workflows used during development were removed from the final diff.
