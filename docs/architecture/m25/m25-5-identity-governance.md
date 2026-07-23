# M25.5 Calibrated Concept Identity and Knowledge Governance

Status: implementation candidate  
Predecessor: `m25_4_gold_benchmark_accepted`  
Exit status after merge and reconciliation: `m25_5_identity_governance_accepted`

## 1. Purpose

M25.5 adds a conservative calibration and governance layer above the inherited M21 resolver. It does
not replace the resolver, silently relabel the M25.4 gold set or grant canonical authority. The layer
exists to close the explanation gaps identified by M25.4 while preserving the resolver's zero-false-
merge baseline.

The implementation performs four jobs:

1. rank plausible Source concepts with explicit score components;
2. enforce a fail-closed merge and alias gate;
3. add deterministic explanation signals for near matches, parent/child distinctions, polysemy and
   supersession;
4. emit candidate-only `narrower_than` and `supersedes` relation proposals for human review.

## 2. Frozen inputs

M25.5 consumes only the approved M25.4 identities:

- approved suite: `pilot/m25/m25-4-gold-suite.json`;
- accepted baseline: `pilot/m25/m25-4-baseline-report.json`;
- predecessor acceptance: `pilot/m25/m25-4-acceptance.json`;
- inherited resolver: `src/knowledge_engine/m21_entity_resolution.py`.

No M25.4 labels, splits or case bytes are changed.

## 3. Calibration discipline

Only the 20 train and calibration items participate in calibration. The ten final items remain held
out. The final split may measure the frozen policy but may not change weights, thresholds, signal
rules or relation rules.

The committed policy records the exact calibration and held-out item IDs. Validation fails closed if
an item appears in both populations or if any final item enters the calibration population.

## 4. Conservative ranking

Each endpoint candidate is ranked against Source concepts using separately exposed components:

- exact title ownership;
- exact approved alias ownership;
- exact bilingual-term ownership;
- token Jaccard overlap;
- token containment;
- sequence similarity;
- governed-tag overlap;
- audience mismatch penalty;
- version mismatch penalty.

Lexical similarity and governed tags are weak evidence. They may rank candidates for review but may
never independently authorise an identity merge.

## 5. Merge and alias gate

The M21 outcome remains the inherited decision. M25.5 adds a second safety gate:

- `exact_existing_match` requires an exact identity signal and a score at or above the frozen floor;
- `attach_alias_candidate` requires the inherited unique-target signal and an exact target binding;
- lexical-only and tag-only merges are forbidden;
- ambiguity, duplicate clusters and policy rejections always block destructive action;
- every output remains `pending_review` and `candidate_only`;
- automatic canonical writes are always false.

A gate failure never converts a case into a different destructive decision. It blocks packaging and
surfaces the reason for review.

## 6. Explanation closure

M25.4 found 12 explanation gaps across four classes. M25.5 adds deterministic signals without using
the final split for calibration:

| Signal | Evidence rule |
|---|---|
| `near_match_distinction` | lexical proximity exists, but there is no exact identity owner |
| `parent_child_distinction` | one concept has a narrower scope or a governed semantic hierarchy |
| `polysemy_collision` | one surface form has multiple exact owners |
| `supersession_distinction` | temporal or version markers differ while the non-version stem matches |

Inherited exact-match, alias, duplicate, contradiction, ambiguity and policy-block signals are
preserved.

## 7. Relation and tag governance

Parent/child and supersession findings create relation candidates only:

- child candidate to broader Source concept: `narrower_than`;
- later version candidate to earlier Source concept: `supersedes`.

Each relation is evidence-bound, pending review, non-canonical and non-production-authoritative.
Governed tag candidates are copied without authority upgrade, reclassification or canonical write.

## 8. Bilingual alias safety

Bilingual terms participate as exact ownership signals, but multiple owners produce ambiguity rather
than a selected target. Alias chains remain forbidden by the inherited resolver. Audience mismatch,
ownership collision or multiple targets fail closed.

## 9. Contradiction and supersession

Contradictions concern incompatible claims about one resolved subject. They do not merge or split the
subject identity. Supersession represents a temporal relationship between distinct identities. A new
version may link to an older version, but identity collapse is forbidden.

## 10. Benchmark gate

The M25.5 candidate gate requires all of the following:

- semantic decision accuracy `1.0`;
- explanation-signal coverage `1.0`;
- combined governance pass rate `1.0`;
- held-out final governance pass rate `1.0`;
- false merge count `0`;
- critical false-merge risk count `0`;
- destructive decision count `0`;
- final split remained held out.

Passing this gate produces `m25_5_identity_governance_ready`. The accepted status is written only by
the independent post-merge reconciliation.

## 11. Protected boundaries

M25.5 does not mutate or enable:

- Source or Foundation;
- release objects or production pointers;
- R2 production content;
- Qdrant collections;
- semantic or hybrid serving;
- production answer serving;
- canonical merge, split or alias decisions;
- M25.6.

## 12. Operational commands

```bash
knowledge-m25-identity-governance policy \
  --suite pilot/m25/m25-4-gold-suite.json \
  --baseline pilot/m25/m25-4-baseline-report.json \
  --output /tmp/m25-5-policy.json

knowledge-m25-identity-governance run \
  --suite pilot/m25/m25-4-gold-suite.json \
  --baseline pilot/m25/m25-4-baseline-report.json \
  --policy pilot/m25/m25-5-calibration-policy.json \
  --output /tmp/m25-5-report.json \
  --gate-output /tmp/m25-5-gate.json
```

Committed artifacts must reproduce byte-for-byte from these commands on the exact PR head.
