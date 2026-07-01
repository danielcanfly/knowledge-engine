# Contributing

Every change must pass:

```bash
ruff check .
pytest -q
python -m compileall -q src tests scripts
```

Changes to release layout, ACL behavior, provenance, channel promotion, or Runtime wire format must also update the corresponding contract in `knowledge-os-foundation` before this implementation diverges.

Use commit prefixes: `feat:`, `fix:`, `test:`, `ci:`, `deploy:`, `docs:`.
