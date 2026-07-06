# M6-001 Source Inventory Runbook

Status: `inventory only`

Parent tracker: `#42`

Child slice: `#51`

Batch spec: `docs/batches/m6-001-llm-wiki-foundation-batch.md`

Proposal: `docs/batches/m6-001-source-pr-proposal.md`

This runbook defines the evidence contract for local inventory of `danielcanfly/knowledge-source`.

## Purpose

M6.4 did not identify concrete Source paths through GitHub search. M6.5 therefore requires a local inventory pass before any exact Source path can be proposed.

## Required inventory evidence

The local inventory must capture:

- repository name;
- local root;
- UTC timestamp;
- current branch;
- HEAD SHA;
- git status;
- complete file tree;
- text-like file list;
- text-like file sizes;
- M6 keyword hits;
- candidate paths derived from keyword hits;
- a short summary suitable for pasting back into the M6 session.

## Required paste-back fields

The operator must paste back:

1. inventory directory path;
2. inventory zip path;
3. checksum line;
4. summary block;
5. candidate paths from keyword hits;
6. unusually large text-like files, if any.

## Candidate path review table

After inventory, candidate paths must be reviewed with this table:

| Source path | Candidate family | Inclusion rationale | Citation target | Boundary risk | Proposed decision |
| --- | --- | --- | --- | --- | --- |
| `pending` | `pending` | `pending` | `pending` | `pending` | `pending` |

## Interpretation

If candidate paths are found, the next M6 step should review them and update the Source PR proposal.

If no candidate paths are found, record that evidence and decide whether a future Source PR should add curated Source files.

## Non-authorization

This inventory is evidence only. It does not approve Source content, run a candidate build, create a production request, or change production state.

## Completion criteria

M6.5 is complete when this runbook is merged to `main` and CI is green. Running the local inventory is the next execution step after M6.5.
