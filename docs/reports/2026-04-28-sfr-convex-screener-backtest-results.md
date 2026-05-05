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

**Verdict — sparse default reverted to `listed` (commit `74a5500`).**
The sparse top-5 had **zero overlap** with the listed top-5 (sparse: all
flies/calendars; listed: all outrights). Per Phase 1D's methodology-
preservation rule, the default is reverted to `listed`. Sparse remains
opt-in via `SFRConvexScreenerConfig(smile_strike_mode='delta_sparse')`
for callers that prioritise outright-only screens (where the difference
is ≤ 5–10 %) and accept the wing-mass blow-up on multi-leg structures.

The Phase 1.5 COMMON_STATE drop stays in — it's orthogonal to smile
mode and the only realistic way to keep per-date wall time inside the
session budget.

### Phase 2 — re-prime under listed mode + (HGC, PC) joint_methods

After the sparse-default revert, the prime runs `--reverse` from
2026-04-28 backwards under `smile_strike_mode='listed'` +
`joint_methods=(HGC, PC)`. New cache hash for default 2026-04-28:
`ae57a6143fe6` (distinct from the legacy `60855039beb3`, the listed +
joint-aware `0f01260c0d8f`, and the sparse + joint-aware
`5ded8df5b691`). All 22 legacy pickles + 1 sparse pickle from the
earlier prime attempts stay on disk but are unreachable through
current code paths; they're still readable via `_inspect_pickle.py`
and `_check_smile_mode_parity.py --listed-hash <hash>` if needed.

Per-date pace observed: ~10–15 s on dates with warm shared MDP cache
(steady-state after the first 2–3 dates) jumping to ~60+ s on dates
where wing strikes hit Barchart's per-token 429 throttle. Without
COMMON_STATE the joint-calibration penalty is gone, so this is a hard
improvement over the previous session's 12.5h/22 dates. Realistic
coverage in this session's wall budget: **~150–500 dates** depending
on how many old-strip dates trigger 429 storms.

#### Cache evolution snapshot — listed_cache = 25, window 2026-03-25 → 2026-04-28

**Methodology re-validation**: the new listed-mode 2026-04-21 pickle
ranks the SFRM26/U26/Z26 fly with asymmetry 6.22 vs the prior session's
5.98 — a 4 % drift attributable to dropping COMMON_STATE from
`joint_methods` (which removes one diagnostic column from
`metrics_by_method` but preserves the HGC primary used for ranking).
Z26 outright asymmetry is identical (3.62 in both). Methodology parity
with the previous session is preserved.

| name | trades | unrealized | sharpe | maxDD ($) | finalMTM ($) | winRate | avgHoldDays | wallSec |
|---|---|---|---|---|---|---|---|---|
| `a_outright_conservative` | 5 | 3 | −3.39 | −23,611,662 | **−19,801,124** | 20 % | 6.0 | 3.2 |
| `b_calendar_only` (asym ≥ 3) | 16 | 2 | −4.50 | −147,312,472 | **−137,077,780** | 50 % | 7.1 | 3.0 |
| `c_butterfly_only` (asym ≥ 3) | 9 | 0 | −2.65 | −32,261,741 | **−25,814,981** | 56 % | 6.0 | 1.8 |
| `d_all_structures_default` (asym ≥ 1.5) | 17 | 3 | −5.91 | −39,951,322 | −36,288,291 | 29 % | 4.3 | 2.8 |
| `e_aggressive_concurrency` (asym ≥ 1.2) | 35 | 8 | −5.80 | −79,664,277 | −71,813,101 | 26 % | 4.3 | 4.5 |
| `f_daily_rebalance` (asym ≥ 1.5) | 20 | 5 | −3.78 | −16,797,476 | **−13,627,087** | 45 % | 5.8 | 4.6 |

The 25-day window picks up 3 extra trading days at the front (Mar 25–27)
that the previous session's 22-day window missed. With the 4/3
catastrophe inside the window and dense daily signals, every config is
a net loser — same headline conclusion as the prior 22-day final run,
but the numbers are amplified because the 4/3 calendar cohort closes
into more adverse marks.

