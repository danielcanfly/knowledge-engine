# P02 contract note

P02 consumes the canonical Gate-A Repair-A admin contract and does not redefine shared transport/read/capability semantics.

A deliberate integration gate remains: the production capability provider must expose the canonical Repair-A mapping fields (`effective_state` and `mutation_authorized`) before any P02 mutation can be enabled. The older B01-only `state` field is intentionally insufficient and is rejected fail-closed.
