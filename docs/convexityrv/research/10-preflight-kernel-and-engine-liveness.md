<!-- Verbatim return of a preflight investigation agent, 2026-08-20/21.
     Measured on this machine; see the report's own probe list. Kept as
     research evidence, not as a design document. -->

# Preflight scout: kernel and engine liveness

# CONVEXITY-RV KERNEL + ENGINE LIVENESS — MEASURED REPORT

Worktree `C:/Users/chris/clee/ARBS-cvx2`, branch `feat/convexity-rv2` @ `61fa6d1a`. All probes run as
`ARBS_SUPABASE_ENABLED=0 C:/Users/chris/anaconda3/envs/stir/python.exe <script>` from cwd `C:/Users/chris/clee/ARBS-cvx2`.

Probe scripts (durable, in scratchpad):
- `C:/Users/chris/AppData/Local/Temp/claude/C--Users-chris-clee-ARBS/f3c71cad-b780-41e9-8455-68991655ae55/scratchpad/step1_probe.py`
- `.../scratchpad/step2a_curve_coverage.py`, `.../scratchpad/step2a2_meta.py`
- `.../scratchpad/step2b_vol_coverage.py`, `.../scratchpad/step2c_addendum.py`, `.../scratchpad/step2d_exact.py`

---

## STEP 1 — KERNEL IS LIVE (step1_probe.py, TOTAL 8.1 s, zero network)

### 1a. OUTRIGHT sign probe — `bpv>0 == PAYER` CONFIRMED
Verbatim reproduction of `notebooks/backtests/citivelo_rv/sv_h13_qdb.py:86 _run_sign_probe` (tenor `5Y`, dates 2022-09-12..15, `QueryDrivenBacktest` end-to-end):

```
+bpv +2,303,346   -bpv -2,303,346
mirror residual |plus+minus| = 0.000000e+00   (exact, not 1e-6)
```
Matches the pinned +$2,303,346 in `docs/convexityrv/results/strat1-jpm-curve-as-gamma.md:21`. **The backtest engine (`QueryDrivenBacktest` + `DateTrigger`/`AddQueryAction`/`UnwindPositionsAction`) is LIVE.**

### 1a2. CURVE sign probe — `bpv<0 == FLATTENER` CONFIRMED
`s1.resolve_package(pricer, "20Yx5Y", "25Yx5Y", package_dv01=100_000, direction=s1.FLATTENER)` on 2022-09-13 (mirrors `tests/test_convexity_rv_strat1.py::test_resolve_package_is_dv01_neutral_and_direction_mirrors`):

| | weights | pv01 front / back | notionals front / back |
|---|---|---|---|
| FLATTENER (`bpv=−100k`) | `[1.0, −1.0]` | `+100000.000 / −100000.000` | `+392,493,220 / −438,431,773` |
| STEEPENER (`bpv=+100k`) | `[−1.0, 1.0]` | `−100000.000 / +100000.000` | `−392,493,220 / +438,431,773` |

`sum(pv01)_flat = 1.455192e-11` (DV01-neutral); `max|pv01_flat + pv01_steep| = 0.000e+00` (exact mirror). Front pv01 `>0`, back `<0` ⇒ **pay front / receive back = FLATTENER**.

### 1b. PAYOFF-PROFILE REGRESSION CHECK vs `docs/convexityrv/DESIGN.md` §0
`s1.structure_profile(...).convexity_bp`, `Strat1Config()` default 13-point grid `[-250,-200,-150,-100,-50,-25,0,25,50,100,150,200,250]`, carry excluded. **All four structures reproduce; the pinned table is rounded to 1dp, so every disagreement is rounding.**

| structure | max abs disagreement | at shift | carry_bp (1Y) | probe time |
|---|---:|---:|---:|---:|
| **20Yx5Y/25Yx5Y** | **0.0493 bp** | −150 | +0.0061 | 0.3 s |
| **30Y/50Y** | **0.0441 bp** | −250 | +0.3632 | 1.8 s |
| **10Yx10Y/20Yx10Y** | **0.0432 bp** | +150 | −2.8401 | 0.5 s |
| **5Y/30Y** | **0.0500 bp** | +250 | −20.6697 | 0.8 s |