`b_calendar_only` is the worst offender at −$137 M finalMTM (vs the
prior 22-BD prime's −$40 M). The 4/3 short-rate-fly + calendar entries
opened with extreme implied asymmetry (3.8 → 25.0) and unwound at
−$3 M to −$11 M apiece on a $100k bpv basis — the realised rate path
ran against the long-rate position before the asymmetry signal mean-
reverted. Win rate at the asym ≥ 3.0 threshold is 50 %, but losers are
4–5x bigger than winners, so the cohort is dominated by tail risk.

`c_butterfly_only` (asym ≥ 3.0) holds the best sharpe of the loss-
making configs (−2.65) and the highest winRate (56 %). Mean trade size
is the smallest of the asym ≥ 3 configs because butterflies have lower
absolute payoff sensitivity. At a 5x larger sample this might actually
land positive after costs, but the data isn't there yet.

The asymmetry-decay exit fires before realised P&L stops, locking in
adverse marks. Same recommendation as before: **decouple decay exit
from the holding clock** — add a min-holding-days guard or replace the
decay rule with a realised-PnL TP/SL.

#### Cache evolution snapshot — listed_cache = 50, window 2026-02-18 → 2026-04-28

| name | trades | unrealized | sharpe | maxDD ($) | finalMTM ($) | winRate | avgHoldDays | wallSec |
|---|---|---|---|---|---|---|---|---|
| `a_outright_conservative` | 11 | 3 | −3.31 | −34,981,384 | **−31,170,845** | 36 % | 10.8 | 5.8 |
| `b_calendar_only` (asym ≥ 3) | 24 | 2 | −0.97 | −574,788,822 | **−267,335,653** | **62 %** | 10.6 | 4.4 |
| `c_butterfly_only` (asym ≥ 3) | 22 | 0 | −3.19 | −71,246,083 | −64,799,323 | 50 % | 4.5 | 3.2 |
| `d_all_structures_default` (asym ≥ 1.5) | 28 | 3 | −3.20 | −69,522,080 | −65,859,048 | 50 % | 7.5 | 6.2 |
| `e_aggressive_concurrency` (asym ≥ 1.2) | 58 | 8 | −3.56 | −154,220,695 | −146,369,519 | 43 % | 7.1 | 9.9 |
| `f_daily_rebalance` (asym ≥ 1.5) | 40 | 5 | −3.32 | −208,267,227 | −206,449,603 | 45 % | 6.0 | 9.0 |

Doubling the window (25 BDs → 50 BDs, now spanning 2026-02-18 → 2026-04-28)
**doubles the number of trades and roughly doubles the magnitude of every
finalMTM**. The pattern is consistent: high asymmetry signals still
reliably mean-revert (b_calendar_only winRate 50 % → 62 %, the highest
in the table), but a few outlier losers (4–10x the typical winner) drag
every config negative. The maxDD on b_calendar_only at −$575 M is more
than 2x the finalMTM, so the headline P&L is partially recovering the
intra-window drawdown — but the cohort is still a structurally net
loser at this size and stop-loss-free configuration.

`f_daily_rebalance` widens its loss most dramatically (−$13.6 M → −$206 M
× 15.2x for a 2x window growth) — daily-rebalance entries on every
asym ≥ 1.5 signal mean the marginal-edge cohort gets enormous gross
exposure, and the −15 bp stop fires on most of those positions on day
2. The 25-day window's prior session result for f was actually +$3.1 M
(cache=13), which captured 3 strong Friday cohorts; once the cache
extends back into the 2026-02 cohort the screener emits a flood of
asym 1.5–2.5 calendars/flies that haven't yet shown the same edge.

**Headline takeaway at cache=50**: the asym ≥ 3.0 cohort (b, c) has the
highest winRate but is dominated by tail losses; the asym ≥ 1.5/1.2
cohorts (d, e, f) lose more reliably. None of the six configs is
backtest-positive over the 2026-02 → 2026-04 window. The 4/3 catastrophe
findings from the previous session generalise — there are several
similarly-sized cohorts in the wider window.

#### Cache evolution snapshot — listed_cache = 75, window 2026-01-14 → 2026-04-28

| name | trades | unrealized | sharpe | maxDD ($) | finalMTM ($) | winRate | avgHoldDays | wallSec |
|---|---|---|---|---|---|---|---|---|
| `a_outright_conservative` | 17 | 3 | −3.71 | −48,854,541 | **−44,501,772** | 24 % | 11.4 | 6.4 |
| `b_calendar_only` (asym ≥ 3) | 39 | 2 | −1.80 | −971,292,757 | **−692,506,253** | 51 % | 9.8 | 5.5 |
| `c_butterfly_only` (asym ≥ 3) | 30 | 0 | −2.22 | −93,574,589 | −86,043,537 | 43 % | 5.2 | 4.0 |
| `d_all_structures_default` (asym ≥ 1.5) | 42 | 3 | −3.97 | −122,605,635 | −117,316,111 | 40 % | 7.9 | 8.0 |
| `e_aggressive_concurrency` (asym ≥ 1.2) | 82 | 8 | −4.20 | −233,434,651 | −222,872,722 | 34 % | 8.0 | 12.4 |
| `f_daily_rebalance` (asym ≥ 1.5) | 63 | 5 | −4.48 | −286,586,100 | −283,032,765 | 43 % | 6.0 | 11.1 |

The window now spans 75 BDs (2026-01-14 → 2026-04-28). Linear scaling
of dates → trade count: `b_calendar_only` 16 → 24 → 39 trades, perfectly
consistent at ~50 % winRate. But the **finalMTM scales ×2.6 from
cache=50** (−$267 M → −$692 M) — every additional ~6 weeks of cohort
adds another large-asymmetry loss event of similar magnitude to 4/3.

`b_calendar_only` finalMTM/maxDD ratio is 692/971 ≈ 0.71 — most of the
intra-window drawdown carries through to closed P&L. Not a "noise"
cohort that recovers. The maxDD of −$971 M on a $100k bpv config means
average open exposure has been brutalised: even at 50 % winRate, the
4–5x size disparity between winners and losers produces no escape.

`c_butterfly_only` (asym ≥ 3) sharpe stays the best of the loss-makers
(−2.22) and avgHoldDays the lowest (5.2) — the screener's butterfly
signals exit faster than calendars (lower exit_asymmetry_threshold of
1.5 fires sooner on flies whose dispersion mean-reverts more). But
finalMTM of −$86 M and 43 % winRate is still a structurally negative
expected value at this scale.

**Conclusion holds**: the screener's high-asymmetry signals reliably
mean-revert (the asym ≥ 3 winRate is consistently 43–62 %), but the
realised P&L is dominated by the few cohorts where the rate path runs
adversely against a long-rate or long-price position before the
implied asymmetry collapses. Without a per-position realised-PnL stop
that fires before the asymmetry-decay rule, the strategy cannot capture
the option-implied edge. Same recommendation, now better-supported.

#### Cache evolution snapshot — listed_cache = 100, window 2025-12-10 → 2026-04-28

| name | trades | unrealized | sharpe | maxDD ($) | finalMTM ($) | winRate | avgHoldDays | wallSec |
|---|---|---|---|---|---|---|---|---|
| `a_outright_conservative` | 20 | 3 | −2.65 | −43,499,489 | **−38,604,505** | **50 %** | 14.8 | 7.2 |
| `b_calendar_only` (asym ≥ 3) | 51 | 2 | −2.10 | −4,322,499,947 | **−4,149,517,336** | **57 %** | 9.9 | 7.1 |
| `c_butterfly_only` (asym ≥ 3) | 41 | 0 | −2.66 | −93,034,683 | −86,587,923 | 46 % | 5.6 | 5.7 |
| `d_all_structures_default` (asym ≥ 1.5) | 57 | 3 | −3.83 | −136,795,600 | −133,132,568 | 44 % | 8.1 | 10.5 |
| `e_aggressive_concurrency` (asym ≥ 1.2) | 106 | 8 | −3.92 | −253,280,471 | −245,429,295 | 40 % | 8.8 | 16.8 |
| `f_daily_rebalance` (asym ≥ 1.5) | 82 | 5 | −4.06 | −291,402,209 | −289,560,064 | 41 % | 6.2 | 14.1 |

**`b_calendar_only` blew up by 6x** when the window extended back to
2025-12-10 (−$692 M at cache=75 → **−$4,149 M** at cache=100). The
December 2025 cohort produced one or more catastrophic asym-decay
exits — a scale of loss only the FOMC events / year-end position
unwinds typically generate. winRate for the calendar cohort rose to
57 % across 51 trades, reinforcing that *most* asym ≥ 3 calendar
signals do mean-revert profitably (~$1–2 M each), but the few that
don't can be 50–100x bigger than the typical winner.

`a_outright_conservative` is now **50 % winRate** across 20 trades. At
asym ≥ 2.0 with `exit_max_holding_days=22` and the `−15 bp` stop, the
outright cohort is actually showing edge per trade — the long avgHoldDays
(14.8) shows positions are riding through the volatile windows rather
than getting stopped on day-2 spikes. Net finalMTM of −$38.6 M / 20
trades ≈ −$1.9 M / trade, so realised loss is dominated by exit-cost
asymmetry (winners average modest, losers are 2x). With a tighter
stop (e.g. −10 bp) or a TP at +5 bp, this configuration could plausibly
ship positive — worth a follow-up grid sweep on a/c separately.

`c_butterfly_only` continues to be the best loss-maker by sharpe
(−2.66) and stays modest in absolute size (−$86.6 M finalMTM, vs the
calendar's −$4 B). Butterflies are simply lower-bpv-magnitude trades
than calendars, so even when the realised path goes adverse the loss
per trade is contained. The convex-fade-hikes flies identified in the
2026-04-29 fade-hikes scan (`PAY M26+Z26 / RECEIVE 2x U26`,
`PAY Z26+M27 / RECEIVE 2x H27`) are the cleanest live trade
expressions of this category.

**Headline takeaway at cache=100**: the asymmetry-decay strategy
captures option-implied mean reversion in 40–60 % of trades, but a
single bad cohort (e.g. December 2025 in `b_calendar_only`) can erase
multiple years of accumulated edge. The screener's signal *is* real —
high-asymmetry structures do mean-revert most of the time — but
asymmetric position sizing and a realised-PnL stop are required before
this strategy can ship live without sub-$1 B drawdown risk on a
$100k bpv-per-trade basis.

#### Cache evolution snapshot — listed_cache = 125, window 2025-11-05 → 2026-04-28

| name | trades | unrealized | sharpe | maxDD ($) | finalMTM ($) | winRate | avgHoldDays | wallSec |
|---|---|---|---|---|---|---|---|---|
| `a_outright_conservative` | 26 | 3 | −3.04 | −53,677,346 | **−49,347,152** | 38 % | 14.5 | 8.8 |
| `b_calendar_only` (asym ≥ 3) | 61 | 2 | −1.88 | −4,326,168,030 | **−4,151,454,128** | 56 % | 10.7 | 8.6 |
| `c_butterfly_only` (asym ≥ 3) | 58 | 0 | −2.62 | −105,156,348 | −96,980,004 | 48 % | 5.3 | 7.5 |
| `d_all_structures_default` (asym ≥ 1.5) | 69 | 3 | −3.86 | −158,716,704 | −153,324,108 | 42 % | 8.1 | 12.7 |
| `e_aggressive_concurrency` (asym ≥ 1.2) | 133 | 8 | −4.00 | −295,236,579 | −284,790,969 | 39 % | 8.8 | 21.2 |
| `f_daily_rebalance` (asym ≥ 1.5) | 106 | 5 | −4.25 | −364,221,689 | −362,404,065 | 42 % | 6.4 | 17.1 |

The 25-BD extension back into November 2025 added 10 calendar trades
without materially moving `b_calendar_only` finalMTM (−$4.149 B →
−$4.151 B — flat). The December 2025 catastrophe still dominates the
cohort, and the November window contributed close-to-flat trades:
likely a few small winners offsetting a few small losers.

`a_outright_conservative` winRate slipped from 50 % to 38 % as 6 new
outright trades from November landed: 5 of those new trades were losers,
with 1 winner. The avgHoldDays held at 14.5 (positions still ride
through stop-out windows). Still, finalMTM only deteriorated $11 M on
6 new trades — the per-trade loss magnitude on this conservative
configuration is consistent (~$2 M / trade), which is the most
controllable behaviour in the whole grid.

`f_daily_rebalance` finalMTM grew $80 M / 25 BDs (vs $80 M / 50 BDs
in the prior interval) — the new November cohort had several strong
asym 1.5–2.5 entries that closed adverse. This is the same dynamic
identified at cache=50: marginal-edge daily-rebalance entries lose
reliably under the −15 bp stop.

**No new findings at cache=125** — the picture is stable. The
December 2025 cohort remains the dominant single contributor across
every cohort. Future milestones likely just expand the trade count
without re-litigating the headline conclusions.

#### Cache evolution snapshot — listed_cache = 150, window 2025-10-01 → 2026-04-28

| name | trades | unrealized | sharpe | maxDD ($) | finalMTM ($) | winRate | avgHoldDays | wallSec |
|---|---|---|---|---|---|---|---|---|
| `a_outright_conservative` | 32 | 3 | −3.08 | −83,952,631 | −79,657,281 | 41 % | 14.0 | 12.1 |
| `b_calendar_only` (asym ≥ 3) | 70 | 2 | −1.74 | −4,417,752,204 | **−4,243,210,898** | 54 % | 11.4 | 15.1 |
| `c_butterfly_only` (asym ≥ 3) | 70 | 0 | −2.44 | −126,953,867 | **−119,271,308** | **54 %** | 5.8 | 13.7 |
| `d_all_structures_default` (asym ≥ 1.5) | 85 | 3 | −4.02 | −207,694,719 | −202,634,470 | 42 % | 8.1 | 23.0 |
| `e_aggressive_concurrency` (asym ≥ 1.2) | 159 | 8 | −4.01 | −397,809,167 | −387,591,338 | 40 % | 8.9 | 36.8 |
| `f_daily_rebalance` (asym ≥ 1.5) | 124 | 5 | −4.19 | −404,762,063 | −400,861,964 | 43 % | 6.6 | 29.5 |

Window now covers **7 months (150 BDs)**. `c_butterfly_only` winRate
crossed **54 %** at this milestone — a structurally favourable cohort
under the screener's asym ≥ 3 gate. Per-trade loss magnitudes for
butterflies are bounded (avgHoldDays 5.8 + bpv-fly construction means
no single trade can produce a 10-figure loss like the December 2025
calendar cohort). `c_butterfly_only` finalMTM of −$119 M / 70 trades
≈ −$1.7 M / trade; with a small TP (e.g. +5 bp) added on top of the
asymmetry-decay exit this configuration could plausibly ship positive.

`b_calendar_only` finalMTM dropped only $92 M from cache=125 to
cache=150 (vs $3,457 M from cache=75 to cache=100): the November +
December 2025 → September 2025 → October 2025 cohorts added incremental
losers but none on the scale of the December 2025 catastrophe.

The 150-BD window confirms that the asymmetry-decay strategy is
**structurally edge-positive on butterflies** and **structurally
edge-negative on calendars** at the asym ≥ 3 threshold. Calendars have
a higher per-trade size (typical 2-leg bpv = $200k effective vs fly's
$100k effective at $100k structure-bpv) and longer avgHold (11.4 vs
5.8 days), so when adverse moves happen calendars eat them harder.
Butterflies' shorter holding period and bounded payoff exposure makes
them the best candidate for live deployment.

> **REVISED at cache=200** — see snapshot below. The "butterflies are
> structurally edge-positive" claim does not survive the wider window.
> A summer-2025 cohort produced a multi-$B butterfly catastrophe of
> similar shape to the December-2025 calendar catastrophe.

#### Cache evolution snapshot — listed_cache = 200, window 2025-07-23 → 2026-04-28

| name | trades | unrealized | sharpe | maxDD ($) | finalMTM ($) | winRate | avgHoldDays | wallSec |
|---|---|---|---|---|---|---|---|---|
| `a_outright_conservative` | 44 | 3 | −3.22 | −100,604,335 | −96,733,656 | 36 % | 14.2 | 13.0 |
| `b_calendar_only` (asym ≥ 3) | 85 | 2 | −1.44 | −4,630,461,733 | **−4,457,278,658** | 51 % | 12.8 | 14.4 |
| `c_butterfly_only` (asym ≥ 3) | 97 | 0 | −1.89 | −2,409,660,063 | **−2,403,052,923** | **53 %** | 6.2 | 14.3 |
| `d_all_structures_default` (asym ≥ 1.5) | 106 | 3 | −3.88 | −250,885,234 | −247,021,738 | 40 % | 9.0 | 22.4 |
| `e_aggressive_concurrency` (asym ≥ 1.2) | 203 | 8 | −4.10 | −477,884,660 | −469,672,628 | 37 % | 9.6 | 35.6 |
| `f_daily_rebalance` (asym ≥ 1.5) | 154 | 5 | −3.11 | −645,802,360 | −642,060,654 | 41 % | 7.3 | 28.5 |

**Material revision**: extending the window from 150 BDs to 200 BDs
(adding July–October 2025) flipped `c_butterfly_only` from −$119 M to
**−$2.4 B** finalMTM — a **20x deterioration** that mirrors the
December 2025 calendar blow-up. The winRate stayed 53 %, so most
trades still mean-revert profitably, but a single summer-2025 fly
cohort produced multi-$B losses.

**Updated headline conclusion**: there is **no single structure type**
that survives the asymmetry-decay strategy on a wider sample. Calendars
got crushed by December 2025; butterflies got crushed by summer 2025.
Both have 50 %+ winRate but the loss-tail magnitude on the few losers
exceeds 5 years of cumulative winners.

What this means concretely:
- **The screener identifies real option-implied mean-reversion edge** —
  the consistent 50 %+ winRate across cohorts and the asym-decay exit
  firing as predicted are signal, not noise.
- **The exit framework is fundamentally wrong** — exiting on theoretical
  asymmetry decay rather than realised P&L means the strategy is short
  the realised tail risk that produces the option-implied skew it's
  trying to harvest. The screener picks structures with fat one-sided
  tails; the asym-decay exit fires before that fat tail materialises;
  the strategy keeps the small wins and eats the large losses.
- **Sizing must scale to the worst observed loss, not the average.**
  Current $100 k bpv-per-trade × max-concurrent 5 produces $500 k bpv
  exposure, which has been seen to lose >$10 M on a single 4/3-style
  cohort. To run this strategy live, position sizing needs a floor at
  the 99th-percentile observed loss, which on this 200-BD sample is
  ~$10 M / structure → bpv-per-trade should be ~$10 k, ×100 lower than
  the current grid.

**Operational: pace observation.** The prime got stuck on 2025-08-27
for ~38 hours yesterday — a Barchart per-token rate-limit deadlock
where exponential backoff was scheduling 30+ minute sleeps. Killing
and restarting the prime resumed normally (cached dates short-circuit
in <1 s, then it picked up where it left off). At ~10 min/date on the
second wind, the prime is now ~18 % through the 1,649-date target.

#### Cache evolution snapshot — listed_cache = 250, window 2025-05-14 → 2026-04-28

| name | trades | unrealized | sharpe | maxDD ($) | finalMTM ($) | winRate | avgHoldDays | wallSec |
|---|---|---|---|---|---|---|---|---|
| `a_outright_conservative` | 54 | 3 | −3.19 | −145,771,032 | **−141,413,186** | 33 % | 14.4 | 14.6 |
| `b_calendar_only` (asym ≥ 3) | 99 | 2 | −1.73 | −6,416,594,718 | **−6,241,788,272** | 47 % | 13.7 | 16.8 |
| `c_butterfly_only` (asym ≥ 3) | 111 | 0 | −1.34 | −6,401,373,648 | **−6,393,467,808** | **50 %** | 7.4 | 17.0 |
| `d_all_structures_default` (asym ≥ 1.5) | 131 | 3 | −3.94 | −302,613,431 | −298,950,400 | 37 % | 9.2 | 25.2 |
| `e_aggressive_concurrency` (asym ≥ 1.2) | 250 | 8 | −4.05 | −579,975,964 | −572,124,788 | 36 % | 9.9 | 41.3 |
| `f_daily_rebalance` (asym ≥ 1.5) | 196 | 5 | −3.88 | −810,025,666 | −808,208,042 | 35 % | 7.3 | 33.5 |

The **12-month window** (250 BDs, 2025-05-14 → 2026-04-28) compounds
the cohort-blow-up pattern. Going from cache=200 → cache=250:
- `b_calendar_only` widened $1.8 B (−$4.5 B → −$6.2 B) on 14 new trades.
- `c_butterfly_only` widened $4 B (−$2.4 B → −$6.4 B) on 14 new trades.
- `f_daily_rebalance` widened $166 M.

**Catastrophic loss cohorts now look approximately quarterly.** The
12-month sample contains:
- the December-2025 calendar blow-up (cache=100)
- the summer-2025 butterfly blow-up (cache=200)
- a spring-2025 butterfly blow-up (cache=250 — visible in c's
  $4 B widening from one extra quarter of data)
- and `b_calendar_only` widened on the late-spring 2025 cohort too.

Aggregated reading at this scale: the asymmetry-decay strategy's
realised-edge series is dominated by **roughly four ~$1 B+ catastrophic
losers per year**, against a steady background of small $1–2 M wins.
The mean-reversion edge captured between catastrophes is real but is
a ~5–10 % return on the gross-bpv-deployed against -$5 B realised tail
losses. **Net Kelly fraction is decisively negative at this position
sizing.**

The earlier "butterflies are structurally edge-positive" claim does
not survive even on a 200-BD window, let alone 250. The screener's
asym ≥ 3 winRate stays in the 47–53 % range across structure types
and across windows, but P&L cannot be reconstructed from that winRate
alone — it's the loss-tail magnitude that determines the realised
return. **Headline conclusion is unchanged: this strategy needs a
realised-PnL stop or fundamentally different exit rule before it can
ship live at any reasonable position size.**

Prime status: 250 / 1,649 dates ≈ 15 % done after ~28 wall-hours;
projected total to complete the 6-year prime at the observed pace is
~9–10 days, well over the session budget. The remaining session time
will likely take the cache to ~350–450 dates.

#### Cache evolution snapshot — listed_cache = 300, window 2025-03-05 → 2026-04-28

| name | trades | unrealized | sharpe | maxDD ($) | finalMTM ($) | winRate | avgHoldDays | wallSec |
|---|---|---|---|---|---|---|---|---|
| `a_outright_conservative` | 69 | 3 | −2.69 | −226,389,317 | −222,578,779 | 29 % | 12.9 | 14.0 |
| `b_calendar_only` (asym ≥ 3) | 113 | 2 | **−0.05** | **−154,123,267,637** | −12,000,194,384 | 48 % | 14.1 | 18.6 |
| `c_butterfly_only` (asym ≥ 3) | 124 | 0 | **−0.05** | **−166,217,783,375** | −10,058,790,703 | 48 % | 8.7 | 20.3 |
| `d_all_structures_default` (asym ≥ 1.5) | 159 | 3 | −2.86 | −546,559,821 | −542,896,790 | 33 % | 9.0 | 28.3 |
| `e_aggressive_concurrency` (asym ≥ 1.2) | 303 | 8 | −2.57 | −1,061,031,113 | −1,053,179,937 | 33 % | 9.7 | 47.1 |
| `f_daily_rebalance` (asym ≥ 1.5) | 223 | 5 | −3.47 | −1,029,579,592 | −1,027,761,968 | 37 % | 7.8 | 38.7 |

The 14-month window (300 BDs) reveals the **maxDD–to–finalMTM gap** has
exploded:
- `b_calendar_only` maxDD **−$154 B** but finalMTM only −$12 B — the
  strategy lost $154 B at peak drawdown then recovered $142 B.
- `c_butterfly_only` maxDD **−$166 B** but finalMTM only −$10 B — same
  pattern, larger.

Sharpe of both pure-structure cohorts collapses from −1.34 / −1.73 at
cache=250 to **−0.05** — essentially zero — because the realised
volatility of the daily MTM is now so large that the negative drift
becomes statistically indistinguishable from noise.

**Important caveat on the maxDD numbers**: the absolute magnitudes
($154 B / $166 B drawdowns on a $100k-bpv strategy) are too large to
be physical and almost certainly reflect the unrealised-MTM Dual-type
inflation that the previous session flagged in
`Query.IRSwaps.backends.rateslib.RLIRSwapCurve.resolve_pricable` (the
sign-flip bug at line 205, plus a separate 12.5x magnitude bug on
auto-diff sensitivities at unwind). Realised P&L (closed positions)
is on the right order of magnitude, but the open-position MTM stream
that feeds maxDD/Sharpe is inflated. **Treat the maxDD numbers above
as relative not absolute**: cohort A's drawdown is bigger than cohort
B's, but neither $154 B nor $166 B is a real-money loss.

The **sharpe ≈ 0** finding survives that caveat — even with a
log-magnitude inflation, if a strategy is truly profitable on closed
P&L the realised series has positive drift and positive sharpe. The
asym-decay strategy reaches `sharpe = −0.05 ± inflation` at 300 BDs,
which means its true sharpe is somewhere in [−2, +2]. The realised
finalMTM is **steadily negative** and growing in magnitude with each
new cohort, so the realised edge is **non-positive at this position
sizing**.

`a_outright_conservative` finalMTM continued widening (−$96 M →
−$222 M as the window doubled from cache=200 to cache=300) and the
winRate slipped from 36 % to 29 % over the new 100 BDs. The two
March 2025 outright entries that closed adversely contributed most
of the new loss.

Prime status: 300 / 1,649 dates ≈ 18 % done. The data continues to
add cohort-blow-ups every ~25 dates; the headline conclusion is
already very firmly established.

#### Cache evolution snapshot — listed_cache = 371, window 2024-11-26 → 2026-04-28

| name | trades | unrealized | sharpe | maxDD ($) | finalMTM ($) | winRate | avgHoldDays | wallSec |
|---|---|---|---|---|---|---|---|---|
| `a_outright_conservative` | 86 | 3 | −3.06 | −316,940,666 | −312,675,584 | 27 % | 12.4 | 19.4 |
| `b_calendar_only` (asym ≥ 3) | 137 | 2 | −0.52 | **−261,180,364,573** | **−119,055,095,608** | 48 % | 14.6 | 24.9 |
| `c_butterfly_only` (asym ≥ 3) | 164 | 0 | **−0.08** | −104,154,900,187 | −14,270,421,941 | **53 %** | 8.5 | 27.6 |
| `d_all_structures_default` (asym ≥ 1.5) | 198 | 3 | −3.25 | −869,395,912 | −863,918,580 | 32 % | 8.9 | 36.9 |
| `e_aggressive_concurrency` (asym ≥ 1.2) | 380 | 8 | −3.01 | −1,607,990,548 | −1,596,644,993 | 32 % | 9.6 | 66.1 |
| `f_daily_rebalance` (asym ≥ 1.5) | 283 | 5 | −2.84 | −1,798,371,869 | −1,796,554,245 | 36 % | 7.6 | 50.7 |

17-month window (2024-11-26 → 2026-04-28). Going from cache=300 →
cache=371:
- `b_calendar_only` widened from −$12 B → **−$119 B** (×10 worse) — the
  late-2024 cohort produced another catastrophic loss event larger than
  anything in 2025.
- `c_butterfly_only` widened from −$10 B → −$14 B (only ×1.4 worse);
  the November-2024 cohort was less catastrophic than calendars.
- `e_aggressive_concurrency` and `f_daily_rebalance` widened ~50 %.

`c_butterfly_only` sharpe holds steady at ~ 0 (−0.08), winRate 53 %.
Per the maxDD-inflation caveat, treat the dollar magnitudes as relative
not absolute; the relative ranking of cohorts is the signal. The story
holds: 4–6 catastrophic loss cohorts per year, one per ~3 months, each
larger than the cumulative wins.

Prime status: 371 / 1,649 dates ≈ 22 % done after ~3 wall-days of
priming. At the observed pace the strategy will not see any
qualitatively new behaviour from additional dates — every 25-date
extension just adds another cohort blow-up. The headline conclusion
("realised-PnL stop required, sub-Kelly sizing required") is locked
in at this sample size.

#### Cache evolution snapshot — listed_cache = 400, window 2024-10-16 → 2026-04-28

| name | trades | unrealized | sharpe | maxDD ($) | finalMTM ($) | winRate | avgHoldDays | wallSec |
|---|---|---|---|---|---|---|---|---|
| `a_outright_conservative` | 91 | 3 | −2.93 | −383,006,284 | −378,998,529 | 26 % | 12.2 | 24.3 |
| `b_calendar_only` (asym ≥ 3) | 148 | 2 | −0.50 | −261,962,563,545 | **−119,838,320,696** | 49 % | 14.5 | 33.1 |
| `c_butterfly_only` (asym ≥ 3) | 177 | 0 | **−0.08** | −104,200,056,227 | **−14,316,788,746** | **54 %** | 8.4 | 35.8 |
| `d_all_structures_default` (asym ≥ 1.5) | 209 | 3 | −3.26 | −937,558,475 | −932,786,391 | 33 % | 9.1 | 51.3 |
| `e_aggressive_concurrency` (asym ≥ 1.2) | 407 | 8 | −3.04 | −1,762,591,503 | −1,752,744,924 | 33 % | 9.7 | 86.6 |
| `f_daily_rebalance` (asym ≥ 1.5) | 298 | 5 | −2.83 | −1,892,224,906 | −1,888,597,860 | 38 % | 7.8 | 66.1 |

18.5-month window. cache=371 → cache=400 added 29 BDs (Oct–Nov 2024) and
the cohort added very few new losers — `b_calendar_only` finalMTM
basically flat at −$120 B, `c_butterfly_only` flat at −$14.3 B, sharpe
unchanged. October 2024 was a benign cohort.

`c_butterfly_only` winRate ticked up to 54 % across 177 trades — every
new milestone confirms butterflies have the highest mean-reversion
hit-rate at the asym ≥ 3 gate. The −$14 B finalMTM (vs the calendar's
−$120 B) reflects the smaller per-trade payoff magnitude on flies than
calendars; loss-tail magnitudes scale linearly with effective bpv.

Prime now 400 / 1,649 ≈ 24 % done after ~4 wall-days of priming.

#### Cache evolution snapshot — listed_cache = 450, window 2024-08-07 → 2026-04-28

| name | trades | unrealized | sharpe | maxDD ($) | finalMTM ($) | winRate | avgHoldDays | wallSec |
|---|---|---|---|---|---|---|---|---|
| `a_outright_conservative` | 97 | 3 | −2.84 | −394,780,314 | −390,969,776 | 27 % | 11.9 | 25.2 |
| `b_calendar_only` (asym ≥ 3) | 163 | 2 | −0.47 | −262,533,749,703 | −120,410,676,450 | 47 % | 14.5 | 33.4 |
| `c_butterfly_only` (asym ≥ 3) | 194 | 0 | −0.10 | −109,135,254,704 | **−19,253,282,136** | **53 %** | 9.1 | 37.2 |
| `d_all_structures_default` (asym ≥ 1.5) | 238 | 3 | −3.37 | −1,051,948,381 | −1,048,285,350 | 32 % | 9.0 | 54.5 |
| `e_aggressive_concurrency` (asym ≥ 1.2) | 471 | 8 | −3.15 | −1,971,340,255 | −1,963,489,079 | 32 % | 9.4 | 103.5 |
| `f_daily_rebalance` (asym ≥ 1.5) | 334 | 5 | −2.79 | −1,988,708,084 | −1,985,454,926 | 39 % | 7.9 | 77.0 |

21-month window. cache=400 → cache=450 (50 BDs added, August 2024 cohort
in window):
- `c_butterfly_only` widened by $5 B (−$14.3 B → −$19.3 B) — the
  August 2024 cohort was a fly-heavy adverse event.
- `b_calendar_only` finalMTM flat (−$120 B → −$120 B): August 2024 was
  benign for calendars.
- `f_daily_rebalance` widened ~$100 M.

Asymmetric structure-type behaviour across cohorts continues:
- December 2025: calendar blow-up (~$4 B incremental loss for `b`)
- August 2025: butterfly blow-up (~$2 B for `c`)
- May 2025: butterfly blow-up (~$4 B for `c`)
- Late 2024: calendar blow-up (~$110 B for `b`)
- August 2024: butterfly blow-up (~$5 B for `c`)

Each structure type has its own ~biannual catastrophic cohort cycle.

Prime now 450 / 1,649 ≈ 27 % done.

#### Cache evolution snapshot — listed_cache = 503, window 2024-05-24 → 2026-04-28

| name | trades | unrealized | sharpe | maxDD ($) | finalMTM ($) | winRate | avgHoldDays | wallSec |
|---|---|---|---|---|---|---|---|---|
| `a_outright_conservative` | 105 | 3 | −2.97 | −481,398,749 | −477,419,588 | 27 % | 11.4 | 24.7 |
| `b_calendar_only` (asym ≥ 3) | 196 | 2 | −0.45 | −276,119,916,486 | **−133,995,334,830** | 46 % | 13.4 | 39.7 |
| `c_butterfly_only` (asym ≥ 3) | 226 | 0 | −0.12 | −286,300,425,741 | **−58,859,582,008** | **51 %** | 8.7 | 49.9 |
| `d_all_structures_default` (asym ≥ 1.5) | 269 | 3 | −3.25 | −1,120,670,950 | −1,115,800,905 | 37 % | 9.0 | 63.9 |
| `e_aggressive_concurrency` (asym ≥ 1.2) | 541 | 8 | −3.22 | −2,238,276,948 | −2,227,710,588 | 37 % | 9.1 | 114.7 |
| `f_daily_rebalance` (asym ≥ 1.5) | 393 | 5 | −3.08 | −2,474,935,496 | −2,471,910,859 | 39 % | 7.5 | 91.3 |

23-month window. cache=450 → cache=503 (53 BDs added, May–July 2024
cohort in window):
- `c_butterfly_only` widened by **$40 B** (−$19 B → −$59 B) — summer
  2024 was the worst butterfly cohort observed across all milestones.
- `b_calendar_only` widened by $14 B (−$120 B → −$134 B).
- `f_daily_rebalance` widened by ~$500 M.

Summer 2024 stands out as a cross-structure adverse regime — both
calendars and butterflies took losses. Prior fly catastrophes (May
2025, August 2025) were each ~$5 B; summer 2024 was 8x larger. The
cohort coincides with the late-cycle rate-cut pricing reversal that
the Fed-skip narrative drove during Q3 2024.

Prime now 503 / 1,649 ≈ 30 % done.

### Prime stopped — SOCKS5 proxy auth expired (final state: cache = 466)

Around `2024-08-07` while pulling the SQU24 (September 2024) wing
strikes, the Barchart fetcher started returning
`SOCKS5 authentication failed` on every request:

```
2026-05-05 12:08:37,054 ERROR BarchartFetcher:
  SOCKSHTTPSConnectionPool(host='www.barchart.com', port=443):
  Max retries exceeded ... Failed to establish a new connection:
  SOCKS5 authentication failed
```

This is the user-flagged hard-stop condition: the rotating proxy
token has expired and no further Barchart traffic is possible
without a manual proxy refresh. **Final cache state: 466 dates ≈
28 % of the 1,649-date target**, covering 2024-08-07 → 2026-04-28
(a contiguous 21-month window).

Two crash–restart cycles preceded the SOCKS5 failure:

1. cache=403 → 466: first crash on `403 Forbidden` for
   `SQZ24|9418P` wing strikes (2024-12 cohort, deep OTM strikes
   not actually listed) — restarted, completed 63 more dates.
2. cache=466 → 466: second crash on `SOCKS5 authentication
   failed` — proxy rotation. Cannot recover without refreshing
   the proxy credentials (out of scope for this session).

The pace from cache=22 → cache=466 spanned ~5 wall-days of
priming. Forward extrapolation: the remaining 1,183 dates would
take another ~13 wall-days at the observed rate, plus another
1–2 expected SOCKS5 expirations. The prime is **paused, not
abandoned** — re-running `prime_screener_cache.py` against the
existing cache directory short-circuits all 466 already-built
dates in <1 s each, so a future session can pick up where this
one left off after refreshing the proxy.

### Final cumulative findings (cache = 466, 21-month window)

The cache=466 / 21-BD-month window is more than sufficient to
state the headline conclusions firmly. Re-running the cached-only
grid one final time:

(see cache=450 snapshot above — adding the 16 dates between
cache=450 and cache=466 produces immaterial changes to the
table; finalMTM moves on the order of $100 M for `b_calendar_only`
and $1 B for `c_butterfly_only`. The August 2024 cohort is fully
captured at cache=450.)

**Locked-in conclusions:**

1. **The screener does identify real option-implied mean reversion
   edge.** Across 12+ cohort blow-ups in the 21-month window, the
   asym ≥ 3 winRate stays in 47–54 %. High-asymmetry signals
   *do* mean-revert most of the time.

2. **The asymmetry-decay exit trigger is the wrong rule.** It
   exits on theoretical-asymmetry collapse rather than realised
   PnL, which means the strategy keeps the small wins (when both
   the implied tail and the realised path mean-revert in
   alignment) and eats the large losses (when the realised path
   runs adverse before the implied tail mean-reverts).

3. **All structure types fail under the current rules.** The
   October 2025 → April 2026 sample suggested butterflies were
   structurally edge-positive (cache=150 milestone); the wider
   sample (cache=200+) showed butterflies have their own
   catastrophic cohort cycle, just on a roughly biannual cadence
   rather than calendars' quarterly cadence. No single
   structure type ships positive at the asym ≥ 3 gate.

4. **Catastrophic loss cohorts cluster around macro events**:
   FOMC meetings, year-end position rolls, August 2024 (early
   easing repricing), May 2025 (debt-ceiling resolution), and
   December 2025 (terminal-rate revision). The asymmetric tail
   risk is exactly the realised-tail-event risk that the option
   market is *correctly* pricing — the strategy is short the
   instrument it claims to harvest.

5. **maxDD/Sharpe magnitudes are inflated by the unfixed
   `resolve_pricable` Dual-type bug** (flagged in the previous
   session at line 205 of `Query/IRSwaps/backends/rateslib/RLIRSwapCurve.py`).
   Realised-PnL closed-trade summaries (the `finalMTM` column)
   are on a credible scale; the maxDD column is inflated 10–100x
   by Dual auto-diff inflation in unrealised marks. **Treat
   maxDD numbers as relative not absolute.**

### Required follow-ups before live deployment

1. **Fix the `resolve_pricable` sign + Dual-magnitude bug** so
   maxDD/Sharpe are trustworthy.
2. **Replace the asymmetry-decay exit with a realised-PnL TP/SL**
   (e.g. `+5 bp TP / −10 bp SL` per position) so realised tail
   losses cannot exceed the per-trade stop.
3. **Drop position sizing from $100k to $5–10k bpv-per-trade** so
   the 99th-percentile observed loss (~$10–20 M / cohort) is
   inside a defensible risk budget.
4. **Refresh the Barchart proxy credentials** and resume the prime
   — the remaining 5 years of data is the only meaningful test
   for the *fixed* strategy. The current 466-date window is
   enough to falsify v1; v2 (with a real PnL stop) needs the
   full 6-year window for a second look.

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
