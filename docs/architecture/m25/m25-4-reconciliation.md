# M25.4 Reconciliation and Acceptance

**Accepted status:** `m25_4_gold_benchmark_accepted`  
**Implementation issue:** #1046  
**Implementation PR:** #1047  
**Approved policy and label head:** `cf56bad3b9128020214c3a30100ec741d6842e56`  
**Final implementation head:** `a58df21e1ace0bf5793fab3de3aca161818df528`  
**Implementation merge:** `9b75e467678889980aa91d31f1c41bfb72e41ee6`

## Acceptance result

M25.4 is accepted after Daniel's exact policy and label decision, final-head validation and
independent reconciliation. Engine main now contains an evidence-bound 30-item concept-identity gold
suite across ten governance classes, balanced train/calibration/final splits, immutable annotation and
adjudication policy, an approved adjudication ledger, leakage checks, deterministic baseline metrics,
confidence intervals, error taxonomy and a benchmark runner over the unchanged M21 resolver.

The accepted baseline records 30/30 semantic decisions, zero false merges and 18/30 explanation-signal
coverage. The twelve explanation gaps are concentrated in near-match, parent/child, polysemy and
supersession classes. These gaps are evidence for M25.5 calibration work; M25.4 did not modify resolver
code, thresholds or runtime authority.

## Daniel authority

Daniel approved the exact candidate head `cf56bad3b9128020214c3a30100ec741d6842e56`, the exact annotation
and adjudication policy, all 30 provisional labels and disputed-item count zero. The authority record is
GitHub issue comment `5053875354` by `huaihsuanbusiness`. The approval explicitly did not authorise
M25.5 and did not authorise resolver calibration, Source mutation or production mutation.

Post-approval commits were restricted to approval records, accepted wrappers, tests and exact-head CI.
The approved policy, provisional suite, provisional baseline, gate, resolver and CLI were verified
unchanged from the approved candidate.

## Exact evidence

The final implementation head passed M25.4 benchmark, Daniel approval finalisation, global CI, M17
architecture, independent operator GA, M18 graph, M25.2, M25.3 and R2 integration workflows. Retained
evidence artifacts bind the exact head to both benchmark and authority decisions:

- benchmark evidence digest:
  `sha256:091aa7a584c2ba7ba056647dbaeeab73ba95bca3b0c66ac52ea1a8e247f43e81`;
- Daniel approval evidence digest:
  `sha256:1eef2312f88d38d7316c05911ba175c8a38ee058f9cfea6b5fbf710aab1960f1`.

## Preserved boundaries

- No resolver calibration or threshold change occurred.
- The final evaluation split was not used for calibration.
- No Source, Foundation, release, production pointer, R2 production or Qdrant mutation occurred.
- No semantic/hybrid serving, production answer serving or large-scale ingestion authority changed.
- ChatGPT was the primary executor; Codex usage and escalation were zero.

## Next legal stage

M25.5 **Calibrated Concept Identity and Knowledge Governance** becomes the only authorised next stage
after this M25.4 closure. This authorisation arises from the accepted roadmap predecessor status
`m25_4_gold_benchmark_accepted`, not from Daniel's M25.4 approval alone.

Machine-readable acceptance: `pilot/m25/m25-4-acceptance.json`.
