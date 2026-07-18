# M23.7 R3.8.34 Exact Deletion Authorization for Worker 29646853002

This authorization permits deletion of exactly one diagnostic Worker: `knowledge-engine-r3-8-29646853002`.

It is bound to observation run `29646853002`, recovery run `29649737557`, receipt digest `58162b70bd2bf6a97e57aba6b33c7620334f9be556a511a671dac06eeea69800`, evidence seal digest `4d3f47c70e907c3b2ac32ea69e8a6f9c37be2e18bfc274b69431add1fce01202`, independent reconciliation digest `7449466168661986f2d0c29e4c0be47288110bc513a525eb58e81efac480931f`, and the exact four Worker version IDs plus four deployment IDs recorded in the authorization JSON.

No production, Qdrant, R2, pointer, source, route, secret, promotion, blocker-clearance, parent-closure, or M23.7-closure mutation is authorized.

The deletion workflow must use attempt 1, exact accepted `main` head, the canonical authorization path, and the exact confirmation value. Post-delete absence still requires separate evidence, sealing, and independent reconciliation.
