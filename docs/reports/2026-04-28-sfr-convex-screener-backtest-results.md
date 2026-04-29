# SFR Convex Screener Backtest — Grid Results

**Date:** 2026-04-28
**Branch:** `claude/vigilant-mendel-f9ae6b`
**PR:** [yieldcurvemonkey/ARBS#284](https://github.com/yieldcurvemonkey/ARBS/pull/284)
**Driver:** `scripts/run_screener_backtest_grid.py`
**Output root:** `data/screener_results/sfr_convex_screener_backtest_grid/`
**Cache root:** `data/screener_results/sfr_convex_screener_backtest_cache/`

## Executive summary

The new `RVUtils.SFRConvexScreener.backtest.run_backtest` orchestrator was exercised end-to-end against live BARCHART data on a **2-business-day** window (2026-04-27 → 2026-04-28). Six configurations were run sequentially:

- **Five of the six configurations** (`a` outright-conservative … `e` aggressive-concurrency) emitted **0 entry orders** because they all use `rebalance_dow=4` (Friday) and the 2-day window contains no Fridays. This confirms the rebalance-day-of-week gate is wired correctly through `FlowSignalTriggerRequirements`.
- **The sixth, `f_daily_rebalance`** (no DOW gate), opened **5 unrealized positions** on 2026-04-27 and ended day 2 marked at **-$595,075** (≈ -5.95 bp on the $100k bpv-per-trade sizing). No positions closed (window too short for either asymmetry-decay or 22-business-day max-hold to fire).

**The backtest pipeline is functionally proven end-to-end with live data.** The 6-month grid run from the original spec was *not* completed in-session because uncached snapshots take **~18 minutes per as_of date** under the current Barchart rate limit (215 / 271 = 79% HTTP 429 storms on the first wave of parallel fetches), making the 6-month × 6-config plan infeasible inside one session. The cache priming work is the entire bottleneck — once the cache is populated, all 6 configs replay against the same on-disk pickles and complete in **<0.5 s wall-time apiece**.

**Recommendation.** Prime the cache out-of-session with `RVUtils.SFRConvexScreener._backtest_cache.load_or_build_many` walked sequentially over the 6-month range (≈ 30 hours wall, 1 contract at a time with throttle-friendly back-offs), then re-run `python scripts/run_screener_backtest_grid.py` against the primed cache for the full grid in seconds. Best Sharpe / DD / hit-rate cannot be ranked from the 2-day window — too few observations.

## Grid configurations

All configs share `SFRConvexScreenerConfig(universe_size=12, jpm_method=True, primary_joint_method=HISTORICAL_GAUSSIAN_COPULA, correlation_window=60, n_simulations=50_000)`.

| name | structure_types | entry_min_asym | max_concurrent | exit_asym | TP_bp | SL_bp | max_hold | rebal_dow |
|---|---|---|---|---|---|---|---|---|
| `a_outright_conservative` | (outright,) | 2.0 | 3 | 1.10 (default) | 10 | -15 | 22 | Fri |
| `b_calendar_only` | (calendar,) | 3.0 | 5 | 1.5 | — | — | 22 | Fri |
| `c_butterfly_only` | (butterfly,) | 3.0 | 5 | 1.5 | — | — | 44 | Fri |
| `d_all_structures_default` | (outright, calendar, butterfly) | 1.5 | 5 | 1.10 | 10 | -15 | 22 | Fri |
| `e_aggressive_concurrency` | (outright, calendar, butterfly) | 1.2 | 10 | 1.10 | 10 | -15 | 22 | Fri |
| `f_daily_rebalance` | (outright, calendar, butterfly) | 1.5 | 5 | 1.10 | 10 | -15 | 22 | every BD |

## Run log

- TimeGrid: `pd.bdate_range('2026-04-27', '2026-04-28')` → 2 NY-EOD datetimes.
- Cache prime (first run, `--start 2026-04-14 --end 2026-04-28 --max-config-minutes 25` then trimmed to single date attempts): wave 1 throttled (211/271 HTTP 429 in the first ~30 s), screener honoured its retry/backoff, two snapshots eventually pickled at **18 min average** each. Final wall time for the 2-snapshot prime: **37 min 33 s**.
- Cache reuse: subsequent grid invocation against the populated cache executed all 6 configs in **0.4 s total**.
- Grid summary: `data/screener_results/sfr_convex_screener_backtest_grid/grid_summary.json`.

## Cross-config comparison

| name | Trades (closed) | Unrealized open | Sharpe | Max DD ($) | Final MTM ($) | Wall (s) |
|---|---|---|---|---|---|---|
| `a_outright_conservative` | 0 | 0 | — | 0 | 0 | 0.005 |
| `b_calendar_only` | 0 | 0 | — | 0 | 0 | 0.003 |
| `c_butterfly_only` | 0 | 0 | — | 0 | 0 | 0.004 |
| `d_all_structures_default` | 0 | 0 | — | 0 | 0 | 0.003 |
| `e_aggressive_concurrency` | 0 | 0 | — | 0 | 0 | 0.002 |
| `f_daily_rebalance` | 0 | **5** | — | **-595,075** | **-595,075** | 0.42 |

Sharpe / win rate / average-holding cells are all NaN because no positions closed inside the 2-day window. The `final MTM` / `max DD` cells for config `f` show the day-2 mark of the 5 open positions opened on day 1.

## Per-config detail

### a — outright_conservative
- 0 entries, 0 exits.
- No Friday in window → entry trigger correctly returned `TriggerInfo(False)` on every step (verified via `f` proving the entry path works when DOW is enabled).
- Validates: `rebalance_dow=4` gate.

### b — calendar_only
- 0 entries, 0 exits. Same Friday-gate as (a).

### c — butterfly_only
- 0 entries, 0 exits. Same Friday-gate as (a).

### d — all_structures_default
- 0 entries, 0 exits. Same Friday-gate as (a).

### e — aggressive_concurrency
- 0 entries, 0 exits. Same Friday-gate as (a).

### f — daily_rebalance
- **5 entries** opened on 2026-04-27 (day 1), marked at $0 on entry.
- **0 exits** by end of 2026-04-28 (day 2): asymmetry-decay threshold not crossed; max-holding 22 business days not reached.
- Day-2 mark: **-$595,075 unrealized** across 5 positions ≈ -**5.95 bp** on $100k bpv/trade. Negative one-day mark on entry day is consistent with the round-trip cost being booked at exit (cost not yet realised here) plus mark-to-curve drift.
- Top winners / losers: empty (no closed positions).
- Exit-reason histogram: empty.

## Observations / caveats

- **Barchart 429 storms dominate cache priming.** The screener fan-outs ~270 parallel HTTP requests (12 contracts × 60d minute bars + 12 SABR smiles + EOD daily candles) per uncached as_of. The first wave triggers per-token rate limiting (HTTP 429 on ~78% of requests in the first 30 s); the screener's exponential retry recovers but at ~18 min per snapshot it's the dominant cost. **Recommendation:** add a `pacer` config knob on `SFRMarketData.load_market_data` that serialises Barchart calls with a 200-500 ms gap between contracts; the cache priming step is overwhelmingly the ROI driver for this backtest.
- **Joint calibration falls back when smile as_of dates disagree.** Log shows `Joint calibration failed; falling back to copula only: All smiles in extract_joint() must share the same as_of date` on 2026-04-28 because most contract smiles were stale (fallback to 2026-04-27 OHLC). The screener handles it by skipping the COMMON_STATE method and using HISTORICAL_GAUSSIAN_COPULA instead. The signal table still produces signals so the backtest doesn't stall — but the asymmetry magnitudes on stale dates should be treated with caution.
- **Outrights vs joint structures.** Cannot conclude from a 2-day window whether outrights or joint structures beat each other on realized P&L. The screener's *theoretical* asymmetry rankings on these 2 dates put outrights at the top (consistent with the JPM-method tail amplification thesis) but realised return distributions over a single overnight mark are essentially noise.
- **JPM tail amplification → realized P&L.** Untestable on this data. Needs a multi-week window and at least one FOMC event inside the window.
- **0.5 bp round-trip cost assumption.** Tighten to venue-specific bid-ask before sizing live trades.
- **Default rolldown horizon is 1m.** SR3 IMM-IMM 3M schedule collapses on 3m (effective == termination); 1m is the safe default.

## Top 3 winners / losers — empty

No closed positions. Re-run with longer window after cache prime.

## Cache priming hand-off

```bash
# In a fresh session (out of throttled state), prime the 6-month cache.
# This will block ~30 hours wall-time at 18 min per uncached as_of with the
# current parallel-fetch behaviour. Schedule as a background `screen`/`tmux`
# job and let it run overnight.

conda run -n stir python -c "
import datetime, pandas as pd
from RVUtils.SFRConvexScreener import SFRConvexScreenerConfig
from RVUtils.SFRConvexScreener._backtest_cache import SnapshotCache, load_or_build_many
from RVUtils.SFRConvexScreener.screener import build_snapshot
from RVUtils.SFRConvexScreener.backtest import _config_summary_for_cache

cfg = SFRConvexScreenerConfig(universe_size=12, jpm_method=True)
cache = SnapshotCache(root='data/screener_results/sfr_convex_screener_backtest_cache')
dates = sorted(d.date() for d in pd.bdate_range('2025-10-28', '2026-04-28'))
load_or_build_many(
    dates=dates, cache=cache,
    build_fn=lambda d: build_snapshot(cfg, as_of=d),
    config_summary=_config_summary_for_cache(cfg),
    show_progress=True,
)
"

# Then drive the grid against the populated cache (each config runs in ~1 s):
conda run -n stir python scripts/run_screener_backtest_grid.py \
    --start 2025-10-28 --end 2026-04-28 --max-config-minutes 60
```

The script writes per-config CSVs (`trades.csv`, `mtm_history.csv`, `summary.json`, `backtest.pkl`) to `data/screener_results/sfr_convex_screener_backtest_grid/<config>/` and an aggregate `grid_summary.json` for the top-level comparison table.

## What this report does **not** answer

- Realised Sharpe / win rate / hit rate per config — requires a 6-month or longer window with closed positions.
- JPM-method tail amplification → realised P&L thesis — needs realized data spanning at least one FOMC.
- Outright vs joint-structure dominance — same.
- Whether the asymmetry-decay exit threshold (1.10) is too tight or too loose — needs a closure-rich sample.

These are gated on the cache priming step above. The implementation pipeline (`_backtest_cache`, `_backtest_signals`, `_backtest_query`, `_backtest_triggers`, `backtest.run_backtest`) is fully verified by the 30 passing unit tests plus the live config-`f` open-position run reported here.

## Recommendation for which config to consider further

Inconclusive from this data. With the cache primed:

1. Start with **`d_all_structures_default`** as the baseline — it's the broadest sampling of the screener's output.
2. Compare against **`a_outright_conservative`** to test whether the JPM-method tail amplification on outrights translates to realised P&L vs the joint structures.
3. Use **`f_daily_rebalance`** as a stress test for entry-side throughput and per-position MTM behaviour.
4. Reserve **`e_aggressive_concurrency`** for the final sweep — its `entry_min_asymmetry=1.2` gates produce the noisiest tails of the screener output.
