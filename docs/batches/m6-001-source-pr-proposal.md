# M6-001 Source PR Proposal Draft

Status: `proposal / no Source edit`

Parent tracker: `#42`

Child slice: `#49`

Batch spec: `docs/batches/m6-001-llm-wiki-foundation-batch.md`

Source selection plan: `docs/batches/m6-001-source-selection-plan.md`

This proposal defines the intended future Source PR review surface for `m6-001-llm-wiki-foundation`. It does not edit `danielcanfly/knowledge-source`, does not approve Source content, does not run a candidate build, does not create a production request spec, and does not authorize production promotion.

## 1. Repository inventory note

Engine-side GitHub search did not return concrete `danielcanfly/knowledge-source` file matches for the broad M6-001 keywords at proposal time. Therefore this proposal must not invent Source file paths.

Exact Source file paths remain required before a real Source PR can be opened.

## 2. Proposed future Source PR title

```text
source: propose M6-001 LLM Wiki foundation source files
```

The future Source PR must be opened in:

```text
danielcanfly/knowledge-source
```

## 3. Review surface

The future Source PR must be the only review surface for canonical Source changes. This Engine proposal is only a planning artifact.

A future Source PR must include:

- exact file paths added or modified;
- why each file belongs in M6-001;
- whether each file is public, internal, or ACL-sensitive;
- citation target for each public acceptance query;
- ACL negative query if the content creates a boundary risk;
- confirmation that sensitive private material and raw chat transcripts are excluded;
- expected Source validation workflow result.

## 4. Candidate Source families

Candidate families for future review:

| Candidate family | Proposal status | Notes |
| --- | --- | --- |
| LLM Wiki foundation notes | `candidate family only` | Requires exact Source file paths before review. |
| Knowledge OS governance notes | `candidate family only` | Must avoid private operator-only implementation details. |
| Production-RAG / agent architecture notes | `candidate family only` | Must map to citation-backed public Q&A. |
| Operator glossary entries | `candidate family only` | Only include terms needed for public or governed runtime questions. |
| Safe closeout-derived operational explanations | `candidate family only` | Must be curated, not raw chat transcript copy. |

No family above is approved Source content.

## 5. Required candidate file table for future Source PR

The future Source PR must fill this table. Until then, approved Source files remain `none`.

| Source path | Change type | Candidate family | Inclusion rationale | Citation target | ACL risk | Decision |
| --- | --- | --- | --- | --- | --- | --- |
| `pending` | `pending` | `pending` | `pending` | `pending` | `pending` | `not approved` |

## 6. Inclusion rationale format

For every proposed Source file, the Source PR must answer:

1. What user question should this file help answer?
2. What stable fact or concept does this file provide?
3. What citation target should appear in runtime results?
4. What content was excluded and why?
5. Does this file introduce any ACL-sensitive boundary?

## 7. Exclusion checklist

Every proposed Source file must pass these checks:

- [ ] No sensitive private material.
- [ ] No private personal data or private account identifiers.
- [ ] No raw chat transcript copied directly into canonical Source.
- [ ] No operator-only runbook detail that should be hidden from public retrieval.
- [ ] No content that requires raw fallback to answer.
- [ ] No content without a viable citation target.
- [ ] No content that requires weakening Source review, candidate gate, production request spec, citation checks, ACL checks, replay, or rollback gates.

## 8. Proposed public acceptance query refinement

Current provisional query from the batch spec:

```text
what is the LLM Wiki foundation for Knowledge OS?
```

The future Source PR may refine this query only after exact Source files are listed.

The final public query must have:

- expected status: `answered`;
- expected citation URL or Source-backed citation target: `required`;
- raw fallback used: `false`.

## 9. Proposed ACL negative query refinement

Current provisional ACL negative query:

```text
operator-only deployment phrase for LLM Wiki production pipeline
```

The future Source PR may refine this query if the selected Source files create a better boundary test.

The final ACL negative query must have:

- expected status: `not_found`;
- raw fallback used: `false`;
- unauthorized content returned: `none`.

If no ACL risk exists, the Source PR must explicitly justify `n/a`.

## 10. Required evidence before updating batch spec

Before `docs/batches/m6-001-llm-wiki-foundation-batch.md` may move from `draft / not approved` to `ready for Source PR`, this proposal or a successor must record:

- exact Source file paths;
- inclusion rationale for each file;
- exclusion checklist result for each file;
- final public acceptance query;
- expected citation URL or citation target;
- final ACL negative query or `n/a` rationale;
- Builder SHA / Foundation SHA rotation decision;
- reviewer decision.

## 11. Required evidence after future Source PR merge

After a future Source PR is merged, update the M6-001 batch spec and candidate evidence summary with:

- Source PR URL;
- Source branch;
- merged Source SHA;
- Source validation workflow run ID;
- Source validation conclusion;
- candidate channel derived from Source SHA;
- final public acceptance query;
- expected citation URL or citation target;
- final ACL negative query or `n/a` rationale;
- Builder / Foundation rotation decision.

Do not run a candidate build until this evidence exists.

## 12. Non-authorization statement

This proposal does not authorize any of the following:

- editing `danielcanfly/knowledge-source`;
- approving Source content;
- opening a production request spec;
- running a candidate build;
- promoting production;
- weakening citation, ACL, raw fallback, replay, rollback, or ledger requirements.

## 13. Current decision

- Proposal status: `proposal / no Source edit`
- Approved Source files: `none`
- Reviewer: `pending`
- Decision date: `pending`
- Next required action: identify exact Source file paths through a future Source PR planning pass.