Full measured rows (bp of $100k package DV01):
```
20Yx5Y/25Yx5Y    60.01  33.67  16.55   6.38   1.34   0.28   0.00   0.36   1.25   4.21   8.22  12.79  17.54
30Y/50Y         137.86  82.12  44.73  20.86   6.87   2.69   0.00  -1.43  -1.81  -0.13   3.92   9.48  15.92
10Yx10Y/20Yx10Y 104.89  59.97  29.92  11.58   2.32   0.41   0.00   0.88   2.86   9.49  18.74  29.71  41.66
5Y/30Y          101.91  62.62  34.30  15.32   4.28   1.37   0.00   0.06   1.44   7.70  18.04  31.77  48.35
```
Carry values also reproduce `CARRY_2022_09_13` in the test file to 4dp. (Note: `REGRESSION_2022_09_13` in the pytest file has only 3 rows; **5Y/30Y exists only in DESIGN.md §0** — the pytest suite does not pin it.)

### 1c. U-SHAPE AND FITTED QUADRATIC
`np.polyfit(shifts, convexity_bp, 2)` — `a` is bp of P&L per bp² of parallel shift.

| structure | argmin | min value | **a (bp/bp²)** | b (bp/bp) | c (bp) | `is_convex` flattener | `is_convex` steepener | mirror max\|sum\| |
|---|---:|---:|---:|---:|---:|---|---|---:|
| 20Yx5Y/25Yx5Y | **0 bp** | 0.000 | **+6.156014e-04** | −5.887e-02 | −0.5749 | True | False | 0.000e+00 |
| 30Y/50Y | **+50 bp** | −1.815 | **+1.219821e-03** | −1.946e-01 | −1.2241 | True | False | 0.000e+00 |
| 10Yx10Y/20Yx10Y | **0 bp** | 0.000 | **+1.166277e-03** | −8.582e-02 | −0.7488 | True | False | 0.000e+00 |
| 5Y/30Y | **0 bp** | 0.000 | **+1.199429e-03** | −8.302e-02 | −0.3219 | True | False | 0.000e+00 |

**Correction to the task's premise:** the minimum is at zero for 3 of 4 structures. **30Y/50Y's minimum is at +50 bp (−1.815 bp)** — and this is *correct*, not a defect: DESIGN.md §0's own pinned row carries −1.4 / −1.8 at +25 / +50. The profile carries a linear term; `s1.is_convex` (which handles the uneven grid) returns True for all four flatteners and False for all four steepeners, and the steepener is the exact negation (max |sum| = 0.000e+00 in currency).

---

## STEP 2 — DATA COVERAGE, MEASURED

### 2a. `USD-SOFR-1D` CurveStore (step2a_curve_coverage.py)
Store root `C:\Users\chris\AppData\Local\ARBS\Cache\curve_store\raw\asset=USD-SOFR-1D-CITIVELOEXCEL`
(`CurveStore._default_base_dir`, `Caching/curve_store.py:517`; `ARBS_CACHE_DIR` is UNSET → `%LOCALAPPDATA%/ARBS/Cache/curve_store`; asset from `MDP/IRSwaps/CITIVELO_EXCEL/warm.py:85 asset_for`).

**Exhaustive partition enumeration** (not sampled):
```
partitions total = 5511 ; with >=1 parquet = 5511 ; empty = 0
first partition = 2005-01-03   last partition = 2026-08-14
```
Window **2021-01-01 .. 2026-08-20**:
```
pd.bdate_range business days      = 1470
store partitions in window        = 1466
business days WITH a partition    = 1466  (99.73%)
business days WITHOUT a partition = 4     -> 2026-08-17, -18, -19, -20 (store's warm tail only)
non-business-day partitions       = 0
in-window first = 2021-01-01   last = 2026-08-14
```
So the store publishes on US holidays too (Jan-1 partitions exist), and the only in-window holes are the last 4 unwarmed days.

**Buildability — SAMPLED, 9 dates, 9/9 succeeded** (first partition, last partition, first partition of each year 2021-26, plus 2022-09-13):
```
2005-01-03 built 1.13s (cold imports)   all others 0.02-0.06s   type=RLIRSwapCurve
```
No-COM evidence (step2a2_meta.py, `RLIRSwapCurve._meta_data`):
```
{'source':'citivelo_excel','backend':'rl','mode':'eod','from_curve_store': True,
 'timestamp': 2022-09-13 17:00 America/New_York, 'id':'CITIVELO_EXCEL-USD-SOFR-1D-2022-09-13T17:00:00-04:00'}
```
"Every partition is buildable" is **not measured** — 9 sampled dates spread 2005-2026 are.

### 2a2. ULTRA-LONG FORWARD PRICEABILITY — **7/7 tenors price on 9/9 dates, 0 failures, 0 out-of-band**
Par rate in PERCENT via the `RVUtils/ConvexityRV/strat2_sofr_convexity.py:646 _swap_par_rate` pattern (`IRSwapQuery(OUTRIGHT, RATE, tenor=..., structure_kwargs={"bpv":1.0})` → `resolve_package` → `resolve_pricable` → `build_value_map().apply(RATE)`):

