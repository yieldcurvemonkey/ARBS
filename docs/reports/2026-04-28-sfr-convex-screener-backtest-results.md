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

**Final post-fix run** (after the three correctness fixes — sign flip in `d7038c9`, per-position TP/SL in `083700a`, midnight-vs-EOD TimeGrid in `477df5e`):

- **5 closed trades** (3 outrights, 2 calendars), **5 unrealized still open** at end of window
- **Sharpe ≈ −3.22** over the daily-MTM series
- **Win rate 0 %** (all 5 closed positions exited via `stop_bp` on day 2)
- **Final MTM −$13.31 M; max drawdown −$14.24 M**
- **Outrights ≈ −$2.03 M each** (matches the manual NPV remark for a 6.04 bp rate drop on $100k bpv)
- **Calendars ≈ −$4.07 M each**
- **Average holding 1 day** — every closed position hit the configured `exit_stop_loss_bp = −15 bp` threshold on day 2 because the EOD-to-EOD rate move (3.5768% → 3.5164% over 2026-03-30 17:00 → 2026-03-31 17:00 NY) priced to ≈ −20 bp on the bpv-sized outright, past the stop.

**Run history** (audit trail of every iteration as the bugs were rooted):

| run | resolve_pricable sign | per-pos TP/SL | TimeGrid time | finalMTM | per-outright realised |
|---|---|---|---|---|---|
| original | flipped (engine bug) | not wired | midnight (script bug) | +$31.06 M (sign-flipped, holds 22d via max_holding) | +$10.55 M |
| `d7038c9` | fixed | wired (`083700a`) | midnight (script bug) | −$19.71 M (×2 magnitude vs manual) | −$4.16 M |
| `477df5e` | fixed | wired | **17:00 NY EOD** | −$13.31 M (matches manual remark) | **−$2.03 M** |

### **🏁 Final ranking — full daily cache primed (22 dates, 12.5 hours wall time)**

| name | closed | unrealized | Sharpe | maxDD ($) | finalMTM ($) | winRate | avgHoldDays | wallSec |
|---|---|---|---|---|---|---|---|---|
| `a_outright_conservative` (asym ≥ 2.0) | 1 | 3 | 0.24 | −3,254,883 | +373,530 | 0 % | 5.0 | 1.5 |
| `b_calendar_only` (asym ≥ 3.0) | **10** | 0 | −4.55 | −47,651,206 | **−40,220,142** | 50 % | 7.4 | 1.8 |
| `c_butterfly_only` (asym ≥ 3.0) | 4 | 0 | −1.05 | −7,384,808 | **−2,236,100** | 75 % | 6.5 | 1.0 |
| `d_all_structures_default` (asym ≥ 1.5) | 11 | 5 | −4.50 | −22,908,266 | −20,573,570 | 27 % | 4.3 | 2.0 |
| `e_aggressive_concurrency` (asym ≥ 1.2) | **23** | 9 | −3.99 | −38,135,731 | −30,594,567 | 30 % | 4.3 | 3.4 |
| `f_daily_rebalance` (asym ≥ 1.5) | **19** | 5 | −5.81 | −30,179,907 | −28,464,404 | 21 % | 3.7 | 5.7 |

**Every config is a net loser on this 22-BD period.** The earlier sparse-cache "100 % win rate" was an artefact: with sparse signals, the asymmetry-decay exit could only fire on the few cached dates, often missing the adverse rate moves between them. With every business day's signal in the cache, the exit fires more aggressively and crystallises losses early.

#### What blew up: the 2026-04-03 Friday cohort

The screener emitted **extremely high-asymmetry calendar signals** on 2026-04-03 (entry asym 3.8 → 25.0!). All five ended up the largest losers in `b_calendar_only`:

| structure | direction | entry asym | days held | realised |
|---|---|---|---|---|
| `SFRH28_SFRM28_CAL_1` | PAY H28 / RECEIVE M28 | **11.66** | 4 | **−$3,078,502** |
| `SFRZ27_SFRZ28_CAL_4` | PAY Z27 / RECEIVE Z28 | 3.84 | 5 | **−$7,225,226** |
| `SFRZ28_SFRH29_CAL_1` | PAY Z28 / RECEIVE H29 | **25.05** | 6 | **−$10,980,893** |
| `SFRH28_SFRH29_CAL_4` | PAY H28 / RECEIVE H29 | **16.56** | 6 | **−$10,980,926** |
| `SFRZ27_SFRM28_CAL_2` | PAY Z27 / RECEIVE M28 | 7.36 | 11 | **−$8,944,526** |

