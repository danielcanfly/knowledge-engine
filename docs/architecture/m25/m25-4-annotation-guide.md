# M25.4 Concept Identity Annotation and Adjudication Guide

**Status:** provisional, awaiting Daniel approval  
**Policy authority:** Daniel  
**Proposer and executor:** ChatGPT  
**Resolver under measurement:** `knowledge_engine.m21_entity_resolution`

## Purpose

This guide labels identity cases before any M25.5 resolver calibration. It separates identity decisions
from explanation quality so that a correct conservative outcome cannot hide missing semantic evidence.
Every item is synthetic, candidate-only, evidence-bound, digest-signed, and incapable of changing
canonical Source or production state.

## Annotation precedence

Apply the first matching rule:

1. **Blocked policy:** ACL, audience, authority, secret, or other policy constraints require rejection.
2. **Polysemy:** one surface form has multiple plausible semantic owners, so the item is ambiguous.
3. **Insufficient evidence:** an alias or identity target cannot be uniquely selected.
4. **Contradiction:** incompatible claims about one subject are contradiction candidates, not identity
   evidence.
5. **Approved alias:** one new alias has a unique target, unique ownership, and matching audience.
6. **Duplicate:** same normalized candidate labels or an explicit duplicate hint indicate probable
   duplicate candidates, still requiring review.
7. **Supersession:** temporal versions remain distinct identities even when one supersedes another.
8. **Parent/child:** broader and narrower concepts remain distinct identities.
9. **Near match:** lexical or topical resemblance without exact identity evidence remains distinct.
10. **Exact match:** exact ID, path, canonical title, approved alias, or bilingual term identifies one
    existing concept.

## Class definitions

| Class | Gold meaning | Expected conservative behaviour |
|---|---|---|
| `exact_match` | One exact approved identity owner | `exact_existing_match` |
| `approved_alias` | New alias with one unique target | `attach_alias_candidate` |
| `duplicate` | Candidate cluster probably denotes one identity | `probable_duplicate`, block |
| `near_match_distinct` | Related wording, no identity proof | `distinct_new_candidate` |
| `parent_child_distinct` | Broader/narrower concepts | distinct identities |
| `polysemy_ambiguous` | Same surface form, different senses | `ambiguous`, block |
| `contradiction_without_identity` | Incompatible claims on one subject | contradiction candidate, block |
| `supersession_without_identity_collapse` | New temporal version replaces old | distinct identities |
| `ambiguous_insufficient_evidence` | No unique owner or target | `ambiguous`, block |
| `blocked_policy` | Policy prevents resolution | `reject`, block |

## Evidence rules

- Every gold item binds the complete case payload by SHA-256.
- Every candidate carries M21-compatible evidence spans.
- Labels and rationales are part of the signed item identity.
- Gold artifacts remain candidate-only and carry no canonical or production authority.
- A changed label, rationale, split, or case creates a new item and suite digest.

## Adjudication

ChatGPT may propose labels but may not approve them. Codex may execute tests but may not approve labels.
Daniel is the sole final annotation authority. A policy or label change requires a new revision and
SHA-256; silent edits are forbidden. Disputed items require an evidence bundle and explicit decision.

The provisional suite contains no internally disputed labels. Daniel must still approve the exact
policy and all 30 provisional labels before they become an accepted gold set.

## Split and leakage policy

- Exactly one item per class appears in each of `train`, `calibration`, and `final`.
- A semantic family appears in exactly one split.
- Duplicate case digests are forbidden.
- The final split may be measured but never used to calibrate thresholds.
- Split changes require a new suite revision and digest.

## Baseline interpretation

M25.4 does not alter resolver code or thresholds. It reports:

- semantic decision accuracy;
- false identity merge count and rate;
- contradiction and blocking correctness;
- explanation-signal coverage;
- per-class and per-split denominators;
- Wilson 95% confidence intervals;
- a deterministic error taxonomy.

A baseline score is evidence, not an authority grant. M25.5 remains blocked until M25.4 is approved,
merged, and reconciled.
