# M23.7 R3.8.39 Exact Deletion Authorization for Worker 29667556969

This authorization permits deletion of exactly one diagnostic Worker: `knowledge-engine-r3-8-29667556969`.

It is bound to observation run `29667556969`, recovery run `29693171225`, receipt digest `95cad3e49f8fc925a055d64b9c974340d5f6d5369109d993d9b75c4d7dccf35e`, evidence seal digest `67952491ef6fe004ddb33ca9672b0385ce207d5c21c69ff02b49bf6f69218983`, independent reconciliation digest `0bf9ec2941636550ade2b857e28218009f545aa800ad1964713b1929188e552a`, and the exact four Worker version IDs plus four deployment IDs recorded in the authorization JSON.

No production, Qdrant, R2, pointer, source, route, secret, promotion, blocker-clearance, parent-closure, or M23.7-closure mutation is authorized.

The deletion workflow must use attempt 1, exact accepted `main` head, the canonical authorization path, and the exact confirmation value. Post-delete absence still requires separate evidence, sealing, and independent reconciliation.