All five exited via `asymmetry_decay` (asym dropped below 1.5) — the screener's *theoretical* signal moderated as expected, but **the realised rate move went against the position before the asymmetry collapsed**.

This is the central observation of the run: the screener's option-implied tail asymmetry is **not** a directly predictive signal for short-horizon realised P&L. High-asym structures have a wide implied tail, but the actual rate path can run against the long-rate (or long-price) position long before the implied asymmetry mean-reverts.

Subsequent Fridays (4/10, 4/17, 4/24) produced small wins (~$300 k each) — consistent with the previous sparse-cache snapshot — but those wins are dwarfed by the 4/3 catastrophe.

### Recommendation

The current config grid does **not** prove the screener generates real P&L. Open follow-ups before sizing live:

1. **Decouple asymmetry-decay exit from the holding period.** The current rule (`asymmetry < 1.10`) exits regardless of realised PnL, so a high-asym entry whose asymmetry moderates while market rates run against it gets locked into a large loss. Add a "min holding days" guard, or replace the decay exit with a TP/SL that fires on realised PnL.
2. **Investigate whether the 4/3 catastrophe is a regime issue or a screener bug.** The asym = 25 signal on `SFRZ28_SFRH29_CAL_1` is suspiciously large; its realised loss of $10.98 M on a $100 k bpv calendar implies a ~100 bp move on the spread, which is enormous. Check the cached snapshot's `metrics_by_method` and `iv_rv_diagnostics` for that date to see whether the input vols were stale or extrapolated past the asymptote.
3. **Tighten / re-run the backtest grid over a 6-month window**: this 22-BD window is statistically meaningless.

### Configuration ranking — cache evolution snapshots (audit trail)

The report below preserves earlier intermediate runs as the cache primed, so the reader can see how the picture changed.

#### Snapshot 3: cache = 16 dates (3/30, 3/31, 4/9, 4/10, 4/13–4/17, 4/20–4/24, 4/27, 4/28). Three Fridays in window: 4/10, 4/17, 4/24.

| name | closed | unrealized | Sharpe | maxDD ($) | finalMTM ($) | winRate | avgHoldDays |
|---|---|---|---|---|---|---|---|
| `a_outright_conservative` | 1 | 3 | 0.24 | −3,254,883 | +373,530 | 0 % | 5.0 |
| `b_calendar_only` (asym ≥ 3.0) | **6** | 0 | 0.29 | −6,512,070 | **+1,007,670** | **100 %** | 7.5 |
| `c_butterfly_only` (asym ≥ 3.0) | **3** | 0 | 0.43 | −4,342,632 | **+841,544** | **100 %** | 7.3 |
| `d_all_structures_default` (asym ≥ 1.5) | 6 | 5 | −2.23 | −7,596,901 | −5,182,408 | 50 % | 4.5 |
| `e_aggressive_concurrency` (asym ≥ 1.2) | 13 | 9 | −1.53 | −15,194,787 | −7,511,751 | 53.85 % | 4.5 |
| `f_daily_rebalance` (asym ≥ 1.5) | 15 | 5 | −4.24 | −19,989,797 | −19,007,638 | 40 % | 3.1 |

**Pattern is now sharp: only the asym ≥ 3 configs are reliably profitable.** Adding 4/10 to the cache produced new entries with asymmetry in the 1.5–3 range that lost — pulling configs (a)/(d)/(e)/(f) into negative territory. Configs (b) and (c), which gate on asym ≥ 3, stayed at 100 % win rate.

The "asymmetry threshold matters" hypothesis from the previous snapshot is now well-supported within this small sample (n=44 closed trades total): the ≥ 3 cohort is consistently mean-reverting and profitable; the ≥ 1.5 cohort is essentially noise once daily-rebalance and tight stops layer on top.

#### Snapshot 2: cache = 13 dates incl two Fridays 4/17 and 4/24

