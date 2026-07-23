# M25.9A Controlled Pilot Control Plane and Inventory Gate

Status: `m25_9a_control_plane_implemented_awaiting_inventory_authority`

## Purpose

M25.9 proves population-scale operation, decision workload, quality, recovery, and bounded adoption across 50–100 heterogeneous sources. It does not grant large-scale ingestion or production authority.

This implementation establishes the deterministic control plane for M25.9A only. It does not execute a live pilot.

## Stage decomposition

- **M25.9A Full-population candidate run:** exact inventory, immutable acquisition, normalization, extraction, identity resolution, relation/tag governance, candidate packets, metrics, and failure drills.
- **M25.9B Human decision population:** every candidate receives a terminal human decision or explicit blocker.
- **M25.9C Approved-subset adoption:** only Daniel-approved candidates may become Source PRs, candidate releases, and recovery drills.

M25.9B and M25.9C remain separately governed and unauthorised here.

## Inventory contract

A live inventory contains 50–100 sources and must represent all of the following:

- long-form Markdown;
- shorter technical notes;
- structured JSON;
- bounded web snapshots;
- English, Traditional Chinese, and mixed-language content;
- low-yield and dense-yield sources;
- public and restricted audiences;
- duplicates, near-duplicates, alias-rich sources, ambiguity, conflicting claims, superseded material, noisy formatting, prompt-injection-like text, and unsupported or irrelevant content.

Every inventory entry binds a stable source ID, source type, exact origin locator, SHA-256 identity, language, audience, licence class, expected yield, and declared traits.

The 30 M25.6/M25.7 gold benchmark fixtures are not reusable as live pilot sources.

## Exact authority gate

Live execution requires an authority envelope that binds:

- the exact inventory SHA-256 and source count;
- Daniel's exact authority comment;
- explicit inventory approval and pilot-start approval;
- provider-call permission;
- maximum pilot cost;
- maximum failed-source count;
- zero tolerated unaccounted sources;
- zero tolerated security failures;
- explicit denial of production pointer, production release, large-scale ingestion, M25.9B, and M25.9C authority.

A general instruction to continue does not authorise an unseen inventory or secret-bearing live execution.

## Full-population accounting

Every source must appear exactly once in the run population and end in one explicit M25.9A state:

- `candidate_ready`;
- `no_new_knowledge`;
- `rejected_policy`;
- `rejected_unsupported`;
- `deferred_ambiguity`;
- `deferred_contradiction`;
- `failed_technical`;
- `cancelled_by_operator`.

There is no silent exclusion state. Non-candidate states cannot claim candidate output.

## Deterministic checkpoints

The control plane requires the exact ordered stages:

1. dry-run inventory and policy validation;
2. immutable acquisition;
3. normalization;
4. extraction;
5. identity resolution;
6. relation/tag governance;
7. candidate packaging.

Each stage must pass and produce a digest-bound checkpoint.

## Failure drills

The M25.9A evidence contract requires passing evidence for:

- interrupted acquisition;
- provider timeout;
- invalid model JSON;
- stale checkpoint;
- Source base drift;
- duplicate path collision;
- incomplete review;
- failed Source CI;
- failed release rebuild;
- candidate rollback;
- Access/security regression.

The later-stage drills are contract simulations in M25.9A. Actual Source CI, release rebuild, and rollback operations belong to M25.9C after separate authority.

## Current live gate

The current M25.8 live disposition is `blocked_awaiting_real_approved_source_pr`. Therefore M25.9A live execution remains:

`blocked_awaiting_m25_8_live_acceptance_and_exact_inventory_authority`

The next legal action is to curate an exact 50–100 source inventory and present its digest, source-class mix, ACL/licence evidence, cost ceiling, provider policy, and stop thresholds to Daniel.

## Protected boundaries

This implementation performs no:

- live provider call;
- Source write or merge;
- candidate deployment;
- Qdrant or R2 production mutation;
- production release or pointer mutation;
- traffic or credential mutation;
- M25.9B, M25.9C, M25.10, or large-scale-ingestion authorisation.
