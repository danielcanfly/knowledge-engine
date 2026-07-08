# M12.3 Reviewer Notes

M12.3 is not a content approval workflow. It is a deterministic runtime-quality regression gate.

Reviewers should verify:

- the baseline references the exact intended suite ID;
- the release ID and manifest digest match the report under review;
- the approved audience set does not broaden beyond the suite's intended ACL surface;
- the quality floor is explicit and non-negative;
- any allowed failure reason is intentionally approved and documented;
- non-empty notes explain why this baseline exists;
- the check output remains non-mutating.

A passing baseline check is not a production approval. It is one required evidence input for later release-gating slices.
