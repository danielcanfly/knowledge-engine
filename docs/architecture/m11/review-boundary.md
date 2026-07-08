# M11 Review and Mutation Boundary

## 1. Compiler authority

The compiler may:

- read immutable M10 evidence objects;
- read an exact clean canonical Source snapshot for resolution;
- write immutable `compiler/v1/` run, event, artifact, rejection, result, validation, and reviewer-packet objects;
- materialize a local copy of reviewer artifacts for inspection;
- report proposed Source operations and exact target paths.

The compiler may not:

- modify canonical Knowledge Source;
- create or merge a Source pull request;
- record a human governance decision;
- build or publish a candidate release;
- create a production promotion request;
- mutate a candidate or production channel;
- promote, rollback, refresh, or deploy production;
- append permanent ledger issue #30;
- broaden audience, principals, access policy, owner, or license evidence;
- treat confidence or model output as approval.

## 2. Required human-review input

A reviewer packet contains:

- exact compiler run and packet-manifest identities;
- exact M10 snapshot, derivative, admission, owner, license, audience, and access-policy references;
- exact canonical Source SHA and snapshot digest when resolution was performed;
- all structured blocks and source-map references needed to inspect claims;
- extraction candidates, rejected unsupported claims, and limits applied;
- resolution outcomes with candidates, scores, reasons, conflicts, contradiction evidence, and supersession basis;
- synthesis proposals and target paths;
- validation report and unresolved findings;
- explicit permissions, all false;
- deterministic file inventory and SHA-256 values.

A packet with unresolved policy, failed validation, unsafe paths, unsupported claims inside a proposal, or incomplete provenance cannot be approved.

## 3. Review decisions

The separate review contract supports:

- `approved`;
- `rejected`;
- `needs_changes`.

Approval must bind the exact packet manifest and proposal IDs. Partial approval must enumerate the exact approved proposal IDs and leave all others rejected or pending. An approval cannot substitute a target, weaken policy, add claims, or edit proposal bytes.

Contradiction, supersession, destructive merge, deletion, and audience changes require explicit reviewer acknowledgement in addition to ordinary approval.

## 4. Source package boundary

Only an approved immutable decision may be converted into a Source PR package. Packaging must:

- reverify the exact clean Source SHA and snapshot digest reviewed by the compiler;
- reject target drift or path substitution;
- preserve existing stable IDs for updates, aliases, contradictions, and supersessions;
- create stable IDs deterministically for new records;
- include concept/entity/comparison pages, provenance, registries, contradiction or supersession records as applicable;
- preserve claim-level evidence references;
- preserve or increase access restriction;
- set direct apply, canonical write, GitHub write, candidate write, and production write to false;
- require Source schema validation and human PR review.

The package is a proposed patch, not a Source mutation.

## 5. Source PR boundary

Opening or merging a Source PR is outside the compiler. That workflow must use a separately granted GitHub write capability, exact package identity, branch protection, Source validation, and human review. A compiler workflow must never hold or inherit this write authority.

## 6. Production boundary

A merged Source PR still does not authorize production. Candidate build, runtime acceptance, production request, explicit promotion approval, production mutation, post-promotion verification, ledger append, idempotent replay, and batch closure remain the governed M7-M9 path.

## 7. ACL and license changes

Policy changes are never incidental content edits. A proposal that would broaden audience or access must stop in `pending_security_review`. A license transition must cite exact evidence and compatibility analysis. Unknown policy remains restricted and unknown license remains blocked from normal publication.

## 8. Corrections

Reviewer feedback creates a new compiler input or synthesis attempt referencing the previous packet. Existing packets and decisions remain immutable. Corrections flow through evidence, compiler, review, Source PR, candidate, and governed release rather than editing a deployed runtime artifact.