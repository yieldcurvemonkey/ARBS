# Strategy 1 — JPM "An option by any other name" (curve-as-gamma vs swaptions)

## Files written (all absolute)
| Path | What |
|---|---|
| `C:/Users/chris/clee/ARBS-cvx/RVUtils/ConvexityRV/strat1_curve_gamma.py` | Strategy module: `Strat1Config` (every knob documented inline), signal computation (both JPM signals), trade construction, overlapping-cohort scheduling, per-cohort attribution |
| `C:/Users/chris/clee/ARBS-cvx/notebooks/backtests/convexity_rv/strat1_curve_gamma_backtest.py` | Percent-format notebook source |
| `C:/Users/chris/clee/ARBS-cvx/notebooks/backtests/convexity_rv/strat1_curve_gamma_backtest.ipynb` | **Executed**: 23 code cells, 29 outputs, 5 plotly figures, **0 unrun, 0 errors** |
| `C:/Users/chris/clee/ARBS-cvx/tests/test_convexity_rv_strat1.py` | 33 tests (24 fast + 9 slow/live) |
| `C:/Users/chris/clee/ARBS-cvx/notebooks/backtests/convexity_rv/_strat1_build.py` | Parallel artifact builder (12 date chunks for the panel, 1 process per structure for the engine) |
| `C:/Users/chris/clee/ARBS-cvx/notebooks/data/convexity_rv/strat1_signal_panel.parquet` | 7,632 rows = 1,908 curve days × 4 structures, 2019-01-02..2026-08-14 |
| `.../strat1_equity_*.parquet`, `.../strat1_cohorts_*.parquet`, `.../strat1_verdict.json` | Daily MTM, per-cohort table, verdict block |

**Tests: 74 pass** across the whole ConvexityRV suite (33 mine + 41 pre-existing), fast gate 65 pass / 9 deselected.

## Tie-outs — all PASS, with numbers
| Tie-out | Result |
|---|---|
| **(a)** payoff-profile regression table, 2022-09-13, 3 structures × 13 shifts | **max abs diff 0.049 bp** (bar ±0.5) |
| **(b)** flattener convex | **1.000 on every day, every structure** (7,632 rows); steepener concave in all cases |
| **(c)** sign probe | payer **+$2,303,346** over the Sep-2022 selloff; ±bpv mirror to 1e-6; package probe DV01-neutral, notionals mirror exactly |
| **(d)** carry pins | max abs diff **3.8e-5 bp** vs +0.0061 (20Yx5Y/25Yx5Y), −20.6697 (5Y/30Y), +0.3632 (30Y/50Y), −2.8401 (10Yx10Y/20Yx10Y) |

(b) is tested as **non-decreasing divided differences**, not `diff(diff(p))` — the shift grid is uneven (50bp wings, 25bp near the money) and the naive test calls a genuinely convex profile concave. A mutation test pins this.

## Backtest — real measured results
Window 2019-01-02..2026-08-14 (7.61y), USD-SOFR-1D, $100k package DV01, **monthly** cohorts, 1-year hold, signal lagged t+1, cost 0.5bp one-way (1.0bp round trip). **88 cohorts entered, 76 closed, 12 live-and-marked (never force-closed)** per structure.

| | 30Y/50Y | **20Yx5Y/25Yx5Y** | 10Yx10Y/20Yx10Y | 5Y/30Y |
|---|---|---|---|---|
| hit rate gross / net | 64.5% / 63.2% | **84.2% / 78.9%** | 63.2% / 61.8% | 59.2% / 59.2% |
| avg gross / net, bp | +5.65 / +4.65 | **+7.16 / +6.16** | +7.42 / +6.42 | +12.40 / +11.40 |
| median gross, bp | +4.44 | +5.95 | +4.82 | +9.30 |
| total gross / net, bp | +429.7 / +353.7 | +544.3 / +468.3 | +563.8 / +487.8 | +942.7 / +866.7 |
| 5th/25th/75th/95th pct gross, bp | −15.5 / −3.4 / +10.8 / +28.1 | −2.7 / +2.7 / +11.6 / +17.2 | −25.9 / −10.3 / +19.4 / +53.8 | −70.5 / −25.0 / +53.1 / +92.1 |
| Sharpe/trade, t-stat | 0.332, 2.89 | **0.933, 8.13** | 0.269, 2.34 | 0.229, 1.99 |
| annualised Sharpe (overlapping) | 1.05 | **2.95** | 0.85 | 0.72 |
| full-MTM total, bp | +356.6 | +469.0 | +416.4 | +950.0 |
| MTM max DD, bp of one package | −367.9 | −205.9 | −846.8 | −721.4 |
| MTM max DD, bp of **peak aggregate** | −28.3 | −15.8 | −65.1 | −55.5 |
| mean carry+roll, bp/yr | **+1.36** | +0.000 | −0.52 | −5.44 |

Concurrency: **mean 10.8, max 13 live cohorts** = up to **$1.3M aggregate DV01**. The MTM drawdowns quoted "in bp of one package" are on ~11× one package's risk; the right-hand row normalises them.

