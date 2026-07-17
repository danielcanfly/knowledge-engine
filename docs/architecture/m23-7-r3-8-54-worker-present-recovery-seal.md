# M23.7 R3.8.54 Worker-Present Recovery Seal

This seal binds two schema-v2 recovery probe runs for retained diagnostic
Workers left by failed fresh R3.8 observations:

- `29569671523` for `knowledge-engine-r3-8-29568576968`
- `29569675689` for `knowledge-engine-r3-8-29568662778`

The recovery probes were authorized by PRs #748 and #749, with effective script
authorization merged at exact head `009268230ab23f8b3b423ad904301fe7ac5893a3`.
Each probe performed only official Cloudflare control-plane read requests for
Worker versions and deployments.

Both Workers are present. Cloudflare returned four unique version identities and
four unique deployment identities for each retained Worker. The recovery receipt
self-digests are:

- `096ca1d0e6a74523b511d23c10c1b0054586579ce1de0c63e4ef888798844430`
- `0adf0ae4da3e84e458de7ba4d20188ad41e76f7b92d18a2b576619d82e8576c7`

The artifact ZIP SHA-256 values are:

- `009def7b019946819fa199cb91da0dca0140fa427b29eb6d7b5cb3c8927efad5`
- `30ae791a2e8b0f01aff685f2487ebb8a4a3c3246820e22088c648b301654e374`

No observation was replayed. No worker delete, deploy, secret mutation, route
invocation, Qdrant access, R2 access, protected mutation, blocker clearance, or
closure action occurred. Production retrieval remains `lexical`.

The next legal step is independent reconciliation of this worker-present seal.
Only after that may a separate deletion authorization be created for the two
retained Workers.
