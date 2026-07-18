# Review checklist

- [ ] Existing one-batch compatibility tests pass.
- [ ] New parallel runtime test observes four six-query batches.
- [ ] Query and result ordering remain exact across all 24 variants.
- [ ] Single-query fallback remains bounded to 24 calls.
- [ ] Worker shadow threshold remains 1200 ms.
- [ ] Quality thresholds remain unchanged.
- [ ] No collection, R2, pointer, production, or index mutation is authorized.
- [ ] Exact PR head is used for merge and subsequent fresh remote observation.
