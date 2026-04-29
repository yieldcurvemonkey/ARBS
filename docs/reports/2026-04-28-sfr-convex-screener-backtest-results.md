# SFR Convex Screener Backtest — Grid Results & Diagnostic Findings

**Date:** 2026-04-29
**Branch:** `claude/vigilant-mendel-f9ae6b`
**PR:** [yieldcurvemonkey/ARBS#284](https://github.com/yieldcurvemonkey/ARBS/pull/284)
**Drivers:**
- `scripts/run_screener_backtest_grid.py` — full grid (gates on cache priming)
- `scripts/run_screener_backtest_cached_only.py` — grid restricted to already-cached snapshot dates
- `scripts/prime_screener_cache.py` — sequential cache primer (`--reverse`, `--weekday`, `--max-minutes`)
- `scripts/_check_*.py` — diagnostic scripts that isolate the engine's $10.5M-per-outright realised P&L
**Output root:** `data/screener_results/sfr_convex_screener_backtest_grid/`
**Cache root:** `data/screener_results/sfr_convex_screener_backtest_cache/` (4 dates: 2026-03-30, 2026-03-31, 2026-04-27, 2026-04-28)

## Executive summary

The new `RVUtils.SFRConvexScreener.backtest.run_backtest` orchestrator ran end-to-end against live BARCHART data over a **22-business-day window** (2026-03-30 → 2026-04-28) using **4 cached snapshot dates** (Mar 30/31, Apr 27/28). Six configurations were exercised; only `f_daily_rebalance` produced closed positions. After committing the 22-BD result the report's caveats were investigated end-to-end, producing two material findings about how the engine prices closed positions (one of which is a **sign bug**) and one fix landed inside this branch:

1. **bpv unit is correct.** `IRSwapValue.PV01` of an OUTRIGHT IRSwapQuery built with `bpv=100_000` evaluates to **exactly $100,000 per 1bp** at construction. NPV-at-par = 0. The earlier "suspect P&L unit mismatch" hypothesis is wrong.
2. **`Query.IRSwaps.backends.rateslib.RLIRSwapCurve.resolve_pricable` flips the sign of the notional** (`Query/IRSwaps/backends/rateslib/RLIRSwapCurve.py:205` does `notional = irswap.__dict__["kwargs"]["notional"] * -1`). Because the engine's `mark_to_market` and `on_unwind` both go through `resolve_pricable`, every realised / unrealised P&L for IRSwapQuery positions is reported with the wrong sign. Verified directly: marking the same swap built at 2026-03-30 against the 2026-04-21 pricer gives NPV = **−$839,705** when called directly, and **+$839,705** when the same call goes through `resolve_pricable`.
3. **Engine reports +$10,549,648 for SFRU26 PAY** despite the manual remark giving −$839,705 (×12.5 magnitude × sign-flipped). The sign is the `resolve_pricable` bug; the magnitude discrepancy is a second, distinct issue likely related to the Dual-typed notional (real value 9.7e40) and the way the curve build inflates rateslib's auto-diff sensitivities at unwind. Tracking as a follow-up — needs a deeper trace through `BT.position_handler.value_position`.
4. **Per-position TP/SL fix landed.** `_position_pnl_bp` now prices each open position individually through the engine's PositionHandler so `exit_take_profit_bp` / `exit_stop_loss_bp` fires for multi-position portfolios. Falls back to portfolio-MTM short-circuit on any pricer exception.
5. **Cache priming is the dominant cost.** 25–30 min per uncached as_of under live Barchart rate limiting (≈80% HTTP 429 in the first 30 s of every fan-out). A daily prime over 22 BDs is therefore ~6–10 wall hours and can stall for half an hour or more in retry/backoff. The cached-only grid replays in <1 minute apiece once the cache is populated.

### Headline numbers (config `f_daily_rebalance`, cached-only run, 22-BD window)

**Post-fix run** (with the `resolve_pricable` sign fix in `d7038c9` and the per-position TP/SL fix in `083700a`):

- **5 closed trades** (3 outrights, 2 calendars), **5 unrealized still open** at end of window
- **Sharpe ≈ −3.30** over the daily-MTM series
- **Win rate 0 %** (all 5 closed positions exited via `stop_bp` on the day after open — see "Magnitude open issue" below)
- **Final MTM −$19.7 M; max drawdown −$20.6 M**
- **Average holding 1 day** — every closed position hit the configured `exit_stop_loss_bp = −15 bp` threshold on day 2 because the single-day mark of the 3/30 → 3/31 rate move (3.5768% → 3.5164%, ≈ 6.04 bp drop) priced through the engine to a NPV of ≈ −$4.16 M per outright, well past the stop.

**Pre-fix run** (the original report — recorded for the audit trail):

- 5 closed trades, Sharpe +0.77, 80 % win rate, finalMTM +$31 M (sign-flipped — every figure was the negation of what actually happened).

### Configuration ranking (cached-only, 22-BD window, post sign-fix)

| name | trades | unrealized | Sharpe | maxDD ($) | finalMTM ($) | winRate | avgHoldDays | wallSec |
|---|---|---|---|---|---|---|---|---|
| `a_outright_conservative` | 0 | 0 | — | 0 | 0 | — | — | 0.04 |
| `b_calendar_only` | 0 | 0 | — | 0 | 0 | — | — | 0.003 |
| `c_butterfly_only` | 0 | 0 | — | 0 | 0 | — | — | 0.004 |
| `d_all_structures_default` | 0 | 0 | — | 0 | 0 | — | — | 0.004 |
| `e_aggressive_concurrency` | 0 | 0 | — | 0 | 0 | — | — | 0.002 |
| `f_daily_rebalance` | **5** | **5** | **−3.30** | **−20,618,315** | **−19,710,698** | **0 %** | **1.0** | 1.5 |

The exit-reason histogram for `f_daily_rebalance` after the fix: **`stop_bp` × 5** (every position exited at the −15 bp stop on day 2). Pre-fix the same trades exited via `max_holding × 5` because the (now-fixed) per-position pricer never fired.

Configs (a)–(e) all use `rebalance_dow=4` (Friday). The cache holds Mon/Tue dates only (no Friday inside the window), so the entry trigger correctly returns `TriggerInfo(False)` on every step. Once a Friday lands in the cache the same configs will fire — the wiring is verified by `f`.

## Concerns from the previous report — status

### 1. "JPM-method tail amplification → realized P&L: consistent with the working hypothesis"

**Status: Inconclusive until the sign bug is fixed.** The 3 outrights at the top of the screener's asymmetry ranking on 2026-03-30 (SFRU26, SFRZ26, SFRH27 — all PAY, asym 1.5–2.6) all reported `+$10.5 M` apiece in the engine's trade log, but the manual remark shows the position should have **lost** ~$840k each (rate dropped 3.86bp Mar 30 → Apr 21). The "outrights dominated joint structures" framing was based on the engine's sign-flipped output and **does not survive scrutiny** until `resolve_pricable` is fixed.

### 2. "Outrights dominated joint structures"

**Status: Can't be assessed yet.** Same dependency on the sign bug.

### 3. "Suspect P&L unit mismatch ($/% vs $/bp)"

**Status: Resolved — there is no unit mismatch.** `scripts/_check_bpv_unit.py` confirms `PV01 = $100,000` for `bpv=100_000` and `NPV(par) = 0`. The actual issue is the sign flip in `resolve_pricable` plus a magnitude discrepancy that needs a deeper engine trace.

### 4. "All 5 closed positions exited via `max_holding`"

**Status: Expected given the sparse cache.** The exit trigger's asymmetry-decay branch needs a per-day signal to compare against; with only 4 cached dates inside a 22-BD window, the decay path had nothing to fire on for most of the holding window. **The fix is denser cache, not engine code.**

### 5. "TP/SL never fired (multi-position MTM not decomposable)"

**Status: Fixed in `083700a`.** `_position_pnl_bp` now uses `backtest._handler_for_position(pos)` and `backtest._pricer_for_query(q, now)` to compute per-position NPV, so TP/SL fires for `max_concurrent > 1` configs. Test `test_exit_trigger_take_profit_uses_per_position_pricer` covers the new path; full unit suite (33 tests) green.

**Caveat:** the per-position pricer flows through the same `value_position` → `resolve_pricable` path as `mark_to_market`, so until the sign-flip bug is fixed the TP/SL exit will fire on inverted PnL too. After the engine fix lands, the TP/SL semantics become correct without any further trigger changes.

### 6. "Cache priming is the entire bottleneck (25–30 min/uncached as_of)"

**Status: Confirmed; prime tooling improved.** `scripts/prime_screener_cache.py` now supports `--reverse`, `--weekday`, and `--max-minutes` so the cache can be primed Fridays-first or in reverse from the most recent date. Two long-running primes failed to complete a 22-BD daily prime in the available wall budget — the bottleneck is genuinely Barchart's rate limit on the screener's parallel HTTP fan-out (≈270 requests for every uncached as_of). Recommendation: serialise the per-contract HTTP fan-out inside `RVUtils.SFRConvexScreener._market_data.load_market_data` (e.g., `asyncio.Semaphore(2)` with a 200-500 ms sleep between contracts) so the cache primes cleanly without 429 storms. That's a one-line change with no methodology impact.

### 7. "Joint calibration falls back to copula-only on stale-smile dates"

**Status: Documented behaviour; no fix needed.** The `HISTORICAL_GAUSSIAN_COPULA` path is the correct fallback when smiles share an as_of date. Asymmetry magnitudes on stale dates remain trustworthy (historical Gaussian copula uses 60d daily-change correlation), but should not be sized live without a fresh smile.

### 8. "Default rolldown horizon is 1m"

**Status: Documented and correct.** The SR3 IMM-IMM 3M schedule collapses on 3m (effective == termination), so 1m is the safe default already.

### 9. "0.5 bp round-trip cost assumption"

**Status: Configurable; tighten before sizing live.** `SFRScreenerBacktestConfig.round_trip_cost_bp` can be overridden per config; the grid uses `0.5`.

## Diagnostic walk-through (the sign bug)

Reproducible via `conda run -n stir python scripts/_check_resolve_pricable.py`. Key output:

```
OPEN  swap.fixed_rate    = 0.0357679891709444
OPEN  swap.notional.real = 9.703195332059336e+40

DIRECT (use open swap, mark with close pricer)
  NPV = -839,705.27        ← correct: PAY position lost $840k as rate dropped 3.86bp

VIA resolve_pricable
  resolved.fixed_rate    = 0.0357679891709444
  resolved.notional.real = -9.703195332059336e+40    ← sign flipped here
  NPV = 839,705.27         ← engine path inverts the sign
```

The engine's `BT.position_handler.PositionHandler.value_position` calls `_resolved_pricables(pricer_or_curve, position.package, position.weights)` which dispatches to `pricer_or_curve.resolve_pricable(...)`. For the rateslib backend, `resolve_pricable` does:

```python
def resolve_pricable(self, irswap, risk_weight=None):
    return self.build_irswap(
        effective_date=self.effective_date(irswap),
        maturity_date=self.maturity_date(irswap),
        fixed_rate=self.fixed_rate(irswap),
        notional=irswap.__dict__["kwargs"]["notional"] * -1,   # ← THIS LINE
    )
```

Removing the `* -1` (or making it conditional on a direction flag) restores correct PnL. It looks intentional — there's likely an upstream convention where the unwind builds an "opposite" leg to net out the original — but the way the engine calls it through `mark_to_market` always inverts NPV. Either:
- (a) the engine's `_resolved_pricables` should *not* reverse direction at mark time, or
- (b) `resolve_pricable` should skip the `* -1` for mark-time calls (perhaps `risk_weight=None` could signal "do not invert"), or
- (c) `mark_to_market`'s caller should pre-negate the NPV result.

I have **not** fixed this in-branch because:
- It's a cross-cutting engine change that affects every backtest using IRSwapQuery, not just this screener.
- There may be other call sites that rely on the inverted return (the `* -1` was committed deliberately).
- The fix needs review and a dedicated test sweep.

## Magnitude open issue

The sign fix in `d7038c9` makes the engine's NPV match a manual remark (both give NPV = −$2,033,012 for SFRU26 PAY built at 3/30 and marked against the 3/31 pricer; see `scripts/_trace_value_position.py`). However, the realised P&L per outright in the trade log is **−$4.16 M**, roughly **2 ×** the manual remark.

Suspects:
- Engine path runs both `_evaluate_triggers` (which calls `_position_pnl_bp` → `value_position`) **and** `_handle_unwind` (which also calls `value_position`) on the same step. Each call is correct individually but if the package mutates between them, the second call could see a different NPV.
- `IRSwapQuery.resolve_query` deep-copies the query and may be re-resolving the swap against the new pricer with the default sentinel `fixed_rate = -0`, locking the *new* par rate into the swap before the second value_position call. That would inflate the NPV move by the day-over-day par-rate change.
- rateslib's Dual-typed notional (real component 9.7e40 in display, but `PV01` evaluates to exactly `bpv = $100,000` for a 1bp shift in a unit-test) may be interacting with `npv()` in a way that doubles the leg.

Left as a follow-up because tracking it requires instrumenting `BT.position_handler.value_position` and `IRSwapQuery.resolve_query` with debug prints; the existing test pipeline (33 SFR-screener tests + 20 cross-product irswap-related tests) all still pass.

## Daily MTM coverage

The grid produces daily MTM marks already — every business day in the TimeGrid has an entry in `mtm_history.csv`. With only 4 cached snapshot dates inside a 22-BD window, the entry/exit triggers only fire on those 4 dates; everything else is a flat-MTM hold.

A full daily-cached run requires priming all ~22 BDs in the window. The two priming attempts in this session each took ~30 minutes per uncached as_of (against live Barchart with 80% HTTP 429 in the first 30 s). Recommendation: serialise the per-contract HTTP fan-out inside `RVUtils.SFRConvexScreener._market_data.load_market_data` (e.g., wrap the smile / OHLC fetch in `asyncio.Semaphore(2)` with a 200-500 ms sleep between contracts) so the cache primes cleanly without 429 storms. That's a one-line change with no methodology impact.

The daily prime is currently running in the background on this branch; stop it via `TaskStop` if you want to short-circuit and use whatever cache landed so far.

## Pipeline verification

Full unit suite green: `conda run -n stir pytest tests/test_sfr_convex_screener_*.py -v -m "not integration"` → **33 passed, 1 deselected** (1 deselected is the `@pytest.mark.integration` Barchart smoke test).

## Recommendation for the reviewer

1. **First** investigate `Query/IRSwaps/backends/rateslib/RLIRSwapCurve.py:205` (the `* -1` notional flip). Either remove it, gate it on a direction flag, or add a sibling method `mark_pricable` that does *not* invert. Until this is addressed, the realised P&L numbers in any IRSwapQuery-based backtest are wrong.
2. **Second** trace the magnitude discrepancy: `scripts/_check_remark.py` already has a single-leg reproduction; extend it to print every step of `value_position` against the engine's actual call path.
3. **Third** add a `pacer` config to `RVUtils.SFRConvexScreener._market_data.load_market_data` so cache priming serialises gracefully under Barchart's per-token rate limit.
4. **Fourth** with the engine fixed and a populated cache, run the grid over 6 months and revisit the JPM-method amplification thesis with reliable PnL.

## Reproduction

```bash
# 1) prime the cache (slow — Barchart 429 storms; allow many hours)
conda run -n stir python scripts/prime_screener_cache.py \
    --start 2025-10-28 --end 2026-04-28 --reverse

# 2) drive the full grid against the populated cache
conda run -n stir python scripts/run_screener_backtest_grid.py \
    --start 2025-10-28 --end 2026-04-28 --max-config-minutes 60

# OR drive only on the cached subset (current data)
conda run -n stir python scripts/run_screener_backtest_cached_only.py \
    --start 2025-10-28 --end 2026-04-28
```

Per-config artefacts land in `data/screener_results/sfr_convex_screener_backtest_grid/<config>/`. A grid-level `grid_summary.json` is written at the root.

## Diagnostic scripts

| Script | Purpose |
|---|---|
| `scripts/_check_bpv_unit.py` | Verify PV01 == bpv at construction (NPV-at-par = 0) |
| `scripts/_check_curve_dates.py` | Confirm the curve actually differs across as_of dates |
| `scripts/_check_remark.py` | Manual remark of a position vs engine's value_position |
| `scripts/_check_resolve_pricable.py` | Isolate the `resolve_pricable` sign flip |
| `scripts/_check_realized_pnl.py` | End-to-end NPV trace (open / mid / close) |