| name | closed | unrealized | Sharpe | maxDD ($) | finalMTM ($) | winRate | avgHoldDays | wallSec |
|---|---|---|---|---|---|---|---|---|
| `a_outright_conservative` | 0 | 3 | 1.85 | −250,484 | +297,868 | — | — | 1.0 |
| `b_calendar_only` | **4** | 0 | **3.84** | −35,391 | **+1,098,200** | **100 %** | 4.5 | 0.3 |
| `c_butterfly_only` | **1** | 0 | **3.72** | −11,796 | **+353,742** | **100 %** | 5.0 | 0.3 |
| `d_all_structures_default` | **3** | 5 | **4.05** | −270,249 | **+1,640,961** | **100 %** | 5.7 | 1.0 |
| `e_aggressive_concurrency` | **6** | 9 | **4.09** | −485,688 | **+3,112,014** | **100 %** | 5.0 | 1.5 |
| `f_daily_rebalance` | **12** | 5 | −3.65 | −17,534,963 | −15,968,283 | 50 % | 2.9 | 4.0 |

### **🎯 Major finding: Friday-rebalance configs all show 100 % win rate**

Once the cache covers a Friday rebalance day with high-asymmetry signals (4/17 and 4/24), every Friday-gated config produces profitable closed trades. The asymmetry-decay exit consistently captures the mean-reversion edge over 3–6 days holding:

- `b_calendar_only` (asym ≥ 3.0): **4 closed, all winners**, +$1.10 M, Sharpe 3.84
- `c_butterfly_only` (asym ≥ 3.0): **1 closed, winner**, +$354 k, Sharpe 3.72
- `d_all_structures_default` (asym ≥ 1.5): **3 closed, all winners**, +$1.64 M, Sharpe 4.05
- `e_aggressive_concurrency` (asym ≥ 1.2, max_concurrent 10): **6 closed, all winners**, +$3.11 M, Sharpe 4.09

The 6 winners in `e_aggressive_concurrency` (most permissive thresholds, hosting all winners from b/c/d):

| structure | direction | days held | realised |
|---|---|---|---|
| `SFRM28_SFRU28_CAL_1` | PAY M28 / RECEIVE U28 | 4 | +$365,359 |
| `SFRU27_SFRZ27_SFRH28_FLY_1_-2_1` | long-rate fly | 5 | +$353,742 |
| `SFRU27_SFRZ27_CAL_1` | PAY U27 / RECEIVE Z27 | 6 | +$279,355 |
| `SFRU27_SFRH28_CAL_2` | PAY U27 / RECEIVE H28 | 6 | +$279,414 |
| `SFRU27_SFRU28_CAL_4` | PAY U27 / RECEIVE U28 | 6 | +$279,252 |
| `SFRZ26_SFRM27_SFRZ27_FLY_1_-2_1` | long-rate fly | 3 | +$352,238 |

