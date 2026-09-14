# Promotion and Rollback Compatibility

`ProductionQdrantQualification` now persists profile, derived identity count, raw identity
aggregate, normalized identity aggregate, and combined evidence aggregate. Durable parsing
rejects missing or unknown profiles and inconsistent evidence.

The existing dataclass-bound predecessor qualification equality now detects profile/evidence
drift before promotion CAS, during idempotent promotion replay, and before rollback CAS.
Synthetic promotion/rollback tests pass. No promotion or rollback was executed against
production during this repair.
