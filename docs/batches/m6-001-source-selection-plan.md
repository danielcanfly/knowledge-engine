# M6-001 Source PR Selection Plan

Status: `planning / no Source approval`

Parent tracker: `#42`

Child slice: `#47`

Batch spec: `docs/batches/m6-001-llm-wiki-foundation-batch.md`

This plan defines how Source files should be selected for `m6-001-llm-wiki-foundation`. It does not create Source content, approve Source content, run a candidate build, create a production request spec, or authorize production promotion.

## 1. Purpose

The M6-001 batch spec creates a named batch envelope. This selection plan defines the review criteria for deciding which Source files may enter that envelope.

The goal is to avoid three failure modes:

1. treating a broad topic label as approved Source scope;
2. copying chat memory into canonical Source without review;
3. selecting content that cannot produce citation-backed runtime acceptance.

## 2. Selection boundary

### Candidate source families

The following families may be considered for a future Source PR:

- LLM Wiki foundation notes
- Knowledge OS governance notes
- production-RAG / agent architecture notes
- operator glossary entries needed for public Q&A
- closeout-derived operational explanations that are safe to publish or cite

These are candidate families only. They are not approved Source files.

### Approved Source files

Approved Source files are only the files explicitly included in a reviewed and merged Source PR in `danielcanfly/knowledge-source`.

Until that Source PR exists, the approved Source file list is:

- `none`

## 3. Inclusion criteria

A Source file may be proposed for M6-001 only if it satisfies all of the following:

- It has a clear relationship to LLM Wiki / Knowledge OS foundation material.
- It can support at least one public acceptance query.
- It has a stable citation target or can be mapped to one during Source review.
- It does not contain secrets, tokens, private account identifiers, or personal private data.
- It is not a raw chat transcript copied directly into canonical Source without cleanup and review.
- It does not require weakening ACL, citation, or raw fallback checks.
- It can be validated through the existing Source validation workflow.

## 4. Exclusion criteria

Exclude any file or content segment that matches any of the following:

- credentials, tokens, keys, or private infrastructure details;
- private operational notes not intended for public retrieval;
- unresolved personal data or account identifiers;
- draft chat material that has not been curated into Source form;
- content whose expected answer would require raw fallback;
- content with no viable citation target;
- content that depends on changing production workflow gates;
- content that cannot be reviewed through a normal Source PR.

## 5. Minimum Source PR structure

The future Source PR should include at minimum:

- a clear title referencing `m6-001-llm-wiki-foundation`;
- a list of added or changed Source files;
- a short explanation of why each file belongs in M6-001;
- proposed public acceptance query or queries;
- expected citation URL or citation target for each public query;
- proposed ACL negative query if the content creates any access boundary risk;
- confirmation that no secrets or private data are included;
- confirmation that no raw chat transcript is copied directly into Source;
- Source validation workflow result after merge.

## 6. Citation target planning

Before a Source PR can be treated as ready, each public acceptance query must have one of the following:

- an existing public URL that should appear as a citation;
- a canonical Source-backed citation target to be produced by the pipeline;
- an explicit blocker explaining why citation acceptance cannot yet be defined.

For M6-001, the provisional public query from the batch spec is:

```text
what is the LLM Wiki foundation for Knowledge OS?
```

The final query may change after Source file selection. Any final query must still require:

- expected public status: `answered`;
- expected citation URL or citation target present;
- raw fallback used: `false`.

## 7. ACL negative query planning

ACL negative queries should be selected by asking: what private or operator-only concept might be accidentally exposed if the Source boundary is wrong?

For M6-001, the provisional ACL negative query from the batch spec is:

```text
private operator token for LLM Wiki production pipeline
```

The final ACL negative query may change after Source file selection. Any final ACL negative query must still require:

- expected status: `not_found`;
- raw fallback used: `false`;
- no unauthorized content returned.

## 8. Required evidence before Source execution

Before the batch spec can move from `draft / not approved` to `ready for Source PR`, record:

- proposed Source files;
- inclusion rationale for each file;
- exclusion check for secrets / private data / raw transcripts;
- proposed public query;
- expected citation URL or citation target;
- proposed ACL negative query or explicit `n/a` rationale;
- Builder SHA / Foundation SHA rotation decision;
- reviewer decision.

## 9. Required evidence after Source PR merge

After a future Source PR exists and is merged, update the M6-001 batch spec with:

- Source PR URL;
- Source branch;
- merged Source SHA;
- Source validation workflow run ID;
- Source validation conclusion;
- final public acceptance query;
- final expected citation URL or citation target;
- final ACL negative query;
- Builder / Foundation rotation decision.

Do not run candidate build until this evidence exists.

## 10. Decision gate

The selection plan reaches `ready for Source PR` only when a reviewer confirms all of the following:

- candidate Source files are explicitly listed;
- inclusion and exclusion criteria are satisfied;
- citation target planning is complete or blockers are explicit;
- ACL negative query planning is complete or `n/a` is justified;
- the plan does not approve Source content by itself;
- the future Source PR remains the review surface for canonical Source.

## 11. Current decision

- Plan status: `planning / no Source approval`
- Reviewer: `pending`
- Decision date: `pending`
- Approved Source files: `none`
- Next step: create a Source PR proposal that lists candidate Source files for review.
