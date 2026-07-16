# M23.7-R3.8.9 Worker-Present Recovery Evidence Seal

## Verified run

- recovery run: `29513606007`
- artifact: `m23-7-r3-8-9-recovery-29513606007`
- artifact ZIP SHA-256: `237641a5365ae8a4865233a876387b5178f8cbf13f519e74e97982dce261fd9a`
- receipt file SHA-256: `80b05a654939a930d69e6a8143d9a384518a10d6c3536d5ad911cbde241ea054`
- receipt self-digest: `ae63a6bf337b6069430d0e50e5e29524127da57e4e0abb367eff7e62aef56ae9`
- seal digest: `14e107b32df40140471fc46e56ad15a6e2a9ef93bf1a803ab12f3c2c7ba36eb5`

The exact Worker `knowledge-engine-r3-8-29506217284` is present. Cloudflare returned
four unique version identities and four unique deployment identities through the
official `result.items[]` and `result.deployments[]` collections.

## Scope of conclusion

This is a successful read-only recovery result. It proves only that the orphan
Worker exists and binds its returned control-plane identities. It is not a latency
or quality acceptance result, does not replay the observation, and does not clear
any blocker.

Every Worker deploy/delete/secret/route flag is false. Qdrant and R2 read/mutation
flags are false. Production retrieval remains lexical.

## Next gate

After this seal is independently reconciled, a separate committed deletion
authorization may target only `knowledge-engine-r3-8-29506217284`. The deletion
workflow must prove post-delete control-plane absence and emit a separate artifact.

No fresh observation, blocker decision, parent closure, serving or promotion is
authorized by this seal.
