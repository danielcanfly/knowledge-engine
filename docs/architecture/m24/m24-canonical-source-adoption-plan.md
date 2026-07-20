# M24 Canonical Source Adoption Plan

This completes the planning deliverable for #967 using Source PR #19 review
state from #974.

The plan assumes Source PR #19 remains a draft review surface. Canonical adoption
must happen through a separate Source PR after human decisions exist.

## Non-Serving Boundary

- production retrieval remains `lexical`;
- canonical Source adoption does not authorize production semantic/hybrid
  retrieval;
- semantic answer serving and semantic promotion remain disabled;
- no production pointer, R2, Qdrant, credential, or traffic change is authorized;
- any semantic activation requires `m24_semantic_activation_reconciliation`.

## Adoption Sequence

1. Record human decisions in Source PR #19.
   - All 15 decisions must be one of `approve_new`, `map_existing`, `edit`,
     `reject`, or `defer`.
   - `human_actor` and `reviewed_at` must be non-null.

2. Freeze a decision artifact.
   - Preserve Source PR head SHA, decision template SHA-256, review manifest
     SHA-256, and provenance summary SHA-256.
   - Keep the artifact review-only until converted.

3. Create a canonical adoption branch in `knowledge-source`.
   - Convert `approve_new` and accepted `edit` decisions into
     `bundle/concepts/*`.
   - Convert `map_existing` decisions into aliases, relationships, or
     provenance updates on existing concepts.
   - Exclude `reject` and `defer` items from canonical concept writes.

4. Add provenance and registry updates.
   - Every canonical concept write needs provenance records.
   - Registry/review records must reference the human decision IDs.

5. Validate Source locally and in CI.
   - Run Source schema/tests.
   - Confirm no review-only proposal path is treated as canonical.

6. Build an Engine candidate from the adopted Source branch.
   - Compile a candidate release.
   - Keep production retrieval lexical.
   - Record compile digest and review evidence.

7. Promote only through existing governed Source/release controls.
   - No production pointer update is allowed from the planning PR.
   - Rollback is the previous Source commit and previous release pointer.

## Rollback and Revert

- Before promotion: close or supersede the canonical adoption PR.
- After Source merge but before release: revert the Source commit.
- After candidate release but before production pointer update: delete or ignore
  candidate artifacts through governed cleanup.
- After production release: use the existing release rollback procedure; semantic
  serving remains disabled throughout this plan.

## #967 Completion

#967 is complete when this plan is merged and linked from the issue. Execution of
the plan depends on #974 human decisions and should continue in Source-specific
implementation PRs.
