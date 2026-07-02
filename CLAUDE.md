# ARBS — Claude Code Notes

## Testing

- Fast gate (pre-commit): `conda run -n stir python -m pytest tests -m "not slow and not network and not db"`
- Full suite (~1.5h; needs network + DATABASE_URL): `conda run -n stir python -m pytest tests`

Full suite ~1.5h; needs network + DATABASE_URL. Slow/network/db markers exclude the heavy tests.
