# ARBS

ARBS is a rates research and backtesting workspace. The current repo is broader than the original IRS-only backtesting setup: it now includes product queries, market data providers, timeseries builders, local cache/sync tooling, simulation utilities, and notebooks covering swaps, swaptions, STIR futures/options, UST futures/options, fixed-rate bonds, spreads, FX forwards, and event contracts.

The repo is not packaged as an installable Python module. Run commands from the repository root so imports like `BT`, `MDP`, `Query`, `TB`, and `Caching` resolve correctly.

## Current Repo Shape

- `BT/`: backtest engines, strategies, triggers, positions, and signals
- `Query/`: product query objects plus the `Query/Unified` translation layer
- `MDP/`: market data providers for IRS, swaptions, STIR/UST futures and options, fixed-rate bonds, spreads, FX forwards, and event contracts
- `TB/`: timeseries builders and product-specific toolbox wrappers
- `Caching/`: local `diskcache` + Parquet/DuckDB stores, plus optional Supabase sync
- `Simulation/`: scenario grids, simulation engine, and extractors
- `RVUtils/`: research utilities, interpolation, PCA, plotting, implied-distribution work
- `SDRUtils/`: SDR and SwapPulse ingestion / analytics helpers
- `scripts/`: operational scripts for cache export, backfill, and migration
- `notebooks/`: working research notebooks
- `tests/`: the most reliable runnable examples of current behavior

## Quick Start

Use the same environment name the repo is actively developed in: `stir`.

```powershell
git clone <repo-url>
cd ARBS

conda create -n stir python=3.13 -y
conda activate stir

python -m pip install --upgrade pip
pip install -r requirements.txt
```

For a safe local-only first run, disable the optional Supabase sync layer and put cache files inside the repo:

```powershell
$env:ARBS_SUPABASE_ENABLED="0"
$env:ARBS_CACHE_DIR="$PWD\\.cache"
```

Then run a representative smoke pass:

```powershell
pytest tests/test_backtest_simple.py tests/test_core_integration.py tests/test_unified_query.py -q
```

If you want notebooks:

```powershell
jupyter lab
```

## Start Here

If you want a zero-external-data sanity check, start with these tests:

- `tests/test_backtest_simple.py`
- `tests/test_unified_query.py`
- `tests/test_core_integration.py`
- `tests/test_timeseries_builder_refactor.py`

If you want working research examples, start with these notebooks:

- `notebooks/simple_irswaps_backtest.ipynb`
- `notebooks/stir_example.ipynb`
- `notebooks/swaptions.ipynb`
- `notebooks/timeseries_builder.ipynb`
- `notebooks/listed_vs_otc_vol.ipynb`

If you want to inspect the main production-style entry points, start with:

- `TB/TimeseriesBuilder.py`
- `MDP/MultiProductMDP.py`
- `Query/Unified/__init__.py`
- `Caching/curve_store.py`
- `scripts/backfill_curve_store.py`
- `scripts/migrate_diskcache_to_supabase.py`

## What Changed Relative To Older Docs

Some older generated docs in `docs/` still describe an earlier architecture. The current codebase has moved away from the older ZODB-centric cache story. The active cache / persistence path in the Python source is:

1. local `diskcache` for some provider-level caches
2. local Parquet + DuckDB stores in `Caching/curve_store.py` and `Caching/timeseries_cache.py`
3. optional Supabase/Postgres synchronization via `Caching/supabase_*.py`

Use this README, the tests, and the source tree as the source of truth for onboarding.

## Configuration And Environment Variables

Most unit tests do not need credentials. Live data fetches, ingestion scripts, and optional sync paths do.

Useful local defaults:

- `ARBS_SUPABASE_ENABLED=0` keeps the repo local-only
- `ARBS_CACHE_DIR=<path>` overrides the local cache root

Optional database / sync settings:

- `ARBS_DATABASE_URL` or `SUPABASE_DATABASE_URL`
- `SWAPPULSE_DB_HOST`
- `SWAPPULSE_DB_PORT`
- `SWAPPULSE_DB_NAME`
- `SWAPPULSE_DB_USER`
- `SWAPPULSE_DB_PASSWORD`

Provider-specific settings used by parts of the repo:

- `FRED_API_KEY`
- `GS_CLIENT_ID`
- `GS_CLIENT_SECRET`
- `SCHWAB_APP_KEY`
- `SCHWAB_APP_SECRET`
- `SCHWABDEV_APP_KEY`
- `SCHWABDEV_APP_SECRET`
- `NORDVPN_USER`
- `NORDVPN_PASS`
- `MONKEYCUBE_DATA_DIR`

There is also an example YAML config at `config/settings.example.yaml`, but a large part of the repo is configured directly through constructor arguments and environment variables rather than a single global settings loader.

## Common Workflows

### 1. Offline / unit-test style backtesting

Use `MockMDP`-driven tests to understand query construction, trigger wiring, and portfolio behavior without live data:

- `tests/conftest.py`
- `tests/test_backtest_simple.py`
- `tests/test_query_basics.py`

### 2. Product timeseries research

The main orchestration layer is `TB/TimeseriesBuilder.py`. It routes queries by product and can use fast local cache paths for IRS curve analytics when available.

Relevant product wrappers include:

- `TB/IRSwapsTB.py`
- `TB/IRSwaptionsTB.py`
- `TB/STIRFuturesTB.py`
- `TB/STIRFutureOptionsTB.py`
- `TB/USTFuturesTB.py`
- `TB/USTFutureOptionsTB.py`
- `TB/FixedRateBondsTB.py`

### 3. Multi-product query routing

For cross-product work, use:

- `Query/Unified` to normalize product selectors
- `MDP/MultiProductMDP.py` to route requests to product-specific providers

### 4. Cache backfill / migration

Operational scripts live under `scripts/`:

- `scripts/backfill_curve_store.py`
- `scripts/backfill_eris_eod_core.py`
- `scripts/export_curve_cache.py`
- `scripts/export_eris_cache.py`
- `scripts/migrate_diskcache_to_supabase.py`

## Notes On Dependencies

`requirements.txt` is now pinned to the versions installed in the active `stir` environment and trimmed to the packages the repo actually imports across source, scripts, tests, and notebooks. It is not a full workstation freeze.

If you already have a working `stir` environment, reinstalling from `requirements.txt` should bring the repo-used packages back in line with the codebase. If you are starting fresh, the commands in Quick Start are the intended path.
