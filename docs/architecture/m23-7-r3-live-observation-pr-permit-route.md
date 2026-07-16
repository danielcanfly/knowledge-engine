# M23.7 R3 Live Observation PR-Permit Route

Issue: #595

This change adds a second static PR-permit route for the fresh R3 live
observation phase after the old R3.8 diagnostic Worker absence chain was
sealed and independently reconciled.

The new command type is `r3_live_reobservation`. It is intentionally separate
from the already accepted `r3_8_post_delete_recovery` route.

## Authorized Surface

The live route may only:

- deploy one uniquely named transient Worker with prefix
  `knowledge-engine-m23-7-r3-live`;
- install transient Worker secrets required for the diagnostic observation;
- invoke that transient Worker route for the bounded R3 observation;
- read the Qdrant collection through the existing observation path;
- call Workers AI through the Worker AI binding;
- delete the transient Worker after the observation attempt;
- upload a privacy-safe GitHub Actions artifact.

The live route may not:

- mutate Qdrant;
- read or mutate R2;
- mutate Source, production pointer, or permanent ledgers;
- serve semantic output to production;
- clear blockers;
- close #520, #474, or M23.7;
- grant promotion eligibility.

## Evidence Semantics

The route writes:

- `live-observation-report.json`, produced by the existing
  M23.7-R3 bounded live re-observation validator;
- `live-observation-receipt.json`, a privacy-safe summary that persists no
  Worker URL, service URL, service hostname, credentials, raw query text, raw
  answer text, or arbitrary exception text.

A passing report is only `pass_live_observation_pending_reconciliation`.
It does not by itself clear blockers. Blocker clearance still requires the
separate seal, independent reconciliation, transient Worker deletion proof, and
R3 final reconciliation required by the M23.7 handoff.

## Next Legal Step

After this route-enablement PR merges, create a request-only PR against the
route merge SHA using:

- authorization path
  `operator_authorizations/m23/r3-live/r3-live-reobservation-v1.json`;
- command type `r3_live_reobservation`;
- exact base SHA equal to the route-enablement merge SHA;
- the authorization nonce and SHA from that file.

Only after the request-only head passes request validation, CI, and M18 may a
single permit file be added as the next commit on the same branch.
