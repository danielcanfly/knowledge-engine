# M12.3 Immutability Note

The baseline contract is immutable by convention and identity. Any changed baseline field produces a different `gqbaseline_` identity.

The baseline check is immutable by content. Any changed report ID, aggregate count, failure reason, missing case, unexpected reason, or audience broadening list produces a different `gqbaselinecheck_` identity.

This keeps reviewer evidence stable and prevents hidden baseline drift.