```
date          20Yx10Y  25Yx10Y  30Yx20Y  20Yx30Y      30Y      40Y      50Y       5Y      10Y
2005-01-03    5.66744  5.84794  5.90615  5.77904  5.20517  5.26676  5.29668  4.02658  4.61920
2021-01-01    1.38271  1.18006  0.77390  0.99813  1.17215  1.13475  1.04037  0.24841  0.71270
2022-01-03    1.46903  1.30856  0.87192  1.09344  1.54920  1.43670  1.33122  1.21163  1.42124
2022-09-13    2.23742  1.95934  1.26375  1.64411  2.91042  2.68292  2.45293  3.37675  3.21308
2023-01-02    2.37100  2.10684  1.48142  1.83395  3.16811  2.92873  2.71586  3.72303  3.52038
2024-01-01    2.75924  2.40879  1.70632  2.13486  3.30618  3.10209  2.90000  3.51258  3.45738
2025-01-01    3.31285  2.87363  2.20772  2.67651  3.93000  3.72315  3.53931  4.05403  4.07679
2026-01-01    4.13768  3.70022  3.08095  3.55991  4.14832  4.04337  3.93943  3.44838  3.78254
2026-08-14    4.42310  3.98852  3.24630  3.78955  4.52977  4.42081  4.29286  4.08627  4.28227
```
Nothing fails; nothing leaves the 0.1–10 % band. **20Yx30Y ends at 50Y and 30Yx20Y at 50Y — the curve carries the whole ultra-long space, including 40Y and 50Y outrights.**

### 2b. SWAPTION CUBE (step2b/2c/2d)
Store root `C:\Users\chris\AppData\Local\ARBS\Cache\swaption_cube_store\vol_raw\asset=USD-SWAPTIONVOL-CITIVELOEXCEL` — **2,706 day partitions, 2015-10-08 .. 2026-08-17**.
`load_vol_panel(5 pairs, full history)` = 108,270 rows in **49.5 s** cold (cached to `volpanel_5pairs.parquet` → instant on rerun). Offsets quoted: `-200,-100,-75,-50,-25,-10,0,+10,+25,+50,+75,+100,+200`; `measure=NORMAL`, `skew_measure=NORMALABSOLUTE`, `vol_unit=bp`.

Coverage 2021-01-01..2026-08-20, **two denominators, both named**:

| node | ATMF (raw bdays, n=1470) | ATMF (holiday-adj, n=1409) | smile ≥5 offsets | full 13 offsets |
|---|---:|---:|---:|---:|
| **1Yx30Y** | 95.6 % | **1401 = 99.43 %** | 1400 = 99.36 % | 1400 = 99.36 % |
| **1Yx20Y** | 95.6 % | **99.43 %** | 99.36 % | 99.36 % |
| **3Mx30Y** | 95.6 % | **99.43 %** | 99.36 % | 99.36 % |
| **6Mx30Y** | 95.6 % | **99.43 %** | 99.36 % | 99.36 % |
| **1Yx10Y** | 95.6 % | **99.43 %** | 99.36 % | 99.36 % |

All five nodes are identical — the cube writes them together or not at all. The 66 `pd.bdate_range` misses decompose as **58 US federal holidays + 8 real gaps**: `2021-03-19, 2021-04-29, 2022-04-15, 2024-03-29, 2025-04-18, 2026-08-18, 2026-08-19, 2026-08-20` (the last three are the unwarmed tail; 2022-04-15 / 2024-03-29 / 2025-04-18 are Good Fridays, which `USFederalHolidayCalendar` does not carry). **One degraded day in-window: 2026-08-17 is ATM-only (1 offset, no smile)** — the store's last day.

Known-answer cross-check: `atmf_vol_series(panel,"1Y","30Y")[2022-09-13] = 98.3785 bp`, exactly the value pinned in `tests/test_convexity_rv_strat1.py::test_straddle_sized_to_fund_the_carry_intakes_exactly_the_carry`. `smile_on(2022-09-13,"1Y","30Y")` returns all 13 offsets.

**Divergences from DESIGN.md §3, stated as denominator differences not as errors:**
- DESIGN claims ATMF 97.8 % / smile 83.9 % over "2019-01-01..2026-08-31, 1900 store days". Re-measured on that window against `pd.bdate_range` (**2000 bdays**, a different denominator): ATMF **1904 = 95.2 %**, smile≥5 **1579 = 79.0 %**. Same numerator scale; DESIGN divided by store days, this divides by business days.
- DESIGN claims the OTM smile starts **2020-03-25**. Measured on this store for 1Yx30Y, the first date with **any** OTM offset (threshold-insensitive: identical answer for ≥2, ≥3, ≥5, ≥7, ≥9, ≥11, ≥13 offsets) is **2020-04-22**. 1,579 days carry a smile; 1,127 days are ATM-only.

