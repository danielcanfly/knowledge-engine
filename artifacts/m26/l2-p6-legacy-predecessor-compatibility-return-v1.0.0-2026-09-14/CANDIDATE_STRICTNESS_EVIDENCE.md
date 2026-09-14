# Candidate Strictness Evidence

Candidate qualification never selects a legacy profile. Every candidate point must carry a
valid lowercase `embedding_input_sha256`; missing identity fails with the `STRICT_V2` guard.
Mixed strict/legacy production populations fail closed. Unknown all-missing production
populations also fail closed.

Historical compatibility is therefore an exact predecessor exception, not a relaxed global
validation rule.
