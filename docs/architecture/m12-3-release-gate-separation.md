# M12.3 Release Gate Separation

M12.3 defines a release-blocking evidence artifact but does not wire it into release execution.

This separation matters because:

- evaluation evidence can be replayed without side effects;
- failing checks can block future workflow stages without mutating production;
- later M12 slices can integrate the check with explicit governance rather than implicit coupling;
- the canonical Source and production baselines remain byte-for-byte unchanged.
