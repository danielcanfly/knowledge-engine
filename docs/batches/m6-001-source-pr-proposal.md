# M6-001 Source PR Proposal Draft

Status: `proposal / reviewed paths available / no Source edit`

Parent tracker: `#42`

Child slices: `#49`, `#55`

Batch spec: `docs/batches/m6-001-llm-wiki-foundation-batch.md`

Source selection plan: `docs/batches/m6-001-source-selection-plan.md`

Candidate path review: `docs/batches/m6-001-candidate-source-paths-review.md`

This proposal defines the intended future Source PR review surface for `m6-001-llm-wiki-foundation`. It now includes reviewed Source paths from M6.6. It does not edit `danielcanfly/knowledge-source`, does not approve new Source content, does not run a candidate build, does not create a production request spec, and does not authorize production promotion.

## 1. Inventory and path review status

M6.4 found no concrete Source paths through GitHub search, so M6.5 required local inventory. M6.6 then reviewed the inventory result.

Reviewed Source identity:

- Source repository: `danielcanfly/knowledge-source`
- Source HEAD reviewed: `6a35f9f35e4c6c599a266710344f760c399d914d`
- Inventory timestamp: `20260706T152049Z`
- Inventory checksum: `375dfe63eaeae00e1aa5a350d98e60f43412f6bc19f15689279fd44ceca9eb57`
- Path review PR: `#54`
- Path review merge commit: `48410e213132dbbd062afb21b2cb4c95e4b399fb`

## 2. Proposed future Source PR title

```text
source: propose M6-001 LLM Wiki foundation source files
```

The future Source PR, if needed, must be opened in:

```text
danielcanfly/knowledge-source
```

## 3. Review surface

The future Source PR remains the review surface for canonical Source changes. This Engine proposal is planning evidence and does not modify Source.

A future Source PR must include:

- exact file paths added or modified;
- why each file belongs in M6-001;
- public / non-public classification for each file;
- citation target for each public acceptance query;
- boundary-check plan when relevant;
- confirmation that sensitive private material and raw chat transcripts are excluded;
- expected Source validation workflow result.

## 4. Candidate Source families

| Candidate family | Proposal status | Notes |
| --- | --- | --- |
| LLM Wiki foundation notes | `reviewed paths available` | M6.6 reviewed exact paths from Source inventory. |
| Knowledge OS governance notes | `reviewed paths available` | M6.6 identified public governance concept content. |
| Production-RAG / agent architecture notes | `reviewed paths available` | M6.6 identified public six-dimensional agent architecture concept content. |
| Operator glossary entries | `support only` | No primary glossary content selected yet. |
| Safe closeout-derived operational explanations | `not selected` | No new curated Source file selected in this proposal. |

No new Source content is approved by this proposal.

## 5. Reviewed candidate file table

| Source path | Change type | Candidate family | Inclusion rationale | Citation target | Boundary risk | Decision |
| --- | --- | --- | --- | --- | --- | --- |
| `bundle/concepts/six-dimensional-map-of-llm-agent-architectures.md` | existing | production-RAG / agent architecture notes | Public reviewed concept supporting six-dimensional review of LLM agent architectures. | `https://www.danielcanfly.com/en/blog/the-atlas-of-agent-design-patterns-part-1/` | low | include |
| `bundle/concepts/source-governance.md` | existing | Knowledge OS governance notes | Public reviewed concept describing the Source boundary and candidate / production gate separation. | Source-backed target pending runtime mapping. | low | include |
| `bundle/concepts/candidate-delivery-controls.md` | existing | Knowledge OS governance notes | Reviewed non-public concept useful as a fixture, not public content. | n/a for public acceptance | high if exposed publicly | fixture only |
| `bundle/index.md` | existing | index support | Links reviewed bundle concepts. | Source-backed target pending runtime mapping. | low | support only |
| `registry/sources.json` | existing | metadata | Confirms source metadata and public URL for the six-dimensional map concept. | metadata only | low | support only |
| `registry/reviews.json` | existing | metadata | Confirms review decisions and audience classification. | metadata only | low | support only |
| `provenance/six-dimensional-map-of-llm-agent-architectures.json` | existing | metadata | Supports provenance chain for the six-dimensional map concept. | metadata only | low | support only |
| `provenance/source-governance.json` | existing | metadata | Supports provenance chain for the source governance concept. | metadata only | low | support only |
| `README.md` | existing | repository guidance | Useful context but not primary concept content for M6-001. | n/a | low | support only |