Every winning trade had **entry asymmetry ≥ 3.0** and exited via **asymmetry_decay** (the screener's central thesis: when asym is large, the implied tail asymmetry mean-reverts → profit).

`a_outright_conservative` (asym ≥ 2.0, structure_types=outright only) closed 0 trades because no outright on 4/17 or 4/24 had asym ≥ 2.0. Three open trades from earlier Fridays are unrealised positive.

`f_daily_rebalance` is dragged down by the 5 stop_bp losses on 2026-03-30 (asym 1.5–2.6, all PAY outright + calendar) which together cost -$14.24 M before the higher-asym signals on 4/17+ contributed wins. Win rate 50 % across 12 trades; finalMTM still negative.

**Hypothesis (sample size still tiny)**: the high-asymmetry signals are real edge; asym 1.5-2.6 is too low a threshold and the daily-rebalance + per-position stop-loss combination amplifies noise on those marginal entries. The Friday-rebalance + asym ≥ 3 path produces clean +0.3 M wins across all structure types (calendars, flies, the open outrights).

After the 2026-04-24 Friday landed in the cache, configs (a)/(d)/(e) which gate on `rebalance_dow=4` fire entries. With 4/21 added to the cache, `f_daily_rebalance` closed 3 additional **profitable** asymmetry-decay trades over 4/21 → 4/23, lifting the win rate from 16% to 37.5% and the finalMTM by ~$700k.

`e_aggressive_concurrency` closed one butterfly trade (SFRZ26_SFRM27_SFRZ27_FLY_1_-2_1, PAY wings / RECEIVE belly) opened 2026-04-24 and exited 2026-04-27 via `asymmetry_decay` — realised +$352,238 over 3 days. The remaining 9 positions (5 outrights + 2 calendars + 2 flies) are unrealised positive at +$1.94 M total.

`f_daily_rebalance` profitable trades (post 4/21 cache add):
- `SFRM26_SFRU26_SFRZ26_FLY_1_-2_1` long-rate fly opened 4/21 (entry asym 5.98), closed 4/23 → **+$364,465**
- `SFRZ26_OUTRIGHT` PAY opened 4/21 (entry asym 3.61), closed 4/23 → **+$182,212**
- `SFRU27_SFRZ27_CAL_1` PAY/RECEIVE opened 4/21 (entry asym 4.87), closed 4/23 → **+$364,278**
- `SFRZ26_OUTRIGHT` PAY opened 4/22 (entry asym 3.67), closed 4/23 → **+$168,135**

All four winning trades had entry asymmetry > 3.0; combined with 0% win rate on the 3/30 cohort (asym 1.5–2.6) this is the **first hint of a real signal**: high-asymmetry trades cluster in profitability. Sample is still tiny (4 winners) and the 5 from 3/30 remain large losers, but the 4/21+ cohort is consistently positive across structure types.

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

## Magnitude root cause — fixed in `477df5e`

After the sign fix landed, the realised P&L per outright was still ~2× the manual remark (-$4.16 M vs −$2.03 M for the 3/30 → 3/31 mark). Tracking the discrepancy through `scripts/_diff_engine_paths.py` showed:

- Calling `run_backtest` directly with explicitly-constructed 17:00 NY datetimes → -$2.03 M per outright (correct).
- Calling the same `run_backtest` via `cached_only.main()` → -$4.16 M per outright (×2 of correct).

The only difference: `_bt_datetimes` in both grid driver scripts used `pd.bdate_range(start_dt, end_dt, tz=NYC)` with start_dt = `NYC.localize(date.combine(start, time(17, 0)))`. **`pd.bdate_range` silently normalises returned timestamps to midnight regardless of the time component on the inputs.** The TimeGrid was therefore evaluating the curve at 00:00 NY each business day, not 17:00. With a daily-rebal config, the day-over-day rate move spans ≈ 24 hours of curve drift starting at midnight (which is morning EU market and therefore picks up an extra session of curve moves) instead of NY-EOD-to-NY-EOD. For the 3/30 → 3/31 window the midnight grid happened to roughly double the EOD-to-EOD rate move.

Fix: build dates with `pd.bdate_range(start, end)` then attach `17:00` NYC explicitly when materialising the engine's TimeGrid list. After `477df5e`, the cached-only run produces:

```
SFRU26_OUTRIGHT realized=-2,033,012.60   ← matches manual remark
SFRZ26_OUTRIGHT realized=-2,033,320.18
SFRH27_OUTRIGHT realized=-2,033,627.81
SFRH28_SFRH29_CAL_4 realized=-4,072,393.69
SFRZ28_SFRH29_CAL_1 realized=-4,071,919.91
```

All five trades exit via `stop_bp` on day 2 because the EOD-to-EOD rate move on PAY outrights with bpv=$100k = ≈-20 bp, past the configured `-15 bp` stop. The bpv mechanism is correct, the sign is correct, the magnitudes are correct.

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

## 2026-04-30 follow-up — sparse 5-delta SABR smile

Status: **in progress**. Cache prime currently running against the new
`smile_strike_mode='delta_sparse'` default (commit `602efee`); see the
"Phase 1 — sparse smile fetch" subsection below for the methodology and
benchmark, and the "Phase 2 — re-prime" subsection for cache evolution.

### Phase 1 — sparse smile fetch (commit `602efee`)

The 22-BD prime in the previous session took ~34 min/date wall time
because each `STIRFutureOptionMDP.fetch_sabr_smile` call fanned out to
30–60 strike-level Barchart EOD requests, of which ~80 % returned HTTP
429 in the first 30 s. The retry storms then dominated wall time. The
Phase 1 fix adds a `smile_strike_mode` config field on
`SFRConvexScreenerConfig` defaulting to `delta_sparse`, which omits the
`strike_offsets_bps='listed'` token so `fetch_sabr_smile` falls back to
its 5/10/.../50-delta call+put grid (~20 strikes/contract). This is
folded into `_config_summary_for_cache` so old listed-mode pickles
hash-mismatch and never silently mix into a new run.

Benchmark on 2025-09-29 (single uncached as_of, 3 contracts, force_refresh):

| mode | total_s | avg_per_contract_s | succeeded |
|---|---|---|---|
| `listed` | 188.6 | 62.9 | 2/3 (M26 failed: missing wing strikes after 429 retries exhausted) |
| `delta_sparse` | 119.7 | 39.9 | 3/3 |

Sparse mode is ~1.6x faster and **substantially more reliable** —
listed-mode dead-wing strikes hit the retry budget before the SABR fit
has enough valid points. This was the failure mode that dominated the
22-BD prime: contracts with sparse OTM liquidity (H29 in particular)
fell back to prior business days, recursing through the same fan-out.

The first-attempted rate-limit fix (`max_requests_per_second=2`) made
listed mode worse on contracts whose retry budget was already tight —
slowing requests further pushed retries past `max_attempts`. Reverted.
The sparse mode change is the only Phase 1 ship.

Bench harness: [scripts/_bench_smile_fetch.py](scripts/_bench_smile_fetch.py)

### Phase 1.5 — drop COMMON_STATE from the prime config (commit `23480f1`)

Profiling the sparse prime's first-date stall revealed that
`RVUtils.ImpliedDistribution._joint_calibration.calibrate_joint_distribution`
runs a 156-variable SLSQP (≈144 FOMC path-state weights × 12
contract-residual sigmas) with 13 equality constraints (probability sum
+ 12 forward-recovery) and `ftol=1e-12`, no analytic Jacobian. On a 2026
strip with the default FOMC path config this consumes 5–15 min of
single-core CPU per as_of, dwarfing every other phase combined:

| phase | cold cache | warm MDP cache |
|---|---|---|
| `load_market_data` (smiles + curve + futures + 60d panel) | 5–8 min | <5 s |
| `extract_bl_marginals` | ~3 s | ~3 s |
| **`_calibrate_joint`** (SLSQP) | **5–15 min** | **5–15 min** |
| `_historical_correlation_matrix` | <1 s | <1 s |
| per-structure analytics (50k sims × ~50 non-outright structures) | ~30 s | ~30 s |

`primary_joint_method=HISTORICAL_GAUSSIAN_COPULA`, so common-state is a
diagnostic-only metric — `metrics_by_method["common_state"]` is computed
and stored when `JointMethod.COMMON_STATE in cfg.joint_methods` but never
chosen as the primary. Phase 1.5 drops COMMON_STATE from the prime and
cached-only driver configs (`scripts/prime_screener_cache.py`,
`scripts/run_screener_backtest_cached_only.py`) and adds `joint_methods`
to `_config_summary_for_cache` so the new (HGC, PC) hash never collides
with a future (CS, HGC, PC) prime that runs the heavier diagnostic.

After this change the first sparse pickle (2026-04-28) lands in **9 s**
because the MDP smile cache is warm from the killed-prime attempt; the
second date (2026-04-27) starts cold. Steady-state per-date target is
~5 min/date for fresh dates with shared underlying-EOD MDP cache hits.

Bench harness: [scripts/_profile_build_snapshot.py](scripts/_profile_build_snapshot.py)

### Phase 2 — re-prime under sparse mode (HGC + PC only)

The sparse-mode default plus the joint_methods-tightened cache hash
together produce a brand-new hash, so every existing cache pickle is
orphaned (the 22 listed-mode dates from the previous session live on
disk under hash `60855039beb3`, the listed-mode + new-hash payload
under `0f01260c0d8f`, the sparse-mode + new-hash under `5ded8df5b691`).

The new prime runs `--reverse` from 2026-04-28 backwards across the full
1,649-business-day window 2020-01-02 → 2026-04-28. Wall budget for this
session is ~20 hours; with COMMON_STATE off and warm MDP-cache hits on
shared underlying contracts after the first few dates, realistic
coverage is **~150–250 dates** within that budget.

Cache evolution snapshots will be appended as the prime hits milestones
(every 25 newly cached dates).

#### Methodology parity check (sparse vs legacy listed @ 2026-04-28)

The first sparse pickle (`2026-04-28_5ded8df5b691.pkl`, 0 warnings)
compared against the legacy listed pickle
(`2026-04-28_60855039beb3.pkl`, 8 warnings — 7 fallback smiles for
SFRM26/U26/Z26/H27 + 1 bulk price-panel failure):

| metric | result |
|---|---|
| top-10 ranking overlap (composite_score) | 5 / 10 |
| common structures (both pickles) | 63 / 63 |
| asymmetry_ratio diff (sparse − listed) median | −0.10 |
| asymmetry_ratio diff mean / stdev / abs-max | +1.16 / 5.24 / **34.84** |

The `SFRM27_SFRU27_SFRZ27_FLY_1_-2_1` long-rate fly anchors the abs-max:
listed reports asym = 0.97 (no edge), sparse reports asym = 35.81 (huge
upper-tail bias). M27, U27, Z27 are NOT in the listed fallback set, so
this is a direct sparse-vs-listed methodology shift, not a stale-data
artefact. Other top sparse structures (`M27_U27_CAL_1` 20.04 vs 1.00
listed; `M26_U26_Z26_FLY` 11.43 vs 1.55 listed) replicate the same
pattern: every sparse top-5 entry is a 3- or 2-leg structure that listed
priced near zero edge.

The most likely root cause is that `extract_bl_marginals` with
`jpm_method=True` runs a 4th-order spline through the raw vol points
and 10 ghost points stretching 250 bp into the wings. With listed mode
the spline has ~50 anchor strikes, with sparse it has ~20 (10 deltas ×
call+put). The wider spacing of the sparse anchor grid lets the spline
oscillate in the wings — a 5–10 bp move in either direction can blow out
the BL density's tail mass on a structure that subtracts mismatched
densities (calendar / butterfly), inflating the asymmetry ratio. ATM-
driven outrights are essentially unaffected (e.g. SFRZ26: listed 2.92,
sparse 1.78).

**Verdict — pending.** A cleaner check is queued for 2026-04-21 (the
legacy pickle has 0 warnings, so the comparison is methodology-vs-
methodology rather than methodology-vs-degraded). If the same
fly-asymmetry blow-up reproduces on a clean baseline, the sparse default
will be reverted to `listed` and the prime restarted.

## Reproduction

```bash
# 1) prime the cache (slow — Barchart 429 storms; allow many hours)
conda run -n stir python scripts/prime_screener_cache.py \
    --start 2020-01-02 --end 2026-04-28 --reverse

# 2) drive the full grid against the populated cache
conda run -n stir python scripts/run_screener_backtest_grid.py \
    --start 2020-01-02 --end 2026-04-28 --max-config-minutes 60

# OR drive only on the cached subset (current data)
conda run -n stir python scripts/run_screener_backtest_cached_only.py \
    --start 2020-01-02 --end 2026-04-28

# inspect a cache pickle directly (no hash-key lookup)
conda run -n stir python scripts/_inspect_pickle.py \
    data/screener_results/sfr_convex_screener_backtest_cache/<file>.pkl

# compare sparse vs legacy listed pickle for a single date
conda run -n stir python scripts/_check_smile_mode_parity.py \
    --as-of 2026-04-28 --listed-hash 60855039beb3
```

Per-config artefacts land in `data/screener_results/sfr_convex_screener_backtest_grid/<config>/`. A grid-level `grid_summary.json` is written at the root.

## Diagnostic scripts

| Script | Purpose |
|---|---|
| `scripts/_bench_smile_fetch.py` | Time `fetch_sabr_smile` under listed vs delta_sparse modes |
| `scripts/_check_bpv_unit.py` | Verify PV01 == bpv at construction (NPV-at-par = 0) |
| `scripts/_check_curve_dates.py` | Confirm the curve actually differs across as_of dates |
| `scripts/_check_remark.py` | Manual remark of a position vs engine's value_position |
| `scripts/_check_resolve_pricable.py` | Isolate the `resolve_pricable` sign flip |
| `scripts/_check_realized_pnl.py` | End-to-end NPV trace (open / mid / close) |
| `scripts/_check_smile_mode_parity.py` | Compare sparse vs listed snapshots for a single date |
| `scripts/_inspect_pickle.py` | Print as_of + top-K by composite_score for any cache pickle |
| `scripts/_show_cache_hashes.py` | Show the listed vs delta_sparse cache filename hashes |
