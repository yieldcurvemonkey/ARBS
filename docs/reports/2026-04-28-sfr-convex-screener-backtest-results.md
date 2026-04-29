# SFR Convex Screener Backtest — Grid Results

**Date:** 2026-04-29
**Branch:** `claude/vigilant-mendel-f9ae6b`
**PR:** [yieldcurvemonkey/ARBS#284](https://github.com/yieldcurvemonkey/ARBS/pull/284)
**Drivers:**
- `scripts/run_screener_backtest_grid.py` — full grid (cache priming gated)
- `scripts/run_screener_backtest_cached_only.py` — grid restricted to already-cached snapshot dates
- `scripts/prime_screener_cache.py` — sequential cache primer
**Output root:** `data/screener_results/sfr_convex_screener_backtest_grid/`
**Cache root:** `data/screener_results/sfr_convex_screener_backtest_cache/` (4 dates: 2026-03-30, 2026-03-31, 2026-04-27, 2026-04-28)

## Executive summary

The new `RVUtils.SFRConvexScreener.backtest.run_backtest` orchestrator ran end-to-end against live BARCHART data over a **22-business-day window** (2026-03-30 → 2026-04-28) using **4 cached snapshot dates** (Mar 30/31, Apr 27/28). Six configurations were exercised; only `f_daily_rebalance` produced closed positions (all 5 hit the 22-BD `max_holding` exit).

### Headline numbers (config `f_daily_rebalance`, cached-only run)

- **5 closed trades** (3 outrights, 2 calendars), **5 unrealized still open** at end of window
- **Sharpe ≈ 0.77** over the 22-day daily-MTM series
- **Win rate 80 %** (4/5 closed trades positive)
- **Final MTM +$31.06 M; max drawdown −$90.35 M** (numbers are ~3 orders of magnitude bigger than expected for $100k bpv-per-trade — see "Caveats" below for the suspected `IRSwapValue` unit mismatch)
- **Average holding 22 days** (every closed position exited via the configured `exit_max_holding_days=22` ceiling — neither asymmetry-decay nor TP/SL fired against the available signals)

### Configuration ranking (cached-only, 22-BD window)

| name | trades | unrealized | Sharpe | maxDD ($) | finalMTM ($) | winRate | avgHoldDays | wallSec |
|---|---|---|---|---|---|---|---|---|
| `a_outright_conservative` | 0 | 0 | — | 0 | 0 | — | — | 0.04 |
| `b_calendar_only` | 0 | 0 | — | 0 | 0 | — | — | 0.004 |
| `c_butterfly_only` | 0 | 0 | — | 0 | 0 | — | — | 0.004 |
| `d_all_structures_default` | 0 | 0 | — | 0 | 0 | — | — | 0.004 |
| `e_aggressive_concurrency` | 0 | 0 | — | 0 | 0 | — | — | 0.004 |
| `f_daily_rebalance` | **5** | **5** | **0.77** | **−90,351,291** | **+31,062,545** | **80 %** | **22.0** | 64.3 |

Configs (a)–(e) all use `rebalance_dow=4` (Friday). The cache holds Mon/Tue dates only (no Friday inside Mar 30 → Apr 28), so the entry trigger correctly returns `TriggerInfo(False)` on every step. Once a Friday lands in the cache the same configs will fire entries — the wiring is verified by `f`.

### Best Sharpe / best return / worst drawdown

Only one config produced realized P&L, so all three winners are the same row: `f_daily_rebalance`. The grid is statistically thin (5 closed trades, 1 open day overlap) — treat the headline Sharpe / DD as a working pipeline check, not a strategy verdict.

## Configurations

All configs share `SFRConvexScreenerConfig(universe_size=12, jpm_method=True, primary_joint_method=HISTORICAL_GAUSSIAN_COPULA, correlation_window=60, n_simulations=50_000)`.

| name | structure_types | entry_min_asym | max_concurrent | exit_asym | TP_bp | SL_bp | max_hold | rebal_dow |
|---|---|---|---|---|---|---|---|---|
| `a_outright_conservative` | (outright,) | 2.0 | 3 | 1.10 (default) | 10 | −15 | 22 | Fri |
| `b_calendar_only` | (calendar,) | 3.0 | 5 | 1.5 | — | — | 22 | Fri |
| `c_butterfly_only` | (butterfly,) | 3.0 | 5 | 1.5 | — | — | 44 | Fri |
| `d_all_structures_default` | (outright, calendar, butterfly) | 1.5 | 5 | 1.10 | 10 | −15 | 22 | Fri |
| `e_aggressive_concurrency` | (outright, calendar, butterfly) | 1.2 | 10 | 1.10 | 10 | −15 | 22 | Fri |
| `f_daily_rebalance` | (outright, calendar, butterfly) | 1.5 | 5 | 1.10 | 10 | −15 | 22 | every BD |

## Per-config detail

### a — `outright_conservative`, b — `calendar_only`, c — `butterfly_only`, d — `all_structures_default`, e — `aggressive_concurrency`
- 0 entries, 0 exits in the cached window.
- All five share `rebalance_dow=4` (Friday). The cache holds 2026-03-30 (Mon), 2026-03-31 (Tue), 2026-04-27 (Mon), 2026-04-28 (Tue) — no Fridays. The DOW gate inside `_entry_signal_fn` returns `TriggerInfo(False)` immediately, so no entry orders are emitted.
- Whether the asymmetry / composite filters are tighter (a) or looser (e) is moot until a Friday lands in the cache.

### f — `daily_rebalance`
- Wall time: **64.3 s** (cache hit on 4 dates + daily MTM marks across 22 business days).
- Entries: **5 on 2026-03-30**: 3 outrights (`SFRU26`, `SFRZ26`, `SFRH27` — all PAY) and 2 calendars (`SFRH28/H29 CAL_4`, `SFRZ28/H29 CAL_1` — both PAY front / RECEIVE back).
- Re-entries on 2026-04-27 (next cached date with `rebalance_dow=None` matching) opened the 5 currently-open unrealized positions.
- Exits: **5 `max_holding` exits on 2026-04-21** (22 BDs from open). Asymmetry-decay never fired (no signals for the 4 days inside the holding window beyond Mar 30 / Mar 31). TP/SL did not fire (the engine's portfolio-level MTM short-circuit only evaluates with one open position).
- Realised P&L histogram (raw, see caveat about unit scaling):

| structure_id | direction | realized_pnl ($) | days | exit |
|---|---|---|---|---|
| `SFRH27_OUTRIGHT` | PAY SFRH27 | +10,555,547 | 22 | max_holding |
| `SFRZ26_OUTRIGHT` | PAY SFRZ26 | +10,552,598 | 22 | max_holding |
| `SFRU26_OUTRIGHT` | PAY SFRU26 | +10,549,649 | 22 | max_holding |
| `SFRZ28_SFRH29_CAL_1` | PAY Z28 / RECEIVE H29 | +81 | 22 | max_holding |
| `SFRH28_SFRH29_CAL_4` | PAY H28 / RECEIVE H29 | −255 | 22 | max_holding |

- MTM curve (USD): rises from $0 on 2026-03-30 → $40 M on 2026-04-01 → $91 M on 2026-04-08 → exits on 2026-04-21 realising $31.7 M; flat through 2026-04-22 / 23 / 24 / 27 then re-marks down on 2026-04-28 to $31.06 M.
- Top 3 winners and top 3 losers are the same 5-row table above (only 5 closed trades).

## Cross-config comparison

See the "Headline ranking" table above. The single non-zero row is `f_daily_rebalance`.

## Observations

- **JPM-method tail amplification → realized P&L:** consistent with the working hypothesis. The three outrights at the top of the screener's asymmetry ranking on 2026-03-30 (SFRU26, SFRZ26, SFRH27 — all PAY, asym 1.5–2.6) all exited positive. The two calendars near the asymmetry threshold (1.7) closed roughly flat. **Caveat:** sample size 5, no FOMC inside window.
- **Outrights dominated joint structures.** The outright PAY trades booked ~$10.5 M apiece while both calendar trades closed within ±$300. Whether that's the screener's edge or the unit mismatch (next bullet) is the open question.
- **Suspect P&L unit mismatch.** $10.5 M on a $100k-bpv outright would imply a **105 bp** rate move in 22 days — implausible. The screener's `IRSwapQuery` builder sets `bpv = sign × leg.weight × bpv` for outrights; the engine's `value_position` then computes MTM via `IRSwapValue.RATE` against the curve. Either:
  - `bpv` is being interpreted in `$/%` rather than `$/bp` (× 100 unit mismatch), or
  - The `IRSwapValue.RATE` path returns a rate change in `%` and the engine multiplies by `bpv` directly.
  Both possibilities trace through `BT.position_handler` and would benefit from a follow-up review against a known-good single-leg PnL calculation. The Sharpe / win rate are unaffected (linear scaling), but the maxDD / finalMTM dollar values should be divided by ~100 before sizing live.
- **All 5 closed positions exited via `max_holding`.** That's expected: the cache only has signals on Mar 30/31, Apr 27/28, so `_exit_signal_fn`'s asymmetry-decay branch had no per-day signals to compare against during the open window. With a denser cache the decay path will fire.
- **TP/SL never fired.** The `_position_pnl_bp` short-circuit returns `None` whenever `> 1` position is open (portfolio MTM is not decomposable per-position in the current engine), so the take-profit / stop-loss branches are no-ops on multi-position runs. Per-position MTM hooks would let those exits fire for `max_concurrent > 1` configs.
- **Cache priming is the entire bottleneck.** Two attempts (in-session and overnight) confirmed ~25–30 minutes per uncached as_of under live Barchart rate limiting, with the first fan-out hitting ~80 % HTTP 429 in the first 30 seconds. The cached-only run shown here completed all 6 configs over 22 BDs in **64 seconds**.
- **Joint calibration falls back to copula-only on stale-smile dates.** Logs show `Joint calibration failed; falling back to copula only: All smiles in extract_joint() must share the same as_of date` on 2026-04-28 because most contract smiles fell back to 2026-04-27 OHLC. The signal still produces (HISTORICAL_GAUSSIAN_COPULA path), but the asymmetry magnitudes on stale dates should be treated with caution.
- **Default rolldown horizon is 1m.** SR3 IMM-IMM 3M schedule collapses on 3m (effective == termination); 1m is the safe default.
- **0.5 bp round-trip cost assumption.** Tighten with venue-specific bid-ask before sizing live.

## Cross-config comparison table

| name | Sharpe | MaxDD | WinRate | Trades | AvgHoldDays |
|---|---|---|---|---|---|
| a_outright_conservative | — | 0 | — | 0 | — |
| b_calendar_only | — | 0 | — | 0 | — |
| c_butterfly_only | — | 0 | — | 0 | — |
| d_all_structures_default | — | 0 | — | 0 | — |
| e_aggressive_concurrency | — | 0 | — | 0 | — |
| f_daily_rebalance | 0.77 | -90.4 M | 80 % | 5 | 22.0 |

## Recommendation

1. **First:** chase down the suspected `IRSwapValue` unit mismatch — divide the `f` realised P&L numbers by ~100 and see whether they line up with a manual `bpv × Δrate(bp)` calculation on the SFRU26 / SFRZ26 / SFRH27 closes between 2026-03-30 and 2026-04-21. That one-line follow-up unblocks every other interpretation.
2. **Second:** prime the cache out-of-session over a 6-month range (the in-session run hit 25 min / uncached as_of with the proxy in its hot rate-limit state; expect ~6–8 hours wall against fewer-throttled tokens). Once primed, `scripts/run_screener_backtest_grid.py` runs all 6 configs in <2 minutes total.
3. **Third:** with a populated cache and a verified P&L unit, focus on `d_all_structures_default` as the broadest baseline; compare against `a_outright_conservative` to test whether the JPM-method tail amplification on outrights *only* survives realised-data scrutiny.
4. **Fourth:** add per-position MTM hooks to `BT.query_engine.QueryDrivenBacktest` so the TP/SL exit branches fire for `max_concurrent > 1` configs. Right now they're effectively dead code outside the single-position case.

## Reproduction

```bash
# 1) prime the cache (slow — Barchart 429 storms)
conda run -n stir python scripts/prime_screener_cache.py \
    --start 2025-10-28 --end 2026-04-28

# 2) drive the full grid against the populated cache
conda run -n stir python scripts/run_screener_backtest_grid.py \
    --start 2025-10-28 --end 2026-04-28 --max-config-minutes 60

# OR (if some dates are missing) drive only on the cached subset
conda run -n stir python scripts/run_screener_backtest_cached_only.py \
    --start 2025-10-28 --end 2026-04-28
```

Per-config artefacts land in `data/screener_results/sfr_convex_screener_backtest_grid/<config>/`:

- `trades.csv` — closed-position log (opened, closed, days, realized_pnl, structure_id, direction, asymmetry, exit_reason)
- `mtm_history.csv` — daily MTM in USD
- `summary.json` — Sharpe / DD / win-rate / exit-reason histogram / top-3 winners + losers
- `backtest.pkl` — pickled `{trades_df, mtm_series, summary}` for downstream analysis

A grid-level `grid_summary.json` is written at the root.

## Caveats / open questions

- **Realised P&L magnitude.** As above, $10.5 M per outright × 22 BD is implausible without a unit mismatch. Investigate before acting on the data.
- **Sample size.** 5 closed trades is statistically meaningless — the 80 % win rate could flip to 20 % with one more sample.
- **No FOMC inside window.** The screener's tail-amplification thesis is largely about FOMC-reaction tails. Need a window with at least one FOMC announcement to test.
- **`IRSwapStructure.SPREAD` unused.** Calendars use `IRSwapStructure.CURVE` (matches existing convention; SPREAD delegates to outright builder per `Query/IRSwaps/IRSwapStructure.py:63`).
- **Round-trip cost assumption.** Flat 0.5 bp; tighten with venue-specific bid-ask before sizing.

## What this report still does **not** answer

- Realised Sharpe / win-rate at 6-month statistical significance — gated on cache priming.
- Whether outrights beat joint structures on realised data once the unit mismatch is resolved.
- Whether the asymmetry-decay exit threshold is appropriately tuned — needs a denser signal table to fire that branch.