## 6. Inclusion rationale format for any future Source PR

For every proposed Source file, the Source PR must answer:

1. What user question should this file help answer?
2. What stable fact or concept does this file provide?
3. What citation target should appear in runtime results?
4. What content was excluded and why?
5. Does this file require a boundary check?

## 7. Exclusion checklist

Every proposed Source file must pass these checks:

- [ ] No sensitive private material.
- [ ] No private personal data or private account identifiers.
- [ ] No raw chat transcript copied directly into canonical Source.
- [ ] No operator-only runbook detail selected as public content.
- [ ] No content that requires raw fallback to answer.
- [ ] No content without a viable citation target or explicit blocker.
- [ ] No content that requires weakening review, candidate, request-spec, citation, boundary, replay, rollback, or ledger gates.

## 8. Proposed public acceptance query refinement

Primary public query family:

```text
what is the Knowledge Source governance boundary in Knowledge OS?
```

Expected result:

- expected status: `answered`;
- expected citation target: `bundle/concepts/source-governance.md` or Source-backed runtime citation target;
- raw fallback used: `false`.

Secondary public query family:

```text
how should LLM agent architectures be reviewed across six engineering dimensions?
```

Expected result:

- expected status: `answered`;
- expected citation target: `https://www.danielcanfly.com/en/blog/the-atlas-of-agent-design-patterns-part-1/`;
- raw fallback used: `false`.

Final query strings should be locked in the candidate evidence step.

## 9. Boundary-check refinement

The reviewed non-public fixture path is:

```text
bundle/concepts/candidate-delivery-controls.md
```

Future candidate acceptance should include a public-audience negative check derived from this fixture. The exact query should be finalized in the candidate evidence step.

Expected result:

- expected status: `not_found` or equivalent negative result;
- raw fallback used: `false`;
- non-public fixture content is not returned to public audience.

## 10. Evidence now available before batch-spec update

The following evidence is now available:

- exact Source paths;
- inventory timestamp;
- inventory checksum;
- reviewed Source HEAD;
- include / support / fixture classifications;
- provisional public query families;
- provisional boundary-check fixture;
- citation target for the six-dimensional map concept;
- pending Source-backed citation target for source governance.

Still required before candidate build:

- Source validation workflow evidence;
- final public query strings;
- final citation target mapping;
- final boundary-check query;
- Builder SHA / Foundation SHA rotation decision;
- candidate channel derived from Source SHA.

## 11. Required evidence after future Source PR or Source validation

After Source validation is available, update the M6-001 batch spec and candidate evidence summary with:

- Source branch;
- Source SHA;
- Source validation workflow run ID;
- Source validation conclusion;
- candidate channel derived from Source SHA;
- final public acceptance queries;
- expected citation URL or citation target;
- final boundary-check query or explicit `n/a` rationale;
- Builder / Foundation rotation decision.

Do not run a candidate build until this evidence exists.

## 12. Non-authorization statement

This proposal does not authorize any of the following:

- editing `danielcanfly/knowledge-source`;
- approving new Source content;
- opening a production request spec;
- running a candidate build;
- promoting production;
- weakening citation, boundary, raw fallback, replay, rollback, or ledger requirements.

## 13. Current decision

- Proposal status: `reviewed paths available / no Source edit`
- Reviewed Source HEAD: `6a35f9f35e4c6c599a266710344f760c399d914d`
- Primary include paths: `2`
- Supporting paths: `6`
- Fixture-only paths: `1`
- Reviewer: `pending`
- Decision date: `pending`
- Next required action: update the M6-001 batch spec and collect Source validation evidence.