## vs JPM Exhibit 5 — ordering, split
| Metric | JPM 30s/50s | here | JPM 25Y/20Yx5Y | here |
|---|---|---|---|---|
| % cheap curve gamma | 70% | 97.3% | 100% | 97.3% |
| hit rate | 56% | 64.5% | 86% | **84.2%** |
| avg P&L, bp | 10.4 | 5.65 | 11.4 | 7.16 |
| carry, bp | −100.6 | **+1.36** | 1.1 | +0.000 |

**Does the "forward flatteners beat 30s/50s" claim hold here? Partly — and I will not average the halves.**
- **Holds on hit rate** (84.2% vs 64.5%) and **on avg P&L** (+7.16 vs +5.65 bp) and on dispersion (5-95 range 19.8bp vs 43.6bp).
- **Fails on carry.** On 2019-2026 SOFR, 30s/50s carried **positively** (+1.36 bp/yr mean, negative on only 13.6% of days). JPM's −100.6 bp belongs to 2009-2017 LIBOR. The forward structure's carry edge exists only against **spot 5Y/30Y** (−5.44 bp mean), which is the pair the one-day assert is pinned to. The 30s/50s carry comparison is reported, not asserted — on 2022-09-13 itself 30s/50s carried at +0.3632 vs the forward's +0.0061, i.e. the *wrong* way round.

## Signal degeneracy — the finding that matters most
The breakeven-vol signal **never fires rich** for the three long-end structures: curve breakeven < 1Yx30Y ATMF on **every** day a vol exists (97.3%; the other 2.7% is missing ATMF). 86.4% of 30s/50s days are the `always_cheap` branch (positive carry → no vol needed at all). So for those three the strategy is **not a timing rule** — it is a permanently-on long-end flattener (88/88 cohorts flattener), and the P&L must be read that way. A separate "always-flattener" control would be the identical book. This matches JPM's 100%-cheap for the forward pair and does **not** match their 70% for 30s/50s.
**5Y/30Y is the two-sided control**: 50.1% cheap / 47.2% rich, **45 flattener / 43 steepener** cohorts — the machinery *can* say rich.
Expected-payoff and breakeven signals **agree 100%** on the three long-end structures (95.0% on 5Y/30Y) over the 1,591-day common sample.

## Straddle leg — verified as the task asked
Sized so premium intake = |carry| over the horizon, via the Bachelier ATMF straddle `sqrt(2/pi)·σ·sqrt(T)`:

| structure | median \|carry\|, bp | median straddle DV01 | as % of package DV01 |
|---|---|---|---|
| **20Yx5Y/25Yx5Y** | 0.0025 | **$4.17** | **0.0042%** |
| 10Yx10Y/20Yx10Y | 0.572 | $937 | 0.94% |
| 30Y/50Y | 1.522 | $2,303 | 2.30% |
| 5Y/30Y | 9.963 | $17,169 | 17.2% |

**Confirmed**: for the forward structure the funding straddle is a rounding error (4,120× smaller than 5Y/30Y's), so `trade_straddle` defaults **off** and the reported books are flattener/steepener only. `build_backtest` now **raises `NotImplementedError`** if the knob is flipped rather than silently ignoring it (tested). **JPM's Exhibit 5 hit rates include the straddle leg; mine do not.**

## What did not work / caveats
- **`rateslib.Curve.translate` ageing is defective for spot-starting swaps.** Measured: 0.000 bp of carry on a DV01-neutral *forward* package (DF renormalisation cancels), −147.7 bp on 30s/50s, −1,747 bp on 5Y/30Y, −531.94 bp on a 1y-aged 30Y payer — the swap's effective date falls behind the translated curve's initial node and a year of missing fixings gets extrapolated. It also crashed outright (`TypeError: date < datetime`) before a `_as_dt` fix. The shared `curve_ops` now **refuses** that path; carry enters `payoff_profile` as `carry_ccy` from the independently-validated `CARRY_AND_ROLL_BPS_RUNNING`. Consequence: the profile *shape* is instantaneous convexity, not horizon-aged — which is what the pinned regression table itself measures (`horizon_date=None` reproduces it to 0.00).
- **`cohort_freq="monthly"`, not JPM's daily.** Measured engine cost 0.030 s/cohort/mark (forward) and 0.090 s (spot, a 50Y leg has ~10× the cashflows). Over 1,908 marks: daily ≈ 40 h for 30s/50s, weekly ≈ 2.5 h, monthly ≈ 35 min. Budget decision only; `weekly`/`daily` are config values.
- **Overlapping cohorts are not independent draws.** 76 closed 1-year holds one month apart contain ~7.6 non-overlapping years; the 2.95 annualised Sharpe is an overlapping-sample number and is flagged as such in the notebook.
- **JPM quote "bp of notional"; I quote bp of package DV01.** For a DV01-neutral package these normalisations may differ — most plausibly the reason their carry magnitudes (−100.6) are an order larger than anything here.
- **Expected-payoff signal only runs from 2020-03-25** (OTM smile 85.7% coverage vs ATMF 100.0% from 2019-01-02, both re-measured in the notebook) — hence `signal_mode="breakeven_vol"` default.
- `GAMMA_01`/`DV01` unavailable on the rateslib backend as documented; convexity measured by repricing under parallel shifts throughout.
- **Environment:** 12-way parallel panel builds exhausted the Windows paging file (31 python processes on the box from concurrent agents); 5 chunks died and were relaunched staggered. Panel took ~17 min wall clock, the four engine runs 560–2,213 s each in parallel.