# ARBS — Claude Code Notes

## Environment

All Python commands must run under the `stir` conda environment:

```bash
conda run -n stir python ...
conda run -n stir python -m pytest ...
```

## Testing

- Fast gate (pre-commit): `conda run -n stir python -m pytest tests -m "not slow and not network and not db"`
- Full suite (~1h+, needs network + DATABASE_URL): `conda run -n stir python -m pytest tests`

### Markers

| Marker    | Meaning                                                  |
|-----------|----------------------------------------------------------|
| `slow`    | Takes >60s; excluded from the fast gate                  |
| `network` | Hits external services (DTCC, Barchart, Supabase)        |
| `db`      | Requires a live `DATABASE_URL`                           |
| `integration` | Requires live market data                            |
| `live`    | End-to-end tests requiring live market data              |

Slow/network offenders (measured durations):
- `test_sfr_convex_screener_backtest_orchestrator.py` — ~1421s (slow)
- `test_lifecycle_v2_integration.py` — ~673s + 3×~138s (slow)
- `test_sfr_convex_screener_market_data.py` — ~626s, live network, FAILS on flaky market data (slow + network)
- `test_sfr_convex_screener_orchestrator.py` — ~328s (slow)
- `test_timeseries_builder_integration.py` — ~14–19s per test, ~3–4 min total (slow)
- `tests/perf/test_stirf_timeseries_optimization.py` — per-test `@pytest.mark.slow` already present