---

## STEP 3 — REUSABLE ENGINE PATTERNS

### 3a. `usd_fomc_configurable_backtest` — the template
**There is no `.py` percent source.** The file the task named does not exist; the notebook is `notebooks/backtests/intraday_fed_hawk_dove/usd_fomc_configurable_backtest.ipynb` (10,873 lines JSON, 14 code cells), emitted directly as JSON by `notebooks/backtests/intraday_fed_hawk_dove/_make_config_notebook.py` (725 lines). Logic lives in `notebooks/backtests/intraday_fed_hawk_dove/hawk_dove_config.py` (484 lines).

**Section headings, in order:**
0. `# FOMC Speaker Hawk/Dove — Configurable Backtest, 2019 – 2026` (md)
1. `## 1. The config` → code cell defines `CONFIG` + `RES = HC.run_config(CONFIG, RAW, MDP)`
   `### 1.1 Recipes` (md only — paste-over configs)
2. `## 2. Does the machine give the right answer to a question we already know?` → **tie-out cell**
3. `## 3. What this config actually trades` (the funnel: every dropped event counted under a reason)
4. `## 4. How this config performed`
5. `## 5. The instrument knob`
6. `## 6. The timing knob`
7. `## 7. The filter knob` / `### 7.1 The rotation as a natural experiment`
8. `## 8. Costs`
9. `## 9. What the search cost` (deflated-Sharpe / trial count)
10. `## 10. Robustness of the active config` (`G.sign_flip_permutation(CLOSED, n_perm=5000)`)
11. `## 11. Trade log`
12. `## 12. Reading this notebook`

**Two corrections to the task's description:**
- **CONFIG is a plain dict, not a dataclass.** The dataclass is `hawk_dove_config.py:315 @dataclass class Result(config, structure, closed, funnel)` with a `.summary` property. The config template is `hawk_dove_config.py:58 DEFAULT_CONFIG` with keys `name / bank / instrument / timing / filters / flip / sizing / cost_bp`; `merge(*overrides)` (`:137`) deep-merges onto it.
- **There is no sign-probe cell in this notebook.** Its §2 is a *tie-out* cell: re-runs the published baseline config and asserts 8 named checks against the pickled engine book (`overlap rule leaves 796`, `data gate leaves 788`, window `2019-01-09→2026-08-07`, every engine trade matched, `timestamps identical`, `P&L within one tick everywhere`, `|mean diff| < 0.1bp`, `n_missing_bars == 0`), then *accounts for* the 64 one-tick differences by re-pricing each with entry∈{prior,next}×exit∈{prior,next} and reporting `unexplained by either bar`. It ends `assert all(ok ...)`. The sign probe for this family lives in `_probe4_sign.py`; the canonical in-notebook sign probe is `sv_h13_qdb.py:86`.

Other API in `hawk_dove_config.py`: `run_config(config, raw_events, mdp, *, show_progress=False, strict=True) -> Result` (`:332`, "Filter → re-time → resolve overlaps → gate → price. In that order."); `compare(configs, raw_events, mdp, *, raise_on_cold=False) -> (DataFrame, {name: Result})` (`:438`); `sweep_knob(base, path, values, raw_events, mdp, *, label=None)` (`:472`, `path` e.g. `("timing","exit_offset_min")`); `apply_filters` (`:202`), `retime` (`:263`), `check_coverage` (`:299`), `resolve_instrument` (`:157`), `catalogue(max_rank)` (`:152`), `flip_sign`/`FLIP_RULES` (`:121`, `:124`).

**GOTCHA:** cell 1 hardcodes `REPO = r"C:\Users\chris\clee\ARBS-gcb"` — a *different* worktree. A builder copying this template must repoint it.

### 3b. `BT/trade_dashboard.py` (579 lines)
Exports: `BG, CATEGORICAL, FG, GRID, MUTED, PANEL, REASON_COLOUR, compare_curves, summary_stats, to_book, trade_dashboard`.

