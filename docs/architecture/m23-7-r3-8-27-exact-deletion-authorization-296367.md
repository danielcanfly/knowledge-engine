# M23.7 R3.8.27 Exact Deletion Authorization for Worker 29636761264

This authorization permits deletion of exactly one diagnostic Worker: `knowledge-engine-r3-8-29636761264`.

It is bound to observation run `29636761264`, recovery run `29640614146`, receipt digest `e9b793da99657cb14e9a7602297e2847462826baa213e6c45742b0dd59dce4a7`, evidence seal digest `bba9f426db0c18696684a9ecf124a4c5dfa0cacccd55d0efd2686eddcab90331`, independent reconciliation digest `2be146bc3821a0fa3eacb44cf840fd546614fee4694b5edb85614cb7fbd2aa57`, and the exact four Worker version IDs plus four deployment IDs recorded in the authorization JSON.

No production, Qdrant, R2, pointer, source, route, secret, promotion, blocker-clearance, parent-closure, or M23.7-closure mutation is authorized.

The deletion workflow must use attempt 1, exact accepted `main` head, the canonical authorization path, and the exact confirmation value. Post-delete absence still requires separate evidence, sealing, and independent reconciliation.
