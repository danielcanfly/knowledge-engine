# M23.7 R3.8.25 Worker-Present Recovery Seal for Run 29640614146

This seal binds schema-v2 recovery probe run `29640614146` for diagnostic Worker `knowledge-engine-r3-8-29636761264`.

The accepted recovery authorization chain culminated in PR #906 and exact `main` head `f59e071cb3aa4717ce789f3fed5dcd81c9e34d1b`. The probe performed only Cloudflare control-plane GET requests for Worker versions and deployments.

Cloudflare reported `worker_present`, with four unique version identities and four unique deployment identities. The receipt self-digest is `e9b793da99657cb14e9a7602297e2847462826baa213e6c45742b0dd59dce4a7`; the artifact ZIP SHA-256 is `83792a08e9a5cbf16c31f918bbbdf7b5ba77430dc5f0cc009463ce41ed0bd6bb`.

No observation replay, Worker delete/deploy, secret mutation, route invocation, Qdrant access, R2 access, protected mutation, blocker clearance, promotion, parent closure, or M23.7 closure occurred. Production retrieval remains `lexical`.

The next legal gate is independent reconciliation of this seal. Only an accepted reconciliation may authorize a separate exact Worker deletion record.
