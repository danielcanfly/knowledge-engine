# M12.3 ACL Boundary

M12.3 does not perform retrieval. It evaluates the report produced by M12.2, which already executed through the ACL-aware Runtime API.

The baseline check still protects the ACL boundary by comparing the report's case audiences with the baseline-approved audience set. Any audience outside that set fails closed with `audience_broadening`.

This prevents a suite report created for a broader caller context from silently satisfying a narrower approved baseline.
