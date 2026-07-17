# M23.7 R3.8.126 Deletion/Absence Evidence Seal for 29602737093

This seal binds deletion run `29603881729` and post-delete recovery probe run `29603984852` for retained diagnostic Worker `knowledge-engine-r3-8-29602737093`.

Deletion run `29603881729` exited 23 at `absence_probe`, but the evidence confirms `worker_delete_dispatched=true` for authorization `a17f1bc4389734992c41ba71cbf1adcfb969827900a451a8eb061979c826558e`.

Post-delete recovery probe run `29603984852` then observed `worker_absent`: versions and deployments both returned 404 with error code `10007`, zero identities, and no protected mutations.

Evidence:

- Deletion artifact id: `8416075581`
- Deletion artifact zip SHA256: `0ae55c286cd28ffa3b7fccf8a9617b3448c3ec94d27fa05df4b7aca586890ad1`
- Deletion failure file SHA256: `c8153f7984a124b66ddef7414b4322da4b4ba6b0a5afc9efccc6b8dc7e7b7e63`
- Deletion failure self digest: `6dc621dbff1ec651ea0e9bb9344c4f242da6e8385e3217bfa578577b1fdf2796`
- Post-delete recovery artifact id: `8416112608`
- Post-delete recovery artifact zip SHA256: `7b93c1efba157ec69e6a0c8848db972fc0a5e9bc4618b2125d8d6e148b01b0f6`
- Post-delete recovery receipt file SHA256: `947ea6c898767f2e33929f7825be97ee44eb451c249ac0197e0a5500f36da993`
- Post-delete recovery receipt self digest: `6ee6670ad84830fa92d4a434620dfc6077ea74771d43b3c87d81b400ff283e10`
- Seal SHA256: `b952ac994ee40f05bb0d0d814fe672c1db9227847685127deefa3f43a0e43dcf`

This seal does not clear blockers, authorize fresh observation, authorize parent closure, or authorize M23.7 closure.
