# M12.3 Exact-Head Gate Requirement

M12.3 cannot merge until the exact PR head SHA has successful results for:

- CI;
- R2 Canary;
- R2 Release Integration.

The exact head SHA must be recorded in the PR and issue completion evidence after the checks finish.

The merge commit must also be recorded after merge.
