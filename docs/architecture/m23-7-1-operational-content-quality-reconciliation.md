# M23.7.1 Reconciliation

- Issue: #409
- Parent: #408
- Implementation PR: #410
- Accepted exact head: `38d581008080646e08056f4b08215213a154254a`
- Expected-head squash merge: `6cc220845df287c58684ef424a31093d612596f3`
- Successful workflows: M23.7.1 #4, CI #831, R2 #558, M17 #156, M18 #267
- Rejected heads: `81c9523b8322042a342fd16c9c59741e0d84bb81` and `1810e1897c524d3e540a2c258ca2e719a9e351aa`

The accepted contract freezes 24 ordered cases across six balanced query classes and locks Recall@5, MRR@10, nDCG@10, provenance, ACL, no-answer and lexical non-regression gates. Semantic output remains evaluation-only; production retrieval remains lexical.

No provider/network call, retrieval, answer generation, deployment, traffic change, Source/R2/pointer/Qdrant mutation, ledger mutation, credential rotation, public Explorer or Graph Neural Retrieval occurred.

M23.7.2 becomes legal only after this reconciliation is merged and #409 is closed completed.

Production mutation dispatched: false.