```python
# :128
to_book(source, *, time_col=None, pnl_col=None, unit=None, signal_col=None,
        colour_col=None, label_col=None, side_col=None, size_metric=None) -> pd.DataFrame
# :260
summary_stats(source, *, span_years: Optional[float] = None, **kw) -> pd.DataFrame
# :333
trade_dashboard(source, *, title="book", span_years=None, signal_col=None,
                colour_col=None, bar_width=None, height=1080, **kw) -> go.Figure
# :530
compare_curves(books: Mapping[str, Any], *, title="comparison", height=520, **kw) -> go.Figure
```
- `to_book` accepts **three shapes**: a trade-log DataFrame (auto-detects `_TIME_COLS=(release_ts, entry_ts, opened_at, closed_at, timestamp)` and `_PNL_COLS=(pnl_bp, pnl, realized_pnl, net_bp)`), a `QueryDrivenBacktest` (walked by `BT.query_tearsheet.closed_trade_frame`; `time_col="closed_at"`, `pnl_col="realized_pnl"`, `unit=""` i.e. **currency not bp**), or a `QueryBacktestTearSheet`/`Analytics` (unwrapped via `.analytics`/`.backtest`). It **also attaches `book.attrs["mtm"] = pd.Series(bt.mtm_history)`** so the dashboard overlays the engine's cumulative total against the closed-log curve and states the terminal gap (that gap is carry + open MTM, not a bug). An already-normalised frame (`attrs["book"]` set) passes through unchanged.
- **`span_years`** is the *only* annualisation input and is deliberately caller-supplied ("a book of 41 event-driven trades has no natural frequency"). When set (`>0`) it adds two rows: `trades / year = len(p)/span_years` and **`annualised Sharpe = (mean/sd) * sqrt(len(p)/span_years)`**. Omit it and the table reports `Sharpe / trade` only. It is the knob that turns a 0.3-per-trade Sharpe into a 3.
- `bar_width` is in **milliseconds on a date axis**; usual choice `(t.max()-t.min())/min(len(book),400)`. Without it plotly sizes bars from the smallest inter-trade gap and a dense book draws 1-pixel bars.
- Renderer is deliberately not pinned — the notebook must set `pio.renderers.default = "plotly_mimetype+notebook_connected"` itself for figures to survive `nbconvert --execute`.

### 3c. `_py2nb.py` / `_verify_nb.py` — exact command lines
`notebooks/backtests/_py2nb.py` (72 lines): splits a `# %%`-delimited script into an `.ipynb`; `# %% [markdown]` starts a markdown cell whose body is the `# `-prefixed comment block. `notebooks/backtests/_verify_nb.py` (57 lines): reads the executed `.ipynb` and reports `N code cells, N outputs, N figures, N unrun, N errors`; exits 1 if any error or unrun cell. **It counts only `image/png`, so a plotly-only notebook correctly verifies as "0 figures".** It globs relative to CWD (`Path().glob(a)`), so it must be invoked with `cwd` = the notebook's directory.

```bash
# 1. source -> notebook
C:/Users/chris/anaconda3/envs/stir/python.exe notebooks/backtests/_py2nb.py <name>.py

# 2. execute in place
ARBS_SUPABASE_ENABLED=0 C:/Users/chris/anaconda3/envs/stir/python.exe -m nbconvert \
    --to notebook --execute --inplace --ExecutePreprocessor.timeout=10800 <name>.ipynb

# 3. verify (cwd MUST be the notebook's dir)
cd notebooks/backtests/convexity_rv && \
  C:/Users/chris/anaconda3/envs/stir/python.exe ../_verify_nb.py <name>.ipynb
```
The house driver that chains all three is `notebooks/backtests/convexity_rv/run_convexity_rv.py` (`NOTEBOOKS` list, `EXEC_TIMEOUT = 10800`, `sh()` sets `env.setdefault("ARBS_SUPABASE_ENABLED","0")` explicitly so "a cache miss cannot escalate into a live COM fetch"). Usage: `python notebooks/backtests/convexity_rv/run_convexity_rv.py [--only strat3] [--no-exec]`.
Contract (spec-level): `# %% .py source → _py2nb.py → nbconvert --execute --inplace → _verify_nb.py (0 errors / 0 unrun) → commit`.

### 3d. `RVUtils/ConvexityRV/strat2_sofr_convexity.py` (1,812 lines) — end-to-end wiring

**Ordered call sequence** (as wired in `notebooks/backtests/convexity_rv/strat2_sofr_convexity_backtest.py`):

