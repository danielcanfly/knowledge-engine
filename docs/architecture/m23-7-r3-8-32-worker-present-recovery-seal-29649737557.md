# M23.7 R3.8.32 Worker-Present Recovery Seal for Run 29649737557

This seal binds schema-v2 recovery probe run `29649737557` for diagnostic Worker `knowledge-engine-r3-8-29646853002`.

The accepted recovery authorization chain culminated in PR #924 and exact `main` head `8e341bc076e6b800f43323952d2dc409ef1da76b`. The probe performed only Cloudflare control-plane GET requests for Worker versions and deployments.

Cloudflare reported `worker_present`, with four unique version identities and four unique deployment identities. The receipt self-digest is `58162b70bd2bf6a97e57aba6b33c7620334f9be556a511a671dac06eeea69800`; the artifact ZIP SHA-256 is `45cb3d874feced81bcb12e70318f938dab55f5bddae837b158304b5fc811bae7`.

No observation replay, Worker delete/deploy, secret mutation, route invocation, Qdrant access, R2 access, protected mutation, blocker clearance, promotion, parent closure, or M23.7 closure is authorized by this seal. Production retrieval remains lexical and both retained blockers remain in force.