```python
CFG = Strat2Config(...)                                          # :343 frozen dataclass
_fut = STIRFutureMDP(source=CFG.futures_source)                  # "BARCHART_STIRF-RL"
_swp = IRSwapsMDP(source=CFG.swap_source)                         # "CITIVELO_EXCEL"

# --- 3 sign probes, live, every execution (nb §2) ---
#   1  IRSwapQuery OUTRIGHT bpv>0 == payer   (QDB, 2022-09-12..15, 5Y, +/-100k, mirror to 1e-6)
#   2  STIRFutureQuery contracts>0 == LONG the future == SHORT the rate
#      (100x SR3M25, 2023-06-09..15, engine == (p1-p0)*100*$25*100 to <$1, and < 0)
#   3  IRSwapStructure.FLY bpv>0 constrains and PAYS the belly
#      risk_weights [0.73,1.0,0.47] + bpv=+21400 -> resolved [-0.73,1.0,-0.47];
#      notionals -82.6mn/+47.5mn/-12.0mn vs Citi 79.0/-44.4/10.9;
#      AND asserts the caller's list WAS mutated in place (_build_fly rewrites it)

_dates = local_cached_dates(CFG, min_contracts=4)                # :1001  enumerate the SR3 diskcache
PANEL_RAW, RATES_RAW = build_panel(_dates, CFG, futures_mdp=_fut, swaps_mdp=_swp)   # :779
coverage_by_run(PANEL_RAW)                                       # :1095  report every contiguous run
PANEL, RATES = trim_to_contiguous_run(PANEL_RAW, RATES_RAW, keep="latest")          # :1117
TS    = panel_timeseries(PANEL, CFG)                             # :1280
MODEL = model_timeseries(PANEL, CFG)                             # :1318
SCREEN = daily_screen(day, PANEL, CFG, ts=TS, model=MODEL)       # :1361  Citi's 13 columns
SPECS = plan_epochs(PANEL, RATES, CFG, ts=TS, model=MODEL)       # :1621  -> List[TradeSpec]
bt = run_backtest(SPECS, CFG, hedged=False|True, futures_mdp=_fut, swaps_mdp=_swp,
                  trading_days=_GRID)                            # :1710  -> QueryDrivenBacktest
eq = assert_ran(bt, SPECS, hedged=..., expect_days=len(_GRID))   # :1772  -> pd.Series
BOOKS = {k: as_book(EQ[k])}   # daily-mark book: {"timestamp": idx, "pnl": eq.diff()}
compare_curves(BOOKS, title=...);  trade_dashboard(BOOKS["unhedged"], span_years=SPAN_YEARS)
```

**Panel columns.** `ca_snapshot` (`:659`) emits one row per (date, pack label): `date, rank, pack, colour, swap_start, swap_end, pack_rate, swap_rate, ca_bp, time_weight, t_mid`. `build_panel` adds three per-date availability columns: **`n_priced`, `strip_depth`, `max_rank_available` (= `strip_depth − 3`)** — sparsity is data, not a hole. `ca_bp = (pack_rate − swap_rate)*100 + cfg.ca_basis_bp`, `pack_rate = 100 − mean(4 settles)` in percent, `swap_rate` from `curve_ops.matched_forward_swap_rate` at **Q/Q** (annual fixed costs −3.89 bp mean vs Citi). `build_panel` returns `(panel, rates)`; `rates` is wide, one row/date, `hedge_tenors` par rates in percent. It **retries every skipped date once** (`_depth` guard) because sqlite-shard contention surfaces as a cache miss, not a lock error. Second `panel_timeseries` output set: `ca, pack_rate, rv (63d realized, ×√252), ca_z3m, ca_z1y, ca_chg_1w`. `model_timeseries`: `fit, vs_model, sigma_model, ca_model, vs_model_z3m, vs_model_z1y`. Keying by **LABEL not rank** is what makes the series constant-contract (no IMM-roll jump).

**Entry/exit rule** (`plan_epochs`, `:1621`):
- Rebalance calendar = `pd.date_range(freq=cfg.rebalance_freq)` (default **`"BMS"`**, first business day of each month), each mark **snapped forward to the next available panel day**.
- A mark with `screen.empty` or with **no finite `vs_model_z1y` anywhere** is a *warm-up day*, skipped (this is the documented cause of an empty plan, see `assert_ran`).
- `select_pack` (`:1457`) = the pack flagged by the **most** of the 8 `RANK_METRICS` (`ca_bp, ca_z3m, ca_z1y, vs_model_bp, vs_model_z3m, vs_model_z1y, roll_3m_bp, implied_over_realized`; top-3 per metric via `rank_flags`, `:1435`); ties broken by mean cross-sectional percentile.
- **Hold**: keep the book while `pick == cur.pack` AND not `stale`. `stale ⇔ m >= cur_entry + DateOffset(months=cfg.max_hold_months)` (default 3). On a change or staleness the current epoch is closed at `m` and a new one struck **at the same mark** — Citi rolled Blues→Greens rather than closing the theme. The final epoch exits at `days[-1]`.
- At every entry, `hedge_regression` (`:1504`) re-fits `CA(bp) ~ a + b2·r2y + b5·r5y + b10·r10y` on the selected label's own trailing `hedge_regression_days` (252) rows; `beta = b5`, `w2 = −b2/beta`, `w10 = −b10/beta`, `belly_DV01 = ca_dv01·beta/100` (`hedge_sizing`, `:1537`). Skipped and *recorded* if `n < max(30, days//4)`, `|beta| < hedge_min_abs_beta` (1.0), or `w2<=0 or w10<=0` (a same-sign wing is not expressible as a fly — `_build_fly` forces opposite signs).

**Legs** (`build_trade_queries`, `:1575`): **4 separate `STIRFutureQuery` OUTRIGHT legs**, `contracts = round(ca_dv01/(4·$25))` each — *never* a pack-alias query, because the STIR handler marks a multi-leg package with the unweighted PV01 sum against the risk-weighted price sum and **quadruples** a 4-leg pack's P&L. Plus one `IRSwapQuery` OUTRIGHT NPV with explicit `effective_date`/`maturity_date` and `bpv=+ca_dv01` (payer). Plus, if hedged, one `IRSwapQuery` FLY NPV with a **freshly constructed** `risk_weights` list (`_build_fly` mutates in place).

**Cost model.** One knob: `Strat2Config.cost_bp_per_roundtrip: float = 0.0` (bp of CA DV01 per round trip). `run_backtest` computes `fee = cost_bp_per_roundtrip * ca_dv01` and passes it to the **single** cost hook, `UnwindPositionsAction(match_tag=spec.tag, fee=fee)` — i.e. charged once, at the unwind, per epoch. Default 0 reproduces Citi's stated convention ("Calculations do not include transaction costs and other fees"); the notebook's §Costs then prices `net = gross − mult·ca_dv01·len(SPECS)` post-hoc at `mult ∈ {0, 0.25, 0.5, 1.0, 2.0}` bp. (Strat 1's analogue: `Strat1Config.cost_bp_one_way = 0.5`, "charged twice (in and out) at the unwind, which is the engine's only cost hook.")

**`assert_ran` (`:1772`) is mandatory** — `QueryDrivenBacktest.run()` swallows exceptions and prints them, so a failed run is indistinguishable from a flat curve. It checks, in order: `len(specs) > 0` (an empty plan is a *planning* failure, named first); `mtm_history` non-empty; `len(eq) == expect_days`; `eq.abs().max() > 0`; `len(closed_positions_log) >= 5·len(specs)` (4 futures + 1 swap per epoch); and `>= 5·len(specs) + n_hedged` when hedged.

---

## CHECKLIST — build a convexity-RV backtest without re-reading the files

**Environment**
1. `ARBS_SUPABASE_ENABLED=0`; python is `C:/Users/chris/anaconda3/envs/stir/python.exe`, called directly (never `conda run` in parallel).
2. Notebook source is `# %%` percent-format `.py`; add `pio.renderers.default = "plotly_mimetype+notebook_connected"` or plotly figures do not survive `nbconvert`.

**Staying offline (the COM trap, traced in `MDP/IRSwaps/IRSwapsMDP.py:2787-2905`)**
3. `IRSwapsMDP(source="CITIVELO_EXCEL").get_data({"curve_name","timestamp": date})` takes the CurveStore EOD fast path only if the day partition exists; on a **cold day it silently falls through to a LIVE EXCEL BUILD over COM** (`:2899` builds a fetcher and calls `fetcher.snapshot`). `_load_citivelo_excel_curve_store_point` returns `None` on any miss by design.
4. `snapshot_policy=SnapshotPolicy.strict(...)` does **not** protect an EOD request — `_assert_policy_mode` (`:3098`) *refuses* a non-intraday request under a minute policy. The only reliable guard is: **enumerate the on-disk partitions first and request only dates that exist.** Confirm a served curve with `pricer.meta()["from_curve_store"] is True` and `["mode"] == "eod"`.
5. Never pass `force_refresh` / `ignore_cache` / `no_curve_store` — all three bypass the store.
6. Never call `IRSwapsMDP(source="BARCHART_STIRF-RL").get_pricer({"curve_name":"USD-SOFR-1D-Q20STIRT"})` (52-57 HTTP requests per date; `offline=True` is accepted then ignored).

**Kernel**
7. Convexity = **reprice, never differentiate**. `RVUtils/ConvexityRV/curve_ops.py::payoff_profile(pricer, package, shifts, carry_ccy=...)`; the shift transform is `pricer._rl_curve_handle.shift(bp)`. `IRSwapValue.GAMMA_01` / `DV01` are unavailable on the rateslib backend.
8. **Never age with `Curve.translate`** — `horizon_handle(..., horizon_date=...)` raises `HorizonAgeingUnsupported`. Convexity is the *shape*, carry is the *level*: pass `carry_ccy = package_carry_roll_bp(...) × package_dv01`.
9. Sign conventions, each with a live probe: `OUTRIGHT bpv>0 = PAYER`; `CURVE bpv<0 = FLATTENER = pay front / receive back = long gamma`; `CURVE bpv>0 = STEEPENER`; `FLY bpv>0 = PAY THE BELLY`; `STIRFuture contracts>0 = LONG the future = SHORT the rate ($25/bp)`.
10. `structure_kwargs["risk_weights"]` is **mutated in place** by the structure builder — construct a fresh list per query.
11. Regression tripwire for any new day/structure: `s1.structure_profile(...).convexity_bp` against DESIGN.md §0's 2022-09-13 table, tolerance 0.5 bp (measured slack today: max 0.05 bp). Use `s1.is_convex(shifts, payoff)`, **not** `np.diff(np.diff(...))` — the production grid is unevenly spaced and the naive form reports a convex profile as concave.
12. Do not assume the profile minimum sits at zero: for a **spot** structure with a linear term (30Y/50Y) it sits at +50 bp and the pinned table agrees.

**Data**
13. Curve: `USD-SOFR-1D` via `CITIVELO_EXCEL`, store partitions **2005-01-03 .. 2026-08-14**, 5,511 days, 0 empty; 1,466/1,470 business days covered 2021-01-01..2026-08-20 (only the last 4 days unwarmed). All of 20Yx10Y / 25Yx10Y / 30Yx20Y / 20Yx30Y / 30Y / 40Y / 50Y price cleanly across 2005-2026.
14. Vol: `RVUtils/ConvexityRV/swaption_cube.py::load_vol_panel(pairs, cache_path=...)` — it scans **all** 2,706 day dirs regardless of `start`/`end` (the filter is post-load), ~50 s cold, so **always pass `cache_path`**. Coverage on 1Yx30Y / 1Yx20Y / 3Mx30Y / 6Mx30Y / 1Yx10Y is **99.4 % of trading days** 2021-2026 for ATMF *and* the full 13-point smile; the 4.4 % raw-`bdate_range` shortfall is US holidays + 3 Good Fridays. The OTM smile starts **2020-04-22** on this store, so an expected-payoff signal cannot run before then; the breakeven-vol signal (ATMF only) runs from 2015-10-08.
15. `implied_shift_density(smile, shifts, tte_years=..., min_points=5)` returns all-NaN rather than guessing when the smile is too sparse — do not collapse that to "no signal" without saying so.

**Engine**
16. Book pattern: `TimeGrid` → `QueryStrategy(triggers=[DateTrigger(entry, [AddQueryAction(q, meta={"tags":[tag]})...]), DateTrigger(exit, [UnwindPositionsAction(match_tag=tag, fee=fee)])])` → `QueryDrivenBacktest(time_grid, strategy, mdp)` → `bt.run()`.
17. Multi-product packages: set `strat.mdps = {"STIRFUTURE": fut_mdp, "IRS": swap_mdp}` and `strat.default_mdp = swap_mdp`.
18. `bt.run()` **swallows exceptions**. Always assert afterwards: `len(specs) > 0`, `mtm_history` non-empty and non-flat, mark count == grid length, and `len(portfolio.closed_positions_log) >= legs_per_epoch × n_epochs`. Copy `strat2_sofr_convexity.assert_ran` (`:1772`).
19. `mtm_history` is the **cumulative total** P&L; the closed log's `realized_pnl` is the **price leg only**. `trade_dashboard` draws both and states the gap.
20. Costs: the engine's only hook is `UnwindPositionsAction(fee=...)`, charged at unwind. Price a cost curve post-hoc as well.
21. Reporting: `compare_curves(books)` for the fork, `trade_dashboard(book, span_years=SPAN)` for the book, `summary_stats(book, span_years=SPAN)` for the table. **Always pass `span_years` explicitly** — it is the only annualisation input and its absence silently drops `annualised Sharpe`. Pass `bar_width` on dense (daily-mark) books.
22. Every notebook re-runs its sign probes at execution time and asserts; a tie-out cell against an independently-produced artifact (§2 of the FOMC template) is the pattern for "is the instrument itself correct".
